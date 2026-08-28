"""启动时：仅在零用户时创建引导管理员；规则目录 upsert；清除历史演示种子。

不写入虚构项目、演示人名、演示证照。引导账号仅用于空库可登录，不是业务演示数据。
"""

from sqlalchemy.orm import Session

from .auth import hash_password
from .engines import rules_data
from .llm_catalog import seed_llm_catalog
from .models import (
    CatalogRule,
    FillerWordRule,
    Project,
    ProjectMember,
    QualificationAsset,
    RulePackage,
    ThresholdRule,
    User,
    VetoRule,
    WeightTemplate,
)
from .project_ops import delete_project_cascade

BOOTSTRAP_ADMIN = {
    "id": "user-000000000001",
    "name": "系统管理员",
    "email": "chen@zhibiaoyun.com",
    "password": "123456",
    "phone": "",
    "company": "",
    "position": "管理员",
    "role": "管理员",
}

DEMO_PROJECT_IDS = [f"p-100{i}" for i in range(1, 8)]
DEMO_USER_IDS = [f"user-m0{i}" for i in range(2, 8)]
DEMO_USER_EMAILS = {
    "linxiaowen@zby.ai",
    "wanghaoran@zby.ai",
    "zhaoqiming@zby.ai",
    "lisiyuan@zby.ai",
    "shenhuimin@zby.ai",
    "fengtiejun@zby.ai",
}
DEMO_QUAL_IDS = [f"qual-q{i}" for i in range(1, 11)]
DEMO_COMPANY = "中建八局·华东公司"
DEMO_PERSON_NAMES = {"陈立群", "林晓雯", "王浩然", "赵启铭", "李思源", "沈慧敏", "冯铁军"}


def purge_demo_data(db: Session) -> None:
    """删除历史上写入的演示项目、演示成员、演示证照，并把引导账号去演示化。"""
    for project_id in DEMO_PROJECT_IDS:
        if db.get(Project, project_id):
            delete_project_cascade(db, project_id)

    db.query(ProjectMember).filter(ProjectMember.user_id.in_(DEMO_USER_IDS)).delete(synchronize_session=False)
    db.query(User).filter(User.id.in_(DEMO_USER_IDS)).delete(synchronize_session=False)
    extra_demo_users = db.query(User).filter(User.email.in_(DEMO_USER_EMAILS)).all()
    for user in extra_demo_users:
        db.query(ProjectMember).filter(ProjectMember.user_id == user.id).delete(synchronize_session=False)
        db.delete(user)

    db.query(QualificationAsset).filter(QualificationAsset.id.in_(DEMO_QUAL_IDS)).delete(synchronize_session=False)

    bootstrap = db.get(User, BOOTSTRAP_ADMIN["id"]) or db.query(User).filter(User.email == BOOTSTRAP_ADMIN["email"]).first()
    if bootstrap:
        if bootstrap.name in DEMO_PERSON_NAMES:
            bootstrap.name = BOOTSTRAP_ADMIN["name"]
        if (bootstrap.company or "") == DEMO_COMPANY:
            bootstrap.company = ""
        if bootstrap.position in DEMO_PERSON_NAMES or bootstrap.position == "投标主管":
            bootstrap.position = BOOTSTRAP_ADMIN["position"]
        bootstrap.role = "管理员"

    for project in db.query(Project).all():
        if project.owner in DEMO_PERSON_NAMES:
            owner_user = db.get(User, project.owner_id) if project.owner_id else None
            project.owner = owner_user.name if owner_user else BOOTSTRAP_ADMIN["name"]

    db.commit()


def seed_defaults(db: Session) -> None:
    """空库才创建引导管理员，便于首次登录；已有任意用户则不动。"""
    if db.query(User).count() > 0:
        return
    db.add(
        User(
            id=BOOTSTRAP_ADMIN["id"],
            name=BOOTSTRAP_ADMIN["name"],
            email=BOOTSTRAP_ADMIN["email"],
            password_hash=hash_password(BOOTSTRAP_ADMIN["password"]),
            phone=BOOTSTRAP_ADMIN["phone"],
            company=BOOTSTRAP_ADMIN["company"],
            position=BOOTSTRAP_ADMIN["position"],
            role=BOOTSTRAP_ADMIN["role"],
        )
    )
    db.commit()


def seed_rules(db: Session) -> None:
    """把 rules_data 目录 upsert 进规则表。已有库会补齐新虚词、改写、阈值和属地条目，不覆盖用户改过的数值/启停。"""
    if db.query(WeightTemplate).count() == 0:
        db.add(
            WeightTemplate(
                name="青天默认五维",
                completeness=rules_data.DEFAULT_WEIGHTS["completeness"],
                relevance=rules_data.DEFAULT_WEIGHTS["relevance"],
                compliance=rules_data.DEFAULT_WEIGHTS["compliance"],
                feasibility=rules_data.DEFAULT_WEIGHTS["feasibility"],
                standardization=rules_data.DEFAULT_WEIGHTS["standardization"],
                scope="全局默认",
                active=True,
            )
        )

    existing_words = {r.word: r for r in db.query(FillerWordRule).all()}
    for item in rules_data.FILLER_WORDS:
        row = existing_words.get(item["word"])
        if row is None:
            db.add(
                FillerWordRule(
                    category=item["category"],
                    level=item["level"],
                    word=item["word"],
                    rewrite=item.get("rewrite") or "",
                    enabled=True,
                )
            )
            continue
        row.category = item["category"]
        row.level = item["level"]
        if not (row.rewrite or "").strip():
            row.rewrite = item.get("rewrite") or ""

    existing_thresholds = {r.key: r for r in db.query(ThresholdRule).all()}
    for item in rules_data.THRESHOLD_CATALOG:
        row = existing_thresholds.get(item["key"])
        if row is None:
            db.add(
                ThresholdRule(
                    key=item["key"],
                    label=item["label"],
                    value=item["value"],
                    unit=item.get("unit") or "%",
                    description=item.get("description") or "",
                )
            )
            continue
        row.label = item["label"]
        row.unit = item.get("unit") or row.unit
        row.description = item.get("description") or ""

    existing_packages = {p.name: p for p in db.query(RulePackage).all()}
    for item in rules_data.LOCAL_RULE_PACKAGES:
        row = existing_packages.get(item["name"])
        if row is None:
            db.add(
                RulePackage(
                    name=item["name"],
                    region=item["region"],
                    status=item["status"],
                    items_json=item["items"],
                )
            )
            continue
        current = list(row.items_json or [])
        for entry in item["items"]:
            if entry not in current:
                current.append(entry)
        row.items_json = current
        row.region = item["region"]

    existing_veto = {r.key: r for r in db.query(VetoRule).all()}
    for seq, item in enumerate(rules_data.VETO_CHECK_POINTS):
        row = existing_veto.get(item["key"])
        payload = dict(
            category=item["category"],
            point=item["point"],
            items_json=item.get("items") or [],
            wired=item.get("wired") or "仅对照",
            wired_note=item.get("wiredNote") or "",
            engine=item.get("engine") or "",
            seq=seq,
        )
        if row is None:
            db.add(VetoRule(key=item["key"], **payload))
            continue
        for field, value in payload.items():
            setattr(row, field, value)

    existing_catalog = {(r.kind, r.key): r for r in db.query(CatalogRule).all()}
    for kind, items in rules_data.RULE_CATALOGS.items():
        for seq, item in enumerate(items):
            payload = dict(
                category=item.get("category") or item.get("module") or "",
                point=item.get("point") or item.get("logic") or "",
                items_json=item.get("items") or [],
                wired=item.get("wired") or "仅对照",
                wired_note=item.get("wiredNote") or "",
                engine=item.get("engine") or "",
                seq=seq,
            )
            row = existing_catalog.get((kind, item["key"]))
            if row is None:
                db.add(CatalogRule(kind=kind, key=item["key"], **payload))
                continue
            for field, value in payload.items():
                setattr(row, field, value)

    db.commit()


def seed_llm(db: Session) -> None:
    seed_llm_catalog(db)
