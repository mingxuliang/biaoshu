"""五引擎编排：抽取文本 → 并行跑 E1/E2/E4/E5(确定性) → 跑 E3(语义) → 合并 Finding → 落库。"""

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import BidDocument, EvaluationChecklist, ReviewFinding, ReviewRun
from . import e1_veto, e2_business, e3_semantic, e4_duplicate_filler, e5_layout
from .docx_extract import extract_full_text, extract_paragraphs
from .rules_data import DEFAULT_WEIGHTS, DIMENSION_LABELS, SEVERITY_PENALTY

LEVEL_META = {
    "L1": {"name": "一票否决扫描", "desc": "星号条款、废标条款、资质证件、暗标残留"},
    "L2": {"name": "商务客观核验", "desc": "业绩匹配度、人员证书、财务一致性、信用材料"},
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


def _load_checklist_params(db: Session, project_id: str) -> dict | None:
    """加载该项目当前锁定的评标尺子（若有），返回其 engine_params_json 供 E1/E2 消费。

    未解析/未锁定尺子时返回 None，E1/E2 会回退到通用正则/关键词，不影响既有行为。
    """
    checklist = (
        db.query(EvaluationChecklist)
        .filter(EvaluationChecklist.project_id == project_id, EvaluationChecklist.locked == True)  # noqa: E712
        .order_by(EvaluationChecklist.version.desc())
        .first()
    )
    if not checklist:
        return None
    return checklist.engine_params_json or None


def run_prereview(db: Session, run_id: str) -> None:
    run = db.get(ReviewRun, run_id)
    if not run:
        return

    run.status = "running"
    db.commit()

    doc = db.get(BidDocument, run.bid_document_id)
    paragraphs = extract_paragraphs(doc.storage_path)
    full_text = extract_full_text(doc.storage_path)

    checklist_params = _load_checklist_params(db, run.project_id)

    e1_findings = e1_veto.run(paragraphs, checklist_params)
    e2_findings = e2_business.run(paragraphs, checklist_params)
    e4_findings = e4_duplicate_filler.run(paragraphs)
    e5_findings = e5_layout.run(doc.storage_path, paragraphs)
    e3_result = e3_semantic.run(full_text)
    e3_findings = e3_result["issues"]

    all_findings = e1_findings + e2_findings + e4_findings + e5_findings + e3_findings

    level_scores: dict[str, float] = {
        "L1": _score_from_findings(e1_findings),
        "L2": _score_from_findings(e2_findings),
        "L4": _score_from_findings(e4_findings),
        "L5": _score_from_findings(e5_findings),
    }

    dims = e3_result["dimensions"]
    level_scores["L3"] = round(sum(dims[k]["score"] * DEFAULT_WEIGHTS[k] / 100 for k in DEFAULT_WEIGHTS), 1)

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
        {"name": DIMENSION_LABELS[k], "weight": DEFAULT_WEIGHTS[k], "score": round(dims[k]["score"], 1)}
        for k in DEFAULT_WEIGHTS
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
