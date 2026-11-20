"""规范 PDF/Word 按条入库。

整本都有文字层时用 PyMuPDF。出现扫描页时，整本 PDF 一次交给 MinerU，不再逐页识图。
抽不出正文就不编造条文。切片单位是 4.1.3 这种条号。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from ..models import KnowledgeDocument, StandardClause

SPECIALTIES = ("水利", "公路", "市政", "房建", "通用")
KINDS = ("验收", "施工", "设计", "通用")
WORK_TYPES = ("新建", "改建", "扩建", "除险加固", "维修养护", "其他")

# 专业识别按加权关键词计分，不用单一命中就定专业。资质名称、专项工艺词权重最高，
# 避免「混凝土、结构、地基、基坑」这类各专业通用的工程词把水利项目误判成房建。
_SPECIALTY_WEIGHTS: tuple[tuple[str, tuple[tuple[str, int], ...]], ...] = (
    (
        "水利",
        (
            ("水利水电工程施工总承包", 8),
            ("水利水电总承包", 8),
            ("水利水电工程施工", 6),
            ("水利水电", 4),
            ("河道治理", 4),
            ("防洪工程", 3),
            ("除险加固", 4),
            ("水土保持", 3),
            ("灌区", 3),
            ("灌溉", 3),
            ("堤防", 3),
            ("泵站", 3),
            ("水闸", 3),
            ("围堰", 3),
            ("导流", 3),
            ("渠道", 2),
            ("水库", 2),
            ("水利", 1),
            ("农田", 1),
        ),
    ),
    (
        "公路",
        (
            ("公路工程施工总承包", 8),
            ("公路交通工程", 4),
            ("高速公路", 3),
            ("国省道", 3),
            ("沥青路面", 3),
            ("路基", 2),
            ("路面", 2),
            ("公路", 1),
        ),
    ),
    (
        "市政",
        (
            ("市政公用工程施工总承包", 8),
            ("综合管廊", 4),
            ("城镇道路", 3),
            ("污水处理厂", 3),
            ("给排水管网", 3),
            ("管网", 2),
            ("桥梁", 2),
            ("燃气", 2),
            ("热力", 2),
            ("市政", 1),
            ("道路", 1),
            ("排水", 1),
            ("给水", 1),
        ),
    ),
    (
        "房建",
        (
            ("房屋建筑工程施工总承包", 8),
            ("房屋建筑工程", 4),
            ("住宅工程", 3),
            ("公共建筑", 3),
            ("装配式建筑", 3),
            ("建筑装饰", 2),
            ("房屋建筑", 2),
            ("房建", 2),
            ("住宅", 1),
            ("公建", 1),
            ("装配式", 1),
            ("建筑", 1),
        ),
    ),
)

_KIND_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("验收", ("验收", "检验", "检测")),
    ("施工", ("施工", "规程", "工艺")),
    ("设计", ("设计", "规范")),
)

# 按加权计分，不因合同里顺带写到的义务定性。
# 「维修加固」常出现在临时道路保通条款里，不能据此把河道治理判成维修养护。
_WORK_TYPE_WEIGHTS: tuple[tuple[str, tuple[tuple[str, int], ...]], ...] = (
    ("除险加固", (("除险加固", 8),)),
    ("维修养护", (("维修养护", 8), ("大修工程", 6), ("养护工程", 6))),
    (
        "改建",
        (
            ("改扩建", 6),
            ("提升改造", 6),
            ("改造工程", 5),
            ("提标", 5),
            ("整治", 4),
            ("治理工程", 4),
            ("改建", 5),
        ),
    ),
    ("扩建", (("扩建", 5),)),
    ("新建", (("新建", 3),)),
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
    for name, words in _SPECIALTY_WEIGHTS:
        score = sum(blob.count(word) * weight for word, weight in words)
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


def detect_work_type(text: str) -> str:
    """只在确认是工程类项目时调用；没有命中任何关键词时按新建处理，而不是「其他」。"""
    blob = text or ""
    best = "新建"
    best_score = 0
    for name, words in _WORK_TYPE_WEIGHTS:
        score = sum(blob.count(word) * weight for word, weight in words)
        if score > best_score:
            best = name
            best_score = score
    return best


_CODE_HINT_RE = re.compile(r"\b(JGJ|JG|GB|CJJ|JTG|SL|NB)\s*[-/／∕]?\s*T?\s*\d{2,6}", re.I)


def looks_like_standard_filename(filename: str) -> bool:
    """文件名像「SL 775-2018」「GB/T 51280-2018」这类规范编号，上传时据此默认选「规范条文」。

    只看文件名前缀，不猜内容：宁可漏判（用户手动选），不要把普通文件误判成规范。
    """
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    return bool(_CODE_HINT_RE.search(stem))


def parse_standard_code(filename: str) -> str:
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    stem = stem.replace("／", "/").replace("∕", "/").replace("+", " ")
    stem = re.sub(r"\b(SL|GB|NB|JGJ|CJJ|JTG)\s*T\b", r"\1/T", stem, flags=re.I)
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


WATER_TOPICS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("导流", ("导流", "度汛", "截流", "围堰")),
    ("土石方", ("土石方", "碾压", "填筑")),
    ("混凝土", ("混凝土", "温控", "防裂")),
    ("堤防", ("堤防", "河道")),
    ("地基处理", ("地基", "防渗墙", "灌浆")),
    ("锚喷", ("锚喷", "锚杆", "喷射混凝土")),
    ("验收", ("验收", "检验批", "单元工程")),
    ("安全", ("安全设施", "危险源", "度汛")),
    ("环保", ("环境保护", "水土保持", "废水")),
)

_MANDATORY_NO = re.compile(r"\d+\.\d+(?:\.\d+)*")


def mandatory_numbers(text: str) -> set[str]:
    """从前言里「强制性条文」后面的条号收集，不把正文里偶然出现的词当成公告。"""
    blob = text or ""
    start = blob.find("强制性条文")
    if start < 0:
        return set()
    window = blob[start : start + 2500]
    stop = re.search(r"\n\s*\d+\s+总则", window)
    if stop:
        window = window[: stop.start()]
    return set(_MANDATORY_NO.findall(window))


def commentary_numbers(text: str) -> set[str]:
    nums: set[str] = set()
    on = False
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("#").strip()
        if line in {"条文说明", "本标准用词说明"} or line.startswith("条文说明"):
            on = line.startswith("条文说明") or line == "条文说明"
            if line == "本标准用词说明":
                on = False
            continue
        if on and re.match(r"^\d+\s+[\u4e00-\u9fff]", line) and not _CLAUSE_LINE.match(line):
            on = False
        match = _CLAUSE_LINE.match(line)
        if on and match:
            nums.add(match.group("no"))
    return nums


def tag_topics(text: str) -> list[str]:
    blob = text or ""
    return [name for name, words in WATER_TOPICS if any(word in blob for word in words)]


def annotate_clauses(clauses: list[dict], full_text: str = "") -> list[dict]:
    mandatory = mandatory_numbers(full_text)
    commentary = commentary_numbers(full_text)
    out: list[dict] = []
    for item in clauses:
        row = dict(item)
        body = str(row.get("text") or "")
        no = str(row.get("clause_no") or "")
        row["mandatory"] = no in mandatory
        row["is_commentary"] = no in commentary
        row["topics"] = tag_topics(body)
        tables = [line for line in body.splitlines() if "允许偏差" in line or line.count("|") >= 2]
        row["table_text"] = "\n".join(tables)[:800]
        out.append(row)
    return out


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


def _batch_progress_path(path: str) -> str:
    return path + ".batches.json"


def _load_batch_progress(path: str, progress_ref: str | None) -> dict:
    """进度存一份固定键（progress_ref），不依赖调用方传进来的本地临时文件路径。

    knowledge_ingest 每次用 storage.as_local 下载到本地的路径都不一样，存在本地文件旁边的
    进度下次重试就找不到了。没传 progress_ref 的调用方（从磁盘直接导入规范库，原文件路径本身
    是稳定的）仍用本地文件，行为不变。
    """
    if progress_ref:
        from .. import storage

        try:
            if storage.exists(progress_ref):
                return json.loads(storage.get_bytes(progress_ref).decode("utf-8"))
        except Exception:  # noqa: BLE001 —— 读进度失败就从头开始，不能因为这个挡住解析
            return {}
        return {}
    progress_path = _batch_progress_path(path)
    if os.path.exists(progress_path):
        try:
            return json.loads(Path(progress_path).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
    return {}


def _save_batch_progress(path: str, progress_ref: str | None, data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    if progress_ref:
        from .. import storage

        try:
            storage.put_at(progress_ref, payload, content_type="application/json")
        except Exception:  # noqa: BLE001 —— 进度写不进去不影响继续识图，只是下次不能从断点续跑
            pass
        return
    Path(_batch_progress_path(path)).write_bytes(payload)


def clear_batch_progress(path: str, progress_ref: str | None) -> None:
    """扫描完所有页（不管抽没抽出够用的正文）就清掉进度，避免下次重新上传同名文件继承旧进度。"""
    if progress_ref:
        from .. import storage

        storage.delete(progress_ref)
        return
    try:
        os.remove(_batch_progress_path(path))
    except OSError:
        pass


def _native_text_if_no_scan(path: str) -> tuple[bool, str]:
    """返回 (含扫描页, 文字层正文)。任一页中文不足 20 字就视为扫描件，整本改交 MinerU。"""
    import pymupdf as fitz

    parts: list[str] = []
    with fitz.open(path) as doc:
        for page in doc:
            text = (page.get_text("text") or "").strip()
            if _cjk_count(text) < 20:
                return True, ""
            if text:
                parts.append(text)
    return False, "\n".join(parts).strip()


def extract_pdf_in_batches(
    path: str,
    batch_pages: int = 1,
    *,
    progress_ref: str | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[str, str]:
    """有文字层的书直接抽字。出现扫描页时整本上传 MinerU，不再按页切开。

    batch_pages 保留给旧调用方，扫描件不再按这个页数切片。
    进度里只保存 MinerU 任务号。中断后按任务号取结果，取不到再重新提交整本。
    以前逐页识图留下的正文不并进来。on_progress(0, 0) 表示正在识别整本。
    """
    del batch_pages
    from .doc_parse import mineru_fetch, mineru_markdown

    scanned, native = _native_text_if_no_scan(path)
    if not scanned:
        clear_batch_progress(path, progress_ref)
        if _cjk_count(native) < 80:
            return "", "未抽出足够正文"
        return native, ""
    if on_progress:
        on_progress(0, 0)
    saved = _load_batch_progress(path, progress_ref)
    request_id = str(saved.get("request_id") or "") if saved.get("engine") == "mineru" else ""
    if request_id:
        text = mineru_fetch(request_id)
        if _cjk_count(text) >= 80:
            clear_batch_progress(path, progress_ref)
            return text, ""

    def on_ticket(ticket: str) -> None:
        _save_batch_progress(path, progress_ref, {"engine": "mineru", "request_id": ticket})

    text = mineru_markdown(Path(path).read_bytes(), Path(path).name or "standard.pdf", on_ticket=on_ticket)
    clear_batch_progress(path, progress_ref)
    if _cjk_count(text) < 80:
        return "", "扫描页未能抽出文字"
    return text, ""


def extract_standard_text(
    path: str,
    *,
    progress_ref: str | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[str, str]:
    """返回 (正文, 说明)。说明为空表示抽出了可用文字。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        text, note = extract_pdf_in_batches(path, progress_ref=progress_ref, on_progress=on_progress)
        if text:
            return text, note
        return "", note or "扫描页未能抽出文字"
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


def clauses_from_path(
    path: str,
    filename: str = "",
    *,
    progress_ref: str | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[list[dict], str]:
    name = filename or os.path.basename(path)
    text, note = extract_standard_text(path, progress_ref=progress_ref, on_progress=on_progress)
    if not text:
        return [], note or "未抽出正文"
    pieces = annotate_clauses(split_clauses(text), text)
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
            "mandatory": bool(piece.get("mandatory")),
            "is_commentary": bool(piece.get("is_commentary")),
            "topics": piece.get("topics") or [],
            "table_text": piece.get("table_text") or "",
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
                mandatory=bool(item.get("mandatory")),
                is_commentary=bool(item.get("is_commentary")),
                topics_json=item.get("topics") or [],
                table_text=item.get("table_text") or "",
                source_file=item.get("source_file") or doc.filename or "",
            )
        )
    return len(clauses)


def save_platform_standard(path: str, filename: str, catalog_id: str | None = None) -> dict:
    """写入平台规范库。同编号先删旧条再写入，方便重试。"""
    import json

    from ..db import platform_session
    from ..platform_models import StdCatalog, StdClause

    clauses, note = clauses_from_path(path, filename)
    code = parse_standard_code(filename)
    with platform_session() as db:
        catalog = db.get(StdCatalog, catalog_id) if catalog_id else None
        if catalog is None and code:
            catalog = db.query(StdCatalog).filter(StdCatalog.code == code).first()
        if catalog is None:
            catalog = StdCatalog(code=code, name=filename, source_file=filename, storage_path=path)
            db.add(catalog)
            db.flush()
        else:
            db.query(StdClause).filter(StdClause.catalog_id == catalog.id).delete(synchronize_session=False)
        catalog.code = code or catalog.code
        catalog.name = filename
        catalog.source_file = filename
        catalog.storage_path = path
        catalog.status = "现行" if clauses else "失败"
        catalog.note = note
        catalog.clause_count = len(clauses)
        catalog.specialty = clauses[0]["specialty"] if clauses else detect_specialty(filename)
        blob = filename + "\n" + "\n".join(str(item.get("text") or "")[:160] for item in clauses[:6])
        for older in re.findall(r"代替\s*((?:SL/T|SLT|SL|GB/T|GB)\s*[\d.]+(?:-\d{4})?)", blob):
            older_code = parse_standard_code(older) or re.sub(r"\s+", " ", older).strip()
            if not older_code or older_code == code:
                continue
            previous = db.query(StdCatalog).filter(StdCatalog.code == older_code).first()
            if previous is not None and previous.id != catalog.id:
                previous.status = "废止"
                previous.replaced_by = code
        for item in clauses:
            db.add(
                StdClause(
                    catalog_id=catalog.id,
                    code=item.get("code") or "",
                    clause_no=item.get("clause_no") or "",
                    text=item.get("text") or "",
                    mandatory=bool(item.get("mandatory")),
                    is_commentary=bool(item.get("is_commentary")),
                    topics_json=json.dumps(item.get("topics") or [], ensure_ascii=False),
                    table_text=item.get("table_text") or "",
                    specialty=item.get("specialty") or "通用",
                    source_file=filename,
                )
            )
        db.commit()
        return {"code": code, "clauses": len(clauses), "note": note, "status": catalog.status}


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
