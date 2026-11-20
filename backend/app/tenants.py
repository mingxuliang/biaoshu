"""企业生命周期：开通、默认企业迁入、账号索引、注销。"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import get_settings
from .db import ensure_tenant_schema, migrate_legacy_public, platform_session, tenant_session
from .tenancy import DEFAULT_TENANT, use_tenant, valid_tenant_id

logger = logging.getLogger(__name__)

TENANT_ACTIVE_STATUSES = ("试用", "正常")
KIND_ENTERPRISE = "企业"
KIND_PERSONAL = "个人"
TENANT_KINDS = (KIND_ENTERPRISE, KIND_PERSONAL)
UPGRADE_SEATS = 3


def tenant_kind(tenant) -> str:
    return (getattr(tenant, "kind", None) or KIND_ENTERPRISE) if tenant is not None else KIND_ENTERPRISE


def plan_fits(plan, kind: str) -> bool:
    audience = plan.audience or "通用"
    return audience == "通用" or audience == kind


def upgrade_to_enterprise(pdb: Session, tenant, company_name: str) -> None:
    """个人空间升级为企业：数据、钱包、套餐原样保留，只放开席位和组织架构。"""
    if tenant_kind(tenant) != KIND_PERSONAL:
        raise HTTPException(400, "已经是企业，无需升级")
    name = (company_name or "").strip()
    if len(name) < 2:
        raise HTTPException(400, "请填写企业名称")
    tenant.kind = KIND_ENTERPRISE
    tenant.name = name
    tenant.seats = max(int(tenant.seats or 0), UPGRADE_SEATS)
    tenant.verify_status = "未认证"
    tenant.verify_note = ""


def active_tenant_ids() -> list[str]:
    from .platform_models import Tenant

    with platform_session() as db:
        rows = db.query(Tenant.id).filter(Tenant.status != "已注销").order_by(Tenant.created_at.asc()).all()
    return [row[0] for row in rows if valid_tenant_id(row[0])]


def new_tenant_id(db: Session) -> str:
    from .platform_models import Tenant

    for _ in range(20):
        candidate = "e" + secrets.token_hex(4)
        if not db.get(Tenant, candidate):
            return candidate
    raise RuntimeError("无法生成企业 ID")


def register_account(pdb: Session, login: str, tenant_id: str, user_id: str) -> None:
    from .platform_models import Account

    key = (login or "").strip().lower()
    if not key:
        return
    row = pdb.get(Account, key)
    if row is None:
        pdb.add(Account(login=key, tenant_id=tenant_id, user_id=user_id))
    elif row.tenant_id != tenant_id or row.user_id != user_id:
        raise HTTPException(409, "该账号已被其他企业使用")


def unregister_account(pdb: Session, login: str) -> None:
    from .platform_models import Account

    row = pdb.get(Account, (login or "").strip().lower())
    if row is not None:
        pdb.delete(row)


def login_taken(pdb: Session, login: str) -> bool:
    from .platform_models import Account

    return pdb.get(Account, (login or "").strip().lower()) is not None


def find_account(pdb: Session, login: str):
    from .platform_models import Account

    return pdb.get(Account, (login or "").strip().lower())


def sync_accounts(tenant_id: str) -> int:
    """把企业内全部用户登记进账号索引（单企业版升级、或手工改库后调用）。"""
    from .models import User
    from .platform_models import Account

    added = 0
    with use_tenant(tenant_id):
        tdb = tenant_session(tenant_id)
        pdb = platform_session()
        try:
            for user in tdb.query(User).all():
                key = (user.email or "").strip().lower()
                if not key:
                    continue
                existing = pdb.get(Account, key)
                if existing is None:
                    pdb.add(Account(login=key, tenant_id=tenant_id, user_id=user.id))
                    added += 1
                elif existing.tenant_id != tenant_id:
                    logger.error("账号 %s 同时存在于企业 %s 和 %s，保留前者", key, existing.tenant_id, tenant_id)
            pdb.commit()
        finally:
            tdb.close()
            pdb.close()
    return added


def seed_tenant(tenant_id: str) -> None:
    """企业 schema 内的初始数据：规则表从平台模板复制，企业之后可自行修改。"""
    from .seed import seed_rules

    with use_tenant(tenant_id):
        db = tenant_session(tenant_id)
        try:
            seed_rules(db)
        finally:
            db.close()


def seats_used(tenant_id: str) -> int:
    from .models import User

    with use_tenant(tenant_id):
        db = tenant_session(tenant_id)
        try:
            return db.query(func.count(User.id)).filter(User.disabled.is_(False)).scalar() or 0
        finally:
            db.close()


def create_tenant(
    *,
    name: str,
    admin_name: str,
    admin_login: str,
    admin_password: str,
    contact_phone: str = "",
    contact_email: str = "",
    plan_code: str = "trial",
    tenant_id: str | None = None,
    operator: str = "自助开通",
    kind: str = "企业",
) -> tuple[str, str]:
    """开通企业或个人空间：platform 登记、建 schema 和 bucket、复制规则、建管理员、发试用积分。返回 (企业ID, 管理员用户ID)。

    个人空间和企业走同一套隔离（独立 schema、bucket、钱包），区别只在席位固定为 1、不开放组织架构。
    """
    if kind not in TENANT_KINDS:
        raise HTTPException(400, "开通类型不合法")
    personal = kind == KIND_PERSONAL
    from . import billing, storage
    from .auth import hash_password
    from .models import User
    from .platform_models import Plan, Tenant
    from .tenancy import bucket_for

    settings = get_settings()
    login = (admin_login or "").strip().lower()
    pdb = platform_session()
    try:
        if login_taken(pdb, login):
            raise HTTPException(409, "该账号已注册，请直接登录")
        tid = tenant_id or new_tenant_id(pdb)
        if not valid_tenant_id(tid):
            raise HTTPException(400, "企业 ID 不合法")
        if pdb.get(Tenant, tid):
            raise HTTPException(409, "企业 ID 已存在")
        plan = pdb.get(Plan, plan_code)
        if plan is not None and not plan_fits(plan, kind):
            raise HTTPException(400, f"套餐「{plan.name}」不适用于{kind}")
        now = datetime.utcnow()
        tenant = Tenant(
            id=tid,
            name=name.strip(),
            kind=kind,
            status="试用" if plan_code == "trial" else "正常",
            plan_code=plan_code,
            seats=1 if personal else (plan.seats if plan and plan.seats else 3),
            storage_quota_mb=(plan.storage_mb if plan and plan.storage_mb else 2048),
            features_json=(plan.features_json if plan else {}) or {},
            contact_name=admin_name,
            contact_phone=contact_phone,
            contact_email=contact_email or (login if "@" in login else ""),
            trial_ends_at=now + timedelta(days=settings.trial_days) if plan_code == "trial" else None,
        )
        pdb.add(tenant)
        pdb.commit()
    finally:
        pdb.close()

    ensure_tenant_schema(tid)
    seed_tenant(tid)
    try:
        storage.ensure_bucket(bucket_for(tid), retries=3)
    except Exception:  # noqa: BLE001 —— MinIO 暂不可用时首次上传再建
        logger.warning("企业 %s 的 bucket 暂未创建，首次上传时再建", tid)

    with use_tenant(tid):
        tdb = tenant_session(tid)
        try:
            user = User(
                name=admin_name.strip() or login,
                email=login,
                password_hash=hash_password(admin_password),
                phone=contact_phone,
                company="" if personal else name.strip(),
                position="本人" if personal else "企业管理员",
                role="管理员",
            )
            tdb.add(user)
            tdb.commit()
            user_id = user.id
        finally:
            tdb.close()

    pdb = platform_session()
    try:
        register_account(pdb, login, tid, user_id)
        pdb.commit()
        billing.ensure_wallet(pdb, tid)
        if plan_code == "trial" and settings.trial_credits > 0:
            billing.grant(
                pdb,
                tid,
                settings.trial_credits,
                source="试用",
                expires_at=datetime.utcnow() + timedelta(days=settings.trial_days),
                note="新个人空间试用积分" if personal else "新企业试用积分",
                operator=operator,
                idem_key=f"trial:{tid}",
            )
        pdb.commit()
    finally:
        pdb.close()
    return tid, user_id


def bootstrap_default_tenant() -> None:
    """单企业版升级：public 里的业务表迁入 t_default，旧 bucket 继续作为默认企业的 bucket。"""
    from . import billing
    from .platform_models import Tenant

    pdb = platform_session()
    try:
        tenant = pdb.get(Tenant, DEFAULT_TENANT)
        if tenant is None:
            pdb.add(Tenant(id=DEFAULT_TENANT, name="默认企业", status="正常", plan_code="legacy", seats=999, storage_quota_mb=1024 * 1024))
            pdb.commit()
        billing.ensure_wallet(pdb, DEFAULT_TENANT)
        pdb.commit()
    finally:
        pdb.close()
    migrate_legacy_public(DEFAULT_TENANT)
    ensure_tenant_schema(DEFAULT_TENANT)
    with use_tenant(DEFAULT_TENANT):
        from .seed import purge_demo_data, seed_defaults

        db = tenant_session(DEFAULT_TENANT)
        try:
            purge_demo_data(db)
            seed_defaults(db)
        finally:
            db.close()
    seed_tenant(DEFAULT_TENANT)
    sync_accounts(DEFAULT_TENANT)


def migrate_all_tenants() -> None:
    for tid in active_tenant_ids():
        if tid == DEFAULT_TENANT:
            continue
        try:
            ensure_tenant_schema(tid)
            seed_tenant(tid)
        except Exception:  # noqa: BLE001 —— 一家企业迁移失败不阻塞平台启动
            logger.exception("企业 %s 迁移失败", tid)


_BLOCK_CACHE: dict[str, tuple[float, str | None]] = {}
_BLOCK_TTL = 30


def write_block_reason(tenant_id: str) -> str | None:
    """企业当前不能写入的原因：停用、试用到期、套餐到期。到期后数据仍可查看和导出，充值续费后恢复。"""
    import time

    from .platform_models import Tenant

    cached = _BLOCK_CACHE.get(tenant_id)
    if cached and time.time() - cached[0] < _BLOCK_TTL:
        return cached[1]
    now = datetime.utcnow()
    with platform_session() as pdb:
        t = pdb.get(Tenant, tenant_id)
        if t is None or t.status in ("停用", "已注销"):
            reason = "企业已停用，请联系平台客服"
        elif t.status == "试用" and t.trial_ends_at and t.trial_ends_at < now:
            reason = "试用已到期，请在费用中心购买套餐后继续使用"
        elif t.status == "正常" and t.expires_at and t.expires_at < now:
            reason = "套餐已到期，请在费用中心续费后继续使用"
        else:
            reason = None
    _BLOCK_CACHE[tenant_id] = (time.time(), reason)
    return reason


def clear_block_cache(tenant_id: str | None = None) -> None:
    if tenant_id:
        _BLOCK_CACHE.pop(tenant_id, None)
    else:
        _BLOCK_CACHE.clear()


def require_active_tenant(tenant_id: str) -> None:
    """企业停用或试用到期时，拒绝写入类操作。"""
    from .platform_models import Tenant

    with platform_session() as pdb:
        tenant = pdb.get(Tenant, tenant_id)
    if tenant is None or tenant.status in ("停用", "已注销"):
        raise HTTPException(403, "企业已停用，请联系平台客服")


def deregister_tenant(tenant_id: str, *, drop_data: bool) -> dict:
    """企业注销：作废账号索引；drop_data 时删除 schema 和 bucket（不可恢复）。"""
    from . import storage
    from .db import drop_tenant_schema
    from .platform_models import Account, Tenant
    from .tenancy import bucket_for

    if tenant_id == DEFAULT_TENANT and drop_data:
        raise HTTPException(400, "默认企业不能删除数据")
    pdb = platform_session()
    try:
        tenant = pdb.get(Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(404, "企业不存在")
        removed_accounts = pdb.query(Account).filter(Account.tenant_id == tenant_id).delete(synchronize_session=False)
        tenant.status = "已注销"
        pdb.commit()
    finally:
        pdb.close()
    objects = 0
    if drop_data:
        drop_tenant_schema(tenant_id)
        try:
            objects = storage.remove_bucket(bucket_for(tenant_id))
        except Exception:  # noqa: BLE001
            logger.exception("删除企业 %s 的 bucket 失败", tenant_id)
    return {"accounts": removed_accounts, "objects": objects}
