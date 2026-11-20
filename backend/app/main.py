import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .body_limit import BodyLimitMiddleware
from .config import get_settings
from .db import ensure_platform_schema, tenant_session
from .routers import (
    admin,
    admin_system,
    auditlog,
    auth,
    billing,
    collab,
    documents,
    duplicate,
    export,
    knowledge,
    llm_config,
    org,
    pay_notify,
    prereview,
    products,
    projects,
    qualifications,
    revision,
    rules,
    standards_admin,
    tender,
    users,
    writer,
)
from .security_headers import SecurityHeadersMiddleware
from .sliding_session import SlidingSessionMiddleware
from .storage import StorageQuotaExceeded
from .tenancy import DEFAULT_TENANT, TenantRequired, use_tenant
from .tenant_context import TenantContextMiddleware

settings = get_settings()
log = logging.getLogger("uvicorn.error")

if settings.is_prod and settings.insecure_defaults:
    # 默认 SECRET_KEY 可被任何人伪造登录令牌，生产环境宁可起不来
    raise RuntimeError("生产环境拒绝启动：" + "；".join(settings.insecure_defaults))


def _bootstrap() -> None:
    """启动迁移：平台 schema → 平台种子数据 → 默认企业（旧单企业数据迁入）→ 其他企业 schema 补齐。"""
    from .job_reaper import reap_all_tenants
    from .platform_seed import seed_platform
    from .seed import BOOTSTRAP_ADMIN, bootstrap_uses_legacy_password
    from .tenants import bootstrap_default_tenant, migrate_all_tenants

    ensure_platform_schema()
    seed_platform()
    bootstrap_default_tenant()
    migrate_all_tenants()
    # 超过 3 小时仍是 running 的任务不会再有结果，置为失败让界面可以重试
    reap_all_tenants(older_than_minutes=180)
    with use_tenant(DEFAULT_TENANT), tenant_session(DEFAULT_TENANT) as db:
        if bootstrap_uses_legacy_password(db):
            log.warning("安全配置提醒：引导管理员 %s 仍在使用历史默认密码 123456，请立即登录修改", BOOTSTRAP_ADMIN["email"])


_bootstrap()

app = FastAPI(
    title="慧投标 AI 预审引擎",
    docs_url=None if settings.is_prod else "/docs",
    redoc_url=None if settings.is_prod else "/redoc",
    openapi_url=None if settings.is_prod else "/openapi.json",
)

app.add_middleware(TenantContextMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_upload_mb * 1024 * 1024)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Bid-Document-Id"],
)


@app.exception_handler(StorageQuotaExceeded)
def _quota_exceeded(request: Request, exc: StorageQuotaExceeded) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=413)


@app.exception_handler(TenantRequired)
def _tenant_required(request: Request, exc: TenantRequired) -> JSONResponse:
    return JSONResponse({"detail": "缺少企业上下文，请重新登录"}, status_code=401)


for module in (
    auth,
    projects,
    documents,
    prereview,
    duplicate,
    tender,
    writer,
    revision,
    knowledge,
    products,
    export,
    rules,
    llm_config,
    users,
    qualifications,
    auditlog,
    org,
    collab,
    billing,
    pay_notify,
    admin,
    admin_system,
    standards_admin,
):
    app.include_router(module.router)
app.include_router(llm_config.admin_router)


@app.on_event("startup")
def _ensure_object_storage() -> None:
    from .storage import ensure_ready

    ensure_ready()
    for issue in settings.insecure_defaults:
        log.warning("安全配置提醒：%s，上线前请在 .env 中替换", issue)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
