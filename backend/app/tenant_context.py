"""按企业令牌设置本次请求的企业上下文和操作人。令牌无效时不设置，由 get_db / get_current_user 返回 401。

企业停用或到期时拦截写操作（读取、导出、充值续费不拦）。
"""

from __future__ import annotations

import json

from fastapi import HTTPException

from .tenancy import reset_tenant, reset_user_id, set_tenant, set_user_id
from .tokens import bearer, decode_tenant_token

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# 到期后仍要能登录、改密码、充值续费、开票、已读通知
WRITE_ALLOWED_PREFIXES = ("/api/auth/", "/api/billing/", "/api/collab/notifications", "/api/org/support-grants")


def _claims_from_scope(scope) -> dict | None:
    headers = dict(scope.get("headers") or [])
    raw = headers.get(b"authorization")
    token = bearer(raw.decode("latin-1")) if raw else None
    if not token:
        return None
    try:
        return decode_tenant_token(token)
    except HTTPException:
        return None


def _blocked(scope, tenant_id: str) -> str | None:
    if scope.get("method") not in WRITE_METHODS:
        return None
    path = scope.get("path") or ""
    if path.startswith(WRITE_ALLOWED_PREFIXES) or path.endswith("/export"):
        return None
    from .tenants import write_block_reason

    try:
        return write_block_reason(tenant_id)
    except Exception:  # noqa: BLE001 —— 平台库暂时不可用时不因此拒绝业务
        return None


class TenantContextMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        claims = _claims_from_scope(scope)
        if not claims:
            await self.app(scope, receive, send)
            return
        reason = _blocked(scope, claims["tid"])
        if reason:
            body = json.dumps({"detail": reason, "code": "tenant_inactive"}, ensure_ascii=False).encode("utf-8")
            await send({"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
            return
        tenant_token = set_tenant(claims["tid"])
        user_token = set_user_id(claims.get("sub"))
        try:
            await self.app(scope, receive, send)
        finally:
            reset_user_id(user_token)
            reset_tenant(tenant_token)
