"""规范 PDF/Word 按条入库。

MinerU 优先抽出 Markdown；本机没有 MinerU 时退回 PyMuPDF 文字层。
扫描页抽不出正文就跳过，不编造条文。切片单位是 4.1.3 这种条号。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import KnowledgeDocument, StandardClause

SPECIALTIES = ("水利", "公路", "市政", "房建", "通用")
KINDS = ("验收", "施工", "设计", "通用")

_SPECIALTY_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("水利", ("水利", "农田", "灌溉", "水库", "堤防", "渠道", "泵站", "水闸")),
    ("公路", ("公路", "路基", "路面", "沥青路面")),
    ("市政", ("市政", "城镇道路", "给水", "排水", "燃气", "热力", "桥梁")),
    ("房建", ("建筑", "混凝土", "砌体", "基坑", "装配式", "屋面", "装修", "地基", "结构")),
)

_KIND_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("验收", ("验收", "检验", "检测")),
    ("施工", ("施工", "规程", "工艺")),
    ("设计", ("设计", "规范")),
)

_CODE_RE = re.compile(
    r"(?P<head>JGJ|JG|GB|CJJ|JTG|SL|NB)(?P<t>/?\s*T)?\s*[-_/ ]*\s*(?P<num>\d+(?:\.\d+)*)\s*[-–—]\s*(?P<year>(?:19|20)\d{2})",
    re.I,
)
_CLAUSE_LINE = re.compile(r"^(?P<no>\d+\.\d+(?:\.\d+)*)(?:\s+|[、.．:：]\s*)(?P<body>\S.*)$")
_TOC_TAIL = re.compile(r"(?:\.{2,}|…{2,}|·{2,})\s*\d+\s*$")
_CLAUSE_MAX = 1500
_MIN_BODY = 8


def detect_specialty(text: str) -> str:
    blob = text or ""
    best = "通用"
    best_score = 0
    for name, words in _SPECIALTY_WORDS:
        score = sum(blob.count(word) for word in words)
        if score > best_score:
            best = name
            best_score = score
    return best


def detect_kind(text: str) -> str:
    blob = text or ""
    for name, words in _KIND_WORDS:
        if any(word in blob for word in words):
            return name
    return "通用"


def parse_standard_code(filename: str) -> str:
    stem = os.path.splitext(os.path.basename(filename or ""))[0].replace("／", "/")
    stem = stem.replace("_T", "/T").replace("-T", "/T")
    match = _CODE_RE.search(stem)
    if not match:
        return ""
    head = match.group("head").upper()
    slash_t = "/T" if match.group("t") else ""
    return f"{head}{slash_t}{match.group('num')}-{match.group('year')}"


def split_clauses(text: str) -> list[dict]:
    """按条号切开。没有条号时返回空列表，不把全文当成一条。"""
    current_no = ""
    current: list[str] = []
    found: list[tuple[str, str]] = []

    def _flush() -> None:
        if not current_no:
            return
        body = re.sub(r"[ \t]+\n", "\n", "\n".join(current)).strip()
        body = re.sub(r"\n{3,}", "\n\n", body)
        if len(re.sub(r"\s+", "", body)) < _MIN_BODY:
            return
        found.append((current_no, body[:_CLAUSE_MAX]))

    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip().lstrip("#").strip()
        if not line or _TOC_TAIL.search(line):
            continue
        match = _CLAUSE_LINE.match(line)
        if match:
            _flush()
            current_no = match.group("no")
            current = [match.group("body").strip()]
            continue
        if current_no:
            current.append(line)
    _flush()

    merged: dict[str, str] = {}
    order: list[str] = []
    for clause_no, body in found:
        if clause_no not in merged:
            order.append(clause_no)
            merged[clause_no] = body
        elif len(body) > len(merged[clause_no]):
            merged[clause_no] = body
    return [{"clause_no": clause_no, "text": merged[clause_no]} for clause_no in order]


def _cjk_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def _mineru_markdown(path: str) -> str:
    exe = shutil.which("mineru")
    if not exe:
        return ""
    with tempfile.TemporaryDirectory(prefix="mineru-") as tmp:
        try:
            proc = subprocess.run(
                [exe, "-p", path, "-o", tmp],
                capture_output=True,
                timeout=600,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if proc.returncode != 0:
            return ""
        markdowns = list(Path(tmp).rglob("*.md"))
        if not markdowns:
            return ""
        best = max(markdowns, key=lambda item: item.stat().st_size)
        return best.read_text(encoding="utf-8", errors="ignore")


def _pymupdf_text(path: str) -> str:
    import pymupdf as fitz

    parts: list[str] = []
    with fitz.open(path) as doc:
        for page in doc:
            parts.append(page.get_text("text") or "")
    return "\n".join(parts)


def _ocr_pdf(path: str, max_pages: int = 40) -> str:
    try:
        import pymupdf as fitz
        import pytesseract
        from PIL import Image
    except Exception:
        return ""
    parts: list[str] = []
    with fitz.open(path) as doc:
        for index, page in enumerate(doc):
            if index >= max_pages:
                break
            try:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                text = pytesseract.image_to_string(img, lang="chi_sim+eng")
            except Exception:
                continue
            if text and text.strip():
                parts.append(text)
    return "\n".join(parts)


def extract_standard_text(path: str) -> tuple[str, str]:
    """返回 (正文, 说明)。说明为空表示抽出了可用文字。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        text = _mineru_markdown(path)
        if _cjk_count(text) >= 80:
            return text, ""
        try:
            text = _pymupdf_text(path)
        except Exception:
            text = ""
        if _cjk_count(text) >= 80:
            return text, ""
        ocr = _ocr_pdf(path)
        if _cjk_count(ocr) >= 80:
            return ocr, ""
        return "", "扫描页未能抽出文字"
    if ext in {".docx", ".doc"}:
        from .docx_extract import extract_full_text
        from .legacy_doc import as_docx

        try:
            if ext == ".doc":
                with as_docx(path) as word_path:
                    text = extract_full_text(word_path)
            else:
                text = extract_full_text(path)
        except Exception:
            return "", "文档无法读取"
        if _cjk_count(text) >= 80:
            return text, ""
        return "", "未抽出足够正文"
    return "", "仅支持 pdf / doc / docx"


def clauses_from_path(path: str, filename: str = "") -> tuple[list[dict], str]:
    name = filename or os.path.basename(path)
    text, note = extract_standard_text(path)
    if not text:
        return [], note or "未抽出正文"
    pieces = split_clauses(text)
    if not pieces:
        return [], "未识别到条号"
    label = f"{name}\n{text[:400]}"
    specialty = detect_specialty(label)
    kind = detect_kind(label)
    code = parse_standard_code(name)
    clauses = [
        {
            "code": code,
            "clause_no": piece["clause_no"],
            "specialty": specialty,
            "kind": kind,
            "text": piece["text"],
            "source_file": name,
        }
        for piece in pieces
    ]
    return clauses, ""


def replace_document_clauses(db: Session, doc: KnowledgeDocument, clauses: list[dict]) -> int:
    db.query(StandardClause).filter(StandardClause.document_id == doc.id).delete(synchronize_session=False)
    for item in clauses:
        db.add(
            StandardClause(
                document_id=doc.id,
                code=item.get("code") or "",
                clause_no=item.get("clause_no") or "",
                specialty=item.get("specialty") or "通用",
                kind=item.get("kind") or "通用",
                text=item.get("text") or "",
                source_file=item.get("source_file") or doc.filename or "",
            )
        )
    return len(clauses)


def import_folder(db: Session, folder: str, limit: int = 0) -> dict:
    """把目录里的规范 PDF 按条入库。同名文件已入库则跳过。"""
    from .. import storage

    root = Path(folder)
    if not root.is_dir():
        raise FileNotFoundError(folder)
    files = sorted(path for path in root.iterdir() if path.suffix.lower() == ".pdf" and path.is_file())
    if limit > 0:
        files = files[:limit]
    imported = 0
    skipped = 0
    empty = 0
    reasons: list[str] = []
    for path in files:
        exists = (
            db.query(KnowledgeDocument)
            .filter(KnowledgeDocument.type == "规范条文", KnowledgeDocument.filename == path.name)
            .first()
        )
        if exists:
            skipped += 1
            continue
        clauses, note = clauses_from_path(str(path), path.name)
        if not clauses:
            empty += 1
            if note and len(reasons) < 8:
                reasons.append(f"{path.name}: {note}")
            continue
        data = path.read_bytes()
        storage_path = storage.put_bytes("knowledge", data, ".pdf")
        doc = KnowledgeDocument(
            scope="企业库",
            type="规范条文",
            title=path.stem,
            tags_json=[clauses[0]["specialty"], clauses[0]["code"]] if clauses[0].get("code") else [clauses[0]["specialty"]],
            filename=path.name,
            storage_path=storage_path,
            size_bytes=len(data),
            slice_count=0,
            review_flag=None,
        )
        db.add(doc)
        db.flush()
        saved = replace_document_clauses(db, doc, clauses)
        doc.slice_count = saved
        imported += 1
    db.commit()
    return {"imported": imported, "skipped": skipped, "empty": empty, "reasons": reasons}
