"""大模型接入目录：平台预设、秘钥掩码、从环境变量引导写入。"""

from __future__ import annotations

from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .models import LlmModel, LlmProvider, gen_id

PROVIDER_KINDS = ("deepseek", "doubao", "qwen", "siliconflow", "openai", "custom", "local")

# 硅基流动当前账号可调用、适合写标书的长文模型。已有 DeepSeek V3 / Qwen3 32B 不在此列。
SILICONFLOW_WRITER_MODELS: list[dict] = [
    {
        "id": "sf-qwen25-72b-128k",
        "name": "Qwen2.5 72B",
        "api_model": "Qwen/Qwen2.5-72B-Instruct-128K",
        "thinking": False,
        "ctx": "128K",
        "speed": "中",
    },
    {
        "id": "sf-qwen35-122b",
        "name": "Qwen3.5 122B",
        "api_model": "Qwen/Qwen3.5-122B-A10B",
        "thinking": True,
        "ctx": "256K",
        "speed": "中",
    },
    {
        "id": "sf-qwen3-30b-instruct",
        "name": "Qwen3 30B Instruct",
        "api_model": "Qwen/Qwen3-30B-A3B-Instruct-2507",
        "thinking": False,
        "ctx": "256K",
        "speed": "快",
    },
    {
        "id": "sf-deepseek-v32",
        "name": "DeepSeek V3.2",
        "api_model": "deepseek-ai/DeepSeek-V3.2",
        "thinking": False,
        "ctx": "128K",
        "speed": "中",
    },
]

PRESETS: list[dict] = [
    {
        "kind": "deepseek",
        "label": "DeepSeek",
        "default_base_url": "https://api.deepseek.com",
        "key_required": True,
        "hint": "在 platform.deepseek.com 创建 API Key。V4.1 Flash 接口名为 deepseek-flash，官方标明 Vision（可看图）；V4 Pro 当前不支持图片。",
        "sample_models": [
            {"id": "deepseek-v4.1-flash", "name": "DeepSeek V4.1 Flash", "api_model": "deepseek-flash", "thinking": False, "ctx": "1M · 多模态", "speed": "快"},
            {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro", "api_model": "deepseek-v4-pro", "thinking": False, "ctx": "1M", "speed": "中", "is_default": True},
            {"id": "deepseek-v4-flash", "name": "DeepSeek V4 Flash（兼容）", "api_model": "deepseek-v4-flash", "thinking": False, "ctx": "1M · 已路由到 V4.1", "speed": "快"},
        ],
    },
    {
        "kind": "doubao",
        "label": "豆包 · 火山方舟",
        "default_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "key_required": True,
        "hint": "同一把火山方舟 Key 下挂两个模型：文本用对话模型，生图用 Seedream。生图不会出现在撰写模型列表里。",
        "sample_models": [
            {"id": "doubao", "name": "豆包文本", "api_model": "", "thinking": False, "ctx": "256K", "speed": "快", "task": "chat"},
            {
                "id": "doubao-seedream",
                "name": "豆包 Seedream 生图",
                "api_model": "doubao-seedream-4-0-250828",
                "thinking": False,
                "ctx": "文生图",
                "speed": "中",
                "task": "image",
            },
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
            *SILICONFLOW_WRITER_MODELS,
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


def ensure_deepseek_v41_flash(db: Session) -> None:
    """已有 DeepSeek 接入时补上 V4.1 Flash（官方多模态型号 deepseek-flash），不改用户默认模型。"""
    provider = db.query(LlmProvider).filter(LlmProvider.kind == "deepseek").order_by(LlmProvider.created_at.asc()).first()
    if provider is None:
        return
    models = db.query(LlmModel).filter(LlmModel.provider_id == provider.id).all()
    apis = {(m.api_model or "").strip().lower() for m in models}
    ids = {m.id for m in models}
    if "deepseek-flash" in apis or "deepseek-v4.1-flash" in ids:
        return
    max_order = min((m.sort_order or 0) for m in models) if models else 0
    db.add(
        LlmModel(
            id="deepseek-v4.1-flash",
            provider_id=provider.id,
            name="DeepSeek V4.1 Flash",
            api_model="deepseek-flash",
            thinking=False,
            enabled=True,
            is_default=False,
            ctx="1M · 多模态",
            speed="快",
            sort_order=max_order - 1,
        )
    )
    db.commit()


def ensure_doubao_models(db: Session) -> None:
    """豆包接入同时保留文本模型和 Seedream 生图模型。已有记录不改接口名。"""
    settings = get_settings()
    provider = db.query(LlmProvider).filter(LlmProvider.kind == "doubao").order_by(LlmProvider.created_at.asc()).first()
    if provider is None:
        return
    models = db.query(LlmModel).filter(LlmModel.provider_id == provider.id).all()
    changed = False
    for model in models:
        if not (model.task or "").strip():
            model.task = "chat"
            changed = True
    has_image = any((model.task or "") == "image" or "seedream" in (model.api_model or "").lower() for model in models)
    if not has_image:
        seedream = (settings.ark_image_model or "doubao-seedream-4-0-250828").strip()
        db.add(
            LlmModel(
                id="doubao-seedream",
                provider_id=provider.id,
                name="豆包 Seedream 生图",
                api_model=seedream,
                thinking=False,
                enabled=True,
                is_default=False,
                ctx="文生图",
                speed="中",
                sort_order=100,
                task="image",
            )
        )
        changed = True
    else:
        for model in models:
            if "seedream" in (model.api_model or "").lower() and (model.task or "chat") != "image":
                model.task = "image"
                model.is_default = False
                changed = True
    has_chat = any((model.task or "chat") != "image" and (model.api_model or "").strip() for model in models)
    if not has_chat:
        chat_model = (settings.ark_chat_model or "doubao-seed-1-8-251228").strip()
        db.add(
            LlmModel(
                id="doubao",
                provider_id=provider.id,
                name="豆包文本",
                api_model=chat_model,
                thinking=False,
                enabled=True,
                is_default=False,
                ctx="256K",
                speed="快",
                sort_order=0,
                task="chat",
            )
        )
        changed = True
    if changed:
        db.commit()


def ensure_siliconflow_writer_models(db: Session) -> None:
    """已有硅基密钥时补上适合写标书的长文模型，不改用户默认模型，也不重复已有接口名。"""
    provider = db.query(LlmProvider).filter(LlmProvider.kind == "siliconflow").order_by(LlmProvider.created_at.asc()).first()
    if provider is None:
        return
    models = db.query(LlmModel).filter(LlmModel.provider_id == provider.id).all()
    apis = {(model.api_model or "").strip().lower() for model in models}
    ids = {model.id for model in models}
    max_order = max((model.sort_order or 0) for model in models) if models else 0
    changed = False
    for offset, sample in enumerate(SILICONFLOW_WRITER_MODELS, start=1):
        api_model = (sample.get("api_model") or "").strip()
        model_id = sample["id"]
        if api_model.lower() in apis or model_id in ids:
            continue
        db.add(
            LlmModel(
                id=model_id,
                provider_id=provider.id,
                name=sample["name"],
                api_model=api_model,
                thinking=bool(sample.get("thinking")),
                enabled=True,
                is_default=False,
                ctx=sample.get("ctx") or "",
                speed=sample.get("speed") or "",
                sort_order=max_order + offset,
                task="chat",
            )
        )
        changed = True
    if changed:
        db.commit()


def seed_llm_catalog(db: Session) -> None:
    """空表时写入平台模板，并把 .env 里已有的 DeepSeek / 豆包 Key 带进来。"""
    if db.query(LlmProvider).count() > 0:
        ensure_deepseek_v41_flash(db)
        ensure_doubao_models(db)
        ensure_siliconflow_writer_models(db)
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
            filled = []
            for row in samples:
                item = dict(row)
                if item.get("task") == "image":
                    item["api_model"] = item.get("api_model") or settings.ark_image_model or "doubao-seedream-4-0-250828"
                else:
                    item["api_model"] = item.get("api_model") or settings.ark_chat_model or "doubao-seed-1-8-251228"
                    item["task"] = "chat"
                filled.append(item)
            samples = filled
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
                    task=sample.get("task") or "chat",
                    is_default=bool(sample.get("is_default")),
                    ctx=sample.get("ctx") or "",
                    speed=sample.get("speed") or "",
                    sort_order=i,
                )
            )
    db.commit()
    ensure_doubao_models(db)
    ensure_siliconflow_writer_models(db)


def load_providers(db: Session) -> list[LlmProvider]:
    return (
        db.query(LlmProvider)
        .options(selectinload(LlmProvider.models))
        .order_by(LlmProvider.created_at.asc())
        .all()
    )
