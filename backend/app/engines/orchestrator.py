"""五引擎编排：抽取文本 → 并行跑 E1/E2/E4/E5(确定性) → 跑 E3(语义) → 合并 Finding → 落库。"""

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import BidDocument, ReviewFinding, ReviewRun
from .. import storage
from . import e1_veto, e2_business, e3_semantic, e3_tech_modules, e4_duplicate_filler, e5_layout, e_parse_match, rules_config
from .docx_extract import extract_document_plain_text, extract_full_text, extract_paragraphs
from .review_context import load_review_context
from .rules_data import DIMENSION_LABELS, SEVERITY_PENALTY

LEVEL_META = {
    "L1": {"name": "一票否决扫描", "desc": "星号条款、废标条款、资质证件、负数报价、签字盖章"},
    "L2": {"name": "商务客观核验", "desc": "业绩四件套、财务指标、报价偏离、属地细则"},
    "L3": {"name": "技术标五维打分", "desc": "完整性/针对性/合规性/可落地性/规范性"},
    "L4": {"name": "虚词与模板查重", "desc": "虚词密度、高危句式、相似度比对"},
    "L5": {"name": "版式终审", "desc": "标题层级、目录页码、图表编号、空白页"},
}

# L3 由 E3 五维加权得出，覆盖率最高体现"核心技术评审"权重；其余四层各占一定比例。
OVERALL_WEIGHTS = {"L1": 0.15, "L2": 0.15, "L3": 0.45, "L4": 0.15, "L5": 0.10}


def _score_from_findings(findings: list[dict]) -> float:
    score = 100.0
    for f in findings:
        score -= SEVERITY_PENALTY.get(f["severity"], 0)
    return max(0.0, round(score, 1))


def _status(score: float, issue_count: int, has_waste: bool) -> str:
    if has_waste or score < 80 or issue_count >= 3:
        return "风险"
    return "通过"


def run_prereview(db: Session, run_id: str) -> None:
    run = db.get(ReviewRun, run_id)
    if not run:
        return

    run.status = "running"
    db.commit()

    doc = db.get(BidDocument, run.bid_document_id)
    paragraphs: list[dict] = []
    full_text = ""
    checklist = rules_config.load_project_checklist(db, run.project_id)
    checklist_params, must_respond = checklist.params, checklist.must_respond
    weights = rules_config.load_active_weights(db)
    word_rules = rules_config.load_enabled_filler_words(db)
    thresholds = rules_config.load_thresholds(db)
    local_items = rules_config.load_enabled_package_items(db)

    # 管理员规则页开关：关闭的条目在对应引擎里直接跳过检查，不再产生 Finding。
    veto_keys = rules_config.load_enabled_veto_keys(db)
    biz_keys = rules_config.load_enabled_catalog_keys(db, "business")
    tech_keys = rules_config.load_enabled_catalog_keys(db, "tech")
    dup_keys = rules_config.load_enabled_catalog_keys(db, "dup_check")
    strategy_keys = rules_config.load_enabled_catalog_keys(db, "strategy")

    def _run_with_path(path: str | None):
        paras: list[dict] = []
        text = ""
        if path:
            try:
                paras = extract_paragraphs(path)
                try:
                    text = extract_document_plain_text(path)
                except Exception:
                    text = extract_full_text(path)
            except Exception:
                paras = []
                text = ""
        ctx = load_review_context(db, run.project_id, path)
        e1 = e1_veto.run(paras, checklist_params, must_respond, thresholds, ctx, veto_keys)
        e2 = e2_business.run(paras, checklist_params, thresholds, local_items, ctx, biz_keys, veto_keys, strategy_keys)
        e4 = e4_duplicate_filler.run(paras, word_rules, thresholds, ctx, dup_keys)
        e5 = e5_layout.run(path, paras, ctx, veto_keys, dup_keys, strategy_keys) if path else []
        e3 = e3_semantic.run(text, weights, tech_keys, strategy_keys, dup_keys, checklist.score_rules)
        tech_findings = e3_tech_modules.run(text, paras, ctx.project_name, tech_keys)
        parse_findings = e_parse_match.run(
            text,
            checklist.score_rules,
            checklist.qualification,
            checklist.format_requirements,
            must_respond,
            tech_keys,
            veto_keys,
            strategy_keys,
            headings=[(p.get("text") or "") for p in paras],
        )
        e3_issues = e3["issues"] + tech_findings + [f for f in parse_findings if f["level"] == "L3"]
        e1 = e1 + [f for f in parse_findings if f["level"] == "L1"]
        e5 = e5 + [f for f in parse_findings if f["level"] == "L5"]
        return paras, text, e1, e2, e4, e5, e3, e3_issues

    if doc and doc.storage_path and storage.exists(doc.storage_path):
        with storage.as_local(doc.storage_path) as path:
            paragraphs, full_text, e1_findings, e2_findings, e4_findings, e5_findings, e3_result, e3_issues = (
                _run_with_path(path)
            )
    else:
        paragraphs, full_text, e1_findings, e2_findings, e4_findings, e5_findings, e3_result, e3_issues = (
            _run_with_path(None)
        )

    all_findings = e1_findings + e2_findings + e4_findings + e5_findings + e3_issues

    level_scores: dict[str, float] = {
        "L1": _score_from_findings(e1_findings),
        "L2": _score_from_findings(e2_findings),
        "L4": _score_from_findings(e4_findings),
        "L5": _score_from_findings(e5_findings),
    }

    dims = e3_result["dimensions"]
    dim_score = round(sum(dims[k]["score"] * weights[k] / 100 for k in weights), 1)
    l3_penalty = sum(SEVERITY_PENALTY.get(f["severity"], 0) for f in e3_issues)
    level_scores["L3"] = max(0.0, round(dim_score - l3_penalty, 1))

    levels_out = []
    for key, meta in LEVEL_META.items():
        level_findings = [f for f in all_findings if f["level"] == key]
        has_waste = any(f["severity"] == "废标" for f in level_findings)
        levels_out.append(
            {
                "key": key,
                "name": meta["name"],
                "desc": meta["desc"],
                "score": level_scores[key],
                "full": 100,
                "issues": len(level_findings),
                "status": _status(level_scores[key], len(level_findings), has_waste),
            }
        )

    dimensions_out = [
        {"name": DIMENSION_LABELS[k], "weight": weights[k], "score": round(dims[k]["score"], 1)}
        for k in weights
    ]

    overall = round(sum(level_scores[k] * w for k, w in OVERALL_WEIGHTS.items()), 1)
    waste = sum(1 for f in all_findings if f["severity"] == "废标")
    risk = sum(1 for f in all_findings if f["severity"] in ("降档", "扣分"))
    suggest = sum(1 for f in all_findings if f["severity"] == "建议")

    if waste > 0 or overall < 70:
        light = "红"
    elif overall < 90:
        light = "橙"
    else:
        light = "绿"

    run.status = "done"
    run.overall = overall
    run.waste = waste
    run.risk = risk
    run.suggest = suggest
    run.light = light
    run.levels_json = levels_out
    run.dimensions_json = dimensions_out
    run.finished_at = datetime.utcnow()
    db.commit()

    for f in all_findings:
        db.add(
            ReviewFinding(
                run_id=run.id,
                engine=f["engine"],
                level=f["level"],
                severity=f["severity"],
                location=f["location"],
                excerpt=f["excerpt"],
                rule=f["rule"],
                tender_quote=f.get("tenderQuote", ""),
                suggestion=f["suggestion"],
                evidence_json={},
                confidence=f.get("confidence", 1.0),
            )
        )
    db.commit()
