"""请求体大小上限。

先按 Content-Length 提前拒绝；分块传输或谎报长度的请求，在读取过程中累计实际字节，超限即断开。
"""

from __future__ import annotations

import json

from fastapi import HTTPException


def _limit_message(max_bytes: int) -> str:
    return f"上传内容超过 {max_bytes // (1024 * 1024)} MB 上限，请拆分后重试"


class BodyTooLarge(HTTPException):
    """继承 HTTPException：FastAPI 解析请求体时会原样抛出，前端拿到 413 而不是 400。"""

    def __init__(self, max_bytes: int) -> None:
        super().__init__(status_code=413, detail=_limit_message(max_bytes))


class BodyLimitMiddleware:
    def __init__(self, asgi_app, max_bytes: int) -> None:
        self.app = asgi_app
        self.max_bytes = max_bytes

    def _payload(self) -> bytes:
        return json.dumps({"detail": _limit_message(self.max_bytes)}, ensure_ascii=False).encode()

    async def _reject(self, send) -> None:
        body = self._payload()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        raw = dict(scope.get("headers") or []).get(b"content-length")
        try:
            size = int(raw) if raw else 0
        except ValueError:
            size = 0
        if size > self.max_bytes:
            await self._reject(send)
            return

        received = 0
        started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body") or b"")
                if received > self.max_bytes:
                    raise BodyTooLarge(self.max_bytes)
            return message

        async def tracking_send(message):
            nonlocal started
            if message.get("type") == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLarge:
            if not started:
                await self._reject(send)
