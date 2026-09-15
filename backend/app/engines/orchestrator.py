"""五引擎编排：抽取文本 → 并行跑 E1/E2/E4/E5(确定性) → 跑 E3(语义) → 合并 Finding → 落库。"""

import logging
import re
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import BidDocument, ReviewFinding, ReviewRun
from .. import storage
from . import e1_veto, e2_business, e3_semantic, e3_tech_modules, e4_duplicate_filler, e5_layout, e_business_vision, e_custom_rules, e_parse_match, e_tender_score, rules_config
from .bid_kind import (
    KIND_COMBINED,
    SCOPE_BUSINESS,
    SCOPE_FULL,
    SCOPE_TECH,
    filter_tender_rules,
    format_requirements_for_scope,
    normalize_kind,
    normalize_scope,
    score_rules_for_scope,
    split_paragraphs_for_scope,
    tree_for_scope,
)
from .bid_media import extract_review_pack, filter_pack_for_paragraphs
from .docx_extract import extract_full_text, extract_paragraphs
from .excerpt_guard import snap_bid_excerpt, split_bid_and_tender
from .review_context import load_review_context
from .rules_data import DIMENSION_LABELS, SEVERITY_PENALTY

logger = logging.getLogger(__name__)

LEVEL_META = {
    "L1": {"name": "一票否决扫描", "desc": "星号条款、废标条款、资质证件、负数报价、签字盖章"},
    "L2": {"name": "商务客观核验", "desc": "业绩四件套、财务指标、报价偏离、属地细则"},
    "L3": {"name": "技术标五维打分", "desc": "完整性/针对性/合规性/可落地性/规范性"},
    "L4": {"name": "虚词语义", "desc": "大模型阅读原文，找出空话并提示补数据"},
    "L5": {"name": "版式终审", "desc": "标题层级、目录页码、图表编号、空白页"},
}

# L3 由 E3 五维加权得出，覆盖率最高体现"核心技术评审"权重；其余四层各占一定比例。
OVERALL_WEIGHTS = {"L1": 0.15, "L2": 0.15, "L3": 0.45, "L4": 0.15, "L5": 0.10}
BUSINESS_WEIGHTS = {"L1": 0.40, "L2": 0.60}
TECH_WEIGHTS = {"L3": 0.55, "L4": 0.25, "L5": 0.20}

SCOPE_LEVELS = {
    SCOPE_BUSINESS: ("L1", "L2"),
    SCOPE_TECH: ("L3", "L4", "L5"),
    SCOPE_FULL: ("L1", "L2", "L3", "L4", "L5"),
}


def _score_from_findings(findings: list[dict]) -> float:
    score = 100.0
    for f in findings:
        score -= SEVERITY_PENALTY.get(f["severity"], 0)
    return max(0.0, round(score, 1))


_WS = re.compile(r"\s+")
_SEVERITIES = {"废标", "降档", "扣分", "建议"}


def _norm_ws(text: str) -> str:
    return _WS.sub("", text or "")


def _keep_bid_excerpt(excerpt: str, *blobs: str, location: str = "", rule: str = "") -> str:
    """落库前只保留确实出现在投标书里的摘句，引擎结论不得写入 excerpt。

    问题项本身必须落库：摘不到原文时 excerpt 为空，不能把 Finding 丢掉。
    五维语义评审常把原句改写后再吐出，这里对齐回投标书句子。
    """
    hay = "\n".join(b or "" for b in blobs)
    loc = location if "五维语义" in (rule or "") else ""
    snapped = snap_bid_excerpt(excerpt, hay, loc)
    if snapped:
        return snapped
    excerpt = (excerpt or "").strip()
    if not excerpt:
        return ""
    if excerpt in hay:
        return excerpt
    n_ex, n_hay = _norm_ws(excerpt), _norm_ws(hay)
    if n_ex and n_hay and n_ex in n_hay:
        return excerpt
    parts = [p.strip() for p in excerpt.replace("；", ";").split(";") if p.strip()]
    if len(parts) > 1 and all(p in hay or (_norm_ws(p) and _norm_ws(p) in n_hay) for p in parts):
        return excerpt
    return ""


def _finding_row(run_id: str, f: dict, *blobs: str) -> ReviewFinding:
    severity = f.get("severity") if f.get("severity") in _SEVERITIES else "建议"
    rule = str(f.get("rule") or "")
    quote = str(f.get("tenderQuote") or f.get("tender_quote") or "")
    excerpt, quote = split_bid_and_tender(
        _keep_bid_excerpt(
            str(f.get("excerpt") or ""),
            *blobs,
            location=str(f.get("location") or ""),
            rule=rule,
        ),
        quote,
        rule,
    )
    return ReviewFinding(
        run_id=run_id,
        engine=str(f.get("engine") or "unknown"),
        level=str(f.get("level") or ""),
        severity=severity,
        location=str(f.get("location") or ""),
        excerpt=excerpt,
        rule=rule,
        tender_quote=quote,
        suggestion=str(f.get("suggestion") or ""),
        evidence_json={
            "strategyKey": str(f.get("strategyKey") or ""),
            "applyText": str(f.get("applyText") or "")[:4000],
        },
        confidence=float(f.get("confidence") or 1.0),
    )


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
    custom_rules = rules_config.load_project_custom_rules(db, run.project_id)

    # 管理员规则页开关：关闭的条目在对应引擎里直接跳过检查，不再产生 Finding。
    veto_keys = rules_config.load_enabled_veto_keys(db)
    biz_keys = rules_config.load_enabled_catalog_keys(db, "business")
    tech_keys = rules_config.load_enabled_catalog_keys(db, "tech")
    dup_keys = rules_config.load_enabled_catalog_keys(db, "dup_check")
    strategy_keys = rules_config.load_enabled_catalog_keys(db, "strategy")
    scope = normalize_scope(getattr(run, "scope", None) or SCOPE_FULL)

    def _empty_e3() -> dict:
        return {"dimensions": {k: {"score": 0.0, "reason": ""} for k in weights}, "issues": []}

    def _run_with_path(path: str | None):
        paras: list[dict] = []
        text = ""
        images: list[dict] = []
        if path:
            try:
                pack = extract_review_pack(path)
                paras = pack.get("paragraphs") or []
                images = pack.get("images") or []
                text = pack.get("full_text") or ""
            except Exception:
                logger.exception("extract_review_pack failed, fallback to extract_paragraphs")
                paras = []
                images = []
                try:
                    paras = extract_paragraphs(path)
                    text = "\n".join((p.get("text") or "") for p in paras)
                except Exception:
                    try:
                        text = extract_full_text(path)
                    except Exception:
                        text = ""
        kind = normalize_kind(getattr(doc, "kind", None) if doc else None, getattr(doc, "filename", "") if doc else "")
        if scope in (SCOPE_BUSINESS, SCOPE_TECH) and kind == KIND_COMBINED:
            paras = split_paragraphs_for_scope(paras, scope)
            paras, images = filter_pack_for_paragraphs(paras, images)
        if paras:
            text = "\n".join((p.get("text") or "") for p in paras)
        scoped_score_rules = score_rules_for_scope(checklist.score_rules, scope)
        scoped_tree = tree_for_scope(checklist.dimensions, scope)
        ctx = load_review_context(db, run.project_id, path)
        e1: list = []
        e2: list = []
        e4: list = []
        e5: list = []
        e3 = _empty_e3()
        tech_findings: list = []
        tech_modules: list = []
        parse_findings: list = []

        biz_paras = paras
        if scope in (SCOPE_BUSINESS, SCOPE_FULL):
            vision = e_business_vision.run(paras, images, checklist_params, veto_keys, biz_keys)
            vis_paras = vision.get("paragraphs") or []
            vis_findings = vision.get("findings") or []
            if vis_paras:
                biz_paras = list(paras) + vis_paras
            e1 = e1_veto.run(biz_paras, checklist_params, must_respond, thresholds, ctx, veto_keys, dup_keys)
            e2 = e2_business.run(biz_paras, checklist_params, thresholds, local_items, ctx, biz_keys, veto_keys, strategy_keys, dup_keys)
            for item in vis_findings:
                if item.get("level") == "L2":
                    e2.append(item)
                else:
                    e1.append(item)
        if scope in (SCOPE_TECH, SCOPE_FULL):
            e4 = e4_duplicate_filler.run(paras, word_rules, thresholds, ctx, dup_keys)
            e5 = e5_layout.run(path, paras, ctx, veto_keys, dup_keys, strategy_keys) if path else []
            e3 = e3_semantic.run(text, weights, tech_keys, strategy_keys, dup_keys, scoped_score_rules, images=images)
            tech_findings, tech_modules = e3_tech_modules.evaluate(
                text,
                paras,
                ctx.project_name,
                tech_keys,
                images=images,
                dimensions=checklist.dimensions,
                thresholds=thresholds,
            )
        parse_paras = biz_paras if scope in (SCOPE_BUSINESS, SCOPE_FULL) else paras
        parse_text = "\n".join((p.get("text") or "") for p in parse_paras) if parse_paras else text
        parse_findings = e_parse_match.run(
            parse_text,
            scoped_score_rules,
            checklist.qualification if scope in (SCOPE_BUSINESS, SCOPE_FULL) else [],
            format_requirements_for_scope(checklist.format_requirements, scope),
            must_respond if scope in (SCOPE_BUSINESS, SCOPE_FULL) else [],
            tech_keys,
            veto_keys,
            strategy_keys,
            headings=[(p.get("text") or "") for p in parse_paras],
            paragraphs=parse_paras,
        )
        custom_findings = e_custom_rules.run(parse_text, parse_paras, custom_rules)
        parse_findings = parse_findings + custom_findings
        if scope == SCOPE_BUSINESS:
            parse_findings = [f for f in parse_findings if f.get("level") in ("L1", "L2")]
        elif scope == SCOPE_TECH:
            parse_findings = [f for f in parse_findings if f.get("level") in ("L3", "L5")]
        e3_issues = (e3.get("issues") or []) + tech_findings + [f for f in parse_findings if f["level"] == "L3"]
        e1 = e1 + [f for f in parse_findings if f["level"] == "L1"]
        e2 = e2 + [f for f in parse_findings if f["level"] == "L2"]
        e5 = e5 + [f for f in parse_findings if f["level"] == "L5"]
        tender_rules = e_tender_score.run(
            parse_text if scope in (SCOPE_BUSINESS, SCOPE_FULL) else text,
            scoped_score_rules,
            scoped_tree,
            headings=[(p.get("text") or "") for p in parse_paras],
            strategy_keys=strategy_keys,
            paragraphs=parse_paras,
        )
        tender_rules = filter_tender_rules(tender_rules, scope)
        return paras, text, e1, e2, e4, e5, e3, e3_issues, tech_modules, tender_rules

    if doc and doc.storage_path and storage.exists(doc.storage_path):
        with storage.as_local(doc.storage_path) as path:
            (
                paragraphs,
                full_text,
                e1_findings,
                e2_findings,
                e4_findings,
                e5_findings,
                e3_result,
                e3_issues,
                tech_modules,
                tender_rules,
            ) = _run_with_path(path)
    else:
        (
            paragraphs,
            full_text,
            e1_findings,
            e2_findings,
            e4_findings,
            e5_findings,
            e3_result,
            e3_issues,
            tech_modules,
            tender_rules,
        ) = _run_with_path(None)

    all_findings = e1_findings + e2_findings + e4_findings + e5_findings + e3_issues

    level_scores: dict[str, float] = {
        "L1": _score_from_findings(e1_findings),
        "L2": _score_from_findings(e2_findings),
        "L4": _score_from_findings(e4_findings),
        "L5": _score_from_findings(e5_findings),
    }

    dims = e3_result.get("dimensions") or {}
    dim_score = round(sum(dims[k]["score"] * weights[k] / 100 for k in weights if k in dims), 1) if dims else 0.0
    l3_penalty = sum(SEVERITY_PENALTY.get(f["severity"], 0) for f in e3_issues)
    level_scores["L3"] = max(0.0, round(dim_score - l3_penalty, 1)) if scope in (SCOPE_TECH, SCOPE_FULL) else 0.0

    level_keys = SCOPE_LEVELS.get(scope) or SCOPE_LEVELS[SCOPE_FULL]
    score_weights = (
        BUSINESS_WEIGHTS if scope == SCOPE_BUSINESS else TECH_WEIGHTS if scope == SCOPE_TECH else OVERALL_WEIGHTS
    )
    levels_out = []
    for key in level_keys:
        meta = LEVEL_META[key]
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

    dimensions_out = []
    if scope in (SCOPE_TECH, SCOPE_FULL):
        dimensions_out = [
            {"name": DIMENSION_LABELS[k], "weight": weights[k], "score": round(dims[k]["score"], 1)}
            for k in weights
            if k in dims
        ]
    if scope == SCOPE_BUSINESS:
        tech_modules = []

    overall = round(sum(level_scores[k] * w for k, w in score_weights.items()), 1)
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
    run.tech_modules_json = tech_modules
    run.tender_rules_json = tender_rules
    run.finished_at = datetime.utcnow()

    para_blob = "\n".join(str(p.get("text") or "") for p in paragraphs)
    for f in all_findings:
        db.add(_finding_row(run.id, f, full_text, para_blob))
    db.commit()
