"""给所有响应补上基础安全头；JSON 响应额外加严格 CSP。"""

from __future__ import annotations

HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"SAMEORIGIN"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    (b"content-security-policy", b"default-src 'none'; img-src 'self' data:; frame-ancestors 'self'"),
]
# /docs 页面需要加载外部脚本，不套 CSP
DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


class SecurityHeadersMiddleware:
    def __init__(self, asgi_app) -> None:
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_doc = str(scope.get("path") or "").startswith(DOC_PATHS)

        async def send_with_headers(message):
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {name.lower() for name, _ in headers}
                ctype = next((v for n, v in headers if n.lower() == b"content-type"), b"")
                # 内联预览的 PDF / 图片交给浏览器内置查看器，严格 CSP 会挡住 Chrome 的 PDF 插件
                json_only = b"json" in ctype.lower()
                for name, value in HEADERS:
                    if name == b"content-security-policy" and (is_doc or not json_only):
                        continue
                    if name not in present:
                        headers.append((name, value))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
