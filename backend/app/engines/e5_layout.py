"""E5 版式终审引擎（对应青天第五层「最终一键终审」，前端 L5）。

全部基于 Word OOXML 文档对象模型直接检查，不调用大模型，确保这一层零幻觉、可复现。
"""

from .docx_extract import extract_paragraphs, get_core_author, has_revision_marks, has_toc_field

HEADING_PREFIX = "Heading "


def _finding(severity: str, location: str, excerpt: str, rule: str, suggestion: str, tender_quote: str = "") -> dict:
    return {
        "engine": "e5_layout",
        "level": "L5",
        "severity": severity,
        "location": location,
        "excerpt": excerpt,
        "rule": rule,
        "tenderQuote": tender_quote,
        "suggestion": suggestion,
        "confidence": 0.9,
    }


def _outline_from_style(style_name: str) -> int | None:
    if style_name and style_name.startswith(HEADING_PREFIX):
        try:
            return int(style_name.replace(HEADING_PREFIX, "").strip())
        except ValueError:
            return None
    return None


def run(path: str, paragraphs: list[dict] | None = None) -> list[dict]:
    findings: list[dict] = []
    paragraphs = paragraphs if paragraphs is not None else extract_paragraphs(path)

    levels_seen = [lvl for lvl in (_outline_from_style(p["style"]) for p in paragraphs) if lvl is not None]
    for i in range(1, len(levels_seen)):
        if levels_seen[i] - levels_seen[i - 1] > 1:
            findings.append(
                _finding(
                    severity="建议",
                    location="全文 / 标题层级",
                    excerpt=f"检测到标题层级从 Heading {levels_seen[i - 1]} 跳到 Heading {levels_seen[i]}",
                    rule="F06.06 版式终审-标题连续性",
                    suggestion="补齐中间层级标题，保持三级标题编号连续（1 → 1.1 → 1.1.1）",
                )
            )
            break

    has_catalog_heading = any("目录" in p["text"] and len(p["text"]) < 10 for p in paragraphs)
    if has_catalog_heading and not has_toc_field(path):
        findings.append(
            _finding(
                severity="建议",
                location="全文 / 目录",
                excerpt="检测到「目录」标题但未使用自动域生成目录",
                rule="F06.06 版式终审",
                suggestion="使用 Word「引用 → 目录」自动域生成，确保页码与正文一致",
            )
        )

    if has_revision_marks(path):
        findings.append(
            _finding(
                severity="建议",
                location="全文 / 修订痕迹",
                excerpt="检测到 Word 修订标记（插入/删除）残留",
                rule="F06.06 版式终审",
                suggestion="接受或拒绝全部修订后再提交，避免评审时看到修改痕迹",
            )
        )

    author = get_core_author(path)
    if author:
        findings.append(
            _finding(
                severity="建议",
                location="文档属性 / 作者信息",
                excerpt=f"文档属性中检测到作者信息「{author}」",
                rule="F06.06 版式终审-暗标残留",
                suggestion="若本项目要求暗标评审，请在 Word「文件→信息→检查文档」中清除作者等个人身份信息",
            )
        )

    return findings
