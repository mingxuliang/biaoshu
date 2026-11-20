"""撰写助手自研工具的运行时：不引用 agentscope。

招标摘录落在隔离工作区，Skill 脚本只能点名执行，浏览器取材走边车 HTTP。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

TENDER_SECTION_MAX = 8000
TENDER_HIT_MAX = 4000
MATERIAL_TEXT_MAX = 12000
SCRIPT_TIMEOUT_SEC = 30
SCRIPT_OUTPUT_MAX = 8000

_SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SCRIPT_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*\.py$")
_SAFE_ARG = re.compile(r"^[A-Za-z0-9_./:=+\-@]{1,200}$")
_SECRET_ENV = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|PASS|CREDENTIAL|DATABASE_URL|REDIS_URL)", re.I)

_SECTIONS = ("tech", "business", "format")
_SECTION_FILES = {
    "tech": "tech.txt",
    "business": "business.txt",
    "format": "format.txt",
    "original": "original.txt",
}
_SECTION_TITLES = {
    "tech": "技术标应答需求",
    "business": "商务标应答",
    "format": "投标文件格式要求",
    "original": "招标书原文",
}
TENDER_ORIGINAL_PAGE_CHARS = TENDER_SECTION_MAX
_ITEM_MARKER = re.compile(r"^(?:（\d{1,2}）|\(\d{1,2}\)|\d{1,2}[、.．])")

DEFAULT_BROWSER_HOSTS = (
    "gov.cn,ccgp.gov.cn,ggzy.gov.cn,chinabidding.com,"
    "bidcenter.com.cn,duckduckgo.com,bing.com"
)


def skills_root() -> Path:
    return Path(__file__).resolve().parent / "writer_skills"


WATER_SKILL = "water-bid"


def skill_directories(track: str = "") -> list[str]:
    root = skills_root()
    if not root.is_dir():
        return []
    out: list[str] = []
    for path in sorted(root.iterdir()):
        if not (path.is_dir() and (path / "SKILL.md").is_file()):
            continue
        if path.name == WATER_SKILL and track != "water":
            continue
        out.append(str(path))
    return out


def format_requirements_text(items: list | None) -> str:
    lines: list[str] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        desc = str(item.get("desc") or "").strip()
        if title:
            lines.append(f"- {title}" + (f"：{desc}" if desc else ""))
    return "\n".join(lines)


def split_requirement_items(text: str) -> list[str]:
    """把应答摘要拆成完整条目。多条挤在一段里时按「1、」「2.」切开，不从句子中间截断。"""
    normalized = (text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return []
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    marked = [line for line in lines if _ITEM_MARKER.match(line)]
    if len(lines) > 1 and len(marked) >= (len(lines) + 1) // 2:
        return lines
    parts = re.split(r"(?<=[。；\s）)])(?=\d{1,2}[、.．](?!\d))", normalized)
    cleaned = [part.strip() for part in parts if part.strip()]
    return cleaned if len(cleaned) >= 2 else [normalized]


_CN_DIGITS = "零一二两三四五六七八九"
_UNIT = (
    r"%|％|个工作日|工作日|个月|小时|分钟|毫秒|秒钟|秒|天|日|周|月|年|人次|人|次|并发|万|条|项|种|个|级|套|台|路|页|倍|"
    r"GB|TB|MB|KB|ms|kb|mb|gb|tb"
)
_FACT_ARABIC = re.compile(rf"(?:[≥≤>＞<＜]|不少于|不低于|不超过|不大于|不小于|至少|最多)?\s*\d+(?:\.\d+)?\s*(?:{_UNIT}|[+＋])")
_FACT_CN = re.compile(rf"[一二两三四五六七八九十百千]+(?:{_UNIT})")
_FACT_VERSION = re.compile(r"[Vv]\d+(?:\.\d+)+")
_FACT_SPLIT = re.compile(r"^(?:[≥≤>＞<＜]|不少于|不低于|不超过|不大于|不小于|至少|最多)?\s*(\d+(?:\.\d+)?|[一二两三四五六七八九十百千]+)\s*(.+)$")


def _cn_to_int(text: str) -> int | None:
    value = text.strip()
    if not value or any(ch not in "一二两三四五六七八九十百千" for ch in value):
        return None
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    total = 0
    current = 0
    units = {"十": 10, "百": 100, "千": 1000}
    for ch in value:
        if ch in digits:
            current = digits[ch]
        else:
            total += (current or 1) * units[ch]
            current = 0
    return total + current


def _int_to_cn(number: int) -> str:
    if number < 0 or number > 99:
        return ""
    if number < 10:
        return _CN_DIGITS[number] if number else "零"
    tens, ones = divmod(number, 10)
    head = "十" if tens == 1 else _CN_DIGITS[tens] + "十"
    return head + (_CN_DIGITS[ones] if ones else "")


def extract_hard_facts(text: str, limit: int = 24) -> list[str]:
    """从招标条款里抽出必须原样应答的数字指标：数字加单位、百分比、时限、版本号。"""
    source = (text or "").replace("％", "%")
    found: list[str] = []
    generic_units = ("个", "项", "种", "条", "套", "台", "路", "页", "倍", "级", "次", "人")
    for pattern in (_FACT_ARABIC, _FACT_CN, _FACT_VERSION):
        for match in pattern.finditer(source):
            fact = re.sub(r"\s+", "", match.group(0))
            if not fact or fact in found:
                continue
            split = _FACT_SPLIT.match(fact)
            if split and split.group(2) in generic_units:
                raw = split.group(1)
                value = int(float(raw)) if raw.replace(".", "", 1).isdigit() else _cn_to_int(raw)
                if value is not None and value <= 2 and not re.search(r"[≥≤>＞<＜]|不少于|不低于|不超过|至少|最多", fact):
                    continue
            found.append(fact)
    # 去掉被更长指标完整包含的短指标（"99.9%" 里的 "9%"、"三天" 里的重复项）
    result = [fact for fact in found if not any(fact != other and fact in other for other in found)]
    return result[:limit]


def _fact_number_variants(number: str) -> list[str]:
    variants = [number]
    if number.isdigit():
        cn = _int_to_cn(int(number))
        if cn:
            variants.append(cn)
            if cn.startswith("二"):
                variants.append("两" + cn[1:])
    else:
        value = _cn_to_int(number)
        if value is not None:
            variants.append(str(value))
    return variants


def missing_hard_facts(facts: list[str], body: str) -> list[str]:
    """哪些指标在正文里找不到。数字允许中文/阿拉伯写法互换，数字和单位之间允许夹几个字。"""
    compact = re.sub(r"\s+", "", (body or "").replace("％", "%"))
    missing: list[str] = []
    for fact in facts:
        if fact in compact:
            continue
        split = _FACT_SPLIT.match(fact)
        if not split:
            missing.append(fact)
            continue
        number, unit = split.group(1), split.group(2)
        if unit in ("+", "＋"):
            # 「5500+」在正文里常写成「5500名以上」「不少于5500」，只要数字本身出现即可
            if any(
                re.search(rf"(?<![\d.]){re.escape(variant)}(?![\d])", compact)
                for variant in _fact_number_variants(number)
            ):
                continue
            missing.append(fact)
            continue
        if any(
            re.search(re.escape(variant) + r".{0,4}?" + re.escape(unit), compact)
            for variant in _fact_number_variants(number)
        ):
            continue
        missing.append(fact)
    return missing


_ITEM_PREFIX = {"tech": "T", "business": "B"}


def numbered_requirement_items(text: str, section: str) -> list[tuple[str, str]]:
    """给应答条目编号：技术标 T1、T2……，商务标 B1、B2……。

    read_tender 返回的编号和代码侧绑定条款用的是同一个函数，编号只取决于条目在摘要里的顺序。
    """
    prefix = _ITEM_PREFIX.get(section, "")
    if not prefix:
        return []
    return [(f"{prefix}{index}", item) for index, item in enumerate(split_requirement_items(text), start=1)]


def requirement_item_map(extracts: dict[str, str] | None) -> dict[str, str]:
    """编号 -> 条目原文，技术标和商务标合在一张表里。"""
    data = extracts or {}
    result: dict[str, str] = {}
    for section in _ITEM_PREFIX:
        for item_id, item in numbered_requirement_items(str(data.get(section) or ""), section):
            result[item_id] = item
    return result


_REF_LINE = re.compile(r"^\s*(?:[-*>]\s*)?(?:依据|条目依据|对应条目)\s*[:：]\s*(.+?)\s*$")
_REF_RANGE = re.compile(r"([TBtb])\s*(\d{1,3})\s*[-~—至到]\s*[TBtb]?\s*(\d{1,3})")
_REF_ID = re.compile(r"([TBtb])\s*(\d{1,3})")


def parse_source_refs(line: str) -> list[str] | None:
    """目录里的「依据：T5,T6」行 -> ["T5", "T6"]。不是依据行返回 None。"""
    match = _REF_LINE.match(line or "")
    if not match:
        return None
    body = match.group(1)
    refs: list[str] = []
    for prefix, start, end in _REF_RANGE.findall(body):
        lo, hi = sorted((int(start), int(end)))
        if hi - lo <= 40:
            refs.extend(f"{prefix.upper()}{n}" for n in range(lo, hi + 1))
    body_no_range = _REF_RANGE.sub(" ", body)
    refs.extend(f"{p.upper()}{n}" for p, n in _REF_ID.findall(body_no_range))
    seen: set[str] = set()
    ordered = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            ordered.append(ref)
    return ordered


def outline_cited_ids(markdown: str) -> set[str]:
    cited: set[str] = set()
    for line in (markdown or "").splitlines():
        refs = parse_source_refs(line)
        if refs:
            cited.update(refs)
    return cited


def _numbered_line(item_id: str, item: str) -> str:
    return f"【{item_id}】{item}"


def _page_complete_items(items: list[str], page: int, limit: int) -> tuple[str, int, int]:
    """按整条装进页。单条超过上限时单独成页，不把这一条切碎。"""
    pages: list[list[str]] = []
    current: list[str] = []
    size = 0
    for item in items:
        extra = len(item) + (1 if current else 0)
        if current and size + extra > limit:
            pages.append(current)
            current = [item]
            size = len(item)
        else:
            current.append(item)
            size += extra
    if current:
        pages.append(current)
    if not pages:
        return "", 1, 1
    total = len(pages)
    page_no = max(1, min(int(page or 1), total))
    return "\n".join(pages[page_no - 1]), page_no, total


def load_tender_extracts(project_id: str) -> dict[str, str]:
    """从最新解析清单读取三段应答材料。不经过 tasks，避免循环导入。"""
    from ..db import SessionLocal

    empty = {"tech": "", "business": "", "format": ""}
    pid = (project_id or "").strip()
    if not pid:
        return empty
    db = SessionLocal()
    try:
        from .rules_config import select_checklist

        checklist = select_checklist(db, pid)
        data = (checklist.checklist_json or {}) if checklist else {}
        if not isinstance(data, dict):
            data = {}
        formats = data.get("formatRequirements") or []
        if not isinstance(formats, list):
            formats = []
        return {
            "tech": str(data.get("techBidResponseRequirements") or "").strip(),
            "business": str(data.get("businessBidResponse") or "").strip(),
            "format": format_requirements_text(formats),
        }
    finally:
        db.close()


SUPPLEMENT_HEAD = {
    "addendum": "【补遗/澄清文件（与招标正文不一致时以本文件为准）】",
    "boq": "【工程量清单/报价清单】",
}


def load_supplement_text(project_id: str, limit: int = 60000) -> str:
    """同项目补遗、澄清和清单文件的正文。补遗放在前面，口径以补遗为准。没有这类文件返回空串。"""
    pid = (project_id or "").strip()
    if not pid:
        return ""
    from .. import storage
    from ..db import SessionLocal
    from ..models import TenderDocument
    from .docx_extract import extract_document_plain_text, extract_full_text

    db = SessionLocal()
    try:
        docs = (
            db.query(TenderDocument)
            .filter(TenderDocument.project_id == pid, TenderDocument.kind.in_(("addendum", "boq")))
            .order_by(TenderDocument.uploaded_at.asc())
            .all()
        )
        entries = [(d.kind, d.filename, d.storage_path) for d in docs if d.storage_path and storage.exists(d.storage_path)]
    finally:
        db.close()
    blocks: list[str] = []
    for kind, filename, path in sorted(entries, key=lambda e: 0 if e[0] == "addendum" else 1):
        try:
            with storage.as_local(path) as local:
                try:
                    body = (extract_document_plain_text(local) or "").strip()
                except Exception:
                    body = (extract_full_text(local) or "").strip()
        except Exception:
            continue
        if body:
            blocks.append(f"{SUPPLEMENT_HEAD.get(kind, '【附加文件】')}《{filename}》\n{body[:limit]}")
    return "\n\n".join(blocks)


def load_original_tender_text(project_id: str) -> str:
    """读取招标正文，后面接补遗和清单。对话工作区和目录任务共用，避免只剩三段抽取摘要。"""
    main = _load_main_tender_text(project_id)
    extra = load_supplement_text(project_id)
    return f"{main}\n\n{extra}".strip() if extra else main


def _load_main_tender_text(project_id: str) -> str:
    pid = (project_id or "").strip()
    if not pid:
        return ""
    from .. import storage
    from ..db import SessionLocal
    from ..models import TenderDocument
    from .docx_extract import extract_document_plain_text, extract_full_text

    db = SessionLocal()
    try:
        from .rules_config import select_checklist

        checklist = select_checklist(db, pid)
        doc = None
        if checklist and checklist.tender_document_id:
            doc = db.get(TenderDocument, checklist.tender_document_id)
        if doc is None:
            doc = (
                db.query(TenderDocument)
                .filter(TenderDocument.project_id == pid)
                .order_by(TenderDocument.uploaded_at.desc())
                .first()
            )
        path = doc.storage_path if doc and doc.storage_path and storage.exists(doc.storage_path) else ""
    finally:
        db.close()
    if not path:
        return ""
    try:
        with storage.as_local(path) as local:
            try:
                return (extract_document_plain_text(local) or "").strip()
            except Exception:
                return (extract_full_text(local) or "").strip()
    except Exception:
        return ""


def materialize_tender_extracts(workdir: Path, extracts: dict[str, str] | None) -> Path:
    folder = Path(workdir) / "tender"
    folder.mkdir(parents=True, exist_ok=True)
    payload = extracts or {}
    for key in _SECTIONS:
        text = str(payload.get(key) or "").strip()
        (folder / _SECTION_FILES[key]).write_text(text, encoding="utf-8")
    return folder


def materialize_full_tender_text(workdir: Path, text: str) -> Path:
    """把招标书原文（不截断）落地，供 read_tender(section="original") 分页通读。"""
    folder = Path(workdir) / "tender"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / _SECTION_FILES["original"]).write_text((text or "").strip(), encoding="utf-8")
    return folder


def original_tender_page_count(text: str) -> int:
    length = len((text or "").strip())
    if length <= 0:
        return 0
    return max(1, (length + TENDER_ORIGINAL_PAGE_CHARS - 1) // TENDER_ORIGINAL_PAGE_CHARS)


def materialize_outline_snapshot(workdir: Path, outline: list | None) -> None:
    lines = []
    for node in outline or []:
        if not isinstance(node, dict):
            continue
        lines.append(f"- {node.get('id')} {node.get('num') or ''} {node.get('title') or ''}".strip())
    (Path(workdir) / "outline.txt").write_text("\n".join(lines[:120]), encoding="utf-8")


def _read_section_file(workdir: Path, section: str) -> str:
    path = Path(workdir) / "tender" / _SECTION_FILES[section]
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _extracts_from_workdir(workdir: Path) -> dict[str, str]:
    data = {key: _read_section_file(workdir, key) for key in _SECTIONS}
    data["original"] = _read_section_file(workdir, "original")
    return data


def _search_original(text: str, query: str, page: int) -> str:
    body = (text or "").strip()
    title = _SECTION_TITLES["original"]
    if not body:
        return f"【{title}】（空，尚未提供招标书原文）"
    needle = re.sub(r"\s+", "", (query or "").strip())
    if needle:
        hits = [line.strip() for line in body.splitlines() if needle in re.sub(r"\s+", "", line)]
        if not hits:
            return f"【{title}】未命中「{query.strip()}」"
        text_out = "\n".join(hits[:40])
        if len(text_out) > TENDER_HIT_MAX:
            text_out = text_out[:TENDER_HIT_MAX] + "\n……（已截断）"
        return f"【{title}】命中 {min(len(hits), 40)} 行\n{text_out}"
    total_pages = max(1, (len(body) + TENDER_ORIGINAL_PAGE_CHARS - 1) // TENDER_ORIGINAL_PAGE_CHARS)
    page_no = max(1, min(int(page or 1), total_pages))
    start = (page_no - 1) * TENDER_ORIGINAL_PAGE_CHARS
    chunk = body[start : start + TENDER_ORIGINAL_PAGE_CHARS]
    if page_no < total_pages:
        tail = f"\n……（第 {page_no}/{total_pages} 页，还没读完，请把 page 改成 {page_no + 1} 继续调用 read_tender 通读）"
    else:
        tail = f"\n（第 {page_no}/{total_pages} 页，原文到此结束）"
    return f"【{title}】第 {page_no}/{total_pages} 页\n{chunk}{tail}"


def search_tender_text(extracts: dict[str, str], section: str = "all", query: str = "", page: int = 1) -> str:
    wanted = (section or "all").strip().lower() or "all"
    if wanted == "original":
        return _search_original(str(extracts.get("original") or ""), query, page)
    if wanted not in ("all", *_SECTIONS):
        return "section 只能是 tech、business、format、original 或 all"
    keys = list(_SECTIONS) if wanted == "all" else [wanted]
    needle = re.sub(r"\s+", "", (query or "").strip())
    blocks: list[str] = []
    for key in keys:
        title = _SECTION_TITLES[key]
        body = str(extracts.get(key) or "").strip()
        if not body:
            blocks.append(f"【{title}】（空）")
            continue
        numbered = numbered_requirement_items(body, key)
        if numbered:
            note = "（每条前的【T1】是条目编号，目录里用「依据：T1」引用）\n"
        else:
            note = ""
        if not needle:
            if numbered:
                lines_all = [_numbered_line(item_id, item) for item_id, item in numbered]
                full = "\n".join(lines_all)
            else:
                lines_all = split_requirement_items(body)
                full = body
            if len(full) <= TENDER_SECTION_MAX:
                blocks.append(f"【{title}】\n{note}{full}")
                continue
            chunk, page_no, total_pages = _page_complete_items(lines_all, page, TENDER_SECTION_MAX)
            chunk = note + chunk
            if page_no < total_pages:
                tail = (
                    f"\n……（第 {page_no}/{total_pages} 页，条目还没列完，"
                    f"请把 page 改成 {page_no + 1} 继续调用 read_tender）"
                )
            else:
                tail = f"\n（第 {page_no}/{total_pages} 页，条目到此结束）"
            blocks.append(f"【{title}】第 {page_no}/{total_pages} 页\n{chunk}{tail}")
            continue
        hits: list[str] = []
        if numbered:
            for item_id, item in numbered:
                if needle not in re.sub(r"\s+", "", item):
                    continue
                matched = [ln.strip() for ln in item.splitlines() if needle in re.sub(r"\s+", "", ln)]
                hits.extend(_numbered_line(item_id, ln) for ln in (matched or [item.strip()]))
        else:
            for line in body.splitlines():
                if needle in re.sub(r"\s+", "", line):
                    hits.append(line.strip())
        if not hits:
            blocks.append(f"【{title}】未命中「{query.strip()}」")
            continue
        text = "\n".join(hits[:40])
        if len(text) > TENDER_HIT_MAX:
            text = text[:TENDER_HIT_MAX] + "\n……（已截断）"
        blocks.append(f"【{title}】命中 {min(len(hits), 40)} 行\n{text}")
    return "\n\n".join(blocks) if blocks else "没有招标摘录"


def read_tender_text(
    workdir: Path, project_id: str = "", section: str = "all", query: str = "", page: int = 1
) -> str:
    extracts = _extracts_from_workdir(workdir)
    wanted = (section or "all").strip().lower() or "all"
    pid = (project_id or "").strip()
    needs_extracts = wanted in ("all", *_SECTIONS)
    if pid and needs_extracts and not any(extracts.get(key) for key in _SECTIONS):
        extracts.update(load_tender_extracts(pid))
        materialize_tender_extracts(workdir, extracts)
    if pid and wanted in ("original", "all") and not str(extracts.get("original") or "").strip():
        original = load_original_tender_text(pid)
        if original:
            materialize_full_tender_text(workdir, original)
            extracts["original"] = original
    return search_tender_text(extracts, section, query, page)


def resolve_skill_script(skill: str, script: str) -> Path:
    name = (skill or "").strip()
    filename = os.path.basename((script or "").strip())
    if not _SKILL_NAME.match(name):
        raise ValueError("无效的 skill 名称")
    if not _SCRIPT_NAME.match(filename):
        raise ValueError("只能执行 Skill 目录里的 .py 脚本")
    root = skills_root().resolve()
    path = (root / name / "scripts" / filename).resolve()
    try:
        path.relative_to(root / name / "scripts")
    except ValueError as exc:
        raise ValueError("脚本路径越界") from exc
    if not path.is_file():
        raise ValueError(f"没有这个脚本：{name}/scripts/{filename}")
    return path


def _script_env(workdir: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not _SECRET_ENV.search(key)}
    backend_root = str(Path(__file__).resolve().parents[2])
    previous = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = backend_root if not previous else backend_root + os.pathsep + previous
    env["WRITER_WORKSPACE"] = str(Path(workdir).resolve())
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def run_skill_script(workdir: Path, skill: str, script: str, args: list[str] | None = None) -> str:
    try:
        path = resolve_skill_script(skill, script)
    except ValueError as exc:
        return str(exc)
    argv = []
    for item in args or []:
        text = str(item).strip()
        if not text:
            continue
        if not _SAFE_ARG.match(text):
            return f"参数不安全，已拒绝：{text[:80]}"
        argv.append(text)
    try:
        completed = subprocess.run(
            [sys.executable, str(path), *argv],
            cwd=str(Path(workdir).resolve()),
            env=_script_env(workdir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SCRIPT_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "脚本超时（30 秒）"
    except OSError as exc:
        return f"脚本无法启动：{exc}"
    output = ((completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")).strip()
    if completed.returncode != 0 and not output:
        output = f"脚本退出码 {completed.returncode}"
    if len(output) > SCRIPT_OUTPUT_MAX:
        output = output[:SCRIPT_OUTPUT_MAX] + "\n……（已截断）"
    return output or "脚本没有输出"


def browser_settings() -> tuple[str, float, list[str]]:
    from ..config import get_settings

    settings = get_settings()
    base = str(getattr(settings, "writer_browser_url", "") or "").strip().rstrip("/")
    try:
        timeout = float(getattr(settings, "writer_browser_timeout_sec", 25) or 25)
    except (TypeError, ValueError):
        timeout = 25.0
    raw = str(getattr(settings, "writer_browser_hosts", "") or "").strip() or DEFAULT_BROWSER_HOSTS
    hosts = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return base, timeout, hosts


def host_allowed(url: str, hosts: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    for allowed in hosts:
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def _material_name(prefix: str, hint: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "-", (hint or "material").strip())[:40].strip("-") or "material"
    return f"{prefix}-{slug}.txt"


def list_materials(workdir: Path) -> str:
    folder = Path(workdir) / "materials"
    if not folder.is_dir():
        return "暂无取材"
    names = sorted(path.name for path in folder.glob("*.txt"))
    if not names:
        return "暂无取材"
    return "已保存的取材：\n" + "\n".join(f"- {name}" for name in names[:40])


def read_material_text(workdir: Path, filename: str = "") -> str:
    folder = (Path(workdir) / "materials").resolve()
    target = (filename or "").strip()
    if not target:
        return list_materials(workdir)
    name = os.path.basename(target)
    path = (folder / name).resolve()
    try:
        path.relative_to(folder)
    except ValueError:
        return "没有这份取材"
    if not path.is_file():
        return "没有这份取材"
    text = path.read_text(encoding="utf-8", errors="ignore")
    if len(text) > MATERIAL_TEXT_MAX:
        return text[:MATERIAL_TEXT_MAX] + "\n……（已截断）"
    return text


def collect_material(workdir: Path, action: str = "", query: str = "", url: str = "") -> str:
    verb = (action or "").strip().lower()
    if verb in ("", "list"):
        return list_materials(workdir)
    if verb == "read":
        return read_material_text(workdir, query or url)
    if verb not in ("search", "fetch"):
        return "action 只能是 search、fetch、list 或 read"
    base, timeout, hosts = browser_settings()
    if not base:
        return "浏览器未启用"
    payload = {"action": verb, "query": (query or "").strip(), "url": (url or "").strip()}
    if verb == "fetch":
        if not payload["url"]:
            return "fetch 需要 url"
        if not host_allowed(payload["url"], hosts):
            return "该网址不在取材白名单"
    elif not payload["query"]:
        return "search 需要 query"
    try:
        import httpx

        from ..config import get_settings

        token = (get_settings().writer_browser_token or "").strip()
        response = httpx.post(
            f"{base}/collect",
            json=payload,
            timeout=timeout,
            headers={"X-Writer-Browser-Token": token} if token else {},
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:  # noqa: BLE001 —— 边车故障时对话继续
        return f"浏览器未启用：{exc}"
    if not isinstance(data, dict):
        return "浏览器返回无法解析"
    if data.get("error"):
        return str(data.get("error"))
    text = str(data.get("text") or "").strip()
    source = str(data.get("source") or payload["url"] or payload["query"]).strip()
    if not text:
        return f"没有从 {source} 取到正文"
    folder = Path(workdir) / "materials"
    folder.mkdir(parents=True, exist_ok=True)
    name = _material_name(verb, payload["query"] or payload["url"] or "page")
    saved = f"来源：{source}\n\n{text[:MATERIAL_TEXT_MAX]}"
    (folder / name).write_text(saved, encoding="utf-8")
    preview = text[:1200]
    if len(text) > 1200:
        preview += "\n……（全文已存入 materials）"
    return f"已保存 {name}\n来源：{source}\n\n{preview}"


def export_readiness_notes(outline: list[dict], contents: dict, image_ids: set[str]) -> list[str]:
    """导出前检查：技术叶子章没有正文、引用的图片已不存在。只提示，不阻止导出。"""
    import re

    from .e_writer import chapter_kind

    parents = {str(n.get("parentId")) for n in outline if isinstance(n, dict) and n.get("parentId")}
    notes: list[str] = []
    for node in outline:
        if not isinstance(node, dict) or not node.get("id"):
            continue
        text = str(contents.get(node["id"]) or "")
        title = f"{node.get('num') or ''} {node.get('title') or ''}".strip()
        if str(node["id"]) not in parents and not text.strip():
            kind = chapter_kind(
                str(node.get("title") or ""), node.get("part"), str(node.get("idea") or ""), str(node.get("requirement") or "")
            )
            if kind in ("tech", "response"):
                notes.append(f"「{title}」还没有正文")
        for image_id in re.findall(r"\(/api/writer-images/([^/\s)]+)/file\)", text):
            if image_id not in image_ids:
                notes.append(f"「{title}」引用的图片 {image_id} 已不存在")
    return notes


def export_bound_draft(user_id: str, draft_id: str) -> str:
    from fastapi import HTTPException
    from sqlalchemy.orm.attributes import flag_modified

    from .. import storage
    from ..db import SessionLocal
    from ..models import BidDocument, Project, User, WriterDraft, WriterImage
    from ..permissions import PERM_WRITER, require_project
    from .writer_export import build_draft_export

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        draft = db.get(WriterDraft, draft_id)
        if user is None or draft is None:
            return "草稿不存在"
        try:
            require_project(db, user, draft.project_id, PERM_WRITER)
        except HTTPException as exc:
            return str(exc.detail)
        if not draft.outline_json:
            return "尚无目录内容，请先生成目录后再导出"
        images = db.query(WriterImage).filter(WriterImage.project_id == draft.project_id).all()
        refs = {img.id: img.storage_path for img in images}
        from .submission_check import refresh_forms

        refresh_forms(db, draft)
        notes = export_readiness_notes(draft.outline_json or [], draft.chapter_contents_json or {}, set(refs))
        docx_bytes, display_name, doc_kind = build_draft_export(db, draft)
        key = storage.put_bytes(f"bid-documents/{draft.project_id}", docx_bytes, ".docx")
        doc = BidDocument(
            project_id=draft.project_id,
            filename=display_name,
            storage_path=key,
            size_bytes=len(docx_bytes),
            source="writer",
            kind=doc_kind,
        )
        db.add(doc)
        db.commit()
        del flag_modified
        tail = ("\n导出前检查发现：\n" + "\n".join(f"- {item}" for item in notes[:12])) if notes else "\n导出前检查：章节和图片齐全。"
        return f"已导出 Word《{display_name}》，文档 id {doc.id}。请在撰写工作台下载，不要手写 docx。{tail}"
    except Exception as exc:  # noqa: BLE001 —— 工具失败要告诉模型
        db.rollback()
        return f"导出失败：{exc}"
    finally:
        db.close()


def read_ledger_text(project_id: str, query: str = "", page: int = 1, size: int = 40) -> str:
    """需求台账：编号、类型、是否必须、出处、逐字原文。query 为空时分页列出，否则按关键词或编号过滤。"""
    from .req_ledger import full_project_ledger

    ledger = full_project_ledger(project_id)
    if not ledger:
        return "台账为空：还没有抽取到技术标、商务标应答条目。"
    key = (query or "").strip()
    rows = [
        e
        for e in ledger
        if not key or key.upper() == str(e["id"]).upper() or key in e["text"] or key in str(e.get("source") or "")
    ]
    total = max(1, (len(rows) + size - 1) // size)
    page_no = max(1, min(int(page or 1), total))
    lines = [f"台账共 {len(ledger)} 条，命中 {len(rows)} 条，第 {page_no}/{total} 页："]
    for e in rows[(page_no - 1) * size : page_no * size]:
        flag = "★必须" if e.get("mandatory") else "一般"
        src = f" 出处：{e['source']}" if e.get("source") else ""
        lines.append(f"【{e['id']}】[{e.get('kind')}·{flag}]{src}\n{e['text']}")
    return "\n".join(lines)


def _project_settings(project_id: str) -> list[dict]:
    from ..db import SessionLocal
    from ..models import WriterDraft

    db = SessionLocal()
    try:
        return [
            dict(d.settings_json) if isinstance(d.settings_json, dict) else {}
            for d in db.query(WriterDraft).filter(WriterDraft.project_id == project_id).all()
        ]
    finally:
        db.close()


def read_form_registry_text(project_id: str, index: int = -1) -> str:
    """附录格式登记表：给标题、类别；给 index 时返回该份格式的原文 Markdown。"""
    registry: list[dict] = []
    for settings in _project_settings(project_id):
        if isinstance(settings.get("formRegistry"), list) and settings["formRegistry"]:
            registry = settings["formRegistry"]
            break
    if not registry:
        return "本项目没有登记附录格式：招标书没有给出响应文件格式，或尚未生成目录。"
    if index is not None and int(index) >= 0:
        if int(index) >= len(registry):
            return f"序号超出范围，共 {len(registry)} 份。"
        entry = registry[int(index)]
        return f"《{entry.get('title')}》（{entry.get('kind')}）原文：\n{entry.get('md')}"
    return "\n".join(
        f"{i}. {e.get('title')}（{e.get('kind')}{'，含表格' if e.get('table') else ''}）" for i, e in enumerate(registry)
    )


def match_qualification_text(project_id: str, requirement: str) -> str:
    """按一条招标要求查企业资质证照库（只含已入库材料）：命中的条目 id 与字段、库内缺失的数量。只读。"""
    from ..db import SessionLocal
    from ..models import WriterDraft
    from . import business_materials

    db = SessionLocal()
    try:
        draft = db.query(WriterDraft).filter(WriterDraft.project_id == project_id).first()
        return business_materials.match_text(db, "", requirement, draft.model_id if draft else None)
    finally:
        db.close()


def match_product_text(project_id: str, requirement: str, limit: int = 6) -> str:
    """列出产品库里与要求最接近的功能点和应标原文摘要，供判断「有没有标品可用」。只读。"""
    from sqlalchemy.orm import selectinload

    from ..db import SessionLocal
    from ..models import ProductFeature, WriterDraft
    from .standard_product import rank_features

    db = SessionLocal()
    try:
        library_id = ""
        for d in db.query(WriterDraft).filter(WriterDraft.project_id == project_id).all():
            if d.selected_product_library_id:
                library_id = d.selected_product_library_id
                break
        if not library_id:
            return "本项目没有选择产品库，没有标准产品可匹配，请自行撰写并如实标注。"
        rows = (
            db.query(ProductFeature)
            .options(selectinload(ProductFeature.images))
            .filter(ProductFeature.library_id == library_id)
            .all()
        )
        rows = [f for f in rows if (f.status or "待审核") != "已停用"]
        picked = rank_features(rows, requirement or "", int(limit or 6))
        if not picked:
            return "产品库里没有与该要求对应的功能点。"
        lines = []
        for f in picked:
            copy = (f.bid_copy or f.intro or "").strip().replace("\n", " ")[:160]
            lines.append(f"- {f.name}（{f.module or '未分模块'}，原图 {len(f.images or [])} 张）：{copy}")
        return "\n".join(lines)
    finally:
        db.close()


def record_response_text(workdir: Path, item_id: str, status: str, how: str = "", deviation: str = "") -> str:
    """记录某条要求的应答结论到工作区 responses.json，章节验收和偏离表按它核对。"""
    import json

    item = (item_id or "").strip().upper()
    if not re.fullmatch(r"[TB]\d{1,3}", item):
        return "item_id 必须是台账编号，例如 T5 或 B3。"
    if status not in ("满足", "部分满足", "不满足"):
        return "status 只能是 满足、部分满足、不满足。"
    path = Path(workdir) / "responses.json"
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    data[item] = {"status": status, "how": how[:300], "deviation": deviation[:200]}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return f"已记录 {item}：{status}"


def persist_response(draft_id: str, item_id: str, status: str, how: str = "", deviation: str = "") -> bool:
    """把智能体记录的应答结论写进草稿 settings.responses，偏离表和追溯矩阵读的是这里。"""
    from sqlalchemy.orm.attributes import flag_modified

    from ..db import SessionLocal
    from ..models import WriterDraft

    item = (item_id or "").strip().upper()
    if not draft_id or not re.fullmatch(r"[TB]\d{1,3}", item) or status not in ("满足", "部分满足", "不满足"):
        return False
    db = SessionLocal()
    try:
        row = (
            db.query(WriterDraft).filter(WriterDraft.id == draft_id).with_for_update().populate_existing().first()
        )
        if row is None:
            return False
        settings = dict(row.settings_json or {}) if isinstance(row.settings_json, dict) else {}
        responses = dict(settings.get("responses") or {})
        current = dict(responses.get(item) or {})
        current.update({"status": status, "how": how[:300], "deviation": deviation[:200]})
        responses[item] = current
        settings["responses"] = responses
        row.settings_json = settings
        flag_modified(row, "settings_json")
        db.commit()
        return True
    except Exception:  # noqa: BLE001 —— 落库失败不影响本轮写作，工作区文件仍保留
        db.rollback()
        return False
    finally:
        db.close()
