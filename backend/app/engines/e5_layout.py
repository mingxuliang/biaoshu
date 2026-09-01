"""E5 版式终审引擎（对应青天第五层「最终一键终审」，前端 L5）。

全部基于 Word OOXML 文档对象模型直接检查，不调用大模型，确保这一层零幻觉、可复现。
"""

from .docx_extract import (
    extract_paragraphs,
    get_core_author,
    has_blank_page_hint,
    has_comments,
    has_revision_marks,
    has_toc_field,
)

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


def _enabled(key: str, enabled_keys: set[str] | None) -> bool:
    return enabled_keys is None or key in enabled_keys


def run(
    path: str,
    paragraphs: list[dict] | None = None,
    context=None,
    veto_keys: set[str] | None = None,
    dup_keys: set[str] | None = None,
    strategy_keys: set[str] | None = None,
) -> list[dict]:
    findings: list[dict] = []
    paragraphs = paragraphs if paragraphs is not None else extract_paragraphs(path)

    file_form_enabled = _enabled("file_form", veto_keys)
    structured_layout_enabled = _enabled("structured_layout", strategy_keys)
    anon_meta_enabled = _enabled("anon_meta", dup_keys)

    if structured_layout_enabled:
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

        if has_comments(path):
            findings.append(
                _finding(
                    severity="建议",
                    location="全文 / 批注",
                    excerpt="检测到 Word 批注残留",
                    rule="F06.06 版式终审-批注",
                    suggestion="删除全部批注后再提交，避免评审端看到内部讨论",
                )
            )

    if file_form_enabled and has_blank_page_hint(path):
        findings.append(
            _finding(
                severity="建议",
                location="全文 / 空白页",
                excerpt="检测到连续空段落，可能存在空白页",
                rule="F06.06 版式终审-空白页",
                suggestion="删除多余空段与空白页，避免被认定为文件形态不合规",
            )
        )

    if anon_meta_enabled:
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

    if file_form_enabled and context is not None:
        if getattr(context, "encrypted", False):
            findings.append(
                _finding(
                    severity="废标",
                    location="全文 / 文件形态",
                    excerpt="投标文件无法正常打开或已加密",
                    rule="F06.06 版式终审-文件加密",
                    suggestion="请提交未加密、可正常打开的 .docx；加密文件无法完成预审抽取",
                )
            )
        if getattr(context, "scanned_pdf", False):
            findings.append(
                _finding(
                    severity="降档",
                    location="全文 / 扫描件 PDF",
                    excerpt="检测到纯图片扫描 PDF，几乎无文字层",
                    rule="F06.06 版式终审-扫描件 PDF",
                    suggestion="请改用可复制文字的 Word/PDF，避免评审端无法检索",
                )
            )

    return findings
