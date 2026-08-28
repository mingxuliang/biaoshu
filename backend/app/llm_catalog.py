"""大模型接入目录：平台预设、秘钥掩码、从环境变量引导写入。"""

from __future__ import annotations

from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .models import LlmModel, LlmProvider, gen_id

PROVIDER_KINDS = ("deepseek", "doubao", "qwen", "siliconflow", "openai", "custom", "local")

PRESETS: list[dict] = [
    {
        "kind": "deepseek",
        "label": "DeepSeek",
        "default_base_url": "https://api.deepseek.com",
        "key_required": True,
        "hint": "在 platform.deepseek.com 创建 API Key。思维链关闭可避免推理模型只输出思考、正文为空。",
        "sample_models": [
            {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro", "api_model": "deepseek-v4-pro", "thinking": False, "ctx": "1M", "speed": "中", "is_default": True},
            {"id": "deepseek-v4-flash", "name": "DeepSeek V4 Flash", "api_model": "deepseek-v4-flash", "thinking": False, "ctx": "1M", "speed": "快"},
        ],
    },
    {
        "kind": "doubao",
        "label": "豆包 · 火山方舟",
        "default_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "key_required": True,
        "hint": "模型名填写方舟推理接入点 ID（ep-xxxxxxxx）。支持多模态读图。",
        "sample_models": [
            {"id": "doubao", "name": "豆包", "api_model": "", "thinking": False, "ctx": "256K", "speed": "快"},
        ],
    },
    {
        "kind": "qwen",
        "label": "通义千问 · 阿里云",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key_required": True,
        "hint": "DashScope OpenAI 兼容模式。Qwen3 等模型可用思维链开关。",
        "sample_models": [
            {"name": "Qwen Plus", "api_model": "qwen-plus", "thinking": False, "ctx": "1M", "speed": "快"},
            {"name": "Qwen Max", "api_model": "qwen-max", "thinking": False, "ctx": "1M", "speed": "中"},
            {"name": "Qwen3 235B", "api_model": "qwen3-235b-a22b", "thinking": True, "ctx": "128K", "speed": "中"},
        ],
    },
    {
        "kind": "siliconflow",
        "label": "硅基流动",
        "default_base_url": "https://api.siliconflow.cn/v1",
        "key_required": True,
        "hint": "在 cloud.siliconflow.cn 创建 Key，模型名用「厂商/模型」格式。",
        "sample_models": [
            {"name": "DeepSeek V3", "api_model": "deepseek-ai/DeepSeek-V3", "thinking": False, "ctx": "64K", "speed": "快"},
            {"name": "Qwen3 32B", "api_model": "Qwen/Qwen3-32B", "thinking": True, "ctx": "128K", "speed": "快"},
        ],
    },
    {
        "kind": "openai",
        "label": "OpenAI",
        "default_base_url": "https://api.openai.com/v1",
        "key_required": True,
        "hint": "官方或 Azure 兼容网关均可，Azure 请改 Base URL。",
        "sample_models": [
            {"name": "GPT-4.1", "api_model": "gpt-4.1", "thinking": False, "ctx": "1M", "speed": "中"},
        ],
    },
    {
        "kind": "custom",
        "label": "自定义接口",
        "default_base_url": "",
        "key_required": False,
        "hint": "任意 OpenAI 兼容 /v1/chat/completions 网关。填写 Base URL、模型名，秘钥按网关要求选填。",
        "sample_models": [],
    },
    {
        "kind": "local",
        "label": "本地模型",
        "default_base_url": "http://host.docker.internal:11434/v1",
        "key_required": False,
        "hint": "Ollama / vLLM / LM Studio。后端在 Docker 内时用 host.docker.internal 访问本机；Ollama 默认 11434，LM Studio 1234。秘钥可留空。",
        "sample_models": [
            {"name": "本机 Ollama", "api_model": "qwen2.5:14b", "thinking": False, "ctx": "32K", "speed": "视显卡"},
        ],
    },
]

_PRESET_BY_KIND = {p["kind"]: p for p in PRESETS}


def preset_for(kind: str) -> dict:
    return _PRESET_BY_KIND.get(kind) or _PRESET_BY_KIND["custom"]


def mask_key(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return "未配置"
    if len(raw) <= 8:
        return "已配置 · ****"
    return f"已配置 · {raw[:3]}••••{raw[-4:]}"


def provider_ready(provider: LlmProvider) -> bool:
    preset = preset_for(provider.kind)
    url = (provider.base_url or "").strip()
    if not url:
        return False
    if preset.get("key_required") and not (provider.api_key or "").strip():
        return False
    return True


def seed_llm_catalog(db: Session) -> None:
    """空表时写入平台模板，并把 .env 里已有的 DeepSeek / 豆包 Key 带进来。"""
    if db.query(LlmProvider).count() > 0:
        return
    settings = get_settings()
    env_keys = {
        "deepseek": (settings.deepseek_api_key or "", settings.deepseek_base_url or "https://api.deepseek.com"),
        "doubao": (settings.ark_api_key or "", settings.ark_base_url or "https://ark.cn-beijing.volces.com/api/v3"),
    }
    for preset in PRESETS:
        kind = preset["kind"]
        key, url = env_keys.get(kind, ("", preset["default_base_url"]))
        provider = LlmProvider(
            id=f"lp-{kind}" if kind not in ("custom", "local") else gen_id("lp"),
            name=preset["label"],
            kind=kind,
            base_url=(url or preset["default_base_url"] or "").rstrip("/"),
            api_key=key,
            enabled=True,
            note=preset.get("hint") or "",
        )
        samples = list(preset.get("sample_models") or [])
        if kind == "doubao":
            samples = [
                {**row, "api_model": row.get("api_model") or settings.ark_chat_model or "doubao-seed-1-8-251228"}
                for row in samples
            ]
        db.add(provider)
        db.flush()
        for i, sample in enumerate(samples):
            api_model = (sample.get("api_model") or "").strip() or sample["name"]
            db.add(
                LlmModel(
                    id=sample.get("id") or gen_id("llm"),
                    provider_id=provider.id,
                    name=sample["name"],
                    api_model=api_model,
                    thinking=bool(sample.get("thinking")),
                    enabled=True,
                    is_default=bool(sample.get("is_default")),
                    ctx=sample.get("ctx") or "",
                    speed=sample.get("speed") or "",
                    sort_order=i,
                )
            )
    db.commit()


def load_providers(db: Session) -> list[LlmProvider]:
    return (
        db.query(LlmProvider)
        .options(selectinload(LlmProvider.models))
        .order_by(LlmProvider.created_at.asc())
        .all()
    )
