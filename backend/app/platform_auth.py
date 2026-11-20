"""平台后台认证：独立账号表、独立令牌 aud、可选 TOTP 二次验证和 IP 白名单。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import secrets
import struct
import time
import urllib.parse

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_platform_db
from .tokens import bearer, decode_platform_token

ROLE_SUPER = "超级管理员"
ROLE_OPS = "运营"
ROLE_FINANCE = "财务"
ROLE_READONLY = "只读"
ADMIN_ROLES = (ROLE_SUPER, ROLE_OPS, ROLE_FINANCE, ROLE_READONLY)


# ---------------------------------------------------------------------------
# TOTP（RFC 6238，兼容 Google Authenticator / 企业微信 / 阿里云 App）
# ---------------------------------------------------------------------------


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _totp_at(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def totp_now(secret: str, at: float | None = None) -> str:
    return _totp_at(secret, int((at or time.time()) // 30))


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    code = (code or "").strip()
    if not secret or len(code) != 6 or not code.isdigit():
        return False
    counter = int(time.time() // 30)
    return any(hmac.compare_digest(_totp_at(secret, counter + d), code) for d in range(-window, window + 1))


def totp_uri(secret: str, account: str) -> str:
    label = urllib.parse.quote(f"标书平台后台:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={urllib.parse.quote('标书平台后台')}"


# ---------------------------------------------------------------------------
# 访问控制
# ---------------------------------------------------------------------------


def client_ip(request: Request) -> str:
    real = (request.headers.get("x-real-ip") or "").strip()
    if real:
        return real
    return request.client.host if request.client else ""


def ip_allowed(ip: str) -> bool:
    raw = (get_settings().platform_admin_ip_allowlist or "").strip()
    if not raw:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for item in raw.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            if addr in ipaddress.ip_network(item, strict=False):
                return True
        except ValueError:
            continue
    return False


def get_current_admin(
    request: Request,
    authorization: str | None = Header(default=None),
    pdb: Session = Depends(get_platform_db),
):
    from .platform_models import PlatformAdmin

    if not ip_allowed(client_ip(request)):
        raise HTTPException(403, "当前 IP 不允许访问平台后台")
    token = bearer(authorization)
    if not token:
        raise HTTPException(401, "请先登录平台后台")
    claims = decode_platform_token(token)
    admin = pdb.get(PlatformAdmin, claims["sub"])
    if admin is None or admin.disabled or int(claims.get("ver", 0)) != int(admin.token_version or 0):
        raise HTTPException(401, "登录状态已失效，请重新登录")
    return admin


def require_roles(*roles: str):
    """返回依赖：只允许指定角色；超级管理员总是允许。"""

    def _dep(admin=Depends(get_current_admin)):
        if admin.role != ROLE_SUPER and admin.role not in roles:
            raise HTTPException(403, "无权执行该操作")
        return admin

    return _dep


def can_write(admin) -> bool:
    return admin.role != ROLE_READONLY


def platform_audit(pdb: Session, admin, action: str, *, tenant_id: str = "", target: str = "", detail: str = "", ip: str = "") -> None:
    from .platform_models import PlatformAudit

    pdb.add(
        PlatformAudit(
            admin_id=getattr(admin, "id", None),
            admin_name=getattr(admin, "name", "") or getattr(admin, "email", ""),
            action=action,
            tenant_id=tenant_id,
            target=target[:200],
            detail=detail[:2000],
            ip=ip,
        )
    )


def active_support_grant(pdb: Session, tenant_id: str):
    """企业是否授予了有效的运维查看权限。没有授权时后台只能看统计，看不到文件内容。"""
    from datetime import datetime

    from .platform_models import SupportGrant

    return (
        pdb.query(SupportGrant)
        .filter(SupportGrant.tenant_id == tenant_id, SupportGrant.revoked.is_(False), SupportGrant.expires_at > datetime.utcnow())
        .order_by(SupportGrant.expires_at.desc())
        .first()
    )
