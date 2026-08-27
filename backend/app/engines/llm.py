"""撰写工作台大模型路由：DeepSeek V4 Pro / Flash、豆包（火山方舟）。"""

from __future__ import annotations

import httpx

from ..config import get_settings

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


def normalize_model_id(model_id: str | None) -> str:
    raw = (model_id or "").strip() or DEEPSEEK_V4_PRO
    mapped = _ALIASES.get(raw, raw)
    if mapped in (DEEPSEEK_V4_PRO, DEEPSEEK_V4_FLASH, DOUBAO):
        return mapped
    return DEEPSEEK_V4_PRO


def resolve_endpoint(model_id: str | None) -> tuple[str, str, str, str]:
    """返回 (provider, base_url, api_key, api_model)。"""
    settings = get_settings()
    mid = normalize_model_id(model_id)
    if mid == DOUBAO:
        if not settings.ark_api_key:
            raise LlmError("未配置豆包 ARK_API_KEY，无法调用该模型", "doubao")
        return "doubao", settings.ark_base_url, settings.ark_api_key, settings.ark_chat_model
    if not settings.deepseek_api_key:
        raise LlmError("未配置 DeepSeek API Key，无法调用该模型", "deepseek")
    return "deepseek", settings.deepseek_base_url, settings.deepseek_api_key, _DEEPSEEK_API_MODELS[mid]


def chat_complete(
    *,
    model_id: str | None,
    messages: list[dict],
    temperature: float = 0.2,
    timeout: float = 60,
    max_tokens: int | None = None,
) -> str:
    provider, base_url, api_key, api_model = resolve_endpoint(model_id)
    payload: dict = {
        "model": api_model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        with httpx.Client(base_url=base_url, timeout=timeout) as client:
            resp = client.post("/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"] or ""
    except httpx.HTTPStatusError as exc:
        detail = (exc.response.text or "")[:240]
        raise LlmError(f"{provider} 接口返回 {exc.response.status_code}：{detail}", provider) from exc
    except httpx.HTTPError as exc:
        raise LlmError(f"调用 {provider} 失败（{exc.__class__.__name__}）", provider) from exc
