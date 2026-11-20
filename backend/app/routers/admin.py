"""平台管理后台：企业、组织架构、积分与扣费规则、订单与对公转账、发票、后台账号。

后台默认只看企业的元数据和统计；企业的文件和知识库内容需要企业管理员授予「运维授权」后才能查看，
且每次查看都会记入平台审计。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import billing, fee_stats, ratelimit, storage
from ..auth import hash_password, random_password, verify_password
from ..db import get_platform_db, tenant_session
from ..platform_auth import (
    ADMIN_ROLES,
    ROLE_FINANCE,
    ROLE_OPS,
    ROLE_READONLY,
    ROLE_SUPER,
    active_support_grant,
    client_ip,
    get_current_admin,
    ip_allowed,
    new_totp_secret,
    platform_audit,
    require_roles,
    totp_uri,
    verify_totp,
)
from ..tenancy import DEFAULT_TENANT, bucket_for, use_tenant, valid_tenant_id
from ..tenants import tenant_kind
from ..tokens import create_platform_token
from .billing import invoice_out, ledger_out, order_out

router = APIRouter(prefix="/api/admin", tags=["admin"])

ops = require_roles(ROLE_OPS)
finance = require_roles(ROLE_FINANCE)
anyone = require_roles(ROLE_OPS, ROLE_FINANCE, ROLE_READONLY)


def _dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


def _parse_dt(text: str | None) -> datetime | None:
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
    raise HTTPException(400, "日期格式应为 YYYY-MM-DD")


def _admin_out(a) -> dict:
    return {
        "id": a.id,
        "email": a.email,
        "name": a.name,
        "role": a.role,
        "disabled": bool(a.disabled),
        "totpEnabled": bool(a.totp_secret),
        "lastLoginAt": _dt(a.last_login_at),
    }


def _tenant(pdb: Session, tenant_id: str):
    from ..platform_models import Tenant

    if not valid_tenant_id(tenant_id):
        raise HTTPException(404, "企业不存在")
    t = pdb.get(Tenant, tenant_id)
    if t is None:
        raise HTTPException(404, "企业不存在")
    return t


# ---------------------------------------------------------------------------
# 登录与后台账号
# ---------------------------------------------------------------------------


class AdminLoginIn(BaseModel):
    email: str
    password: str
    totp: str = ""


@router.post("/auth/login")
def admin_login(payload: AdminLoginIn, request: Request, pdb: Session = Depends(get_platform_db)) -> dict:
    from ..platform_models import PlatformAdmin

    ip = client_ip(request)
    if not ip_allowed(ip):
        raise HTTPException(403, "当前 IP 不允许访问平台后台")
    email = payload.email.strip().lower()
    keys = (f"padm:{email}", f"padm-ip:{ip}")
    if ratelimit.is_locked(*keys):
        raise HTTPException(429, "登录失败次数过多，请稍后再试")
    admin = pdb.query(PlatformAdmin).filter(PlatformAdmin.email == email).first()
    if admin is None or admin.disabled or not verify_password(payload.password, admin.password_hash):
        ratelimit.record_failure(*keys)
        raise HTTPException(401, "账号或密码不正确")
    if admin.totp_secret:
        if not payload.totp:
            raise HTTPException(401, "请输入动态验证码")
        if not verify_totp(admin.totp_secret, payload.totp):
            ratelimit.record_failure(*keys)
            raise HTTPException(401, "动态验证码不正确")
    ratelimit.reset(*keys)
    admin.last_login_at = datetime.utcnow()
    platform_audit(pdb, admin, "后台登录", ip=ip)
    pdb.commit()
    return {"token": create_platform_token(admin.id, admin.token_version or 0), "admin": _admin_out(admin)}


@router.get("/auth/me")
def admin_me(admin=Depends(get_current_admin)) -> dict:
    return _admin_out(admin)


class PasswordIn(BaseModel):
    oldPassword: str
    newPassword: str = Field(min_length=10, max_length=128)


@router.post("/auth/password")
def change_password(payload: PasswordIn, request: Request, admin=Depends(get_current_admin), pdb: Session = Depends(get_platform_db)) -> dict:
    if not verify_password(payload.oldPassword, admin.password_hash):
        raise HTTPException(400, "原密码不正确")
    if payload.newPassword.isdigit() or payload.newPassword.isalpha():
        raise HTTPException(400, "密码需同时包含字母和数字")
    admin.password_hash = hash_password(payload.newPassword)
    admin.token_version = int(admin.token_version or 0) + 1
    platform_audit(pdb, admin, "修改后台密码", ip=client_ip(request))
    pdb.commit()
    return {"token": create_platform_token(admin.id, admin.token_version)}


@router.post("/auth/totp/setup")
def totp_setup(admin=Depends(get_current_admin)) -> dict:
    secret = new_totp_secret()
    return {"secret": secret, "uri": totp_uri(secret, admin.email)}


class TotpEnableIn(BaseModel):
    secret: str
    code: str


@router.post("/auth/totp/enable")
def totp_enable(payload: TotpEnableIn, request: Request, admin=Depends(get_current_admin), pdb: Session = Depends(get_platform_db)) -> dict:
    if not verify_totp(payload.secret, payload.code):
        raise HTTPException(400, "动态验证码不正确，请确认手机时间准确")
    admin.totp_secret = payload.secret
    platform_audit(pdb, admin, "开启二次验证", ip=client_ip(request))
    pdb.commit()
    return _admin_out(admin)


class TotpDisableIn(BaseModel):
    code: str


@router.post("/auth/totp/disable")
def totp_disable(payload: TotpDisableIn, request: Request, admin=Depends(get_current_admin), pdb: Session = Depends(get_platform_db)) -> dict:
    if admin.totp_secret and not verify_totp(admin.totp_secret, payload.code):
        raise HTTPException(400, "动态验证码不正确")
    admin.totp_secret = ""
    platform_audit(pdb, admin, "关闭二次验证", ip=client_ip(request))
    pdb.commit()
    return _admin_out(admin)


class AdminIn(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    name: str = Field("", max_length=60)
    role: str = ROLE_OPS


class AdminPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    disabled: bool | None = None
    resetPassword: bool = False
    resetTotp: bool = False


@router.get("/admins")
def list_admins(admin=Depends(require_roles()), pdb: Session = Depends(get_platform_db)) -> list[dict]:
    from ..platform_models import PlatformAdmin

    return [_admin_out(a) for a in pdb.query(PlatformAdmin).order_by(PlatformAdmin.created_at.asc()).all()]


@router.post("/admins")
def create_admin(payload: AdminIn, request: Request, admin=Depends(require_roles()), pdb: Session = Depends(get_platform_db)) -> dict:
    from ..platform_models import PlatformAdmin

    if payload.role not in ADMIN_ROLES:
        raise HTTPException(400, "角色不合法")
    email = payload.email.strip().lower()
    if pdb.query(PlatformAdmin).filter(PlatformAdmin.email == email).first():
        raise HTTPException(409, "该邮箱已是后台账号")
    password = random_password(14)
    row = PlatformAdmin(email=email, name=payload.name.strip(), role=payload.role, password_hash=hash_password(password))
    pdb.add(row)
    platform_audit(pdb, admin, "新增后台账号", target=email, detail=payload.role, ip=client_ip(request))
    pdb.commit()
    return {**_admin_out(row), "initialPassword": password}


@router.patch("/admins/{admin_id}")
def patch_admin(admin_id: str, payload: AdminPatch, request: Request, admin=Depends(require_roles()), pdb: Session = Depends(get_platform_db)) -> dict:
    from ..platform_models import PlatformAdmin

    row = pdb.get(PlatformAdmin, admin_id)
    if row is None:
        raise HTTPException(404, "账号不存在")
    if row.id == admin.id and (payload.disabled or (payload.role and payload.role != ROLE_SUPER)):
        raise HTTPException(400, "不能停用自己或降低自己的角色")
    out: dict = {}
    if payload.name is not None:
        row.name = payload.name.strip()
    if payload.role is not None:
        if payload.role not in ADMIN_ROLES:
            raise HTTPException(400, "角色不合法")
        row.role = payload.role
    if payload.disabled is not None:
        row.disabled = payload.disabled
    if payload.resetPassword:
        password = random_password(14)
        row.password_hash = hash_password(password)
        out["initialPassword"] = password
    if payload.resetTotp:
        row.totp_secret = ""
    if payload.disabled or payload.resetPassword or payload.role is not None:
        row.token_version = int(row.token_version or 0) + 1
    platform_audit(pdb, admin, "修改后台账号", target=row.email, detail=payload.model_dump_json(exclude={"resetPassword"}), ip=client_ip(request))
    pdb.commit()
    return {**_admin_out(row), **out}


# ---------------------------------------------------------------------------
# 概览
# ---------------------------------------------------------------------------


@router.get("/dashboard")
def dashboard(admin=Depends(anyone), pdb: Session = Depends(get_platform_db)) -> dict:
    from ..platform_models import Account, BankTransfer, CreditLedger, Invoice, RechargeOrder, Tenant, UsageRecord

    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = today.replace(day=1)
    by_status = dict(pdb.query(Tenant.status, func.count(Tenant.id)).group_by(Tenant.status).all())
    revenue_month = pdb.query(func.coalesce(func.sum(RechargeOrder.amount_cents), 0)).filter(RechargeOrder.status == "已支付", RechargeOrder.paid_at >= month).scalar()
    consumed_today = pdb.query(func.coalesce(func.sum(CreditLedger.amount), 0)).filter(CreditLedger.kind == "消费", CreditLedger.created_at >= today).scalar()
    tokens_today = pdb.query(
        func.coalesce(func.sum(UsageRecord.prompt_tokens), 0), func.coalesce(func.sum(UsageRecord.completion_tokens), 0)
    ).filter(UsageRecord.created_at >= today).one()
    trend = []
    for i in range(13, -1, -1):
        start = today - timedelta(days=i)
        end = start + timedelta(days=1)
        spent = pdb.query(func.coalesce(func.sum(CreditLedger.amount), 0)).filter(CreditLedger.kind == "消费", CreditLedger.created_at >= start, CreditLedger.created_at < end).scalar()
        paid = pdb.query(func.coalesce(func.sum(RechargeOrder.amount_cents), 0)).filter(RechargeOrder.status == "已支付", RechargeOrder.paid_at >= start, RechargeOrder.paid_at < end).scalar()
        trend.append({"date": start.strftime("%m-%d"), "credits": -int(spent or 0), "revenueCents": int(paid or 0)})
    return {
        "tenants": {"total": sum(by_status.values()), "byStatus": by_status},
        "accounts": pdb.query(func.count(Account.login)).scalar() or 0,
        "revenueMonthCents": int(revenue_month or 0),
        "creditsConsumedToday": -int(consumed_today or 0),
        "tokensToday": int(tokens_today[0] or 0) + int(tokens_today[1] or 0),
        "pending": {
            "invoices": pdb.query(func.count(Invoice.id)).filter(Invoice.status.in_(("待审核", "开具中"))).scalar() or 0,
            "transfers": pdb.query(func.count(BankTransfer.id)).filter(BankTransfer.status == "待认领").scalar() or 0,
            "verifications": pdb.query(func.count(Tenant.id)).filter(Tenant.verify_status == "待审核").scalar() or 0,
        },
        "trend": trend,
    }


# ---------------------------------------------------------------------------
# 企业
# ---------------------------------------------------------------------------


def _tenant_out(t, wallet: dict | None = None, seats_used: int | None = None) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "kind": tenant_kind(t),
        "status": t.status,
        "planCode": t.plan_code,
        "seats": t.seats,
        "seatsUsed": seats_used,
        "storageQuotaMb": t.storage_quota_mb,
        "features": t.features_json or {},
        "verifyStatus": t.verify_status,
        "verifyNote": t.verify_note or "",
        "licenseNo": t.license_no or "",
        "hasLicense": bool(t.license_key),
        "contactName": t.contact_name or "",
        "contactPhone": t.contact_phone or "",
        "contactEmail": t.contact_email or "",
        "trialEndsAt": _dt(t.trial_ends_at),
        "expiresAt": _dt(t.expires_at),
        "lowBalanceThreshold": t.low_balance_threshold or 0,
        "createdAt": _dt(t.created_at),
        "wallet": wallet,
    }


@router.get("/tenants")
def list_tenants(
    q: str = "",
    status: str = "",
    verify: str = "",
    kind: str = "",
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    admin=Depends(anyone),
    pdb: Session = Depends(get_platform_db),
) -> dict:
    from ..platform_models import Tenant, Wallet
    from ..tenants import seats_used

    query = pdb.query(Tenant)
    if kind:
        query = query.filter(Tenant.kind == kind)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter((Tenant.name.ilike(like)) | (Tenant.id.ilike(like)) | (Tenant.contact_phone.ilike(like)) | (Tenant.contact_email.ilike(like)))
    if status:
        query = query.filter(Tenant.status == status)
    if verify:
        query = query.filter(Tenant.verify_status == verify)
    total = query.count()
    rows = query.order_by(Tenant.created_at.desc()).offset((page - 1) * size).limit(size).all()
    wallets = {w.tenant_id: w for w in pdb.query(Wallet).filter(Wallet.tenant_id.in_([t.id for t in rows])).all()}
    items = []
    for t in rows:
        w = wallets.get(t.id)
        try:
            used = seats_used(t.id)
        except Exception:  # noqa: BLE001 —— 已删除 schema 的注销企业读不到成员
            used = None
        items.append(_tenant_out(t, {"balance": int(w.balance or 0), "held": int(w.held or 0)} if w else None, used))
    return {"total": total, "items": items}


class TenantCreateIn(BaseModel):
    kind: str = Field("企业", pattern="^(企业|个人)$")
    name: str = Field(min_length=2, max_length=120)
    adminName: str = Field("", max_length=60)
    adminLogin: str = Field(min_length=3, max_length=64)
    planCode: str = "trial"
    contactPhone: str = ""
    contactEmail: str = ""


@router.post("/tenants")
def create_tenant(payload: TenantCreateIn, request: Request, admin=Depends(ops), pdb: Session = Depends(get_platform_db)) -> dict:
    from ..platform_models import Plan
    from ..tenants import create_tenant as do_create

    if payload.planCode != "trial" and pdb.get(Plan, payload.planCode) is None:
        raise HTTPException(400, "套餐不存在")
    password = random_password(12)
    tid, _ = do_create(
        name=payload.name,
        admin_name=payload.adminName or payload.adminLogin,
        admin_login=payload.adminLogin,
        admin_password=password,
        contact_phone=payload.contactPhone,
        contact_email=payload.contactEmail,
        plan_code=payload.planCode,
        operator=admin.name or admin.email,
        kind=payload.kind,
    )
    platform_audit(pdb, admin, "开通企业" if payload.kind == "企业" else "开通个人账号", tenant_id=tid, target=payload.name, ip=client_ip(request))
    pdb.commit()
    return {"id": tid, "adminLogin": payload.adminLogin.strip().lower(), "initialPassword": password}


@router.get("/tenants/{tenant_id}")
def tenant_detail(tenant_id: str, admin=Depends(anyone), pdb: Session = Depends(get_platform_db)) -> dict:
    from ..platform_models import Subscription
    from ..tenants import seats_used

    t = _tenant(pdb, tenant_id)
    subs = pdb.query(Subscription).filter(Subscription.tenant_id == t.id).order_by(Subscription.created_at.desc()).limit(10).all()
    out = _tenant_out(t, billing.balance_of(pdb, t.id), seats_used(t.id))
    out["subscriptions"] = [
        {"planCode": s.plan_code, "startsAt": _dt(s.starts_at), "endsAt": _dt(s.ends_at), "status": s.status, "orderId": s.order_id} for s in subs
    ]
    try:
        count, size = storage.bucket_usage_bytes(bucket_for(t.id))
        out["storage"] = {"bucket": bucket_for(t.id), "objects": count, "bytes": size}
    except Exception as exc:  # noqa: BLE001
        out["storage"] = {"bucket": bucket_for(t.id), "error": str(exc)[:200]}
    grant = active_support_grant(pdb, t.id)
    out["supportGrant"] = {"expiresAt": _dt(grant.expires_at), "grantedBy": grant.granted_by} if grant else None
    return out


class TenantPatch(BaseModel):
    name: str | None = None
    status: str | None = None
    planCode: str | None = None
    seats: int | None = Field(None, ge=1, le=100000)
    storageQuotaMb: int | None = Field(None, ge=0)
    expiresAt: str | None = None
    features: dict | None = None
    lowBalanceThreshold: int | None = Field(None, ge=0)


def _assign_plan(
    pdb: Session,
    tenant,
    plan_code: str,
    operator: str,
    ends_at: datetime | None = None,
    *,
    open_ended: bool = False,
) -> None:
    """后台改套餐时按套餐入账积分。只改名称、席位时不会走到这里。

    到期日留空表示长期：积分和企业服务都不设到期。填了日期就按该日到期；
    日期已过则从今天起按套餐天数重算，避免积分一入账就过期。席位和存储仍以表单为准。
    """
    from ..platform_models import Plan, Subscription

    plan = pdb.get(Plan, plan_code)
    if plan is None:
        if plan_code not in ("legacy",):
            raise HTTPException(400, "套餐不存在")
        tenant.plan_code = plan_code
        return
    now = datetime.utcnow()
    current = (
        pdb.query(Subscription)
        .filter(Subscription.tenant_id == tenant.id, Subscription.status == "生效", Subscription.ends_at > now)
        .order_by(Subscription.ends_at.desc())
        .first()
    )
    ends = None
    if not open_ended:
        starts = now
        ends = ends_at or (starts + timedelta(days=int(plan.duration_days or 365)))
        if ends <= now:
            ends = now + timedelta(days=int(plan.duration_days or 365))
        if current is not None and current.plan_code != plan.code:
            current.status = "已取消"
        pdb.add(Subscription(tenant_id=tenant.id, plan_code=plan.code, starts_at=starts, ends_at=ends))
        tenant.expires_at = ends
    else:
        if current is not None:
            current.status = "已取消"
        tenant.expires_at = None
    tenant.plan_code = plan.code
    billing.ensure_wallet(pdb, tenant.id)
    stamp = now.strftime("%Y%m%d%H%M%S")
    if int(plan.credits or 0) > 0:
        billing.grant(
            pdb,
            tenant.id,
            int(plan.credits),
            source="套餐",
            expires_at=ends,
            note=f"后台开通{plan.name}",
            operator=operator,
            idem_key=f"admin-plan:{tenant.id}:{plan.code}:{stamp}",
        )
    if int(plan.bonus_credits or 0) > 0:
        billing.grant(
            pdb,
            tenant.id,
            int(plan.bonus_credits),
            source="赠送",
            expires_at=ends,
            note=f"后台开通{plan.name}赠送",
            operator=operator,
            idem_key=f"admin-plan-bonus:{tenant.id}:{plan.code}:{stamp}",
        )


@router.patch("/tenants/{tenant_id}")
def patch_tenant(tenant_id: str, payload: TenantPatch, request: Request, admin=Depends(ops), pdb: Session = Depends(get_platform_db)) -> dict:
    t = _tenant(pdb, tenant_id)
    if payload.status is not None:
        if payload.status not in ("试用", "正常", "停用"):
            raise HTTPException(400, "状态不合法（注销请使用注销接口）")
        if t.id == DEFAULT_TENANT and payload.status == "停用":
            raise HTTPException(400, "默认企业不能停用")
        t.status = payload.status
    if payload.name is not None and payload.name.strip():
        t.name = payload.name.strip()
    plan_changed = payload.planCode is not None and payload.planCode != t.plan_code
    if plan_changed:
        # 表单留空是「长期」；不传该字段则按套餐天数计算，避免旧接口把到期日清掉
        open_ended = payload.expiresAt == ""
        chosen_end = None if payload.expiresAt is None or open_ended else _parse_dt(payload.expiresAt)
        operator = (getattr(admin, "name", "") or getattr(admin, "email", "") or "平台管理员")
        _assign_plan(pdb, t, payload.planCode or "", operator, chosen_end, open_ended=open_ended)
    if payload.seats is not None:
        t.seats = payload.seats
    if payload.storageQuotaMb is not None:
        t.storage_quota_mb = payload.storageQuotaMb
    if payload.expiresAt is not None and not plan_changed:
        t.expires_at = _parse_dt(payload.expiresAt)
    if payload.features is not None:
        t.features_json = payload.features
    if payload.lowBalanceThreshold is not None:
        t.low_balance_threshold = payload.lowBalanceThreshold
    platform_audit(pdb, admin, "修改企业", tenant_id=t.id, target=t.name, detail=payload.model_dump_json(exclude_none=True), ip=client_ip(request))
    pdb.commit()
    from ..tenants import clear_block_cache

    clear_block_cache(t.id)
    return _tenant_out(t)


class VerifyIn(BaseModel):
    approve: bool
    note: str = ""


@router.post("/tenants/{tenant_id}/verify")
def review_verify(tenant_id: str, payload: VerifyIn, request: Request, admin=Depends(ops), pdb: Session = Depends(get_platform_db)) -> dict:
    t = _tenant(pdb, tenant_id)
    if t.verify_status != "待审核":
        raise HTTPException(400, "该企业没有待审核的认证")
    if not payload.approve and not payload.note.strip():
        raise HTTPException(400, "驳回需填写原因")
    t.verify_status = "已认证" if payload.approve else "已驳回"
    t.verify_note = payload.note.strip()
    platform_audit(pdb, admin, "企业认证审核", tenant_id=t.id, target=t.name, detail=f"{t.verify_status} {t.verify_note}", ip=client_ip(request))
    pdb.commit()
    return _tenant_out(t)


@router.get("/tenants/{tenant_id}/license")
def view_license(tenant_id: str, request: Request, admin=Depends(ops), pdb: Session = Depends(get_platform_db)):
    """营业执照是企业为认证主动提交给平台的材料，审核时可查看，查看记审计。"""
    t = _tenant(pdb, tenant_id)
    if not t.license_key:
        raise HTTPException(404, "未上传营业执照")
    platform_audit(pdb, admin, "查看营业执照", tenant_id=t.id, target=t.name, ip=client_ip(request))
    pdb.commit()
    return storage.http_response(t.license_key, inline=True, bucket=bucket_for(t.id))


class DeregisterIn(BaseModel):
    confirmName: str
    dropData: bool = False


@router.post("/tenants/{tenant_id}/deregister")
def deregister(tenant_id: str, payload: DeregisterIn, request: Request, admin=Depends(require_roles()), pdb: Session = Depends(get_platform_db)) -> dict:
    from ..tenants import deregister_tenant

    t = _tenant(pdb, tenant_id)
    if payload.confirmName.strip() != t.name:
        raise HTTPException(400, "请输入完整的企业名称确认注销")
    result = deregister_tenant(t.id, drop_data=payload.dropData)
    platform_audit(pdb, admin, "注销企业", tenant_id=t.id, target=t.name, detail=f"删除数据={payload.dropData} {result}", ip=client_ip(request))
    pdb.commit()
    return result


# ---------------------------------------------------------------------------
# 企业组织架构与成员
# ---------------------------------------------------------------------------


@router.get("/tenants/{tenant_id}/org")
def tenant_org(tenant_id: str, admin=Depends(anyone), pdb: Session = Depends(get_platform_db)) -> dict:
    from ..models import CustomRole, Department, User

    t = _tenant(pdb, tenant_id)
    month_spent = _month_spent_by_user(pdb, t.id)
    with use_tenant(t.id), tenant_session(t.id) as db:
        depts = db.query(Department).order_by(Department.sort_order.asc()).all()
        roles = {r.id: r.name for r in db.query(CustomRole).all()}
        users = db.query(User).order_by(User.created_at.asc()).all()
        dept_names = {d.id: d.name for d in depts}
        return {
            "departments": [{"id": d.id, "name": d.name, "parentId": d.parent_id, "leaderId": d.leader_id} for d in depts],
            "users": [
                {
                    "id": u.id,
                    "name": u.name,
                    "account": u.email,
                    "phone": u.phone or "",
                    "role": u.role,
                    "customRole": roles.get(u.custom_role_id or "", ""),
                    "departmentId": u.department_id,
                    "departmentName": dept_names.get(u.department_id or "", ""),
                    "disabled": bool(u.disabled),
                    "monthlyCreditLimit": u.monthly_credit_limit,
                    "monthSpent": month_spent.get(u.id, 0),
                    "lastLoginAt": _dt(u.last_login_at),
                    "createdAt": _dt(u.created_at),
                }
                for u in users
            ],
        }


def _month_spent_by_user(pdb: Session, tenant_id: str) -> dict[str, int]:
    from ..platform_models import CreditLedger

    start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = (
        pdb.query(CreditLedger.user_id, func.sum(CreditLedger.amount))
        .filter(CreditLedger.tenant_id == tenant_id, CreditLedger.kind == "消费", CreditLedger.created_at >= start)
        .group_by(CreditLedger.user_id)
        .all()
    )
    return {uid: -int(v or 0) for uid, v in rows if uid}


class TenantUserPatch(BaseModel):
    disabled: bool | None = None
    role: str | None = None
    monthlyCreditLimit: int | None = None  # -1 取消限额
    resetPassword: bool = False


@router.patch("/tenants/{tenant_id}/users/{user_id}")
def patch_tenant_user(
    tenant_id: str, user_id: str, payload: TenantUserPatch, request: Request, admin=Depends(ops), pdb: Session = Depends(get_platform_db)
) -> dict:
    from ..models import User
    from ..permissions import ROLE_PERMS

    t = _tenant(pdb, tenant_id)
    out: dict = {}
    with use_tenant(t.id), tenant_session(t.id) as db:
        user = db.get(User, user_id)
        if user is None:
            raise HTTPException(404, "成员不存在")
        if payload.role is not None:
            if payload.role not in ROLE_PERMS:
                raise HTTPException(400, "角色不合法")
            user.role = payload.role
        if payload.disabled is not None:
            user.disabled = payload.disabled
        if payload.monthlyCreditLimit is not None:
            user.monthly_credit_limit = None if payload.monthlyCreditLimit < 0 else payload.monthlyCreditLimit
        if payload.resetPassword:
            password = random_password(12)
            user.password_hash = hash_password(password)
            out["initialPassword"] = password
        if payload.disabled or payload.resetPassword or payload.role is not None:
            user.token_version = int(user.token_version or 0) + 1
        db.commit()
        name = user.name
    platform_audit(pdb, admin, "修改企业成员", tenant_id=t.id, target=name, detail=payload.model_dump_json(exclude={"resetPassword"}, exclude_none=True), ip=client_ip(request))
    pdb.commit()
    return {"ok": True, **out}


# ---------------------------------------------------------------------------
# 企业知识库与存储（默认只看统计；有运维授权才能看明细）
# ---------------------------------------------------------------------------


@router.get("/tenants/{tenant_id}/libraries")
def tenant_libraries(tenant_id: str, request: Request, admin=Depends(anyone), pdb: Session = Depends(get_platform_db)) -> dict:
    from ..models import KnowledgeDocument, ProductFeature, ProductLibrary, Project, QualificationAsset, WriterChatMessage

    t = _tenant(pdb, tenant_id)
    grant = active_support_grant(pdb, t.id)
    with use_tenant(t.id), tenant_session(t.id) as db:
        knowledge = {
            scope: {"count": int(c or 0), "bytes": int(b or 0)}
            for scope, c, b in db.query(KnowledgeDocument.scope, func.count(KnowledgeDocument.id), func.sum(KnowledgeDocument.size_bytes))
            .group_by(KnowledgeDocument.scope)
            .all()
        }
        stats = {
            "knowledge": knowledge,
            "qualifications": db.query(func.count(QualificationAsset.id)).scalar() or 0,
            "productLibraries": db.query(func.count(ProductLibrary.id)).scalar() or 0,
            "productFeatures": db.query(func.count(ProductFeature.id)).scalar() or 0,
            "projects": db.query(func.count(Project.id)).scalar() or 0,
            "chatMessages": db.query(func.count(WriterChatMessage.id)).scalar() or 0,
        }
        detail = None
        if grant is not None:
            detail = {
                "knowledge": [
                    {"id": d.id, "title": d.title, "scope": d.scope, "type": d.type, "sizeBytes": d.size_bytes or 0, "createdAt": _dt(d.created_at)}
                    for d in db.query(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc()).limit(200).all()
                ],
                "qualifications": [
                    {"id": a.id, "name": a.name, "category": a.kind, "validUntil": a.valid_until or "", "reviewStatus": a.review_status}
                    for a in db.query(QualificationAsset).limit(200).all()
                ],
                "productLibraries": [{"id": lib.id, "name": lib.name, "category": lib.category} for lib in db.query(ProductLibrary).all()],
            }
    if detail is not None:
        platform_audit(pdb, admin, "运维查看企业库", tenant_id=t.id, target=t.name, ip=client_ip(request))
        pdb.commit()
    return {
        "stats": stats,
        "supportGrant": {"expiresAt": _dt(grant.expires_at), "grantedBy": grant.granted_by} if grant else None,
        "detail": detail,
    }


@router.get("/tenants/{tenant_id}/storage")
def tenant_storage(tenant_id: str, admin=Depends(anyone), pdb: Session = Depends(get_platform_db)) -> dict:
    """按顶层目录汇总对象数和大小，不列文件名。"""
    t = _tenant(pdb, tenant_id)
    bucket = bucket_for(t.id)
    prefixes: dict[str, list[int]] = {}
    try:
        client = storage._client()
        if client.bucket_exists(bucket):
            for obj in client.list_objects(bucket, recursive=True):
                top = (obj.object_name or "").split("/", 1)[0] or "(root)"
                slot = prefixes.setdefault(top, [0, 0])
                slot[0] += 1
                slot[1] += int(obj.size or 0)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"对象存储不可用：{exc}") from exc
    items = sorted(({"prefix": k, "objects": v[0], "bytes": v[1]} for k, v in prefixes.items()), key=lambda r: -r["bytes"])
    return {
        "bucket": bucket,
        "quotaMb": t.storage_quota_mb,
        "objects": sum(i["objects"] for i in items),
        "bytes": sum(i["bytes"] for i in items),
        "prefixes": items,
    }


# ---------------------------------------------------------------------------
# 积分
# ---------------------------------------------------------------------------


class AdjustIn(BaseModel):
    delta: int
    note: str = Field(min_length=2, max_length=200)
    expiresAt: str | None = None


@router.post("/tenants/{tenant_id}/credits")
def adjust_credits(tenant_id: str, payload: AdjustIn, request: Request, admin=Depends(finance), pdb: Session = Depends(get_platform_db)) -> dict:
    t = _tenant(pdb, tenant_id)
    if abs(payload.delta) > 10_000_000:
        raise HTTPException(400, "单次调整不能超过 1000 万积分")
    billing.adjust(pdb, t.id, payload.delta, note=payload.note.strip(), operator=admin.name or admin.email, expires_at=_parse_dt(payload.expiresAt))
    platform_audit(pdb, admin, "调整积分", tenant_id=t.id, target=t.name, detail=f"{payload.delta:+d} {payload.note}", ip=client_ip(request))
    pdb.commit()
    return billing.balance_of(pdb, t.id)


FEE_KIND = Query("", pattern="^(|企业|个人)$")
FEE_DAYS = Query(30, ge=0, le=3650)


def _csv_response(data: bytes, filename: str) -> Response:
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/wallets")
def list_wallets(
    q: str = "",
    kind: str = FEE_KIND,
    days: int = FEE_DAYS,
    sort: str = "spent",
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    admin=Depends(anyone),
    pdb: Session = Depends(get_platform_db),
) -> dict:
    data = fee_stats.tenant_fees(pdb, q=q, kind=kind, days=days, sort=sort)
    items = data["items"][(page - 1) * size : page * size]
    fee_stats.fill_members(items)
    return {"total": len(data["items"]), "days": days, "items": items, "summary": data["summary"]}


@router.get("/wallets.csv")
def export_wallets(
    request: Request,
    q: str = "",
    kind: str = FEE_KIND,
    days: int = FEE_DAYS,
    sort: str = "spent",
    admin=Depends(finance),
    pdb: Session = Depends(get_platform_db),
) -> Response:
    items = fee_stats.tenant_fees(pdb, q=q, kind=kind, days=days, sort=sort)["items"]
    fee_stats.fill_members(items)
    platform_audit(pdb, admin, "导出企业费用", detail=f"{len(items)} 行，近 {days or '全部'} 天", ip=client_ip(request))
    pdb.commit()
    return _csv_response(fee_stats.to_csv(items, fee_stats.TENANT_COLUMNS), f"企业费用-{datetime.utcnow():%Y%m%d}.csv")


@router.get("/users")
def list_all_users(
    q: str = "",
    tenantId: str = "",
    kind: str = FEE_KIND,
    days: int = FEE_DAYS,
    sort: str = "spent",
    refresh: bool = False,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    admin=Depends(anyone),
    pdb: Session = Depends(get_platform_db),
) -> dict:
    if refresh:
        fee_stats.clear_directory_cache()
    rows = fee_stats.user_fees(pdb, q=q, tenant_id=tenantId, kind=kind, days=days, sort=sort)
    summary = {
        "users": len(rows),
        "activeUsers": sum(1 for r in rows if r["periodCredits"] > 0 or r["calls"] > 0),
        "periodCredits": sum(r["periodCredits"] for r in rows),
        "promptTokens": sum(r["promptTokens"] for r in rows),
        "completionTokens": sum(r["completionTokens"] for r in rows),
    }
    return {"total": len(rows), "days": days, "items": rows[(page - 1) * size : page * size], "summary": summary}


@router.get("/users.csv")
def export_all_users(
    request: Request,
    q: str = "",
    tenantId: str = "",
    kind: str = FEE_KIND,
    days: int = FEE_DAYS,
    sort: str = "spent",
    admin=Depends(finance),
    pdb: Session = Depends(get_platform_db),
) -> Response:
    rows = fee_stats.user_fees(pdb, q=q, tenant_id=tenantId, kind=kind, days=days, sort=sort)
    platform_audit(pdb, admin, "导出全员费用", tenant_id=tenantId or None, detail=f"{len(rows)} 行，近 {days or '全部'} 天", ip=client_ip(request))
    pdb.commit()
    return _csv_response(fee_stats.to_csv(rows, fee_stats.USER_COLUMNS), f"全员费用-{datetime.utcnow():%Y%m%d}.csv")


@router.get("/users/{tenant_id}/{user_id}/usage")
def user_usage_detail(
    tenant_id: str,
    user_id: str,
    days: int = Query(30, ge=1, le=365),
    admin=Depends(anyone),
    pdb: Session = Depends(get_platform_db),
) -> dict:
    if not valid_tenant_id(tenant_id):
        raise HTTPException(404, "企业不存在")
    return fee_stats.user_usage(pdb, tenant_id, user_id, days)


@router.get("/ledger")
def platform_ledger(
    tenantId: str = "",
    kind: str = "",
    userId: str = "",
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    admin=Depends(anyone),
    pdb: Session = Depends(get_platform_db),
) -> dict:
    from ..platform_models import CreditLedger, Tenant

    query = pdb.query(CreditLedger)
    if tenantId:
        query = query.filter(CreditLedger.tenant_id == tenantId)
    if kind:
        query = query.filter(CreditLedger.kind == kind)
    if userId:
        query = query.filter(CreditLedger.user_id == userId)
    total = query.count()
    rows = query.order_by(CreditLedger.created_at.desc()).offset((page - 1) * size).limit(size).all()
    names = dict(pdb.query(Tenant.id, Tenant.name).filter(Tenant.id.in_({r.tenant_id for r in rows})).all())
    return {"total": total, "items": [{**ledger_out(r), "tenantId": r.tenant_id, "tenantName": names.get(r.tenant_id, "")} for r in rows]}


@router.get("/usage")
def platform_usage(
    days: int = Query(30, ge=1, le=366),
    tenantId: str = "",
    admin=Depends(anyone),
    pdb: Session = Depends(get_platform_db),
) -> dict:
    """token 与积分统计：按企业、按模型、按功能。"""
    from ..platform_models import Tenant, UsageRecord

    since = datetime.utcnow() - timedelta(days=days)
    base = pdb.query(UsageRecord).filter(UsageRecord.created_at >= since)
    if tenantId:
        base = base.filter(UsageRecord.tenant_id == tenantId)

    def group(col):
        q = pdb.query(
            col,
            func.sum(UsageRecord.prompt_tokens),
            func.sum(UsageRecord.completion_tokens),
            func.sum(UsageRecord.calls),
            func.sum(UsageRecord.credits),
        ).filter(UsageRecord.created_at >= since)
        if tenantId:
            q = q.filter(UsageRecord.tenant_id == tenantId)
        rows = q.group_by(col).all()
        return sorted(
            (
                {"key": k or "", "promptTokens": int(p or 0), "completionTokens": int(c or 0), "calls": int(n or 0), "credits": round(float(cr or 0), 2)}
                for k, p, c, n, cr in rows
            ),
            key=lambda r: -(r["promptTokens"] + r["completionTokens"]),
        )

    by_tenant = group(UsageRecord.tenant_id)
    names = dict(pdb.query(Tenant.id, Tenant.name).all())
    for row in by_tenant:
        row["name"] = names.get(row["key"], row["key"])
    return {"days": days, "byTenant": by_tenant[:100], "byModel": group(UsageRecord.model), "byFeature": group(UsageRecord.feature)}


@router.get("/tenants/{tenant_id}/user-credits")
def tenant_user_credits(tenant_id: str, admin=Depends(anyone), pdb: Session = Depends(get_platform_db)) -> list[dict]:
    from ..models import User
    from ..platform_models import CreditLedger

    t = _tenant(pdb, tenant_id)
    total = dict(
        pdb.query(CreditLedger.user_id, func.sum(CreditLedger.amount))
        .filter(CreditLedger.tenant_id == t.id, CreditLedger.kind == "消费")
        .group_by(CreditLedger.user_id)
        .all()
    )
    month = _month_spent_by_user(pdb, t.id)
    from ..platform_models import UsageRecord

    usage = {
        uid: (int(p or 0) + int(c or 0), last)
        for uid, p, c, last in pdb.query(
            UsageRecord.user_id,
            func.sum(UsageRecord.prompt_tokens),
            func.sum(UsageRecord.completion_tokens),
            func.max(UsageRecord.created_at),
        )
        .filter(UsageRecord.tenant_id == t.id, UsageRecord.created_at >= fee_stats.month_start())
        .group_by(UsageRecord.user_id)
        .all()
    }
    last_used = dict(
        pdb.query(UsageRecord.user_id, func.max(UsageRecord.created_at)).filter(UsageRecord.tenant_id == t.id).group_by(UsageRecord.user_id).all()
    )
    with use_tenant(t.id), tenant_session(t.id) as db:
        users = db.query(User).all()
        return sorted(
            (
                {
                    "userId": u.id,
                    "name": u.name,
                    "account": u.email,
                    "role": u.role or "成员",
                    "monthSpent": month.get(u.id, 0),
                    "monthTokens": usage.get(u.id, (0, None))[0],
                    "totalSpent": -int(total.get(u.id) or 0),
                    "lastUsedAt": _dt(last_used.get(u.id)),
                    "monthlyCreditLimit": u.monthly_credit_limit,
                    "disabled": bool(u.disabled),
                }
                for u in users
            ),
            key=lambda r: -r["monthSpent"],
        )


class PriceIn(BaseModel):
    name: str | None = None
    mode: str | None = Field(None, pattern="^(per_1k_tokens|per_call|free)$")
    unitPrice: float | None = Field(None, ge=0, le=100000)
    estimate: int | None = Field(None, ge=0, le=1000000)
    enabled: bool | None = None


@router.get("/prices")
def list_prices(admin=Depends(anyone), pdb: Session = Depends(get_platform_db)) -> list[dict]:
    from ..platform_models import PriceRule

    return [
        {"feature": r.feature, "name": r.name, "mode": r.mode, "unitPrice": r.unit_price, "estimate": r.estimate, "enabled": bool(r.enabled)}
        for r in pdb.query(PriceRule).order_by(PriceRule.sort_order.asc()).all()
    ]


@router.put("/prices/{feature}")
def update_price(feature: str, payload: PriceIn, request: Request, admin=Depends(finance), pdb: Session = Depends(get_platform_db)) -> dict:
    from ..platform_models import PriceRule

    row = pdb.get(PriceRule, feature)
    if row is None:
        raise HTTPException(404, "计费项不存在")
    before = f"{row.mode} {row.unit_price} 预占{row.estimate}"
    for field, attr in (("name", "name"), ("mode", "mode"), ("unitPrice", "unit_price"), ("estimate", "estimate"), ("enabled", "enabled")):
        value = getattr(payload, field)
        if value is not None:
            setattr(row, attr, value)
    platform_audit(pdb, admin, "修改扣费规则", target=feature, detail=f"{before} → {row.mode} {row.unit_price} 预占{row.estimate}", ip=client_ip(request))
    pdb.commit()
    return {"feature": row.feature, "name": row.name, "mode": row.mode, "unitPrice": row.unit_price, "estimate": row.estimate, "enabled": bool(row.enabled)}


class RatioIn(BaseModel):
    ratio: float = Field(gt=0, le=1000)
    note: str = ""


@router.get("/model-ratios")
def list_ratios(admin=Depends(anyone), pdb: Session = Depends(get_platform_db)) -> list[dict]:
    from ..models import LlmModel
    from ..platform_models import ModelRatio

    ratios = {r.model_key: r for r in pdb.query(ModelRatio).all()}
    out = []
    for m in pdb.query(LlmModel).order_by(LlmModel.name.asc()).all():
        r = ratios.pop(m.id, None) or ratios.pop(m.api_model or "", None)
        out.append({"key": m.id, "name": m.name, "apiModel": m.api_model, "task": m.task, "ratio": r.ratio if r else 1.0, "note": r.note if r else ""})
    for key, r in ratios.items():
        out.append({"key": key, "name": key, "apiModel": key, "task": "", "ratio": r.ratio, "note": r.note})
    return out


@router.put("/model-ratios/{model_key}")
def set_ratio(model_key: str, payload: RatioIn, request: Request, admin=Depends(finance), pdb: Session = Depends(get_platform_db)) -> dict:
    from ..platform_models import ModelRatio

    row = pdb.get(ModelRatio, model_key)
    if row is None:
        row = ModelRatio(model_key=model_key)
        pdb.add(row)
    row.ratio = payload.ratio
    row.note = payload.note
    platform_audit(pdb, admin, "修改模型倍率", target=model_key, detail=str(payload.ratio), ip=client_ip(request))
    pdb.commit()
    return {"key": model_key, "ratio": row.ratio, "note": row.note}


class PlanIn(BaseModel):
    kind: str = Field(pattern="^(套餐|加油包)$")
    audience: str = Field("通用", pattern="^(企业|个人|通用)$")
    name: str = Field(min_length=1, max_length=60)
    priceCents: int = Field(ge=0)
    durationDays: int = Field(365, ge=1, le=3650)
    seats: int = Field(0, ge=0)
    credits: int = Field(0, ge=0)
    bonusCredits: int = Field(0, ge=0)
    storageMb: int = Field(0, ge=0)
    rechargeBonusPct: int = Field(0, ge=0, le=100)
    features: dict = Field(default_factory=dict)
    description: str = ""
    enabled: bool = True
    sortOrder: int = 0


@router.get("/plans")
def list_plans(admin=Depends(anyone), pdb: Session = Depends(get_platform_db)) -> list[dict]:
    from ..platform_models import Plan
    from .billing import _plan_out

    return [{**_plan_out(p), "enabled": bool(p.enabled), "sortOrder": p.sort_order} for p in pdb.query(Plan).order_by(Plan.sort_order.asc()).all()]


@router.put("/plans/{code}")
def save_plan(code: str, payload: PlanIn, request: Request, admin=Depends(finance), pdb: Session = Depends(get_platform_db)) -> dict:
    import re

    from ..platform_models import Plan
    from .billing import _plan_out

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,30}", code):
        raise HTTPException(400, "套餐编码只能是小写字母、数字和横线")
    row = pdb.get(Plan, code)
    if row is None:
        row = Plan(code=code, name=payload.name)
        pdb.add(row)
    row.kind = payload.kind
    row.audience = payload.audience
    row.name = payload.name.strip()
    row.price_cents = payload.priceCents
    row.duration_days = payload.durationDays
    row.seats = payload.seats
    row.credits = payload.credits
    row.bonus_credits = payload.bonusCredits
    row.storage_mb = payload.storageMb
    row.recharge_bonus_pct = payload.rechargeBonusPct
    row.features_json = payload.features
    row.description = payload.description
    row.enabled = payload.enabled
    row.sort_order = payload.sortOrder
    platform_audit(pdb, admin, "保存套餐", target=code, detail=payload.model_dump_json(), ip=client_ip(request))
    pdb.commit()
    return _plan_out(row)


# ---------------------------------------------------------------------------
# 订单与对公转账
# ---------------------------------------------------------------------------


@router.get("/orders")
def list_orders(
    status: str = "",
    channel: str = "",
    tenantId: str = "",
    q: str = "",
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    admin=Depends(anyone),
    pdb: Session = Depends(get_platform_db),
) -> dict:
    from ..platform_models import RechargeOrder, Tenant

    query = pdb.query(RechargeOrder)
    if status:
        query = query.filter(RechargeOrder.status == status)
    if channel:
        query = query.filter(RechargeOrder.channel == channel)
    if tenantId:
        query = query.filter(RechargeOrder.tenant_id == tenantId)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter((RechargeOrder.id.ilike(like)) | (RechargeOrder.transfer_code.ilike(like)) | (RechargeOrder.channel_trade_no.ilike(like)))
    total = query.count()
    rows = query.order_by(RechargeOrder.created_at.desc()).offset((page - 1) * size).limit(size).all()
    names = dict(pdb.query(Tenant.id, Tenant.name).filter(Tenant.id.in_({o.tenant_id for o in rows})).all())
    return {"total": total, "items": [{**order_out(o), "tenantId": o.tenant_id, "tenantName": names.get(o.tenant_id, "")} for o in rows]}


def _order(pdb: Session, order_id: str):
    from ..platform_models import RechargeOrder

    order = pdb.get(RechargeOrder, order_id)
    if order is None:
        raise HTTPException(404, "订单不存在")
    return order


@router.post("/orders/{order_id}/sync")
def sync_order(order_id: str, admin=Depends(finance), pdb: Session = Depends(get_platform_db)) -> dict:
    from ..payments import orders as order_svc

    order = _order(pdb, order_id)
    order_svc.sync_order(pdb, order)
    pdb.refresh(order)
    return order_out(order)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=2, max_length=200)


@router.post("/orders/{order_id}/close")
def close_order(order_id: str, payload: ReasonIn, request: Request, admin=Depends(finance), pdb: Session = Depends(get_platform_db)) -> dict:
    from ..payments import orders as order_svc

    order = _order(pdb, order_id)
    order_svc.close_order(pdb, order, payload.reason)
    platform_audit(pdb, admin, "关闭订单", tenant_id=order.tenant_id, target=order.id, detail=payload.reason, ip=client_ip(request))
    pdb.commit()
    return order_out(order)


@router.post("/orders/{order_id}/mark-paid")
def mark_paid_manually(order_id: str, payload: ReasonIn, request: Request, admin=Depends(require_roles()), pdb: Session = Depends(get_platform_db)) -> dict:
    """线下已确认收款但回调丢失时补单，仅超级管理员。"""
    from ..payments import orders as order_svc

    order = _order(pdb, order_id)
    if order.status not in ("待支付", "待确认", "已关闭"):
        raise HTTPException(400, "订单状态不允许补单")
    order_svc.mark_paid(pdb, order.id, trade_no=f"MANUAL-{order.id}", operator=admin.name or admin.email)
    platform_audit(pdb, admin, "人工补单", tenant_id=order.tenant_id, target=order.id, detail=payload.reason, ip=client_ip(request))
    pdb.commit()
    return order_out(order)


class RefundIn(BaseModel):
    amountCents: int = Field(gt=0)
    reason: str = Field(min_length=2, max_length=200)


@router.post("/orders/{order_id}/refund")
def refund_order(order_id: str, payload: RefundIn, request: Request, admin=Depends(require_roles()), pdb: Session = Depends(get_platform_db)) -> dict:
    """退款：按退款金额比例扣回积分（余额不够时扣光），在线通道同时发起原路退款。"""
    from ..payments import get_channel
    from ..payments.base import PaymentError

    order = _order(pdb, order_id)
    if order.status != "已支付":
        raise HTTPException(400, "只有已支付订单可以退款")
    if payload.amountCents > order.amount_cents:
        raise HTTPException(400, "退款金额不能超过订单金额")
    if (order.invoiced_cents or 0) > 0:
        raise HTTPException(400, "该订单已开发票，请先红冲发票")
    refund_no = ""
    if order.channel in ("alipay", "wechat"):
        try:
            refund_no = get_channel(order.channel).refund(order, payload.amountCents, payload.reason)
        except PaymentError as exc:
            raise HTTPException(502, f"原路退款失败：{exc}") from exc
    total_credits = (order.credits or 0) + (order.bonus_credits or 0)
    claw = total_credits * payload.amountCents // max(order.amount_cents, 1)
    if claw > 0:
        billing.consume(
            pdb,
            order.tenant_id,
            claw,
            kind="调整",
            note=f"订单 {order.id} 退款扣回",
            operator=admin.name or admin.email,
            allow_partial=True,
            idem_key=f"refund:{order.id}",
            ref_id=order.id,
        )
    order.status = "已退款"
    order.refunded_cents = payload.amountCents
    order.note = f"退款 {payload.amountCents / 100:.2f} 元：{payload.reason} {refund_no}".strip()
    platform_audit(pdb, admin, "订单退款", tenant_id=order.tenant_id, target=order.id, detail=order.note, ip=client_ip(request))
    pdb.commit()
    return order_out(order)


def _transfer_out(bt, order=None, tenant_name: str = "") -> dict:
    return {
        "id": bt.id,
        "orderId": bt.order_id,
        "tenantId": bt.tenant_id,
        "tenantName": tenant_name,
        "payerName": bt.payer_name,
        "payerAccount": bt.payer_account,
        "amountCents": bt.amount_cents,
        "orderAmountCents": order.amount_cents if order else None,
        "transferCode": order.transfer_code if order else "",
        "bankSerial": bt.bank_serial,
        "hasReceipt": bool(bt.receipt_key),
        "status": bt.status,
        "note": bt.note,
        "operator": bt.operator,
        "confirmedAt": _dt(bt.confirmed_at),
        "createdAt": _dt(bt.created_at),
    }


@router.get("/transfers")
def list_transfers(status: str = "待认领", admin=Depends(anyone), pdb: Session = Depends(get_platform_db)) -> list[dict]:
    from ..platform_models import BankTransfer, RechargeOrder, Tenant

    query = pdb.query(BankTransfer)
    if status:
        query = query.filter(BankTransfer.status == status)
    rows = query.order_by(BankTransfer.created_at.desc()).limit(200).all()
    orders = {o.id: o for o in pdb.query(RechargeOrder).filter(RechargeOrder.id.in_({r.order_id for r in rows})).all()}
    names = dict(pdb.query(Tenant.id, Tenant.name).filter(Tenant.id.in_({r.tenant_id for r in rows})).all())
    return [_transfer_out(r, orders.get(r.order_id), names.get(r.tenant_id, "")) for r in rows]


@router.get("/transfers/{transfer_id}/receipt")
def transfer_receipt(transfer_id: str, admin=Depends(finance), pdb: Session = Depends(get_platform_db)):
    from ..platform_models import BankTransfer

    bt = pdb.get(BankTransfer, transfer_id)
    if bt is None or not bt.receipt_key:
        raise HTTPException(404, "回单不存在")
    return storage.http_response(bt.receipt_key, filename=bt.receipt_name or "回单", inline=True, bucket=storage.platform_bucket())


class ConfirmTransferIn(BaseModel):
    bankSerial: str = Field(min_length=1, max_length=80)
    amountCents: int = Field(gt=0)


@router.post("/transfers/{transfer_id}/confirm")
def confirm_transfer(transfer_id: str, payload: ConfirmTransferIn, request: Request, admin=Depends(finance), pdb: Session = Depends(get_platform_db)) -> dict:
    from ..payments import orders as order_svc

    bt = order_svc.confirm_transfer(pdb, transfer_id, operator=admin.name or admin.email, bank_serial=payload.bankSerial, amount_cents=payload.amountCents)
    platform_audit(pdb, admin, "认领对公转账", tenant_id=bt.tenant_id, target=bt.order_id, detail=f"{payload.amountCents / 100:.2f} 元 流水 {payload.bankSerial}", ip=client_ip(request))
    pdb.commit()
    return _transfer_out(bt)


@router.post("/transfers/{transfer_id}/reject")
def reject_transfer(transfer_id: str, payload: ReasonIn, request: Request, admin=Depends(finance), pdb: Session = Depends(get_platform_db)) -> dict:
    from ..platform_models import BankTransfer, RechargeOrder

    bt = pdb.get(BankTransfer, transfer_id)
    if bt is None:
        raise HTTPException(404, "转账记录不存在")
    if bt.status != "待认领":
        raise HTTPException(400, "该记录已处理")
    bt.status = "已驳回"
    bt.note = payload.reason
    bt.operator = admin.name or admin.email
    order = pdb.get(RechargeOrder, bt.order_id)
    if order is not None and order.status == "待确认":
        order.status = "待支付"
    platform_audit(pdb, admin, "驳回对公转账", tenant_id=bt.tenant_id, target=bt.order_id, detail=payload.reason, ip=client_ip(request))
    pdb.commit()
    return _transfer_out(bt)


@router.get("/reconcile")
def reconcile(date: str = "", admin=Depends(finance), pdb: Session = Depends(get_platform_db)) -> dict:
    """对账骨架：按通道汇总某日已支付订单，财务与支付宝/微信账单逐笔核对。"""
    from ..platform_models import RechargeOrder

    day = _parse_dt(date) or datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    end = day + timedelta(days=1)
    rows = pdb.query(RechargeOrder).filter(RechargeOrder.status.in_(("已支付", "已退款")), RechargeOrder.paid_at >= day, RechargeOrder.paid_at < end).all()
    summary: dict[str, dict] = {}
    for o in rows:
        s = summary.setdefault(o.channel, {"count": 0, "amountCents": 0, "refunded": 0})
        s["count"] += 1
        s["amountCents"] += o.amount_cents
        if o.status == "已退款":
            s["refunded"] += 1
    return {
        "date": day.strftime("%Y-%m-%d"),
        "summary": summary,
        "orders": [{"id": o.id, "channel": o.channel, "tradeNo": o.channel_trade_no, "amountCents": o.amount_cents, "status": o.status, "paidAt": _dt(o.paid_at)} for o in rows],
    }


# ---------------------------------------------------------------------------
# 发票
# ---------------------------------------------------------------------------


@router.get("/invoices")
def list_invoices(
    status: str = "",
    tenantId: str = "",
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    admin=Depends(anyone),
    pdb: Session = Depends(get_platform_db),
) -> dict:
    from ..platform_models import Invoice, Tenant

    query = pdb.query(Invoice)
    if status:
        query = query.filter(Invoice.status == status)
    if tenantId:
        query = query.filter(Invoice.tenant_id == tenantId)
    total = query.count()
    rows = query.order_by(Invoice.created_at.desc()).offset((page - 1) * size).limit(size).all()
    names = dict(pdb.query(Tenant.id, Tenant.name).filter(Tenant.id.in_({r.tenant_id for r in rows})).all())
    return {"total": total, "items": [{**invoice_out(i), "tenantId": i.tenant_id, "tenantName": names.get(i.tenant_id, ""), "operator": i.operator} for i in rows]}


def _invoice(pdb: Session, invoice_id: str):
    from ..platform_models import Invoice

    inv = pdb.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "发票不存在")
    return inv


@router.post("/invoices/{invoice_id}/approve")
def approve_invoice(invoice_id: str, request: Request, admin=Depends(finance), pdb: Session = Depends(get_platform_db)) -> dict:
    from .. import invoicing

    inv = _invoice(pdb, invoice_id)
    invoicing.approve(pdb, inv, admin.name or admin.email)
    platform_audit(pdb, admin, "发票审核通过", tenant_id=inv.tenant_id, target=inv.id, ip=client_ip(request))
    pdb.commit()
    return invoice_out(inv)


@router.post("/invoices/{invoice_id}/reject")
def reject_invoice(invoice_id: str, payload: ReasonIn, request: Request, admin=Depends(finance), pdb: Session = Depends(get_platform_db)) -> dict:
    from .. import invoicing

    inv = _invoice(pdb, invoice_id)
    invoicing.reject(pdb, inv, reason=payload.reason, operator=admin.name or admin.email)
    platform_audit(pdb, admin, "驳回发票", tenant_id=inv.tenant_id, target=inv.id, detail=payload.reason, ip=client_ip(request))
    pdb.commit()
    return invoice_out(inv)


@router.post("/invoices/{invoice_id}/upload")
async def upload_invoice(
    invoice_id: str,
    request: Request,
    invoiceNo: str = Form(...),
    file: UploadFile = File(...),
    admin=Depends(finance),
    pdb: Session = Depends(get_platform_db),
) -> dict:
    from .. import invoicing

    inv = _invoice(pdb, invoice_id)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".pdf", ".ofd", ".xml"):
        raise HTTPException(400, "数电票文件仅支持 PDF、OFD 或 XML")
    data = await file.read()
    if not data or len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "发票文件为空或超过 10 MB")
    invoicing.upload_issued(pdb, inv, invoice_no=invoiceNo, data=data, filename=file.filename or f"{invoiceNo}{ext}", operator=admin.name or admin.email)
    platform_audit(pdb, admin, "上传发票", tenant_id=inv.tenant_id, target=inv.id, detail=invoiceNo, ip=client_ip(request))
    pdb.commit()
    return invoice_out(inv)


@router.post("/invoices/{invoice_id}/red-flush")
def red_flush_invoice(invoice_id: str, payload: ReasonIn, request: Request, admin=Depends(finance), pdb: Session = Depends(get_platform_db)) -> dict:
    from .. import invoicing

    inv = _invoice(pdb, invoice_id)
    invoicing.red_flush(pdb, inv, reason=payload.reason, operator=admin.name or admin.email)
    platform_audit(pdb, admin, "发票红冲", tenant_id=inv.tenant_id, target=inv.id, detail=payload.reason, ip=client_ip(request))
    pdb.commit()
    return invoice_out(inv)


@router.get("/invoices/{invoice_id}/file")
def invoice_file(invoice_id: str, admin=Depends(anyone), pdb: Session = Depends(get_platform_db)):
    inv = _invoice(pdb, invoice_id)
    if not inv.file_key:
        raise HTTPException(404, "发票文件不存在")
    return storage.http_response(inv.file_key, filename=inv.file_name or f"{inv.invoice_no}.pdf", bucket=storage.platform_bucket())
