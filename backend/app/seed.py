"""启动时：仅在零用户时创建引导管理员；规则目录 upsert；清除历史演示种子。

不写入虚构项目、演示人名、演示证照。引导账号仅用于空库可登录，不是业务演示数据。
"""

import logging

from sqlalchemy.orm import Session

from .auth import find_user_by_account, hash_password, random_password, verify_password
from .config import get_settings
from .engines import rules_data
from .llm_catalog import seed_llm_catalog
from .models import (
    CatalogRule,
    FillerWordRule,
    Project,
    ProjectMember,
    QualificationAsset,
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
from .project_ops import delete_project_cascade

logger = logging.getLogger(__name__)

BOOTSTRAP_ADMIN = {
    "id": "user-000000000001",
    "name": "系统管理员",
    "email": "chen@zhibiaoyun.com",
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
    """空库才创建引导管理员，便于首次登录；已有任意用户则不动。

    密码取 ADMIN_INITIAL_PASSWORD，未配置时随机生成并只在日志里打印一次。
    """
    if db.query(User).count() > 0:
        return
    password = (get_settings().admin_initial_password or "").strip()
    generated = not password
    if generated:
        password = random_password(16)
    db.add(
        User(
            id=BOOTSTRAP_ADMIN["id"],
            name=BOOTSTRAP_ADMIN["name"],
            email=BOOTSTRAP_ADMIN["email"],
            password_hash=hash_password(password),
            phone=BOOTSTRAP_ADMIN["phone"],
            company=BOOTSTRAP_ADMIN["company"],
            position=BOOTSTRAP_ADMIN["position"],
            role=BOOTSTRAP_ADMIN["role"],
        )
    )
    db.commit()
    if generated:
        logger.warning(
            "已创建引导管理员 %s，初始密码：%s（仅显示这一次，登录后请立即修改）",
            BOOTSTRAP_ADMIN["email"],
            password,
        )


LEGACY_BOOTSTRAP_PASSWORD = "123456"


def bootstrap_uses_legacy_password(db: Session) -> bool:
    """老库里的引导管理员是否仍是历史默认密码 123456。"""
    user = db.get(User, BOOTSTRAP_ADMIN["id"]) or find_user_by_account(db, BOOTSTRAP_ADMIN["email"])
    return bool(user) and verify_password(LEGACY_BOOTSTRAP_PASSWORD, user.password_hash or "")


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
                category="工程类",
                active=True,
            )
        )
    if db.query(WeightTemplate).filter(WeightTemplate.category == "软件服务类").count() == 0:
        db.add(
            WeightTemplate(
                name="软件服务默认五维",
                completeness=rules_data.SW_DEFAULT_WEIGHTS["completeness"],
                relevance=rules_data.SW_DEFAULT_WEIGHTS["relevance"],
                compliance=rules_data.SW_DEFAULT_WEIGHTS["compliance"],
                feasibility=rules_data.SW_DEFAULT_WEIGHTS["feasibility"],
                standardization=rules_data.SW_DEFAULT_WEIGHTS["standardization"],
                scope="软件服务类",
                category="软件服务类",
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

    sim_keys = {item["key"] for item in rules_data.DUP_SIMILARITY_POINTS}
    stale = (
        db.query(CatalogRule)
        .filter(CatalogRule.kind == "dup_check", CatalogRule.key.in_(sim_keys))
        .all()
    )
    moved = {r.key: r for r in db.query(CatalogRule).filter(CatalogRule.kind == "dup_sim").all()}
    for row in stale:
        if row.key in moved:
            db.delete(row)
        else:
            row.kind = "dup_sim"
    db.flush()

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

    # 暗标检查已从专项检查挪到独立目录；合并前的版式草稿不再单独占一行。
    for row in (
        db.query(CatalogRule)
        .filter(CatalogRule.kind == "dup_check", CatalogRule.key == "anon_meta")
        .all()
    ):
        db.delete(row)
    for row in (
        db.query(CatalogRule)
        .filter(CatalogRule.kind == "anon", CatalogRule.key == "plain_format")
        .all()
    ):
        db.delete(row)

    db.commit()
    seed_sw_rules(db)


def seed_sw_rules(db: Session) -> None:
    """把软件服务类专属规则目录（rules_data.SW_*）upsert 进 sw_ 系列独立表。

    与 seed_rules() 同样的 upsert-without-overwriting-enabled 思路，彻底独立于工程类四张表。
    """
    existing_sw_words = {r.word: r for r in db.query(SwFillerWordRule).all()}
    for item in rules_data.FILLER_WORDS:
        row = existing_sw_words.get(item["word"])
        if row is None:
            db.add(
                SwFillerWordRule(
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

    existing_sw_thresholds = {r.key: r for r in db.query(SwThresholdRule).all()}
    for item in rules_data.THRESHOLD_CATALOG:
        row = existing_sw_thresholds.get(item["key"])
        if row is None:
            db.add(
                SwThresholdRule(
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

    existing_sw_packages = {p.name: p for p in db.query(SwRulePackage).all()}
    for item in rules_data.SW_RULE_PACKAGES:
        row = existing_sw_packages.get(item["name"])
        if row is None:
            db.add(
                SwRulePackage(
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

    existing_sw_veto = {r.key: r for r in db.query(SwVetoRule).all()}
    for seq, item in enumerate(rules_data.SW_VETO_CHECK_POINTS):
        row = existing_sw_veto.get(item["key"])
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
            db.add(SwVetoRule(key=item["key"], **payload))
            continue
        for field, value in payload.items():
            setattr(row, field, value)

    existing_sw_catalog = {(r.kind, r.key): r for r in db.query(SwCatalogRule).all()}
    for kind, items in rules_data.SW_RULE_CATALOGS.items():
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
            row = existing_sw_catalog.get((kind, item["key"]))
            if row is None:
                db.add(SwCatalogRule(kind=kind, key=item["key"], **payload))
                continue
            for field, value in payload.items():
                setattr(row, field, value)

    live_sw = {
        (kind, item["key"])
        for kind, items in rules_data.SW_RULE_CATALOGS.items()
        for item in items
    }
    for row in db.query(SwCatalogRule).all():
        if (row.kind, row.key) in live_sw:
            continue
        # 只清掉已从目录撤下的内置项，管理员后来手加的 key 不动。
        if row.key in {"anon_meta", "performance_sla", "plain_format"} or (row.kind == "dup_check" and row.key == "anon_meta"):
            db.delete(row)

    db.commit()


def seed_llm(db: Session) -> None:
    seed_llm_catalog(db)
    encrypt_plaintext_keys(db)


def encrypt_plaintext_keys(db: Session) -> int:
    """把历史明文 API Key 改写成密文。直接读原始列值判断，绕开 ORM 的自动解密。"""
    from sqlalchemy import text

    from .secret_box import encrypt, is_encrypted

    rows = db.execute(text("SELECT id, api_key FROM llm_providers")).fetchall()
    changed = 0
    for row_id, raw in rows:
        if raw and not is_encrypted(raw):
            db.execute(
                text("UPDATE llm_providers SET api_key = :v WHERE id = :id"),
                {"v": encrypt(raw), "id": row_id},
            )
            changed += 1
    if changed:
        db.commit()
    return changed
