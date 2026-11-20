"""E5 版式终审引擎（对应青天第五层「最终一键终审」，前端 L5）。

全部基于 Word OOXML 文档对象模型直接检查，不调用大模型，确保这一层零幻觉、可复现。
暗标身份检查只在招标解析标明暗标或盲评时给出问题，格式过细要求不在这里判。
"""

import re

from .bid_kind import SCOPE_TECH, split_paragraphs_for_scope
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


_PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def _bidder_name(context) -> str:
    for q in getattr(context, "quals", []) or []:
        if getattr(q, "kind", "") == "cert" and "营业执照" in (getattr(q, "name", "") or ""):
            owner = (getattr(q, "owner", "") or "").strip()
            if len(owner) >= 4:
                return owner
    return ""


def _anon_text_findings(paragraphs: list[dict], context, anon_keys: set[str] | None, is_software: bool) -> list[dict]:
    """只扫技术分册。合订文件能切开时，商务分册里的资质和业绩不记暗标违规。"""
    findings: list[dict] = []
    tech_paras = split_paragraphs_for_scope(paragraphs, SCOPE_TECH)
    text = "\n".join((p.get("text") or "") for p in tech_paras)
    if _enabled("identity_text", anon_keys):
        bidder_name = _bidder_name(context)
        if bidder_name and bidder_name in text:
            findings.append(
                _finding(
                    severity="废标",
                    location="技术标 / 暗标身份残留",
                    excerpt=bidder_name,
                    rule="F06.07 暗标不得出现单位名称",
                    suggestion=f"招标要求暗标或盲评，技术标出现本企业名称「{bidder_name}」。请删除单位名称、简称和徽标",
                )
            )
    if is_software and _enabled("brand_case", anon_keys):
        phone = _PHONE_PATTERN.search(text)
        if phone:
            findings.append(
                _finding(
                    severity="废标",
                    location="技术标 / 暗标联系方式",
                    excerpt=phone.group(0),
                    rule="F06.07 暗标不得出现联系电话",
                    suggestion="技术暗标分册出现手机号。请删掉联系电话；商务分册中的资质和业绩不在本项处理",
                )
            )
    return findings


def _anon_typeface_findings(paragraphs: list[dict], anon_keys: set[str] | None) -> list[dict]:
    """加粗只提示，不废标。字号、行距、页边距各地不一致，不在这里判。"""
    if not _enabled("typeface", anon_keys):
        return []
    bold = next((p for p in paragraphs if p.get("bold") and (p.get("text") or "").strip()), None)
    if bold is None:
        return []
    excerpt = str(bold.get("text") or "").strip()
    if len(excerpt) > 40:
        excerpt = excerpt[:40] + "…"
    return [
        _finding(
            severity="建议",
            location="技术标 / 暗标字体",
            excerpt=excerpt,
            rule="F06.08 暗标正文不宜加粗",
            suggestion="招标要求暗标或盲评，技术标有加粗段落。请改为常规字形。这是建议，不按废标处理；字号和页边距以招标文件为准",
        )
    ]


def run(
    path: str,
    paragraphs: list[dict] | None = None,
    context=None,
    veto_keys: set[str] | None = None,
    dup_keys: set[str] | None = None,
    strategy_keys: set[str] | None = None,
    anon_keys: set[str] | None = None,
    anonymity_required: bool = False,
    is_software: bool = False,
) -> list[dict]:
    findings: list[dict] = []
    paragraphs = paragraphs if paragraphs is not None else extract_paragraphs(path)

    file_form_enabled = _enabled("file_form", veto_keys)
    structured_layout_enabled = _enabled("structured_layout", strategy_keys)
    # 旧调用不传暗标目录时，仍按专项检查里的 anon_meta 提示作者属性，避免导出复检行为突变。
    legacy_anon = anon_keys is None and _enabled("anon_meta", dup_keys)
    doc_meta_enabled = _enabled("doc_meta", anon_keys) if anon_keys is not None else False

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

    if anonymity_required and doc_meta_enabled:
        author = get_core_author(path)
        if author:
            findings.append(
                _finding(
                    severity="废标",
                    location="文档属性 / 作者信息",
                    excerpt=f"文档属性中检测到作者信息「{author}」",
                    rule="F06.07 暗标文档属性残留",
                    suggestion="招标要求暗标或盲评。请在 Word「文件→信息→检查文档」中清除作者、单位和最后修改者",
                )
            )
    elif legacy_anon:
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

    if anonymity_required and anon_keys is not None:
        findings.extend(_anon_text_findings(paragraphs, context, anon_keys, is_software))
        findings.extend(_anon_typeface_findings(paragraphs, anon_keys))

    if file_form_enabled:
        findings.extend(file_form_findings(context))

    return findings


def file_form_findings(context) -> list[dict]:
    """加密 / 纯扫描：商务标也要拦，不依赖 E5 全文版式。"""
    findings: list[dict] = []
    if context is None:
        return findings
    if getattr(context, "encrypted", False):
        findings.append(
            _finding(
                severity="废标",
                location="全文 / 文件形态",
                excerpt="投标文件无法正常打开或已加密",
                rule="F06.06 版式终审-文件加密",
                suggestion="请提交未加密、可正常打开的 .docx 或 PDF；加密文件无法完成预审抽取",
            )
        )
        findings[-1]["evidenceOk"] = True
        findings[-1]["engine"] = "e5_layout"
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
        findings[-1]["evidenceOk"] = True
        findings[-1]["engine"] = "e5_layout"
        findings[-1]["issueClass"] = "human_check"
    return findings
