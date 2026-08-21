"""修改闭环（Review）用的辅助构建函数：把 docx 扁平段落分组为章节树，
把 ReviewFinding 锚定回具体段落，并把编辑器序列化出的 blocks 重新写回 docx。

不是预审引擎（不产生 Finding），仅供 routers/revision.py 复用。
"""

import difflib
import io
import re

import docx

_PARA_INDEX_RE = re.compile(r"段落\s*(\d+)")
_FUZZY_THRESHOLD = 0.35


def _heading_level(style_name: str, outline_level: int | None) -> int | None:
    """判断该段落是否为标题，返回 1/2/3；非标题返回 None。"""
    m = re.search(r"(?:Heading|标题)\s*(\d+)", style_name or "", re.IGNORECASE)
    if m:
        return min(max(int(m.group(1)), 1), 3)
    if outline_level is not None and outline_level <= 2:
        return outline_level + 1
    return None


def build_sections(paragraphs: list[dict]) -> list[dict]:
    """把 extract_paragraphs() 的扁平段落列表分组为 BidSection[]。

    非标题段落挂到最近一个标题所在的 section；文档开头若无标题，
    生成一个默认的「文档开头」占位 section 承接。
    """
    sections: list[dict] = []
    current: dict | None = None
    sec_seq = 0
    para_seq = 0

    for p in paragraphs:
        level = _heading_level(p.get("style", ""), p.get("outline_level"))
        if level is not None:
            sec_seq += 1
            current = {
                "id": f"sec-{sec_seq}",
                "heading": p["text"],
                "level": level,
                "paragraphs": [],
            }
            sections.append(current)
            continue

        if current is None:
            sec_seq += 1
            current = {
                "id": f"sec-{sec_seq}",
                "heading": "文档开头",
                "level": 1,
                "paragraphs": [],
            }
            sections.append(current)

        para_seq += 1
        current["paragraphs"].append(
            {
                "id": f"p-{para_seq}",
                "text": p["text"],
                "index": p["index"],
            }
        )

    return sections


def anchor_findings(sections: list[dict], issues: list[dict]) -> list[dict]:
    """把 issues（对齐 PreReviewIssueOut 字段）尽量锚定到 sections 里的具体段落上，
    写入 paragraph["problem"] = {issueId, highlight}。每个段落最多锚定一个问题
    （与前端 BidParagraph.problem 的单问题结构保持一致，先匹配先占用）。
    """
    all_paragraphs = [para for sec in sections for para in sec["paragraphs"]]
    used_para_ids: set[str] = set()

    for issue in issues:
        location = issue.get("location", "")
        excerpt = issue.get("excerpt", "")
        target = None

        m = _PARA_INDEX_RE.search(location)
        if m:
            idx = int(m.group(1))
            for para in all_paragraphs:
                if para["index"] == idx and para["id"] not in used_para_ids:
                    target = para
                    break

        if target is None and excerpt:
            best_ratio = 0.0
            best_para = None
            for para in all_paragraphs:
                if para["id"] in used_para_ids:
                    continue
                ratio = difflib.SequenceMatcher(None, excerpt, para["text"]).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_para = para
            if best_para is not None and best_ratio > _FUZZY_THRESHOLD:
                target = best_para

        if target is None:
            continue

        highlight = excerpt if excerpt and excerpt in target["text"] else target["text"]
        target["problem"] = {"issueId": issue["id"], "highlight": highlight}
        used_para_ids.add(target["id"])

    for sec in sections:
        for para in sec["paragraphs"]:
            para.pop("index", None)

    return sections


def blocks_to_docx(blocks: list[dict]) -> bytes:
    """把编辑器序列化出的 {type: heading|paragraph, level?, text} 顺序块重新写为 .docx。

    仅还原标题层级与纯文本段落，不还原粗体/表格/链接等 Lexical 高级样式（见计划"已知取舍"）。
    """
    document = docx.Document()
    for block in blocks:
        text = block.get("text", "")
        if block.get("type") == "heading":
            level = min(max(int(block.get("level") or 1), 1), 3)
            document.add_heading(text, level=level)
        else:
            document.add_paragraph(text)

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()
