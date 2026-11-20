"""导出中心的导出前复检：对即将导出的 docx 重新跑一遍确定性引擎，
得到「当前文档」真实的最新 Finding，而不是复用可能已经过期的历史 ReviewRun。

口径与预审编排一致：
- 规则表按项目类别（工程类 / 软件服务类）读，和预审读同一份 load_rule_bundle；
- 按分册跑引擎：商务册跑 E1/E2（含文件形态），技术册跑 E4/E5；
- 暗标只对技术册生效。

不跑 E3（语义五维打分）——语义打分耗时且与"能否导出"这个闸门关系不大。
"""

from sqlalchemy.orm import Session

from . import e1_veto, e2_business, e4_duplicate_filler, e5_layout
from .bid_kind import KIND_COMBINED, SCOPE_BUSINESS, SCOPE_TECH, normalize_kind, split_paragraphs_for_scope
from .category_profile import MODE_BLIND, is_engineering_category, load_rule_bundle, tender_requires_anonymity
from .docx_extract import extract_paragraphs, get_core_author
from .review_context import load_review_context

CHECK_LABELS = {
    "waste": "无未关闭废标项",
    "filler": "虚词语义无明显空话",
    "dup": "查重阈值达标",
    "layout": "版式终审通过",
    "anon": "暗标标识无残留",
    "anon_required": "与招标暗标要求一致",
}

# 这条暗标文档属性残留导出时会被自动清除，不能因为它拦住导出
_AUTO_CLEANED_RULE = "F06.07 暗标文档属性残留"


def run_checks(
    db: Session,
    storage_path: str,
    checklist_params: dict | None = None,
    must_respond: list | None = None,
    project_id: str | None = None,
    scope: str = SCOPE_BUSINESS,
    category: str | None = None,
    mode: str = "明标",
    doc_kind: str | None = None,
    filename: str = "",
) -> list[dict]:
    """对指定 docx 按分册重新跑引擎，返回合并后的 Finding 列表。"""
    paragraphs = extract_paragraphs(storage_path)
    if scope in (SCOPE_BUSINESS, SCOPE_TECH) and normalize_kind(doc_kind, filename) == KIND_COMBINED:
        paragraphs = split_paragraphs_for_scope(paragraphs, scope)
    specialty = None
    if project_id:
        from ..models import Project

        project = db.get(Project, project_id)
        if project is not None:
            specialty = (project.specialty or "").strip() or None
            if not category:
                category = project.category
    rules = load_rule_bundle(db, category, specialty)
    context = load_review_context(db, project_id, storage_path) if project_id else None

    findings: list[dict] = []
    if scope == SCOPE_TECH:
        findings += e4_duplicate_filler.run(paragraphs, rules.word_rules, rules.thresholds, context, rules.dup_keys)
        blind = mode == MODE_BLIND
        findings += e5_layout.run(
            storage_path,
            paragraphs,
            context,
            rules.veto_keys,
            rules.dup_keys,
            rules.strategy_keys,
            rules.anon_keys,
            blind,
            not is_engineering_category(category),
        )
    else:
        findings += e1_veto.run(
            paragraphs, checklist_params, must_respond or [], rules.thresholds, context, rules.veto_keys, rules.dup_keys
        )
        findings += e2_business.run(
            paragraphs,
            checklist_params,
            rules.thresholds,
            rules.local_items,
            context,
            rules.biz_keys,
            rules.veto_keys,
            rules.strategy_keys,
            rules.dup_keys,
            local_item_checks=rules.catalog.get("local_item_checks"),
        )
        if "file_form" in (rules.veto_keys or {"file_form"}):
            findings += e5_layout.file_form_findings(context)
    return [f for f in findings if _AUTO_CLEANED_RULE not in str(f.get("rule") or "")]


def summarize(
    findings: list[dict],
    storage_path: str,
    mode: str,
    scope: str = SCOPE_BUSINESS,
    checklist_params: dict | None = None,
) -> tuple[list[dict], bool, str]:
    """把 Finding 列表汇总为用户可读的检查项，并给出是否阻断导出及阻断原因。

    阻断规则：存在「废标」级 Finding。
    虚词/查重/版式/暗标属性仅作为提示项展示，不阻断——与预审中心"扣分/建议不阻断答辩"的语义一致。
    暗标属性残留导出时会自动清除；招标要求暗标但选了明标，只提示、不拦截，由用户决定。
    """
    waste_findings = [f for f in findings if f["severity"] == "废标"]
    filler_findings = [f for f in findings if "F10.02" in f.get("rule", "")]
    dup_findings = [f for f in findings if "F06.05" in f.get("rule", "")]
    layout_findings = [
        f for f in findings if "F06.06" in f.get("rule", "") and "暗标残留" not in f.get("rule", "")
    ]

    items = [
        {
            "key": "waste",
            "label": CHECK_LABELS["waste"],
            "ok": len(waste_findings) == 0,
            "note": waste_findings[0]["excerpt"] if waste_findings else "",
        },
    ]
    if scope == SCOPE_TECH:
        items += [
            {
                "key": "filler",
                "label": CHECK_LABELS["filler"],
                "ok": len(filler_findings) == 0,
                "note": f"检测到 {len(filler_findings)} 处语义空话，建议补数据" if filler_findings else "",
            },
            {
                "key": "dup",
                "label": CHECK_LABELS["dup"],
                "ok": len(dup_findings) == 0,
                "note": dup_findings[0]["excerpt"] if dup_findings else "",
            },
        ]
    items.append(
        {
            "key": "layout",
            "label": CHECK_LABELS["layout"],
            "ok": len(layout_findings) == 0,
            "note": f"检测到 {len(layout_findings)} 处版式问题" if layout_findings else "",
        }
    )

    if scope == SCOPE_TECH:
        required = tender_requires_anonymity(checklist_params)
        if mode == MODE_BLIND:
            has_author = bool(get_core_author(storage_path))
            items.append(
                {
                    "key": "anon",
                    "label": CHECK_LABELS["anon"],
                    "ok": not has_author,
                    "note": "文档属性中仍残留作者信息，导出时将自动清除" if has_author else "",
                }
            )
        if required and mode != MODE_BLIND:
            items.append(
                {
                    "key": "anon_required",
                    "label": CHECK_LABELS["anon_required"],
                    "ok": False,
                    "note": "招标文件要求暗标，当前选择的是明标；按明标导出会保留身份信息，请确认",
                }
            )
        elif not required and mode == MODE_BLIND:
            items.append(
                {
                    "key": "anon_required",
                    "label": CHECK_LABELS["anon_required"],
                    "ok": False,
                    "note": "招标文件没有暗标要求，当前选择的是暗标；暗标会清空文档属性和页眉页脚中的单位名称",
                }
            )

    blocked = len(waste_findings) > 0
    block_reason = ""
    if waste_findings:
        block_reason = f"存在 {len(waste_findings)} 个未关闭废标项：{waste_findings[0]['excerpt']}"

    return items, blocked, block_reason
