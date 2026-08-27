"""预审规则的统一加载层：数据库配置优先，rules_data.py 常量兜底默认值。

供各引擎与路由复用，避免各处重复"查不到就用哪个默认值"的兜底逻辑。
任意一步查询失败或结果为空，都会退回 rules_data.py 里的硬编码常量，
保证规则表为空/未迁移时引擎依然可用。
"""

from sqlalchemy.orm import Session

from ..models import EvaluationChecklist, FillerWordRule, RulePackage, ThresholdRule, WeightTemplate
from . import rules_data


def load_active_weights(db: Session) -> dict[str, float]:
    """五维权重：取当前 active 模板，查不到则回退 DEFAULT_WEIGHTS。"""
    template = db.query(WeightTemplate).filter(WeightTemplate.active.is_(True)).first()
    if not template:
        return dict(rules_data.DEFAULT_WEIGHTS)
    return {
        "completeness": template.completeness,
        "relevance": template.relevance,
        "compliance": template.compliance,
        "feasibility": template.feasibility,
        "standardization": template.standardization,
    }


def load_enabled_filler_words(db: Session) -> list[tuple[str, str, str, str]]:
    """虚词表：(word, category, level, rewrite)，仅含 enabled=True；查不到任何行则回退内置目录。"""
    rows = db.query(FillerWordRule).filter(FillerWordRule.enabled.is_(True)).all()
    if not rows:
        return [
            (item["word"], item["category"], item["level"], item.get("rewrite") or "")
            for item in rules_data.FILLER_WORDS
        ]
    return [(r.word, r.category, r.level, r.rewrite or "") for r in rows]


def load_thresholds(db: Session) -> dict[str, float]:
    """数值阈值：按 key 取 value，缺失的 key 回退 rules_data.THRESHOLDS 对应默认值。"""
    result = dict(rules_data.THRESHOLDS)
    rows = db.query(ThresholdRule).all()
    for row in rows:
        result[row.key] = row.value
    return result


def load_enabled_package_items(db: Session) -> list[str]:
    """启用中的属地细则条目，供 E2 对照正文；无启用包时回退内置启用包。"""
    rows = db.query(RulePackage).filter(RulePackage.status == "启用").all()
    if not rows:
        return [
            item
            for pkg in rules_data.LOCAL_RULE_PACKAGES
            if pkg.get("status") == "启用"
            for item in (pkg.get("items") or [])
        ]
    items: list[str] = []
    for row in rows:
        items.extend(row.items_json or [])
    return items


def load_locked_checklist(db: Session, project_id: str) -> tuple[dict | None, list]:
    """锁定评标尺子的 engine_params 与 mustRespond 清单；未锁定时返回 (None, [])。"""
    checklist = (
        db.query(EvaluationChecklist)
        .filter(EvaluationChecklist.project_id == project_id, EvaluationChecklist.locked == True)  # noqa: E712
        .order_by(EvaluationChecklist.version.desc())
        .first()
    )
    if not checklist:
        return None, []
    data = checklist.checklist_json or {}
    must = data.get("mustRespond") or []
    if not isinstance(must, list):
        must = []
    return checklist.engine_params_json or None, must
