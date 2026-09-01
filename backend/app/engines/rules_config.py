"""预审规则的统一加载层：数据库配置优先，rules_data.py 常量兜底默认值。

供各引擎与路由复用，避免各处重复"查不到就用哪个默认值"的兜底逻辑。
任意一步查询失败或结果为空，都会退回 rules_data.py 里的硬编码常量，
保证规则表为空/未迁移时引擎依然可用。
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models import CatalogRule, EvaluationChecklist, FillerWordRule, RulePackage, ThresholdRule, VetoRule, WeightTemplate
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


def load_enabled_veto_keys(db: Session) -> set[str]:
    """启用中的一票否决项 key 集合；管理员可在规则页逐条关闭对应引擎检查。"""
    rows = db.query(VetoRule).all()
    if not rows:
        return {item["key"] for item in rules_data.VETO_CHECK_POINTS}
    return {r.key for r in rows if r.enabled is not False}


def load_enabled_catalog_keys(db: Session, kind: str) -> set[str]:
    """启用中的商务自查/技术评分/专项检查/高分策略 key 集合，按 kind 过滤。"""
    rows = db.query(CatalogRule).filter(CatalogRule.kind == kind).all()
    if not rows:
        return {item["key"] for item in rules_data.RULE_CATALOGS.get(kind, [])}
    return {r.key for r in rows if r.enabled is not False}


def load_locked_checklist(db: Session, project_id: str) -> tuple[dict | None, list]:
    """兼容旧调用方：返回 (engine_params, mustRespond)。

    优先用已锁定评标尺子；未锁定则回退到该项目最新一轮 status=done 的解析结果，
    避免「解析完但忘了点锁定」时预审完全看不到招标约定。
    """
    cl = load_project_checklist(db, project_id)
    if not cl.params and not cl.must_respond:
        return None, []
    return cl.params or {}, cl.must_respond


@dataclass
class ProjectChecklist:
    """招标解析落到预审引擎的约定内容。"""

    params: dict = field(default_factory=dict)
    must_respond: list = field(default_factory=list)
    score_rules: list = field(default_factory=list)
    qualification: list = field(default_factory=list)
    format_requirements: list = field(default_factory=list)
    locked: bool = False
    version: int | None = None


def load_project_checklist(db: Session, project_id: str) -> ProjectChecklist:
    locked = (
        db.query(EvaluationChecklist)
        .filter(EvaluationChecklist.project_id == project_id, EvaluationChecklist.locked.is_(True))
        .order_by(EvaluationChecklist.version.desc())
        .first()
    )
    row = locked or (
        db.query(EvaluationChecklist)
        .filter(EvaluationChecklist.project_id == project_id, EvaluationChecklist.status == "done")
        .order_by(EvaluationChecklist.version.desc())
        .first()
    )
    if not row:
        return ProjectChecklist()
    data = row.checklist_json or {}

    def _list(key: str) -> list:
        val = data.get(key) or []
        return val if isinstance(val, list) else []

    return ProjectChecklist(
        params=row.engine_params_json or {},
        must_respond=_list("mustRespond"),
        score_rules=_list("scoreRules"),
        qualification=_list("qualification"),
        format_requirements=_list("formatRequirements"),
        locked=bool(row.locked),
        version=row.version,
    )
