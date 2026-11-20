from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import ratelimit
from ..auth import (
    find_user_by_account,
    get_current_user,
    hash_password,
    normalize_account,
    revoke_tokens,
    token_for,
    verify_password,
)
from ..config import get_settings
from ..db import get_db, platform_session, tenant_session
from ..models import User
from ..schemas import AuthOut, LoginIn, RegisterIn, TenantSignupIn, UpdateProfileIn, UserOut
from ..tenancy import DEFAULT_TENANT, use_tenant
from ..tenants import (
    KIND_PERSONAL,
    TENANT_KINDS,
    create_tenant,
    find_account,
    login_taken,
    register_account,
    tenant_kind,
    unregister_account,
)
from .. import verify_codes

router = APIRouter(prefix="/api/auth", tags=["auth"])

MIN_PASSWORD_LEN = 8


def _tenant_brief(tenant_id: str) -> dict:
    from ..platform_models import Tenant

    with platform_session() as pdb:
        tenant = pdb.get(Tenant, tenant_id)
        if tenant is None:
            return {"id": tenant_id, "name": "", "status": "", "kind": "企业"}
        return {
            "id": tenant.id,
            "name": tenant.name,
            "kind": tenant_kind(tenant),
            "status": tenant.status,
            "plan": tenant.plan_code,
            "verifyStatus": tenant.verify_status,
        }


def _to_user_out(user: User, tenant_id: str | None = None) -> UserOut:
    from ..permissions import data_scope, user_perms

    try:
        perms = sorted(user_perms(user))
        scope = data_scope(user)
    except Exception:  # noqa: BLE001 —— 会话已关闭读不到自定义角色时退回内置角色
        perms, scope = [], ""
    out = UserOut(
        perms=perms,
        dataScope=scope,
        id=user.id,
        name=user.name,
        email=user.email,
        phone=user.phone or "",
        company=user.company or "",
        position=user.position or "",
        role=user.role or "成员",
        departmentId=getattr(user, "department_id", None),
    )
    if tenant_id:
        out.tenant = _tenant_brief(tenant_id)
    return out


def client_ip(request: Request) -> str:
    # 生产环境后端只经 nginx 访问，X-Real-IP 由 nginx 覆盖写入，可信
    real = (request.headers.get("x-real-ip") or "").strip()
    if real:
        return real
    return request.client.host if request.client else ""


def check_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LEN:
        raise HTTPException(400, f"密码至少 {MIN_PASSWORD_LEN} 位")
    if password.isdigit() or password.isalpha():
        raise HTTPException(400, "密码需同时包含字母和数字")


_check_password_strength = check_password_strength


def _check_account_format(account: str) -> None:
    if not account:
        raise HTTPException(400, "账号不能为空")
    if any(ch.isspace() for ch in account) or len(account) > 64:
        raise HTTPException(400, "账号不能含空格，且不超过 64 位")


@router.get("/options")
def auth_options() -> dict:
    """登录页用：是否显示注册入口。"""
    settings = get_settings()
    return {
        "allowRegister": bool(settings.allow_register),
        "allowTenantSignup": bool(settings.allow_tenant_signup),
        "signupCodeRequired": verify_codes.required(),
    }


@router.post("/send-code")
def send_code(payload: dict, request: Request) -> dict:
    """企业注册验证码（手机号或邮箱）。"""
    target = normalize_account(str(payload.get("target") or ""))
    _check_account_format(target)
    key = f"code:{target}|{client_ip(request)}"
    if ratelimit.is_locked(key):
        raise HTTPException(429, "验证码发送过于频繁，请稍后再试")
    ratelimit.record_failure(key)
    with platform_session() as pdb:
        verify_codes.issue(pdb, target, purpose="signup")
    return {"ok": True}


@router.post("/signup", response_model=AuthOut)
def tenant_signup(payload: TenantSignupIn, request: Request) -> AuthOut:
    """自助开通：企业（多成员共享积分池）或个人空间（只有本人），都带试用积分。"""
    if not get_settings().allow_tenant_signup:
        raise HTTPException(403, "平台暂未开放自助注册，请联系客服开通")
    if payload.kind not in TENANT_KINDS:
        raise HTTPException(400, "注册类型不合法")
    personal = payload.kind == KIND_PERSONAL
    account = normalize_account(payload.account)
    _check_account_format(account)
    check_password_strength(payload.password)
    display_name = (payload.name or "").strip() or account
    if personal:
        space_name = f"{display_name}的个人空间"
    elif not (payload.companyName or "").strip():
        raise HTTPException(400, "请填写企业名称")
    else:
        space_name = payload.companyName.strip()
    with platform_session() as pdb:
        if login_taken(pdb, account):
            raise HTTPException(409, "该账号已注册，请直接登录")
        verify_codes.consume(pdb, account, payload.code, purpose="signup")
        pdb.commit()
    tenant_id, user_id = create_tenant(
        name=space_name,
        admin_name=display_name,
        admin_login=account,
        admin_password=payload.password,
        contact_phone=payload.phone or "",
        contact_email=account if "@" in account else "",
        kind=payload.kind,
    )
    with use_tenant(tenant_id):
        db = tenant_session(tenant_id)
        try:
            user = db.get(User, user_id)
            return AuthOut(token=token_for(user, tenant_id), user=_to_user_out(user, tenant_id))
        finally:
            db.close()


@router.post("/register", response_model=AuthOut)
def register(payload: RegisterIn) -> AuthOut:
    """个人注册（加入默认企业）。SaaS 下默认关闭，企业请走 /signup。"""
    if not get_settings().allow_register:
        raise HTTPException(403, "系统未开放自助注册，请联系管理员开通账号")
    account = normalize_account(payload.email)
    if not account or not payload.password:
        raise HTTPException(400, "账号和密码不能为空")
    _check_account_format(account)
    check_password_strength(payload.password)
    with platform_session() as pdb:
        if login_taken(pdb, account):
            raise HTTPException(409, "该账号已注册，请直接登录")
    with use_tenant(DEFAULT_TENANT):
        db = tenant_session(DEFAULT_TENANT)
        try:
            if find_user_by_account(db, account):
                raise HTTPException(409, "该账号已注册，请直接登录")
            # 自助注册一律是「成员」：管理员只能由引导账号或已有管理员授予
            user = User(
                name=payload.name.strip() or account,
                email=account,
                password_hash=hash_password(payload.password),
                phone=payload.phone,
                company=payload.company,
                position=payload.position,
                role="成员",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            with platform_session() as pdb:
                register_account(pdb, account, DEFAULT_TENANT, user.id)
                pdb.commit()
            return AuthOut(token=token_for(user, DEFAULT_TENANT), user=_to_user_out(user, DEFAULT_TENANT))
        finally:
            db.close()


@router.post("/login", response_model=AuthOut)
def login(payload: LoginIn, request: Request) -> AuthOut:
    from ..platform_models import Tenant

    account = normalize_account(payload.email)
    ip = client_ip(request)
    keys = (f"acct:{account}", f"acct-ip:{account}|{ip}")
    if ratelimit.is_locked(*keys):
        minutes = get_settings().login_lock_minutes
        raise HTTPException(429, f"登录失败次数过多，请 {minutes} 分钟后再试")
    with platform_session() as pdb:
        acct = find_account(pdb, account)
        tenant = pdb.get(Tenant, acct.tenant_id) if acct else None
        tenant_id = acct.tenant_id if acct else None
        user_id = acct.user_id if acct else None
        tenant_status = tenant.status if tenant else ""
    if not tenant_id:
        ratelimit.record_failure(*keys)
        raise HTTPException(401, "账号或密码不正确")
    with use_tenant(tenant_id):
        db = tenant_session(tenant_id)
        try:
            user = db.get(User, user_id) or find_user_by_account(db, account)
            if not user or not verify_password(payload.password, user.password_hash):
                ratelimit.record_failure(*keys)
                raise HTTPException(401, "账号或密码不正确")
            if getattr(user, "disabled", False):
                raise HTTPException(401, "账号已停用，请联系管理员")
            if tenant_status in ("停用", "已注销"):
                raise HTTPException(403, "所在企业已停用，请联系平台客服")
            ratelimit.reset(*keys)
            user.last_login_at = datetime.utcnow()
            db.commit()
            return AuthOut(token=token_for(user, tenant_id), user=_to_user_out(user, tenant_id))
        finally:
            db.close()


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserOut:
    return _to_user_out(current_user, db.info.get("tenant_id"))


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: UpdateProfileIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    tenant_id = db.info.get("tenant_id")
    if payload.password:
        if not payload.currentPassword or not verify_password(payload.currentPassword, current_user.password_hash):
            raise HTTPException(400, "当前密码不正确")
        check_password_strength(payload.password)
    if payload.name is not None:
        current_user.name = payload.name.strip() or current_user.name
    old_account = (current_user.email or "").lower()
    new_account = None
    if payload.email is not None:
        candidate = normalize_account(payload.email)
        if candidate and candidate != old_account:
            _check_account_format(candidate)
            existing = find_user_by_account(db, candidate)
            if existing and existing.id != current_user.id:
                raise HTTPException(409, "该账号已被其他用户使用")
            if tenant_id:
                with platform_session() as pdb:
                    if login_taken(pdb, candidate):
                        raise HTTPException(409, "该账号已被其他用户使用")
            current_user.email = candidate
            new_account = candidate
    if payload.phone is not None:
        current_user.phone = payload.phone
    if payload.company is not None:
        current_user.company = payload.company
    if payload.position is not None:
        current_user.position = payload.position
    if payload.password:
        current_user.password_hash = hash_password(payload.password)
        revoke_tokens(current_user)

    db.commit()
    db.refresh(current_user)
    if new_account and tenant_id:
        with platform_session() as pdb:
            unregister_account(pdb, old_account)
            register_account(pdb, new_account, tenant_id, current_user.id)
            pdb.commit()
    out = _to_user_out(current_user, tenant_id)
    if payload.password:
        out.token = token_for(current_user)
    return out
