"""平台后台：系统环境、对象存储总览、公告、平台审计。"""

from __future__ import annotations

import platform as pyplatform
import sys
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .. import storage
from ..config import get_settings
from ..db import engine, get_platform_db, is_postgres
from ..platform_auth import ROLE_FINANCE, ROLE_OPS, ROLE_READONLY, client_ip, platform_audit, require_roles

router = APIRouter(prefix="/api/admin", tags=["admin-system"])

ops = require_roles(ROLE_OPS)
anyone = require_roles(ROLE_OPS, ROLE_FINANCE, ROLE_READONLY)


def _dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


def _check(fn) -> dict:
    started = time.perf_counter()
    try:
        detail = fn()
        return {"ok": True, "latencyMs": int((time.perf_counter() - started) * 1000), "detail": detail}
    except Exception as exc:  # noqa: BLE001 —— 环境探测失败只报告
        return {"ok": False, "latencyMs": int((time.perf_counter() - started) * 1000), "detail": str(exc)[:300]}


@router.get("/system/env")
def system_env(admin=Depends(anyone)) -> dict:
    """运行环境：数据库、Redis、MinIO、Celery worker、支付通道就绪情况。不返回任何秘钥。"""
    settings = get_settings()

    def db_info():
        with engine.connect() as conn:
            if is_postgres(conn):
                version = conn.execute(text("SHOW server_version")).scalar()
                size = conn.execute(text("SELECT pg_database_size(current_database())")).scalar()
                schemas = conn.execute(text("SELECT count(*) FROM information_schema.schemata WHERE schema_name LIKE 't\\_%'")).scalar()
                conns = conn.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")).scalar()
                return {"engine": "PostgreSQL", "version": version, "sizeBytes": int(size or 0), "tenantSchemas": int(schemas or 0), "connections": int(conns or 0)}
            return {"engine": conn.dialect.name}

    def redis_info():
        import redis

        r = redis.Redis.from_url(settings.redis_url, socket_timeout=2)
        info = r.info()
        return {"version": info.get("redis_version"), "usedMemory": info.get("used_memory_human"), "clients": info.get("connected_clients")}

    def minio_info():
        buckets = storage._client().list_buckets()
        return {"endpoint": settings.minio_endpoint, "buckets": len(buckets)}

    def celery_info():
        from ..celery_app import celery_app

        replies = celery_app.control.inspect(timeout=1.5).ping() or {}
        return {"workers": sorted(replies.keys())}

    from ..payments import available_channels

    return {
        "app": {
            "env": settings.app_env,
            "python": sys.version.split()[0],
            "os": pyplatform.platform(),
            "publicBaseUrl": settings.public_base_url,
            "tenantSignup": bool(settings.allow_tenant_signup),
            "personalRegister": bool(settings.allow_register),
            "trialCredits": settings.trial_credits,
            "trialDays": settings.trial_days,
            "creditsPerYuan": settings.credits_per_yuan,
            "mockPayment": bool(settings.mock_payment_enabled),
            "verifyCodeChannel": settings.verify_code_channel,
            "adminIpAllowlist": bool((settings.platform_admin_ip_allowlist or "").strip()),
        },
        "database": _check(db_info),
        "redis": _check(redis_info),
        "minio": _check(minio_info),
        "celery": _check(celery_info),
        "payments": available_channels(),
        "checkedAt": _dt(datetime.utcnow()),
    }


@router.get("/storage/buckets")
def list_buckets(admin=Depends(anyone), pdb: Session = Depends(get_platform_db)) -> list[dict]:
    """所有 bucket 的对象数和容量，并对应到企业。统计要遍历对象，企业多时较慢。"""
    from ..platform_models import Tenant
    from ..tenancy import DEFAULT_TENANT, bucket_for

    tenants = {bucket_for(t.id): t for t in pdb.query(Tenant).all()}
    out = []
    try:
        buckets = storage._client().list_buckets()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"对象存储不可用：{exc}") from exc
    for b in buckets:
        t = tenants.get(b.name)
        try:
            count, size = storage.bucket_usage_bytes(b.name)
        except Exception:  # noqa: BLE001
            count, size = None, None
        out.append(
            {
                "bucket": b.name,
                "tenantId": t.id if t else ("platform" if b.name == storage.platform_bucket() else ""),
                "tenantName": t.name if t else ("平台文件（发票、回单）" if b.name == storage.platform_bucket() else "未关联企业"),
                "quotaMb": t.storage_quota_mb if t else None,
                "objects": count,
                "bytes": size,
                "createdAt": _dt(b.creation_date.replace(tzinfo=None)) if b.creation_date else "",
                "isDefault": bool(t and t.id == DEFAULT_TENANT),
            }
        )
    out.sort(key=lambda r: -(r["bytes"] or 0))
    return out


# ---------------------------------------------------------------------------
# 公告
# ---------------------------------------------------------------------------


class AnnouncementIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field("", max_length=5000)
    level: str = Field("info", pattern="^(info|warning)$")
    published: bool = False


def _ann_out(a) -> dict:
    return {"id": a.id, "title": a.title, "body": a.body, "level": a.level, "published": bool(a.published), "createdAt": _dt(a.created_at)}


@router.get("/announcements")
def list_announcements(admin=Depends(anyone), pdb: Session = Depends(get_platform_db)) -> list[dict]:
    from ..platform_models import Announcement

    return [_ann_out(a) for a in pdb.query(Announcement).order_by(Announcement.created_at.desc()).all()]


@router.post("/announcements")
def create_announcement(payload: AnnouncementIn, request: Request, admin=Depends(ops), pdb: Session = Depends(get_platform_db)) -> dict:
    from ..platform_models import Announcement

    a = Announcement(title=payload.title.strip(), body=payload.body, level=payload.level, published=payload.published)
    pdb.add(a)
    platform_audit(pdb, admin, "发布公告", target=a.title, ip=client_ip(request))
    pdb.commit()
    return _ann_out(a)


@router.put("/announcements/{ann_id}")
def update_announcement(ann_id: str, payload: AnnouncementIn, admin=Depends(ops), pdb: Session = Depends(get_platform_db)) -> dict:
    from ..platform_models import Announcement

    a = pdb.get(Announcement, ann_id)
    if a is None:
        raise HTTPException(404, "公告不存在")
    a.title = payload.title.strip()
    a.body = payload.body
    a.level = payload.level
    a.published = payload.published
    pdb.commit()
    return _ann_out(a)


@router.delete("/announcements/{ann_id}")
def delete_announcement(ann_id: str, admin=Depends(ops), pdb: Session = Depends(get_platform_db)) -> dict:
    from ..platform_models import Announcement

    a = pdb.get(Announcement, ann_id)
    if a is None:
        raise HTTPException(404, "公告不存在")
    pdb.delete(a)
    pdb.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# 平台审计
# ---------------------------------------------------------------------------


@router.get("/audit")
def platform_audit_log(
    tenantId: str = "",
    action: str = "",
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    admin=Depends(anyone),
    pdb: Session = Depends(get_platform_db),
) -> dict:
    from ..platform_models import PlatformAudit

    q = pdb.query(PlatformAudit)
    if tenantId:
        q = q.filter(PlatformAudit.tenant_id == tenantId)
    if action:
        q = q.filter(PlatformAudit.action == action)
    total = q.count()
    rows = q.order_by(PlatformAudit.created_at.desc()).offset((page - 1) * size).limit(size).all()
    return {
        "total": total,
        "items": [
            {"id": r.id, "adminName": r.admin_name, "action": r.action, "tenantId": r.tenant_id, "target": r.target, "detail": r.detail, "ip": r.ip, "createdAt": _dt(r.created_at)}
            for r in rows
        ],
        "actions": [a for (a,) in pdb.query(PlatformAudit.action).group_by(PlatformAudit.action).order_by(func.count().desc()).limit(50).all()],
    }
