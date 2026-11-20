"""火山方舟豆包 Seedream 文生图。

未配置 Key 或调用失败时抛出明确异常，不降级成假图。
"""

from __future__ import annotations

import base64
import os

import httpx

from ..config import get_settings
from .. import storage

VALID_MODES = ("normal", "flow", "arch")

_MODE_PREFIX = {
    "normal": (
        "专业投标文件配图，写实摄影风格，干净背景，适合中国大陆工程或信息化招投标标书插图。"
        "不要出现可读乱码、水印或品牌 logo。画面主题："
    ),
    "flow": (
        "专业流程图，白底，扁平矢量风格，清晰的矩形流程框与箭头连接，中文标签清晰可读，"
        "适合投标文件施工组织、进度、质量或安全管理章节。流程主题："
    ),
    "arch": (
        "专业系统架构图，白底，分层方框与连接线，扁平矢量风格，中文标签清晰可读，"
        "适合投标文件技术方案章节。架构主题："
    ),
}

_SIZE_BY_MODE = {
    "normal": "2048x2048",
    "flow": "2560x1440",
    "arch": "2560x1440",
}

_STYLE_HINT = {
    "专业商务风": "画面风格为专业商务，配色克制，适合正式标书。",
    "简约扁平风": "画面风格为简约扁平插画，少阴影。",
    "科技渐变风": "画面风格为科技渐变，不要出现乱码文字。",
    "写实摄影风": "画面风格为写实摄影，自然光线。",
}


class ArkImageError(Exception):
    """生图失败（配置缺失、方舟拒绝、下载失败等）。"""


def build_prompt(user_prompt: str, mode: str, style: str | None = None) -> str:
    prefix = _MODE_PREFIX.get(mode, _MODE_PREFIX["normal"])
    text = (user_prompt or "").strip() or "投标文件相关示意图"
    hint = _STYLE_HINT.get(style or "", "") if mode == "normal" else ""
    return f"{prefix}{hint}{text}"


def resolve_image_endpoint() -> tuple[str, str, str]:
    """返回 (api_key, base_url, api_model)。优先用模型配置里的豆包生图模型。"""
    settings = get_settings()
    api_key = (settings.ark_api_key or "").strip()
    base_url = (settings.ark_base_url or "https://ark.cn-beijing.volces.com/api/v3").strip()
    api_model = (settings.ark_image_model or "doubao-seedream-4-0-250828").strip()
    try:
        from ..db import platform_session
        from ..models import LlmModel, LlmProvider

        db = platform_session()
        try:
            provider = (
                db.query(LlmProvider)
                .filter(LlmProvider.kind == "doubao", LlmProvider.enabled.is_(True))
                .order_by(LlmProvider.created_at.asc())
                .first()
            )
            if provider and (provider.api_key or "").strip():
                api_key = provider.api_key.strip()
            if provider and (provider.base_url or "").strip():
                base_url = provider.base_url.strip()
            if provider is not None:
                image = (
                    db.query(LlmModel)
                    .filter(
                        LlmModel.provider_id == provider.id,
                        LlmModel.enabled.is_(True),
                        LlmModel.task == "image",
                    )
                    .order_by(LlmModel.sort_order.asc())
                    .first()
                )
                if image and (image.api_model or "").strip():
                    api_model = image.api_model.strip()
        finally:
            db.close()
    except Exception:  # noqa: BLE001 —— 库还没迁移时仍可用环境变量里的 Seedream
        pass
    if not api_key:
        raise ArkImageError("未配置豆包生图秘钥，请到「模型配置」填写火山方舟 API Key")
    return api_key, base_url, api_model


def generate_and_save(project_id: str, prompt: str, mode: str, style: str | None = None) -> tuple[str, str]:
    """调用方舟生图并落盘。返回 (storage_path, filename)。"""
    from ..billing import record_usage, require_credits

    require_credits("image")
    api_key, base_url, api_model = resolve_image_endpoint()

    mode = mode if mode in VALID_MODES else "normal"
    full_prompt = build_prompt(prompt, mode, style)
    size = _SIZE_BY_MODE.get(mode, "2K")

    payload = {
        "model": api_model,
        "prompt": full_prompt,
        "size": size,
        "response_format": "url",
        "watermark": False,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        data = _call_generations(base_url, payload, headers)
    except ArkImageError as exc:
        if "size" in str(exc).lower() or "watermark" in str(exc).lower():
            fallback = {
                "model": api_model,
                "prompt": full_prompt,
                "size": "2K",
                "response_format": "url",
            }
            data = _call_generations(base_url, fallback, headers)
        else:
            raise

    image_bytes, ext = _extract_image_bytes(data)
    record_usage(api_model=api_model, calls=1, feature="image")
    key = storage.put_bytes(f"writer-images/{project_id}", image_bytes, ext)
    filename = os.path.basename(key)
    return key, filename


def _call_generations(base_url: str, payload: dict, headers: dict) -> dict:
    try:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=120) as client:
            resp = client.post("/images/generations", json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise ArkImageError(f"调用方舟生图接口失败（{exc.__class__.__name__}）") from exc

    if resp.status_code >= 400:
        detail = _safe_error_text(resp)
        raise ArkImageError(f"方舟生图失败（{resp.status_code}）：{detail}")
    try:
        return resp.json()
    except ValueError as exc:
        raise ArkImageError("方舟生图返回无法解析") from exc


def _extract_image_bytes(data: dict) -> tuple[bytes, str]:
    items = data.get("data")
    if not isinstance(items, list) or not items:
        raise ArkImageError("方舟未返回图片数据")
    item = items[0] if isinstance(items[0], dict) else {}

    b64 = item.get("b64_json")
    if isinstance(b64, str) and b64.strip():
        try:
            return base64.b64decode(b64), ".png"
        except ValueError as exc:
            raise ArkImageError("方舟返回的图片编码无效") from exc

    url = item.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ArkImageError("方舟未返回图片地址")

    try:
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            img_resp = client.get(url.strip())
            img_resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ArkImageError(f"下载生成图片失败（{exc.__class__.__name__}）") from exc

    content_type = (img_resp.headers.get("content-type") or "").lower()
    ext = ".jpg" if "jpeg" in content_type or "jpg" in content_type else ".png"
    if not img_resp.content:
        raise ArkImageError("下载到的生成图片为空")
    return img_resp.content, ext


def _safe_error_text(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or body)[:300]
        if isinstance(body, dict) and body.get("message"):
            return str(body["message"])[:300]
        return str(body)[:300]
    except ValueError:
        return (resp.text or "未知错误")[:300]
