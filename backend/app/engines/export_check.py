"""导出中心的导出前复检：对即将导出的 docx 重新跑一遍确定性引擎（E1/E2/E4/E5），
得到「当前文档」真实的最新 Finding，而不是复用可能已经过期的历史 ReviewRun。

不跑 E3（语义五维打分）——语义打分耗时且与"能否导出"这个闸门关系不大。
"""

from sqlalchemy.orm import Session

from . import e1_veto, e2_business, e4_duplicate_filler, e5_layout, rules_config
from .docx_extract import extract_paragraphs, get_core_author
from .review_context import load_review_context

CHECK_LABELS = {
    "waste": "无未关闭废标项",
    "filler": "虚词密度达标",
    "dup": "查重阈值达标",
    "layout": "版式终审通过",
    "anon": "暗标标识无残留",
}


def run_checks(
    db: Session,
    storage_path: str,
    checklist_params: dict | None = None,
    must_respond: list | None = None,
    project_id: str | None = None,
) -> list[dict]:
    """对指定 docx 重新跑 E1/E2/E4/E5，返回合并后的 Finding 列表。"""
    paragraphs = extract_paragraphs(storage_path)
    word_rules = rules_config.load_enabled_filler_words(db)
    thresholds = rules_config.load_thresholds(db)
    local_items = rules_config.load_enabled_package_items(db)
    context = load_review_context(db, project_id, storage_path) if project_id else None

    e1_findings = e1_veto.run(paragraphs, checklist_params, must_respond or [], thresholds, context)
    e2_findings = e2_business.run(paragraphs, checklist_params, thresholds, local_items, context)
    e4_findings = e4_duplicate_filler.run(paragraphs, word_rules, thresholds, context)
    e5_findings = e5_layout.run(storage_path, paragraphs, context)
    return e1_findings + e2_findings + e4_findings + e5_findings


def summarize(findings: list[dict], storage_path: str, mode: str) -> tuple[list[dict], bool, str]:
    """把 Finding 列表汇总为用户可读的检查项，并给出是否阻断导出及阻断原因。

    阻断规则：存在「废标」级 Finding，或（暗标模式下）文档属性里仍残留作者信息。
    虚词/查重/版式仅作为提示项展示，不阻断——与预审中心"扣分/建议不阻断答辩"的语义一致。
    """
    waste_findings = [f for f in findings if f["severity"] == "废标"]
    filler_findings = [f for f in findings if "F10.02" in f.get("rule", "")]
    dup_findings = [f for f in findings if "F06.05" in f.get("rule", "")]
    layout_findings = [
        f for f in findings if "F06.06" in f.get("rule", "") and "暗标残留" not in f.get("rule", "")
    ]
    has_author = bool(get_core_author(storage_path))

    items = [
        {
            "key": "waste",
            "label": CHECK_LABELS["waste"],
            "ok": len(waste_findings) == 0,
            "note": waste_findings[0]["excerpt"] if waste_findings else "",
        },
        {
            "key": "filler",
            "label": CHECK_LABELS["filler"],
            "ok": len(filler_findings) == 0,
            "note": f"检测到 {len(filler_findings)} 处虚词/空话表达" if filler_findings else "",
        },
        {
            "key": "dup",
            "label": CHECK_LABELS["dup"],
            "ok": len(dup_findings) == 0,
            "note": dup_findings[0]["excerpt"] if dup_findings else "",
        },
        {
            "key": "layout",
            "label": CHECK_LABELS["layout"],
            "ok": len(layout_findings) == 0,
            "note": f"检测到 {len(layout_findings)} 处版式问题" if layout_findings else "",
        },
    ]

    if mode == "暗标":
        items.append(
            {
                "key": "anon",
                "label": CHECK_LABELS["anon"],
                "ok": not has_author,
                "note": "文档属性中仍残留作者信息，导出时将自动清除" if has_author else "",
            }
        )

    blocked = len(waste_findings) > 0
    block_reason = ""
    if waste_findings:
        block_reason = f"存在 {len(waste_findings)} 个未关闭废标项：{waste_findings[0]['excerpt']}"

    return items, blocked, block_reason
