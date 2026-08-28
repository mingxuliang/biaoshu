"""撰写/抽取共用的大模型路由：按「模型配置」模块的秘钥与接入点调用，兼容 .env 旧配置。"""

from __future__ import annotations

import time

import httpx
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..db import SessionLocal
from ..llm_catalog import provider_ready
from ..models import LlmModel, LlmProvider

DEEPSEEK_V4_PRO = "deepseek-v4-pro"
DEEPSEEK_V4_FLASH = "deepseek-v4-flash"
DOUBAO = "doubao"

_ALIASES = {
    "deepseek": DEEPSEEK_V4_PRO,
    "deepseek-v4-pro": DEEPSEEK_V4_PRO,
    "deepseek-4-pro": DEEPSEEK_V4_PRO,
    "deepseek-v4-flash": DEEPSEEK_V4_FLASH,
    "deepseek-flash": DEEPSEEK_V4_FLASH,
    "deepseek-4-flash": DEEPSEEK_V4_FLASH,
    "doubao": DOUBAO,
    "ark": DOUBAO,
}

_DEEPSEEK_API_MODELS = {
    DEEPSEEK_V4_PRO: DEEPSEEK_V4_PRO,
    DEEPSEEK_V4_FLASH: DEEPSEEK_V4_FLASH,
}


class LlmError(Exception):
    def __init__(self, message: str, provider: str = ""):
        super().__init__(message)
        self.provider = provider


class ResolvedLlm:
    def __init__(
        self,
        *,
        model_id: str,
        provider: str,
        base_url: str,
        api_key: str,
        api_model: str,
        thinking: bool,
        vision: bool,
    ) -> None:
        self.model_id = model_id
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_model = api_model
        self.thinking = thinking
        self.vision = vision


def normalize_model_id(model_id: str | None) -> str:
    raw = (model_id or "").strip() or DEEPSEEK_V4_PRO
    return _ALIASES.get(raw, raw)


def is_vision_model(model_id: str | None) -> bool:
    try:
        return resolve_llm(model_id).vision
    except LlmError:
        return normalize_model_id(model_id) == DOUBAO


def get_default_model_id() -> str:
    db = SessionLocal()
    try:
        row = (
            db.query(LlmModel)
            .filter(LlmModel.is_default.is_(True), LlmModel.enabled.is_(True))
            .first()
        )
        if row:
            return row.id
        row = db.query(LlmModel).filter(LlmModel.enabled.is_(True)).order_by(LlmModel.sort_order.asc()).first()
        if row:
            return row.id
    except Exception:  # noqa: BLE001
        pass
    finally:
        db.close()
    settings = get_settings()
    if settings.ark_api_key:
        return DOUBAO
    return DEEPSEEK_V4_FLASH


def _from_row(model: LlmModel, provider: LlmProvider) -> ResolvedLlm:
    if not provider_ready(provider):
        raise LlmError(f"「{provider.name}」未配置 Base URL 或秘钥，请到系统模块「模型配置」补全", provider.kind)
    api_model = (model.api_model or "").strip()
    if not api_model:
        raise LlmError(f"模型「{model.name}」未填写接口模型名", provider.kind)
    return ResolvedLlm(
        model_id=model.id,
        provider=provider.kind,
        base_url=provider.base_url.strip(),
        api_key=(provider.api_key or "").strip(),
        api_model=api_model,
        thinking=bool(model.thinking),
        vision=provider.kind == "doubao",
    )


def _lookup_db(model_id: str | None) -> ResolvedLlm | None:
    raw = (model_id or "").strip()
    alias = _ALIASES.get(raw, raw)
    db = SessionLocal()
    try:
        q = db.query(LlmModel).options(selectinload(LlmModel.provider))
        row = None
        if raw:
            row = db.get(LlmModel, raw) or db.get(LlmModel, alias)
        if row is None and alias:
            row = q.filter(LlmModel.api_model == alias).first()
        if row is None and not raw:
            row = q.filter(LlmModel.is_default.is_(True), LlmModel.enabled.is_(True)).first()
            if row is None:
                row = q.filter(LlmModel.enabled.is_(True)).order_by(LlmModel.sort_order.asc()).first()
        if row is None or row.provider is None:
            return None
        return _from_row(row, row.provider)
    except LlmError:
        raise
    except Exception:  # noqa: BLE001 —— 表尚未迁移时回退 .env
        return None
    finally:
        db.close()


def resolve_llm(model_id: str | None) -> ResolvedLlm:
    found = _lookup_db(model_id)
    if found:
        return found
    settings = get_settings()
    mid = normalize_model_id(model_id)
    if mid == DOUBAO:
        if not settings.ark_api_key:
            raise LlmError("未配置豆包秘钥，请到「模型配置」填写火山方舟 API Key，或在 .env 设置 ARK_API_KEY", "doubao")
        return ResolvedLlm(
            model_id=DOUBAO,
            provider="doubao",
            base_url=settings.ark_base_url,
            api_key=settings.ark_api_key,
            api_model=settings.ark_chat_model,
            thinking=False,
            vision=True,
        )
    if mid in _DEEPSEEK_API_MODELS:
        if not settings.deepseek_api_key:
            raise LlmError("未配置 DeepSeek 秘钥，请到「模型配置」填写 API Key，或在 .env 设置 DEEPSEEK_API_KEY", "deepseek")
        return ResolvedLlm(
            model_id=mid,
            provider="deepseek",
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
            api_model=_DEEPSEEK_API_MODELS[mid],
            thinking=False,
            vision=False,
        )
    raise LlmError("未找到该模型接入，请到系统模块「模型配置」添加或启用", mid or "unknown")


def resolve_endpoint(model_id: str | None) -> tuple[str, str, str, str]:
    """兼容旧调用：(provider, base_url, api_key, api_model)。"""
    resolved = resolve_llm(model_id)
    return resolved.provider, resolved.base_url, resolved.api_key, resolved.api_model


def _apply_thinking(payload: dict, resolved: ResolvedLlm) -> None:
    kind = resolved.provider
    on = resolved.thinking
    if kind in ("deepseek", "doubao"):
        payload["thinking"] = {"type": "enabled" if on else "disabled"}
    elif kind in ("qwen", "siliconflow"):
        payload["enable_thinking"] = on
        payload.setdefault("extra_body", {})["enable_thinking"] = on
    elif kind == "local":
        payload["think"] = on
        payload.setdefault("extra_body", {})["think"] = on
    elif on:
        payload.setdefault("extra_body", {})["enable_thinking"] = True


def _strip_thinking(payload: dict) -> None:
    payload.pop("thinking", None)
    payload.pop("enable_thinking", None)
    payload.pop("think", None)
    extra = payload.get("extra_body")
    if isinstance(extra, dict):
        extra.pop("enable_thinking", None)
        extra.pop("think", None)
        if not extra:
            payload.pop("extra_body", None)


def _message_text(message: dict | None) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts = [str(p.get("text") or "") for p in content if isinstance(p, dict)]
        joined = "".join(parts).strip()
        if joined:
            return joined
    reasoning = message.get("reasoning_content") or message.get("reasoning")
    if isinstance(reasoning, str):
        return reasoning
    return content if isinstance(content, str) else ""


def chat_complete(
    *,
    model_id: str | None,
    messages: list[dict],
    temperature: float = 0.2,
    timeout: float = 60,
    max_tokens: int | None = None,
    extra: dict | None = None,
) -> str:
    resolved = resolve_llm(model_id)
    payload: dict = {
        "model": resolved.api_model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    _apply_thinking(payload, resolved)
    if extra:
        payload.update(extra)
    headers = {"Authorization": f"Bearer {resolved.api_key}"} if resolved.api_key else {}
    try:
        with httpx.Client(base_url=resolved.base_url, timeout=timeout) as client:
            resp = client.post("/chat/completions", json=payload, headers=headers)
            if resp.status_code == 400 and ("thinking" in payload or "enable_thinking" in payload or "think" in payload):
                _strip_thinking(payload)
                resp = client.post("/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
            text = _message_text((body.get("choices") or [{}])[0].get("message"))
            return text or ""
    except httpx.HTTPStatusError as exc:
        detail = (exc.response.text or "")[:240]
        raise LlmError(f"{resolved.provider} 接口返回 {exc.response.status_code}：{detail}", resolved.provider) from exc
    except httpx.HTTPError as exc:
        raise LlmError(f"调用 {resolved.provider} 失败（{exc.__class__.__name__}）", resolved.provider) from exc


def ping_model(model_id: str) -> tuple[bool, str, int, str]:
    started = time.perf_counter()
    try:
        text = chat_complete(
            model_id=model_id,
            messages=[{"role": "user", "content": "请只回复两个字：就绪"}],
            temperature=0,
            timeout=25,
            max_tokens=32,
        )
        ms = int((time.perf_counter() - started) * 1000)
        preview = (text or "").strip().replace("\n", " ")[:80]
        if not preview:
            return False, "接口成功但模型返回空内容，可尝试关闭思维链后重试", ms, ""
        return True, "连通正常", ms, preview
    except LlmError as exc:
        ms = int((time.perf_counter() - started) * 1000)
        return False, str(exc), ms, ""
