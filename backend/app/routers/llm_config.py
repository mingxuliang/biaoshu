"""系统模块：大模型秘钥、自定义/本地接入、思维链开关。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from ..auth import get_current_user
from ..db import get_db
from ..engines.llm import ping_model
from ..llm_catalog import PRESETS, PROVIDER_KINDS, load_providers, mask_key, preset_for, provider_ready
from ..models import LlmModel, LlmProvider, User, gen_id
from ..permissions import PERM_SETTINGS, PERM_WRITER, require_perm
from ..schemas import (
    LlmModelIn,
    LlmModelOut,
    LlmModelPatchIn,
    LlmPresetOut,
    LlmProviderIn,
    LlmProviderOut,
    LlmProviderPatchIn,
    LlmTestOut,
)

router = APIRouter(prefix="/api", tags=["llm"])


def _model_to_out(model: LlmModel, provider: LlmProvider) -> LlmModelOut:
    return LlmModelOut(
        id=model.id,
        providerId=provider.id,
        providerKind=provider.kind,
        providerName=provider.name,
        name=model.name,
        apiModel=model.api_model,
        thinking=bool(model.thinking),
        enabled=bool(model.enabled),
        isDefault=bool(model.is_default),
        ctx=model.ctx or "",
        speed=model.speed or "",
        vision=provider.kind == "doubao",
        ready=provider_ready(provider) and bool((model.api_model or "").strip()),
    )


def _provider_to_out(provider: LlmProvider) -> LlmProviderOut:
    models = sorted(provider.models or [], key=lambda m: (m.sort_order or 0, m.name or ""))
    return LlmProviderOut(
        id=provider.id,
        name=provider.name,
        kind=provider.kind,
        baseUrl=provider.base_url or "",
        apiKeyMasked=mask_key(provider.api_key),
        hasKey=bool((provider.api_key or "").strip()),
        enabled=bool(provider.enabled),
        note=provider.note or "",
        ready=provider_ready(provider),
        models=[_model_to_out(m, provider) for m in models],
    )


def _require_provider(db: Session, provider_id: str) -> LlmProvider:
    row = (
        db.query(LlmProvider)
        .options(selectinload(LlmProvider.models))
        .filter(LlmProvider.id == provider_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "接入不存在")
    return row


def _clear_defaults(db: Session, keep_id: str | None = None) -> None:
    rows = db.query(LlmModel).filter(LlmModel.is_default.is_(True)).all()
    for row in rows:
        if keep_id and row.id == keep_id:
            continue
        row.is_default = False


@router.get("/llm-presets", response_model=list[LlmPresetOut])
def list_llm_presets(current_user: User = Depends(get_current_user)) -> list[LlmPresetOut]:
    require_perm(current_user, PERM_SETTINGS)
    return [
        LlmPresetOut(
            kind=p["kind"],
            label=p["label"],
            defaultBaseUrl=p["default_base_url"],
            keyRequired=bool(p["key_required"]),
            hint=p.get("hint") or "",
            sampleModels=list(p.get("sample_models") or []),
        )
        for p in PRESETS
    ]


@router.get("/llm-models", response_model=list[LlmModelOut])
def list_writer_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[LlmModelOut]:
    require_perm(current_user, PERM_WRITER)
    out: list[LlmModelOut] = []
    for provider in load_providers(db):
        if not provider.enabled:
            continue
        for model in provider.models or []:
            if not model.enabled:
                continue
            out.append(_model_to_out(model, provider))
    out.sort(key=lambda m: (0 if m.isDefault else 1, m.providerName, m.name))
    return out


@router.get("/llm-providers", response_model=list[LlmProviderOut])
def list_llm_providers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[LlmProviderOut]:
    require_perm(current_user, PERM_SETTINGS)
    return [_provider_to_out(p) for p in load_providers(db)]


@router.post("/llm-providers", response_model=LlmProviderOut)
def create_llm_provider(
    payload: LlmProviderIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LlmProviderOut:
    require_perm(current_user, PERM_SETTINGS)
    kind = (payload.kind or "").strip()
    if kind not in PROVIDER_KINDS:
        raise HTTPException(400, "不支持的接入类型")
    name = payload.name.strip() or preset_for(kind)["label"]
    base = (payload.baseUrl or "").strip().rstrip("/") or preset_for(kind)["default_base_url"]
    provider = LlmProvider(
        id=gen_id("lp"),
        name=name,
        kind=kind,
        base_url=base,
        api_key=(payload.apiKey or "").strip(),
        enabled=payload.enabled,
        note=payload.note or preset_for(kind).get("hint") or "",
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return _provider_to_out(provider)


@router.patch("/llm-providers/{provider_id}", response_model=LlmProviderOut)
def patch_llm_provider(
    provider_id: str,
    payload: LlmProviderPatchIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LlmProviderOut:
    require_perm(current_user, PERM_SETTINGS)
    provider = _require_provider(db, provider_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        name = data["name"].strip()
        if name:
            provider.name = name
    if "baseUrl" in data and data["baseUrl"] is not None:
        provider.base_url = data["baseUrl"].strip().rstrip("/")
    if data.get("clearKey"):
        provider.api_key = ""
    elif "apiKey" in data and data["apiKey"] is not None:
        key = data["apiKey"].strip()
        if key:
            provider.api_key = key
    if "enabled" in data and data["enabled"] is not None:
        provider.enabled = data["enabled"]
    if "note" in data and data["note"] is not None:
        provider.note = data["note"]
    db.commit()
    db.refresh(provider)
    return _provider_to_out(_require_provider(db, provider.id))


@router.delete("/llm-providers/{provider_id}")
def delete_llm_provider(
    provider_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    require_perm(current_user, PERM_SETTINGS)
    provider = _require_provider(db, provider_id)
    db.delete(provider)
    db.commit()
    return {"ok": True}


@router.post("/llm-providers/{provider_id}/models", response_model=LlmModelOut)
def create_llm_model(
    provider_id: str,
    payload: LlmModelIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LlmModelOut:
    require_perm(current_user, PERM_SETTINGS)
    provider = _require_provider(db, provider_id)
    name = payload.name.strip()
    api_model = payload.apiModel.strip()
    if not name or not api_model:
        raise HTTPException(400, "请填写显示名称和接口模型名")
    model = LlmModel(
        id=gen_id("llm"),
        provider_id=provider.id,
        name=name,
        api_model=api_model,
        thinking=payload.thinking,
        enabled=payload.enabled,
        is_default=payload.isDefault,
        ctx=payload.ctx or "",
        speed=payload.speed or "",
        sort_order=len(provider.models or []),
    )
    if model.is_default:
        _clear_defaults(db)
    db.add(model)
    db.commit()
    db.refresh(model)
    return _model_to_out(model, provider)


@router.patch("/llm-models/{model_id}", response_model=LlmModelOut)
def patch_llm_model(
    model_id: str,
    payload: LlmModelPatchIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LlmModelOut:
    require_perm(current_user, PERM_SETTINGS)
    model = db.get(LlmModel, model_id)
    if not model:
        raise HTTPException(404, "模型不存在")
    data = payload.model_dump(exclude_unset=True)
    if data.get("name"):
        model.name = data["name"].strip()
    if data.get("apiModel"):
        model.api_model = data["apiModel"].strip()
    if "thinking" in data and data["thinking"] is not None:
        model.thinking = data["thinking"]
    if "enabled" in data and data["enabled"] is not None:
        model.enabled = data["enabled"]
    if "ctx" in data and data["ctx"] is not None:
        model.ctx = data["ctx"]
    if "speed" in data and data["speed"] is not None:
        model.speed = data["speed"]
    if data.get("isDefault"):
        _clear_defaults(db, keep_id=model.id)
        model.is_default = True
    elif "isDefault" in data and data["isDefault"] is False:
        model.is_default = False
    db.commit()
    provider = db.get(LlmProvider, model.provider_id)
    if not provider:
        raise HTTPException(404, "接入不存在")
    return _model_to_out(model, provider)


@router.delete("/llm-models/{model_id}")
def delete_llm_model(
    model_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    require_perm(current_user, PERM_SETTINGS)
    model = db.get(LlmModel, model_id)
    if not model:
        raise HTTPException(404, "模型不存在")
    db.delete(model)
    db.commit()
    return {"ok": True}


@router.post("/llm-models/{model_id}/test", response_model=LlmTestOut)
def test_llm_model(
    model_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LlmTestOut:
    require_perm(current_user, PERM_SETTINGS)
    model = db.get(LlmModel, model_id)
    if not model:
        raise HTTPException(404, "模型不存在")
    ok, message, latency, preview = ping_model(model_id)
    return LlmTestOut(ok=ok, message=message, latencyMs=latency, preview=preview)
