"""附录格式登记表：招标书「响应文件格式」里给出的承诺书、授权书、偏离表、报价表、团队表等，
按原文逐块登记（文字、Markdown、原始 OOXML），章节直接拷贝，不让模型重写。

登记表存在 draft.settings_json["formRegistry"]，条目：
{title, kind, md, ooxml: [xml...], table: bool}
章节节点用 formKeys 指向登记条目序号，一个章节可对应多份格式（如「法定代表人身份证明或授权委托书」）。
"""

from __future__ import annotations

import logging
import re

from lxml import etree

logger = logging.getLogger(__name__)

NO_FORM_NOTE = "招标书未提供本文件的固定格式，请按投标人自有格式提供并签字盖章。"

_ANCHOR = re.compile(r"(响应|投标)文件(参考)?(格式|附件|附录)|文件参考格式|格式附件|附件格式")
_KEY_ATTACH = re.compile(r"^(附件|附录|格式|附表|表)\s*[0-9一二三四五六七八九十]*\s*[:：、.．\s]?\s*\S")
_KEY_CN = re.compile(r"^[一二三四五六七八九十]+\s*[、.．]\s*\S")
_KEY_ARABIC = re.compile(r"^\d{1,2}\s*[、.．]\s*\S")
_KEY_PAREN = re.compile(r"^[（(][一二三四五六七八九十\d]+[）)]\s*\S")
_KEYS = (("attach", _KEY_ATTACH), ("cn", _KEY_CN), ("arabic", _KEY_ARABIC), ("paren", _KEY_PAREN))

_KIND_RULES = (
    ("deviation", re.compile(r"偏离|偏差|响应表|应答表")),
    ("quote", re.compile(r"报价|开标一览|价格表|分项")),
    ("team", re.compile(r"团队|人员|项目组|项目经理")),
    ("authority", re.compile(r"授权|身份证明|法定代表")),
    ("commitment", re.compile(r"承诺|声明|保证")),
)
_MAX_MD = 30000
_MAX_XML = 120000


_FORM_NUM_PREFIX = re.compile(r"^(?:附件|附录|附表|格式)\s*[0-9一二三四五六七八九十]*\s*[:：、.．]?\s*")


def display_form_title(title: str) -> str:
    """登记标题去掉「附件二」这类编号，作章节名。去完为空时保留原标题。"""
    text = (title or "").strip()
    stripped = _FORM_NUM_PREFIX.sub("", text).strip()
    return stripped or text


def classify_form(title: str) -> str:
    name = re.sub(r"\s+", "", title or "")
    for kind, pattern in _KIND_RULES:
        if pattern.search(name):
            return kind
    return "other"


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _title_core(text: str) -> str:
    from .tender_toc import strip_heading_prefix

    return re.sub(r"[\s（）()：:]", "", strip_heading_prefix(text or ""))


def _candidate_key(text: str) -> str:
    stripped = (text or "").strip()
    compact = _compact(stripped)
    if not (2 <= len(compact) <= 32) or re.search(r"[。；，,]", compact):
        return ""
    for name, pattern in _KEYS:
        if pattern.match(stripped):
            return name
    return ""


def _anchor_index(blocks: list) -> int:
    found = -1
    for i, block in enumerate(blocks):
        if block.kind != "p":
            continue
        compact = _compact(block.text)
        if 2 <= len(compact) <= 26 and _ANCHOR.search(compact):
            found = i
    return found


def scan_appendix_forms(docx_path: str) -> list[dict]:
    """确定性扫描：定位「响应文件格式」之后的各份格式。找不到锚点返回空列表。"""
    import docx

    from .tender_form import _body_blocks

    document = docx.Document(docx_path)
    blocks = _body_blocks(document)
    start = _anchor_index(blocks)
    if start < 0:
        return []
    tail = list(range(start + 1, len(blocks)))
    split_key = ""
    starts: list[int] = []
    for i in tail:
        block = blocks[i]
        if block.kind != "p":
            continue
        key = _candidate_key(block.text)
        if not key:
            continue
        if not split_key:
            split_key = key
        if key == split_key:
            starts.append(i)
    entries: list[dict] = []
    for n, first in enumerate(starts):
        last = (starts[n + 1] - 1) if n + 1 < len(starts) else len(blocks) - 1
        chunk = [blocks[i] for i in range(first, last + 1)]
        while chunk and not chunk[-1].md and not chunk[-1].text:
            chunk.pop()
        if not chunk:
            continue
        md = "\n".join(b.md for b in chunk).strip()
        title = chunk[0].text.strip()
        xml: list[str] = []
        total = 0
        for b in chunk:
            if b.el is None:
                continue
            piece = etree.tostring(b.el, encoding="unicode")
            total += len(piece)
            if total > _MAX_XML:
                xml = []
                break
            xml.append(piece)
        entries.append(
            {
                "title": title,
                "kind": classify_form(title),
                "md": md[:_MAX_MD],
                "ooxml": xml,
                "table": any(b.kind == "tbl" for b in chunk),
            }
        )
    return entries


def scan_forms_from_storage(storage_path: str) -> list[dict]:
    from .. import storage
    from .legacy_doc import DocConvertError, as_docx

    try:
        with storage.as_local(storage_path) as local:
            with as_docx(local) as word_path:
                return scan_appendix_forms(word_path)
    except DocConvertError:
        return []
    except Exception:  # noqa: BLE001 —— 扫描失败时走旧的按标题抽取，不阻断目录
        logger.exception("scan appendix forms failed")
        return []


def registry_light(registry: list[dict] | None) -> list[dict]:
    """给目录阶段用的轻量视图（不带 md 和 XML）。"""
    return [
        {"index": i, "title": str(e.get("title") or ""), "kind": str(e.get("kind") or "other")}
        for i, e in enumerate(registry or [])
        if isinstance(e, dict)
    ]


_SPLIT_PARTS = re.compile(r"[或及和与、/，,]")


def match_titles_to_forms(titles: list[str], registry: list[dict]) -> dict[str, list[int]]:
    """确定性映射：章节标题（可含「或」「及」）按组成部分与登记标题互相包含来对应，一对多。"""
    result: dict[str, list[int]] = {}
    cores = [_title_core(str(e.get("title") or "")) for e in registry]
    for title in titles:
        whole = _title_core(title)
        parts = [_title_core(p) for p in _SPLIT_PARTS.split(title or "")]
        parts = [p for p in parts if len(p) >= 2]
        hits: list[int] = []
        for index, core in enumerate(cores):
            if not core:
                continue
            if core == whole or (len(whole) >= 3 and (core in whole or whole in core) and core != ""):
                hits.append(index)
                continue
            if any(len(p) >= 3 and (p in core or core in p) for p in parts):
                hits.append(index)
        if hits:
            result[title] = hits
    return result


def make_form_mapper(model_id: str | None):
    """模型兜底：确定性没对上的组成条目，让模型在登记标题里选，没有对应格式就返回空。"""

    def mapper(titles: list[str], registry: list[dict]) -> dict[str, list[int]]:
        from .llm import LlmError, chat_complete
        from .tender_form import _parse_locate_json

        if not titles or not registry:
            return {}
        listed = "\n".join(f"{i}. {e.get('title')}" for i, e in enumerate(registry))
        pending = "\n".join(f"- {t}" for t in titles)
        try:
            text = chat_complete(
                model_id=model_id,
                messages=[
                    {
                        "role": "system",
                        "content": "你是投标文件编制助手。招标书附录给出了若干份固定格式。判断每个组成条目对应其中哪几份格式，"
                        "一个条目可对应多份，没有对应格式就给空数组，不要凭字面相近硬配。"
                        '只输出 JSON：{"items":[{"title":"与输入完全一致","forms":[序号]}]}。',
                    },
                    {"role": "user", "content": f"附录格式：\n{listed}\n\n组成条目：\n{pending}"},
                ],
                temperature=0.1,
                timeout=60,
            )
        except LlmError:
            return {}
        out: dict[str, list[int]] = {}
        for item in _parse_locate_json(text):
            title = str(item.get("title") or "").strip()
            forms = item.get("forms")
            if not isinstance(forms, list):
                continue
            picked = [int(x) for x in forms if isinstance(x, int) and 0 <= x < len(registry)]
            if picked:
                out[title] = picked
        return out

    return mapper


def apply_registry_to_tree(chapters: list[dict], registry: list[dict], mapper=None) -> list[str]:
    """目录树里能对上附录格式的章，标成 form、清掉下级、记下 formKeys。返回已对上的标题。"""
    from .e_writer import original_form_idea

    if not registry:
        return []
    nodes: list[dict] = []

    def collect(items: list[dict]) -> None:
        for node in items:
            if isinstance(node, dict):
                nodes.append(node)
                collect(node.get("children") or [])

    collect(chapters)
    titles = [str(n.get("title") or "").strip() for n in nodes]
    matched = match_titles_to_forms(titles, registry)
    pending = [
        str(n.get("title") or "").strip()
        for n in nodes
        if n.get("composition") and str(n.get("title") or "").strip() not in matched
    ]
    if pending and mapper:
        try:
            matched.update(mapper(pending, registry) or {})
        except Exception:  # noqa: BLE001
            logger.exception("form mapper failed")
    from .tender_toc import strip_heading_prefix

    def has_structure(node: dict) -> bool:
        """下级里有挂了招标条款的章节，说明这是真正要写的章，不能整章换成格式原文。"""
        stack = [c for c in (node.get("children") or []) if isinstance(c, dict)]
        while stack:
            child = stack.pop()
            if child.get("sourceRefs") or child.get("requirement"):
                return True
            stack.extend(c for c in (child.get("children") or []) if isinstance(c, dict))
        return False

    done: list[str] = []
    detached: set[int] = set()

    def descendants(node: dict) -> None:
        for child in node.get("children") or []:
            if isinstance(child, dict):
                detached.add(id(child))
                descendants(child)

    for node in nodes:
        title = str(node.get("title") or "").strip()
        keys = matched.get(title)
        if not keys or node.get("formKeys") or id(node) in detached:
            continue
        if has_structure(node):
            for key in keys:
                entry_title = display_form_title(str(registry[key].get("title") or ""))
                child = {"title": entry_title, "part": "form", "formKeys": [key], "children": []}
                child["idea"] = original_form_idea(entry_title, "", "")
                child["aiIdea"] = child["idea"]
                node.setdefault("children", []).append(child)
            done.append(title)
            continue
        descendants(node)
        node["formKeys"] = keys
        node["part"] = "form"
        node["children"] = []
        node.pop("sourceRefs", None)
        node["idea"] = original_form_idea(title, "", "")
        node["aiIdea"] = node["idea"]
        done.append(title)
    dedupe_form_nodes(chapters)
    return done


def dedupe_form_nodes(chapters: list[dict]) -> int:
    """同一份附录格式在整棵目录里只放一次：先到先得，后面重复的格式章去掉。返回去掉的章数。"""
    seen: set[int] = set()
    removed = 0

    def walk(items: list[dict]) -> list[dict]:
        nonlocal removed
        kept: list[dict] = []
        for node in items:
            if not isinstance(node, dict):
                kept.append(node)
                continue
            keys = [k for k in (node.get("formKeys") or []) if isinstance(k, int)]
            if keys:
                fresh = [k for k in keys if k not in seen]
                seen.update(fresh)
                if not fresh:
                    removed += 1
                    continue
                node["formKeys"] = fresh
            node["children"] = walk(node.get("children") or [])
            kept.append(node)
        return kept

    chapters[:] = walk(chapters)
    return removed


_AMOUNT_HEAD = re.compile(r"金额|单价|总价|合价|报价|价格|小计")
_NUM_HEAD = re.compile(r"序号|编号")
_REQ_HEAD = re.compile(r"招标要求|招标文件|需求|条款|参数|指标|内容|采购要求|技术要求")
_STATUS_HEAD = re.compile(r"响应情况|是否满足|响应结果|满足情况|投标响应|应答情况")
_HOW_HEAD = re.compile(r"实现方式|响应说明|应答说明|响应内容|投标文件应答|投标内容|佐证")
_DEV_STATE_HEAD = re.compile(r"偏离|偏差")


def _split_row(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells = re.split(r"(?<!\\)\|", body)
    return [c.strip() for c in cells]


def _plain_cell(cell: str) -> str:
    text = re.sub(r"#[cr]\d+#", "", cell or "")
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    text = re.sub(r"^>+\s*", "", text.strip())
    return re.sub(r"[*_`]", "", text).replace("<br>", "").strip()


def _find_table(lines: list[str]) -> tuple[int, int] | None:
    first = None
    for i, line in enumerate(lines):
        if line.strip().startswith("|"):
            if first is None:
                first = i
        elif first is not None:
            return first, i
    return (first, len(lines)) if first is not None else None


def _cell_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).replace("|", "\\|").strip()


def deviation_row_values(headers: list[str], index: int, entry: dict, record: dict | None) -> list[str]:
    """按表头文字决定每一列写什么。录入记录缺失时状态写「待填」。"""
    record = record or {}
    status = str(record.get("status") or "").strip()
    how = str(record.get("how") or "").strip()
    deviation = str(record.get("deviation") or "").strip()
    state = "无偏离" if status == "满足" else ("负偏离" if status in ("部分满足", "不满足") else "待填")
    row: list[str] = []
    for head in headers:
        if _NUM_HEAD.search(head):
            row.append(str(index))
        elif _DEV_STATE_HEAD.search(head) and "说明" in head:
            row.append(deviation or ("无" if state == "无偏离" else "待填"))
        elif _DEV_STATE_HEAD.search(head):
            row.append(state)
        elif _STATUS_HEAD.search(head):
            row.append(status or "待填")
        elif _HOW_HEAD.search(head):
            row.append(how or "待填")
        elif re.search(r"简述|摘要|概述|简要", head):
            row.append(_brief(str(entry.get("text") or "")))
        elif _REQ_HEAD.search(head):
            row.append(str(entry.get("text") or ""))
        else:
            row.append("")
    return [_cell_text(v) for v in row]


def _brief(text: str, limit: int = 40) -> str:
    """需求简述列：取条款第一个分句的前几十字，全文放在条款列。"""
    plain = re.sub(r"\s+", " ", text or "").strip()
    first = re.split(r"[：:；;。]", plain, maxsplit=1)[0] or plain
    return first[:limit]


def fill_deviation_form(md: str, rows: list[dict], responses: dict[str, dict]) -> str:
    """偏离表：表头、列、注释原样保留，数据行按每条要求逐行生成。没有表格时原样返回。"""
    lines = (md or "").split("\n")
    span = _find_table(lines)
    if not span or not rows:
        return md
    start, end = span
    table = lines[start:end]
    if len(table) < 2:
        return md
    head_cells = _split_row(table[0])
    headers = [_plain_cell(c) for c in head_cells]
    kept = table[:2]
    for line in table[2:]:
        cells = [_plain_cell(c) for c in _split_row(line)]
        filled = [c for c in cells if c]
        if filled and len(filled) >= max(2, len(cells) // 2) and not re.fullmatch(r"\d+", cells[0] or "x"):
            kept.append(line)
        else:
            break
    body = [
        "| " + " | ".join(deviation_row_values(headers, n, entry, responses.get(str(entry.get("id"))))) + " |"
        for n, entry in enumerate(rows, start=1)
    ]
    return "\n".join(lines[:start] + kept + body + lines[end:])


def fill_quote_form(md: str) -> str:
    """报价类表格：结构原样，金额列空格写「待填」，价格不由系统编。"""
    lines = (md or "").split("\n")
    span = _find_table(lines)
    if not span:
        return md
    start, end = span
    table = lines[start:end]
    if len(table) < 2:
        return md
    headers = [_plain_cell(c) for c in _split_row(table[0])]
    amount_cols = [i for i, h in enumerate(headers) if _AMOUNT_HEAD.search(h)]
    if not amount_cols:
        return md
    out = table[:2]
    for line in table[2:]:
        cells = _split_row(line)
        for col in amount_cols:
            if col < len(cells) and not _plain_cell(cells[col]):
                cells[col] = "待填"
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines[:start] + out + lines[end:])


def form_content(
    keys: list[int],
    registry: list[dict],
    ledger: list[dict] | None = None,
    responses: dict[str, dict] | None = None,
    filled: dict[str, str] | None = None,
) -> str:
    """一个章节对应的全部格式原文，偏离表按行填入，报价表金额写待填，团队表用已按资质库填好的内容，其余原样。"""
    parts: list[str] = []
    for key in keys:
        if not (0 <= key < len(registry)):
            continue
        entry = registry[key]
        md = str(entry.get("md") or "")
        kind = entry.get("kind")
        if kind == "team" and filled and str(filled.get(str(key)) or "").strip():
            parts.append(str(filled[str(key)]).strip())
            continue
        if kind == "deviation":
            volume = "business" if "商务" in str(entry.get("title") or "") else "tech"
            rows = [e for e in (ledger or []) if e.get("volume") == volume]
            md = fill_deviation_form(md, rows, responses or {})
        elif kind == "quote":
            md = fill_quote_form(md)
        parts.append(md.strip())
    return "\n\n".join(p for p in parts if p)


def pasted_matches_original(content: str, keys: list[int], registry: list[dict]) -> bool:
    """章节正文是否仍是登记原文（只比文字，忽略空白和标记；偏离表和报价表填入的内容不算改动）。"""
    def plain(text: str) -> str:
        t = re.sub(r"#[cr]\d+#|\{\{[^}]*\}\}|[|*_`\s]|<br>|-{3,}", "", text or "")
        return t

    body = plain(content)
    for key in keys:
        if not (0 <= key < len(registry)):
            continue
        entry = registry[key]
        if entry.get("kind") in ("deviation", "quote", "team"):
            # 团队表的数据行会被填入人员，只比开头的标题和表头
            head = plain(str(entry.get("md") or ""))[: 12 if entry.get("kind") == "team" else 30]
            if head and head not in body:
                return False
            continue
        original = plain(str(entry.get("md") or ""))
        if original and original not in body:
            return False
    return True


def has_kind(registry: list[dict] | None, kind: str) -> bool:
    return any(isinstance(e, dict) and e.get("kind") == kind for e in registry or [])


def ooxml_for_chapter(keys: list[int], registry: list[dict]) -> list[str]:
    out: list[str] = []
    for key in keys:
        if 0 <= key < len(registry):
            out.extend(registry[key].get("ooxml") or [])
    return out
