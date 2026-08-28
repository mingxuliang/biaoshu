"""商务标原文：大模型在招标书里定位格式件起止行，再按 Word 正文顺序原样拷贝。

不靠标题打分去「猜」章节。拷贝时保留居中/右对齐、下划线空格、空行和表格，
转成撰写编辑器可还原的 markdown-lite（`>>> ` 居中、`>> ` 右对齐、GFM 表）。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_UNDERLINE
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from .tender_toc import _parse_numbered, strip_heading_prefix

logger = logging.getLogger(__name__)

_PLACEHOLDER_MARKERS = (
    "系统不展开目录、不撰写正文",
    "商务标本章无需撰写应标正文",
    "请直接使用招标书原文填写后打印签字",
    "无需 AI 撰写",
)

_LOCATE_SYSTEM = """你是投标文件编制助手。任务：在招标书正文清单中，为每个商务标章节标出应「原样拷贝」的起止行号。

必须拷贝的是「响应文件格式 / 投标文件格式」里给出的填写模板（承诺书正文、法定代表人身份证明、授权委托书、报价表、偏差表等，带称谓、条款、填空、落款或表格），不是前面「文件组成」里只罗列文件名的清单。

同一名称出现两次时，选后面那份可打印签字的模板。
start 含该模板标题行，end 含落款/注释，不含下一份格式件的标题行。
行号必须与清单左侧编号完全一致。
只输出 JSON：{"items":[{"title":"与输入标题完全一致","start":12,"end":48}]}"""


@dataclass
class _Block:
    kind: str  # p | tbl
    text: str
    md: str
    heading: bool


def is_placeholder_markdown(md: str) -> bool:
    text = (md or "").strip()
    if not text:
        return True
    if re.search(r"应按以上响应文件格式|准备上述材料", text):
        return True
    head = text.lstrip()
    if re.match(r"1\.\d+", head) and ("限制响应情形" in text or "否决" in text[:200]):
        return True
    if not any(m in text for m in _PLACEHOLDER_MARKERS):
        return False
    stripped = text
    for m in _PLACEHOLDER_MARKERS:
        stripped = stripped.replace(m, "")
    stripped = re.sub(r"^#+\s*.+$", "", stripped, flags=re.M)
    return len(re.sub(r"\s+", "", stripped)) < 80


def needs_form_recopy(md: str) -> bool:
    """占位说明或尚未带上字体字号的旧拷贝，打开时重抽。"""
    if is_placeholder_markdown(md):
        return True
    text = (md or "").strip()
    if not text:
        return True
    return "{{" not in text


def extract_forms_markdown(path: str, titles: list[str], model_id: str | None = None) -> dict[str, str]:
    wanted = [t for t in titles if (t or "").strip()]
    if not wanted:
        return {}
    document = docx.Document(path)
    blocks = _body_blocks(document)
    if not blocks:
        return {}
    ranges = _locate_ranges(blocks, wanted, model_id)
    out: dict[str, str] = {}
    for title in wanted:
        span = ranges.get(title)
        if not span:
            continue
        start, end = span
        chunk = [blocks[i].md for i in range(start, end + 1)]
        while chunk and not chunk[-1]:
            chunk.pop()
        md = "\n".join(chunk).strip()
        if md:
            out[title] = md
    return out


def extract_forms_from_storage(
    storage_path: str, titles: list[str], model_id: str | None = None
) -> dict[str, str]:
    from .. import storage
    from .legacy_doc import as_docx

    with storage.as_local(storage_path) as local:
        with as_docx(local) as word_path:
            return extract_forms_markdown(word_path, titles, model_id)


def _core(title: str) -> str:
    return re.sub(r"\s+", "", strip_heading_prefix(title or ""))


def _alignment(para: Paragraph) -> str:
    align = para.alignment
    val = ""
    if para._element.pPr is not None:
        jc = para._element.pPr.find(qn("w:jc"))
        if jc is not None:
            val = (jc.get(qn("w:val")) or "").lower()
    if align == WD_ALIGN_PARAGRAPH.CENTER or val in ("center", "middle"):
        return "center"
    if align == WD_ALIGN_PARAGRAPH.RIGHT or val in ("right", "end"):
        return "right"
    return ""


def _run_underlined(run) -> bool:
    u = run.underline
    if not u:
        return False
    if u is True:
        return True
    try:
        return u != WD_UNDERLINE.NONE
    except Exception:
        return bool(u)


def _run_font_size_pt(run, para: Paragraph) -> float:
    if run.font.size:
        return round(float(run.font.size.pt), 1)
    rPr = run._element.rPr
    if rPr is not None:
        sz = rPr.find(qn("w:sz"))
        if sz is not None and sz.get(qn("w:val")):
            try:
                return int(sz.get(qn("w:val"))) / 2
            except (TypeError, ValueError):
                pass
    try:
        if para.style is not None and para.style.font.size:
            return round(float(para.style.font.size.pt), 1)
    except Exception:
        pass
    return 12.0


def _run_font_name(run, para: Paragraph) -> str:
    rPr = run._element.rPr
    if rPr is not None:
        rf = rPr.find(qn("w:rFonts"))
        if rf is not None:
            for key in (qn("w:eastAsia"), qn("w:ascii"), qn("w:hAnsi"), qn("w:cs")):
                val = rf.get(key)
                if val:
                    return val
    if run.font.name:
        return run.font.name
    try:
        if para.style is not None and para.style.font.name:
            return para.style.font.name
    except Exception:
        pass
    return "宋体"


def _run_md(run, para: Paragraph) -> str:
    raw = run.text or ""
    if not raw:
        return ""
    if "\t" in raw:
        raw = raw.replace("\t", "    ")
    if _run_underlined(run) and not raw.strip():
        raw = "_" * max(len(raw), 6)
    text = raw
    if run.bold:
        text = f"**{text}**"
    if _run_underlined(run) and raw.strip():
        text = f"__{text}__"
    if run.italic:
        text = f"*{text}*"
    name = _run_font_name(run, para)
    pt = _run_font_size_pt(run, para)
    pt_s = f"{pt:g}pt"
    return f"{{{{{name}|{pt_s}}}}}{text}{{{{/}}}}"


def _indent_prefix(para: Paragraph, align: str) -> str:
    if align in ("center", "right"):
        return ""
    try:
        indent = para.paragraph_format.first_line_indent
        if indent and indent.pt >= 10:
            n = max(1, min(8, round(indent.pt / 12)))
            return "　" * n
    except Exception:
        pass
    return ""


def _para_md(para: Paragraph) -> str:
    parts = [_run_md(run, para) for run in para.runs]
    inline = "".join(parts)
    if not inline.strip():
        inline = (para.text or "").replace("\t", "    ")
    align = _alignment(para)
    inline = _indent_prefix(para, align) + inline.rstrip()
    if not inline.strip():
        return ""
    if align == "center":
        return f">>> {inline}"
    if align == "right":
        return f">> {inline}"
    return inline


def _is_heading(para: Paragraph, text: str) -> bool:
    compact = (text or "").strip()
    if not compact or len(compact) > 48:
        return False
    if "。" in compact:
        return False
    style = (para.style.name if para.style is not None else "") or ""
    if _parse_numbered(compact):
        return True
    if style.lower().startswith("heading"):
        return True
    if _alignment(para) == "center" and 2 <= len(_core(compact)) <= 24:
        return True
    return False


def _table_md(table: Table) -> str:
    rows: list[list[str]] = []
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            bits = [_para_md(p).lstrip("> ").strip() for p in cell.paragraphs]
            bits = [b for b in bits if b]
            cells.append(" ".join(bits).replace("|", "\\|"))
        rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    for r in rows:
        while len(r) < width:
            r.append("")
    lines = ["| " + " | ".join(r) + " |" for r in rows]
    lines.insert(1, "| " + " | ".join("---" for _ in range(width)) + " |")
    return "\n".join(lines)


def _table_plain(table: Table) -> str:
    bits: list[str] = []
    for row in table.rows:
        for cell in row.cells:
            t = " ".join(cell.text.split())
            if t:
                bits.append(t)
                break
        if len(bits) >= 4:
            break
    return " ".join(bits)


def _body_blocks(document) -> list[_Block]:
    out: list[_Block] = []
    blanks = 0
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            para = Paragraph(child, document)
            md = _para_md(para)
            text = (para.text or "").strip()
            if not text and not md:
                blanks += 1
                if blanks <= 3:
                    out.append(_Block("p", "", "", False))
                continue
            blanks = 0
            out.append(_Block("p", text, md, _is_heading(para, text)))
        elif child.tag == qn("w:tbl"):
            blanks = 0
            table = Table(child, document)
            md = _table_md(table)
            if md:
                out.append(_Block("tbl", _table_plain(table), md, False))
    while out and not out[-1].md and not out[-1].text:
        out.pop()
    return out


def _catalog_line(i: int, b: _Block) -> str:
    preview = re.sub(r"\s+", " ", b.text or "").strip()[:60]
    if b.kind == "tbl":
        return f"{i}\ttable\t{preview or '（表格）'}"
    if not preview:
        return f"{i}\tp\t（空行）"
    mark = "h" if b.heading else "p"
    return f"{i}\t{mark}\t{preview}"


def _catalog(blocks: list[_Block]) -> str:
    lines = [_catalog_line(i, b) for i, b in enumerate(blocks)]
    text = "\n".join(lines)
    if len(text) <= 48000:
        return text
    keep = [ln for ln in lines if "\th\t" in ln or "\ttable\t" in ln]
    extra = [ln for ln in lines if ln not in keep]
    # 保留全部标题/表格，正文预览抽稀，避免模型看不到格式件
    step = max(1, len(extra) // 400)
    mixed = keep + extra[::step]
    mixed.sort(key=lambda ln: int(ln.split("\t", 1)[0]))
    return "\n".join(mixed)[:48000]


def _parse_locate_json(text: str) -> list[dict]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [x for x in data["items"] if isinstance(x, dict)]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _locate_with_llm(blocks: list[_Block], titles: list[str], model_id: str | None) -> dict[str, tuple[int, int]]:
    from .llm import LlmError, chat_complete

    catalog = _catalog(blocks)
    title_lines = "\n".join(f"- {t}" for t in titles)
    user = (
        f"需要拷贝的商务标章节标题：\n{title_lines}\n\n"
        f"招标书正文清单（编号\\t类型\\t原文预览）：\n{catalog}\n"
    )
    try:
        text = chat_complete(
            model_id=model_id,
            messages=[
                {"role": "system", "content": _LOCATE_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            timeout=90,
        )
    except LlmError:
        logger.exception("locate tender form sections failed")
        return {}
    n = len(blocks)
    out: dict[str, tuple[int, int]] = {}
    by_title = {t: t for t in titles}
    by_core = {_core(t): t for t in titles}
    for item in _parse_locate_json(text):
        title = str(item.get("title") or "").strip()
        mapped = by_title.get(title) or by_core.get(_core(title))
        if not mapped:
            continue
        try:
            start = int(item.get("start"))
            end = int(item.get("end"))
        except (TypeError, ValueError):
            continue
        if start < 0 or end < start or start >= n:
            continue
        out[mapped] = (start, min(end, n - 1))
    return out


def _locate_fallback(blocks: list[_Block], titles: list[str]) -> dict[str, tuple[int, int]]:
    """模型不可用时：取标题最后一次作为独立标题出现的位置，拷到下一份同级标题前。"""
    out: dict[str, tuple[int, int]] = {}
    for title in titles:
        want = _core(title)
        hits: list[int] = []
        for i, b in enumerate(blocks):
            if not b.heading:
                continue
            if re.match(r"^[（(]\d+[）)]", (b.text or "").strip()):
                continue
            got = _core(b.text)
            if got == want or (want and got and (want in got or got in want) and abs(len(got) - len(want)) <= 6):
                hits.append(i)
        if not hits:
            continue
        start = hits[-1]
        if len(hits) >= 2 and hits[-1] - hits[-2] <= 2:
            start = hits[-2]
        end = len(blocks) - 1
        for j in range(start + 1, len(blocks)):
            b = blocks[j]
            if not b.heading:
                continue
            other = _core(b.text)
            if other == want or (other and want and (other in want or want in other)):
                continue
            parsed = _parse_numbered((b.text or "").strip())
            level = parsed[0] if parsed else 99
            # 只在「一、/第X章/附件」或短文件名标题处结束，不把 1. 2. 条款当下一章
            if level <= 2:
                end = j - 1
                break
            if not parsed and 2 <= len(other) <= 16:
                end = j - 1
                break
        out[title] = (start, end)
    return out


def _locate_ranges(
    blocks: list[_Block], titles: list[str], model_id: str | None
) -> dict[str, tuple[int, int]]:
    located = {}
    if model_id:
        located = _locate_with_llm(blocks, titles, model_id)
    missing = [t for t in titles if t not in located]
    if missing:
        located.update(_locate_fallback(blocks, missing))
    return located
