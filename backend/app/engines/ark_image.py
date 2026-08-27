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


class ArkImageError(Exception):
    """生图失败（配置缺失、方舟拒绝、下载失败等）。"""


def build_prompt(user_prompt: str, mode: str) -> str:
    prefix = _MODE_PREFIX.get(mode, _MODE_PREFIX["normal"])
    text = (user_prompt or "").strip() or "投标文件相关示意图"
    return f"{prefix}{text}"


def generate_and_save(project_id: str, prompt: str, mode: str) -> tuple[str, str]:
    """调用方舟生图并落盘。返回 (storage_path, filename)。"""
    settings = get_settings()
    if not settings.ark_api_key:
        raise ArkImageError("未配置方舟 ARK_API_KEY，无法生成图片")

    mode = mode if mode in VALID_MODES else "normal"
    full_prompt = build_prompt(prompt, mode)
    size = _SIZE_BY_MODE.get(mode, "2K")

    payload = {
        "model": settings.ark_image_model,
        "prompt": full_prompt,
        "size": size,
        "response_format": "url",
        "watermark": False,
    }
    headers = {"Authorization": f"Bearer {settings.ark_api_key}"}

    try:
        data = _call_generations(settings.ark_base_url, payload, headers)
    except ArkImageError as exc:
        if "size" in str(exc).lower() or "watermark" in str(exc).lower():
            fallback = {
                "model": settings.ark_image_model,
                "prompt": full_prompt,
                "size": "2K",
                "response_format": "url",
            }
            data = _call_generations(settings.ark_base_url, fallback, headers)
        else:
            raise

    image_bytes, ext = _extract_image_bytes(data)
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
