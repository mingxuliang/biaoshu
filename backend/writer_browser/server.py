"""撰写助手浏览器边车：只做白名单网页正文抽取，不执行用户脚本。

只接受带共享口令的调用（WRITER_BROWSER_TOKEN）；页面跳转和子资源请求逐个校验域名，
防止白名单站点 302 到内网地址。
"""

from __future__ import annotations

import hmac
import ipaddress
import os
import re
import socket
from urllib.parse import quote_plus, urlparse

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="writer-browser", docs_url=None, redoc_url=None, openapi_url=None)

DEFAULT_HOSTS = (
    "gov.cn,ccgp.gov.cn,ggzy.gov.cn,chinabidding.com,"
    "bidcenter.com.cn,duckduckgo.com,bing.com"
)
TEXT_MAX = 12000


class CollectIn(BaseModel):
    action: str = ""
    query: str = ""
    url: str = ""


class CollectOut(BaseModel):
    text: str = ""
    source: str = ""
    error: str = ""


def _hosts() -> list[str]:
    raw = (os.environ.get("WRITER_BROWSER_HOSTS") or DEFAULT_HOSTS).strip()
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def _resolves_private(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return True
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return True
    return False


def _host_allowed(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if not host or parsed.username or parsed.password:
        return False
    try:
        ipaddress.ip_address(host)
        return False  # 白名单只认域名，IP 直连一律拒绝
    except ValueError:
        pass
    if not any(host == allowed or host.endswith("." + allowed) for allowed in _hosts()):
        return False
    return not _resolves_private(host)


def _check_token(token: str | None) -> None:
    expected = (os.environ.get("WRITER_BROWSER_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(503, "WRITER_BROWSER_TOKEN 未配置，浏览器服务拒绝工作")
    if not token or not hmac.compare_digest(token.strip(), expected):
        raise HTTPException(401, "口令不正确")


def _clean_text(raw: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", (raw or "").replace("\r\n", "\n")).strip()
    if len(text) > TEXT_MAX:
        return text[:TEXT_MAX] + "\n……（已截断）"
    return text


def _guard_route(route) -> None:
    request = route.request
    if request.resource_type in ("image", "media", "font"):
        route.abort()
        return
    if _host_allowed(request.url):
        route.continue_()
    else:
        route.abort()


def _extract_page(url: str) -> CollectOut:
    if not _host_allowed(url):
        return CollectOut(error="该网址不在取材白名单")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        return CollectOut(error=f"浏览器未启用：{exc}")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(java_script_enabled=True, accept_downloads=False)
            context.route("**/*", _guard_route)
            page = context.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(800)
            final_url = page.url
            if not _host_allowed(final_url):
                browser.close()
                return CollectOut(error="页面跳转到白名单以外的地址，已拦截", source=url)
            text = page.inner_text("body") if response else ""
            browser.close()
    except Exception as exc:  # noqa: BLE001
        return CollectOut(error=f"页面无法打开：{exc}", source=url)
    return CollectOut(text=_clean_text(text), source=final_url)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/collect", response_model=CollectOut)
def collect(payload: CollectIn, x_writer_browser_token: str | None = Header(default=None)) -> CollectOut:
    _check_token(x_writer_browser_token)
    action = (payload.action or "").strip().lower()
    if action == "fetch":
        url = (payload.url or "").strip()
        if not url:
            return CollectOut(error="fetch 需要 url")
        return _extract_page(url)
    if action == "search":
        query = (payload.query or "").strip()
        if not query:
            return CollectOut(error="search 需要 query")
        url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
        return _extract_page(url)
    return CollectOut(error="action 只能是 search 或 fetch")
