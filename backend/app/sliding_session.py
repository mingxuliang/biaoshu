"""活动会话续期。成功的企业接口在令牌后半段寿命里换发新令牌，通过响应头交回浏览器。"""

from __future__ import annotations

from .tokens import renewed_access_token


class SlidingSessionMiddleware:
    def __init__(self, asgi_app) -> None:
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        raw = dict(scope.get("headers") or []).get(b"authorization", b"")
        try:
            authorization = raw.decode("latin1")
        except Exception:
            authorization = ""
        renewed = renewed_access_token(authorization)

        async def send_renewed(message):
            if message.get("type") == "http.response.start" and renewed:
                status = int(message.get("status") or 0)
                if 200 <= status < 400:
                    headers = list(message.get("headers") or [])
                    headers.append((b"x-access-token", renewed.encode("ascii")))
                    message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_renewed)
