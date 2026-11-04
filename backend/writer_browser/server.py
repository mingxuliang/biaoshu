"""撰写助手浏览器边车：只做白名单网页正文抽取，不执行用户脚本。"""

from __future__ import annotations

import os
import re
from urllib.parse import quote_plus, urlparse

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="writer-browser")

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


def _host_allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    for allowed in _hosts():
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def _clean_text(raw: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", (raw or "").replace("\r\n", "\n")).strip()
    if len(text) > TEXT_MAX:
        return text[:TEXT_MAX] + "\n……（已截断）"
    return text


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
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(800)
            text = page.inner_text("body")
            browser.close()
    except Exception as exc:  # noqa: BLE001
        return CollectOut(error=f"页面无法打开：{exc}", source=url)
    return CollectOut(text=_clean_text(text), source=url)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/collect", response_model=CollectOut)
def collect(payload: CollectIn) -> CollectOut:
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
