"""登录令牌。企业令牌和平台后台令牌用不同 aud，互相不能冒用。"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException

from .config import get_settings
from .tenancy import valid_tenant_id

ALGORITHM = "HS256"
AUD_TENANT = "tenant"
AUD_PLATFORM = "platform"


def _encode(payload: dict, minutes: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    body = {**payload, "iat": now, "exp": now + timedelta(minutes=minutes)}
    return jwt.encode(body, settings.secret_key, algorithm=ALGORITHM)


def create_tenant_token(user_id: str, tenant_id: str, token_version: int = 0) -> str:
    settings = get_settings()
    return _encode(
        {"sub": user_id, "tid": tenant_id, "ver": int(token_version or 0), "aud": AUD_TENANT},
        settings.access_token_expire_minutes,
    )


def create_platform_token(admin_id: str, token_version: int = 0) -> str:
    settings = get_settings()
    return _encode(
        {"sub": admin_id, "ver": int(token_version or 0), "aud": AUD_PLATFORM},
        settings.platform_token_expire_minutes,
    )


def _decode(token: str, audience: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM], audience=audience)
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "登录状态已失效，请重新登录") from exc


def decode_tenant_token(token: str) -> dict:
    claims = _decode(token, AUD_TENANT)
    if not claims.get("sub") or not valid_tenant_id(claims.get("tid")):
        raise HTTPException(401, "登录状态已失效，请重新登录")
    return claims


def decode_platform_token(token: str) -> dict:
    claims = _decode(token, AUD_PLATFORM)
    if not claims.get("sub"):
        raise HTTPException(401, "登录状态已失效，请重新登录")
    return claims


def bearer(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip() or None
