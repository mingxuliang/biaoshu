from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..engines.parse_schema import is_engineering_category
from ..engines.rules_data import catalog_wired_items, rule_scope, sw_catalog_wired_items, sw_veto_wired_items, veto_wired_items
from ..models import (
    CatalogRule,
    FillerWordRule,
    RulePackage,
    SwCatalogRule,
    SwFillerWordRule,
    SwRulePackage,
    SwThresholdRule,
    SwVetoRule,
    ThresholdRule,
    User,
    VetoRule,
    WeightTemplate,
)
from ..permissions import PERM_SETTINGS, require_library_read, require_perm
from ..schemas import (
    CatalogRuleOut,
    FillerWordRuleIn,
    FillerWordRuleOut,
    RulePackageIn,
    RulePackageOut,
    ThresholdRuleOut,
    UpdateCatalogRuleIn,
    UpdateFillerWordRuleIn,
    UpdateRulePackageIn,
    UpdateThresholdIn,
    UpdateVetoRuleIn,
    UpdateWeightTemplateIn,
    VetoRuleOut,
    WeightTemplateIn,
    WeightTemplateOut,
)

def _require_reader(current_user: User = Depends(get_current_user)) -> User:
    # 规则配置属内部评审口径，只给参与撰写、评审、配置的角色看
    require_library_read(current_user, PERM_SETTINGS)
    return current_user


router = APIRouter(prefix="/api/rules", tags=["rules"], dependencies=[Depends(_require_reader)])


def _require_settings(current_user: User = Depends(get_current_user)) -> User:
    require_perm(current_user, PERM_SETTINGS)
    return current_user


def _weight_to_out(t: WeightTemplate) -> WeightTemplateOut:
    return WeightTemplateOut(
        id=t.id,
        name=t.name,
        completeness=t.completeness,
        relevance=t.relevance,
        compliance=t.compliance,
        feasibility=t.feasibility,
        standardization=t.standardization,
        scope=t.scope,
        category=t.category or "工程类",
        active=t.active,
    )


def _filler_to_out(w: FillerWordRule) -> FillerWordRuleOut:
    return FillerWordRuleOut(
        id=w.id, category=w.category, level=w.level, word=w.word, rewrite=w.rewrite or "", enabled=w.enabled
    )


def _threshold_to_out(t: ThresholdRule) -> ThresholdRuleOut:
    return ThresholdRuleOut(
        id=t.id, key=t.key, label=t.label, value=t.value, unit=t.unit or "%", description=t.description or ""
    )


def _package_to_out(p: RulePackage) -> RulePackageOut:
    return RulePackageOut(id=p.id, name=p.name, region=p.region, status=p.status, items=p.items_json or [])


def _validate_weight_sum(completeness, relevance, compliance, feasibility, standardization) -> None:
    total = completeness + relevance + compliance + feasibility + standardization
    if round(total, 3) != 100:
        raise HTTPException(400, f"五维权重之和必须为 100，当前为 {total}")


# ---------------------------------------------------------------------------
# 五维权重模板
# ---------------------------------------------------------------------------


def _weight_category_key(category: str | None) -> str:
    return "工程类" if is_engineering_category(category) else "软件服务类"


@router.get("/weight-templates", response_model=list[WeightTemplateOut])
def list_weight_templates(category: str | None = None, db: Session = Depends(get_db)) -> list[WeightTemplateOut]:
    q = db.query(WeightTemplate)
    if category:
        key = _weight_category_key(category)
        if key == "工程类":
            q = q.filter((WeightTemplate.category == key) | (WeightTemplate.category.is_(None)) | (WeightTemplate.category == ""))
        else:
            q = q.filter(WeightTemplate.category == key)
    templates = q.order_by(WeightTemplate.created_at.asc()).all()
    return [_weight_to_out(t) for t in templates]


@router.post("/weight-templates", response_model=WeightTemplateOut)
def create_weight_template(
    payload: WeightTemplateIn,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_settings),
) -> WeightTemplateOut:
    _validate_weight_sum(
        payload.completeness, payload.relevance, payload.compliance, payload.feasibility, payload.standardization
    )
    template = WeightTemplate(
        name=payload.name,
        completeness=payload.completeness,
        relevance=payload.relevance,
        compliance=payload.compliance,
        feasibility=payload.feasibility,
        standardization=payload.standardization,
        scope=payload.scope,
        category=_weight_category_key(payload.category),
        active=False,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return _weight_to_out(template)


@router.patch("/weight-templates/{template_id}", response_model=WeightTemplateOut)
def update_weight_template(
    template_id: str,
    payload: UpdateWeightTemplateIn,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_settings),
) -> WeightTemplateOut:
    template = db.get(WeightTemplate, template_id)
    if not template:
        raise HTTPException(404, "权重模板不存在")

    data = payload.model_dump(exclude_unset=True)
    merged = {
        "completeness": data.get("completeness", template.completeness),
        "relevance": data.get("relevance", template.relevance),
        "compliance": data.get("compliance", template.compliance),
        "feasibility": data.get("feasibility", template.feasibility),
        "standardization": data.get("standardization", template.standardization),
    }
    _validate_weight_sum(**merged)

    for field, value in data.items():
        setattr(template, field, value)
    db.commit()
    db.refresh(template)
    return _weight_to_out(template)


@router.post("/weight-templates/{template_id}/activate", response_model=WeightTemplateOut)
def activate_weight_template(
    template_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_settings),
) -> WeightTemplateOut:
    template = db.get(WeightTemplate, template_id)
    if not template:
        raise HTTPException(404, "权重模板不存在")

    # 同一类别只留一条生效；工程类和软件服务类互不影响
    key = template.category or "工程类"
    same = (WeightTemplate.category == key)
    if key == "工程类":
        same = same | (WeightTemplate.category.is_(None)) | (WeightTemplate.category == "")
    db.query(WeightTemplate).filter(WeightTemplate.id != template_id, same).update(
        {"active": False}, synchronize_session=False
    )
    template.active = True
    db.commit()
    db.refresh(template)
    return _weight_to_out(template)


# ---------------------------------------------------------------------------
# 虚词表
# ---------------------------------------------------------------------------


@router.get("/word-rules", response_model=list[FillerWordRuleOut])
def list_word_rules(db: Session = Depends(get_db)) -> list[FillerWordRuleOut]:
    rules = db.query(FillerWordRule).order_by(FillerWordRule.created_at.asc()).all()
    return [_filler_to_out(w) for w in rules]


@router.post("/word-rules", response_model=FillerWordRuleOut)
def create_word_rule(
    payload: FillerWordRuleIn,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_settings),
) -> FillerWordRuleOut:
    rule = FillerWordRule(
        category=payload.category, level=payload.level, word=payload.word, rewrite=payload.rewrite, enabled=True
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _filler_to_out(rule)


@router.patch("/word-rules/{rule_id}", response_model=FillerWordRuleOut)
def update_word_rule(
    rule_id: str,
    payload: UpdateFillerWordRuleIn,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_settings),
) -> FillerWordRuleOut:
    rule = db.get(FillerWordRule, rule_id)
    if not rule:
        raise HTTPException(404, "虚词规则不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return _filler_to_out(rule)


# ---------------------------------------------------------------------------
# 查重阈值（key 只读；本企业跨项目两项驱动 E4 查重）
# ---------------------------------------------------------------------------


@router.get("/thresholds", response_model=list[ThresholdRuleOut])
def list_thresholds(db: Session = Depends(get_db)) -> list[ThresholdRuleOut]:
    rows = db.query(ThresholdRule).order_by(ThresholdRule.key.asc()).all()
    return [_threshold_to_out(t) for t in rows]


@router.patch("/thresholds/{threshold_id}", response_model=ThresholdRuleOut)
def update_threshold(
    threshold_id: str,
    payload: UpdateThresholdIn,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_settings),
) -> ThresholdRuleOut:
    row = db.get(ThresholdRule, threshold_id)
    if not row:
        raise HTTPException(404, "阈值不存在")
    row.value = payload.value
    db.commit()
    db.refresh(row)
    return _threshold_to_out(row)


# ---------------------------------------------------------------------------
# 属地细则包（启用后由 E2 核验）
# ---------------------------------------------------------------------------


@router.get("/packages", response_model=list[RulePackageOut])
def list_rule_packages(db: Session = Depends(get_db)) -> list[RulePackageOut]:
    rows = db.query(RulePackage).order_by(RulePackage.created_at.asc()).all()
    return [_package_to_out(p) for p in rows]


@router.post("/packages", response_model=RulePackageOut)
def create_rule_package(
    payload: RulePackageIn,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_settings),
) -> RulePackageOut:
    package = RulePackage(name=payload.name, region=payload.region, status="启用", items_json=payload.items)
    db.add(package)
    db.commit()
    db.refresh(package)
    return _package_to_out(package)


@router.patch("/packages/{package_id}", response_model=RulePackageOut)
def update_rule_package(
    package_id: str,
    payload: UpdateRulePackageIn,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_settings),
) -> RulePackageOut:
    package = db.get(RulePackage, package_id)
    if not package:
        raise HTTPException(404, "细则包不存在")
    data = payload.model_dump(exclude_unset=True)
    if "items" in data:
        package.items_json = data.pop("items")
    for field, value in data.items():
        setattr(package, field, value)
    db.commit()
    db.refresh(package)
    return _package_to_out(package)


# ---------------------------------------------------------------------------
# 一票否决清单（青天 v1.1 表 3，展示接入状态）
# ---------------------------------------------------------------------------


def _veto_to_out(row: VetoRule) -> VetoRuleOut:
    wired = row.wired if row.wired in ("接入判定", "部分接入", "仅对照") else "仅对照"
    items = row.items_json or []
    scope = rule_scope(row.key)
    return VetoRuleOut(
        id=row.id,
        key=row.key,
        category=row.category,
        point=row.point,
        items=items,
        wiredItems=veto_wired_items(row.key, wired, items),
        wired=wired,
        wiredNote=row.wired_note or "",
        engine=row.engine or "",
        seq=row.seq or 0,
        enabled=row.enabled if row.enabled is not None else True,
        specialties=scope["specialties"],
        workTypes=scope["workTypes"],
        itemSpecialties=scope["itemSpecialties"],
    )


@router.get("/veto-points", response_model=list[VetoRuleOut])
def list_veto_points(db: Session = Depends(get_db)) -> list[VetoRuleOut]:
    rows = db.query(VetoRule).order_by(VetoRule.seq.asc(), VetoRule.created_at.asc()).all()
    return [_veto_to_out(r) for r in rows]


@router.patch("/veto-points/{rule_id}", response_model=VetoRuleOut)
def update_veto_point(
    rule_id: str,
    payload: UpdateVetoRuleIn,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_settings),
) -> VetoRuleOut:
    row = db.get(VetoRule, rule_id)
    if not row:
        raise HTTPException(404, "一票否决项不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _veto_to_out(row)


CATALOG_KINDS = ("business", "tech", "dup_check", "dup_sim", "strategy", "anon")


def _catalog_to_out(row: CatalogRule) -> CatalogRuleOut:
    wired = row.wired if row.wired in ("接入判定", "部分接入", "仅对照") else "仅对照"
    kind = row.kind if row.kind in CATALOG_KINDS else "business"
    items = row.items_json or []
    scope = rule_scope(row.key)
    return CatalogRuleOut(
        id=row.id,
        kind=kind,
        key=row.key,
        category=row.category,
        point=row.point,
        items=items,
        wiredItems=catalog_wired_items(kind, row.key, wired, items),
        wired=wired,
        wiredNote=row.wired_note or "",
        engine=row.engine or "",
        seq=row.seq or 0,
        enabled=row.enabled if row.enabled is not None else True,
        specialties=scope["specialties"],
        workTypes=scope["workTypes"],
        itemSpecialties=scope["itemSpecialties"],
    )


@router.get("/catalog", response_model=list[CatalogRuleOut])
def list_catalog_rules(kind: str | None = None, db: Session = Depends(get_db)) -> list[CatalogRuleOut]:
    query = db.query(CatalogRule)
    if kind:
        if kind not in CATALOG_KINDS:
            raise HTTPException(400, "未知目录类型")
        query = query.filter(CatalogRule.kind == kind)
    rows = query.order_by(CatalogRule.kind.asc(), CatalogRule.seq.asc(), CatalogRule.created_at.asc()).all()
    return [_catalog_to_out(r) for r in rows]


@router.patch("/catalog/{rule_id}", response_model=CatalogRuleOut)
def update_catalog_rule(
    rule_id: str,
    payload: UpdateCatalogRuleIn,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_settings),
) -> CatalogRuleOut:
    row = db.get(CatalogRule, rule_id)
    if not row:
        raise HTTPException(404, "目录项不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _catalog_to_out(row)


# ---------------------------------------------------------------------------
# 软件服务类标书专属目录。虚词、专项检查、查重阈值也有独立表，不读工程类数据。
# ---------------------------------------------------------------------------


@router.get("/sw/word-rules", response_model=list[FillerWordRuleOut])
def list_sw_word_rules(db: Session = Depends(get_db)) -> list[FillerWordRuleOut]:
    rules = db.query(SwFillerWordRule).order_by(SwFillerWordRule.created_at.asc()).all()
    return [_filler_to_out(w) for w in rules]


@router.post("/sw/word-rules", response_model=FillerWordRuleOut)
def create_sw_word_rule(
    payload: FillerWordRuleIn,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_settings),
) -> FillerWordRuleOut:
    rule = SwFillerWordRule(
        category=payload.category, level=payload.level, word=payload.word, rewrite=payload.rewrite, enabled=True
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _filler_to_out(rule)


@router.patch("/sw/word-rules/{rule_id}", response_model=FillerWordRuleOut)
def update_sw_word_rule(
    rule_id: str,
    payload: UpdateFillerWordRuleIn,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_settings),
) -> FillerWordRuleOut:
    rule = db.get(SwFillerWordRule, rule_id)
    if not rule:
        raise HTTPException(404, "虚词规则不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return _filler_to_out(rule)


@router.get("/sw/thresholds", response_model=list[ThresholdRuleOut])
def list_sw_thresholds(db: Session = Depends(get_db)) -> list[ThresholdRuleOut]:
    rows = db.query(SwThresholdRule).order_by(SwThresholdRule.key.asc()).all()
    return [_threshold_to_out(t) for t in rows]


@router.patch("/sw/thresholds/{threshold_id}", response_model=ThresholdRuleOut)
def update_sw_threshold(
    threshold_id: str,
    payload: UpdateThresholdIn,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_settings),
) -> ThresholdRuleOut:
    row = db.get(SwThresholdRule, threshold_id)
    if not row:
        raise HTTPException(404, "阈值不存在")
    row.value = payload.value
    db.commit()
    db.refresh(row)
    return _threshold_to_out(row)


# ---------------------------------------------------------------------------
# 软件服务类标书专属目录：一票否决 / 商务自查 / 技术评分 / 高分策略 / 行业合规包。
# 彻底独立于上面的工程类端点，分别读写 sw_ 系列表，不与工程类数据混用。
# ---------------------------------------------------------------------------

SW_CATALOG_KINDS = ("business", "tech", "strategy", "dup_check", "dup_sim", "anon")


def _sw_package_to_out(p: SwRulePackage) -> RulePackageOut:
    return RulePackageOut(id=p.id, name=p.name, region=p.region, status=p.status, items=p.items_json or [])


@router.get("/sw/packages", response_model=list[RulePackageOut])
def list_sw_rule_packages(db: Session = Depends(get_db)) -> list[RulePackageOut]:
    rows = db.query(SwRulePackage).order_by(SwRulePackage.created_at.asc()).all()
    return [_sw_package_to_out(p) for p in rows]


@router.post("/sw/packages", response_model=RulePackageOut)
def create_sw_rule_package(
    payload: RulePackageIn,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_settings),
) -> RulePackageOut:
    package = SwRulePackage(name=payload.name, region=payload.region, status="启用", items_json=payload.items)
    db.add(package)
    db.commit()
    db.refresh(package)
    return _sw_package_to_out(package)


@router.patch("/sw/packages/{package_id}", response_model=RulePackageOut)
def update_sw_rule_package(
    package_id: str,
    payload: UpdateRulePackageIn,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_settings),
) -> RulePackageOut:
    package = db.get(SwRulePackage, package_id)
    if not package:
        raise HTTPException(404, "细则包不存在")
    data = payload.model_dump(exclude_unset=True)
    if "items" in data:
        package.items_json = data.pop("items")
    for field, value in data.items():
        setattr(package, field, value)
    db.commit()
    db.refresh(package)
    return _sw_package_to_out(package)


def _sw_veto_to_out(row: SwVetoRule) -> VetoRuleOut:
    wired = row.wired if row.wired in ("接入判定", "部分接入", "仅对照") else "仅对照"
    items = row.items_json or []
    return VetoRuleOut(
        id=row.id,
        key=row.key,
        category=row.category,
        point=row.point,
        items=items,
        wiredItems=sw_veto_wired_items(row.key, wired, items),
        wired=wired,
        wiredNote=row.wired_note or "",
        engine=row.engine or "",
        seq=row.seq or 0,
        enabled=row.enabled if row.enabled is not None else True,
    )


@router.get("/sw/veto-points", response_model=list[VetoRuleOut])
def list_sw_veto_points(db: Session = Depends(get_db)) -> list[VetoRuleOut]:
    rows = db.query(SwVetoRule).order_by(SwVetoRule.seq.asc(), SwVetoRule.created_at.asc()).all()
    return [_sw_veto_to_out(r) for r in rows]


@router.patch("/sw/veto-points/{rule_id}", response_model=VetoRuleOut)
def update_sw_veto_point(
    rule_id: str,
    payload: UpdateVetoRuleIn,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_settings),
) -> VetoRuleOut:
    row = db.get(SwVetoRule, rule_id)
    if not row:
        raise HTTPException(404, "一票否决项不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _sw_veto_to_out(row)


def _sw_catalog_to_out(row: SwCatalogRule) -> CatalogRuleOut:
    wired = row.wired if row.wired in ("接入判定", "部分接入", "仅对照") else "仅对照"
    kind = row.kind if row.kind in SW_CATALOG_KINDS else "business"
    items = row.items_json or []
    return CatalogRuleOut(
        id=row.id,
        kind=kind,
        key=row.key,
        category=row.category,
        point=row.point,
        items=items,
        wiredItems=sw_catalog_wired_items(kind, row.key, wired, items),
        wired=wired,
        wiredNote=row.wired_note or "",
        engine=row.engine or "",
        seq=row.seq or 0,
        enabled=row.enabled if row.enabled is not None else True,
    )


@router.get("/sw/catalog", response_model=list[CatalogRuleOut])
def list_sw_catalog_rules(kind: str | None = None, db: Session = Depends(get_db)) -> list[CatalogRuleOut]:
    query = db.query(SwCatalogRule)
    if kind:
        if kind not in SW_CATALOG_KINDS:
            raise HTTPException(400, "未知目录类型")
        query = query.filter(SwCatalogRule.kind == kind)
    rows = query.order_by(SwCatalogRule.kind.asc(), SwCatalogRule.seq.asc(), SwCatalogRule.created_at.asc()).all()
    return [_sw_catalog_to_out(r) for r in rows]


@router.patch("/sw/catalog/{rule_id}", response_model=CatalogRuleOut)
def update_sw_catalog_rule(
    rule_id: str,
    payload: UpdateCatalogRuleIn,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_settings),
) -> CatalogRuleOut:
    row = db.get(SwCatalogRule, rule_id)
    if not row:
        raise HTTPException(404, "目录项不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _sw_catalog_to_out(row)
