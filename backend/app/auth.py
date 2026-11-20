"""密码哈希与 JWT 会话（P0：项目/认证真正落库）。"""

import secrets
import string

import bcrypt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, object_session

from .db import get_db
from .models import User
from .tenancy import DEFAULT_TENANT, current_tenant
from .tokens import bearer, create_tenant_token, decode_tenant_token


def normalize_account(value: str) -> str:
    """登录账号：邮箱、手机号、工号或任意数字均可，不强制邮箱格式。"""
    return (value or "").strip().lower()


def find_user_by_account(db: Session, account: str) -> User | None:
    key = normalize_account(account)
    if not key:
        return None
    return db.query(User).filter(func.lower(User.email) == key).first()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def random_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.isdigit() for c in pwd) and any(c.isalpha() for c in pwd):
            return pwd


def _tenant_of(user: User, tenant_id: str | None = None) -> str:
    if tenant_id:
        return tenant_id
    session = object_session(user)
    if session is not None and session.info.get("tenant_id"):
        return session.info["tenant_id"]
    return current_tenant() or DEFAULT_TENANT


def create_access_token(user_id: str, token_version: int = 0, tenant_id: str | None = None) -> str:
    return create_tenant_token(user_id, tenant_id or current_tenant() or DEFAULT_TENANT, token_version)


def token_for(user: User, tenant_id: str | None = None) -> str:
    return create_tenant_token(user.id, _tenant_of(user, tenant_id), getattr(user, "token_version", 0) or 0)


def revoke_tokens(user: User) -> None:
    user.token_version = int(getattr(user, "token_version", 0) or 0) + 1


def get_current_user(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> User:
    token = bearer(authorization)
    if not token:
        raise HTTPException(401, "缺少登录凭证，请先登录")
    claims = decode_tenant_token(token)
    user_id, version = claims["sub"], int(claims.get("ver") or 0)
    session_tenant = db.info.get("tenant_id")
    if session_tenant and session_tenant != claims["tid"]:
        raise HTTPException(401, "登录状态已失效，请重新登录")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(401, "用户不存在，请重新登录")
    if version != int(getattr(user, "token_version", 0) or 0):
        raise HTTPException(401, "登录状态已失效，请重新登录")
    if getattr(user, "disabled", False):
        raise HTTPException(401, "账号已停用，请联系管理员")
    return user
