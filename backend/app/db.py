"""数据库会话与迁移。

- 企业数据：每家企业一个 schema（t_<租户ID>），模型挂在 Base 上。
- 平台数据：platform schema，模型挂在 PlatformBase 上（企业、账号、钱包、订单、发票、模型配置等）。

会话开启事务时设置 search_path = "t_<租户ID>", platform。企业表只存在于企业 schema，
平台表只存在于 platform schema，所以业务代码无需写 schema 前缀，也不可能读到别家企业的表。
sqlite（单元测试）没有 schema，同一个库里同时建两套表。
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from .config import get_settings
from .tenancy import PLATFORM_SCHEMA, TenantRequired, require_tenant, schema_for

settings = get_settings()
log = logging.getLogger(__name__)

engine = create_engine(settings.database_url, pool_pre_ping=True)
Base = declarative_base()
PlatformBase = declarative_base()


def is_postgres(bind) -> bool:
    return bind.dialect.name == "postgresql"


def _search_path(schema: str | None) -> str:
    if schema:
        return f'"{schema}", {PLATFORM_SCHEMA}'
    return PLATFORM_SCHEMA


class ScopedSession(Session):
    """info["schema"] 为企业 schema；为空表示平台会话。"""


@event.listens_for(ScopedSession, "after_begin")
def _apply_search_path(session: Session, transaction, connection) -> None:
    if not is_postgres(connection):
        return
    connection.exec_driver_sql(f"SET LOCAL search_path TO {_search_path(session.info.get('schema'))}")


_factory = sessionmaker(class_=ScopedSession, autocommit=False, autoflush=False, bind=engine)


def tenant_session(tenant_id: str) -> Session:
    db = _factory()
    db.info["schema"] = schema_for(tenant_id)
    db.info["tenant_id"] = tenant_id
    return db


def platform_session() -> Session:
    db = _factory()
    db.info["schema"] = None
    return db


def SessionLocal() -> Session:  # noqa: N802 —— 保留旧名，业务代码和任务里大量使用
    """当前企业上下文的会话；没有企业上下文直接报错。"""
    return tenant_session(require_tenant())


@contextmanager
def platform_db() -> Iterator[Session]:
    db = platform_session()
    try:
        yield db
    finally:
        db.close()


def get_db():
    """企业接口的会话。企业上下文由 TenantContextMiddleware 按登录令牌设置
    （放在中间件里是因为同步依赖跑在线程池，依赖里设置的 contextvar 传不到接口函数）。"""
    from .tenancy import current_tenant

    tenant_id = current_tenant()
    if not tenant_id:
        raise HTTPException(401, "缺少登录凭证，请先登录")
    db = tenant_session(tenant_id)
    try:
        yield db
    finally:
        db.close()


def get_platform_db():
    db = platform_session()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 迁移
# ---------------------------------------------------------------------------


def ensure_platform_schema() -> None:
    from . import platform_models  # noqa: F401 —— 注册平台表

    with engine.begin() as conn:
        if is_postgres(conn):
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {PLATFORM_SCHEMA}"))
            conn.exec_driver_sql(f"SET LOCAL search_path TO {PLATFORM_SCHEMA}")
            _move_legacy_platform_tables(conn)
        PlatformBase.metadata.create_all(bind=conn)
        if is_postgres(conn):
            conn.execute(text("ALTER TABLE llm_models ADD COLUMN IF NOT EXISTS task VARCHAR DEFAULT 'chat'"))
            conn.execute(text("UPDATE llm_models SET task = 'chat' WHERE task IS NULL OR task = ''"))
            conn.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS kind VARCHAR DEFAULT '企业'"))
            # 不给默认值：存量套餐由 seed_plans 按编码回填适用对象
            conn.execute(text("ALTER TABLE plans ADD COLUMN IF NOT EXISTS audience VARCHAR"))
            conn.execute(text("ALTER TABLE recharge_orders ADD COLUMN IF NOT EXISTS refunded_cents INTEGER DEFAULT 0"))


def _move_legacy_platform_tables(conn) -> None:
    """单企业版的模型配置表在 public，迁到 platform 由平台统一管理。"""
    for table in ("llm_providers", "llm_models"):
        in_public = conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=:t"),
            {"t": table},
        ).first()
        in_platform = conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_schema=:s AND table_name=:t"),
            {"s": PLATFORM_SCHEMA, "t": table},
        ).first()
        if in_public and not in_platform:
            conn.execute(text(f"ALTER TABLE public.{table} SET SCHEMA {PLATFORM_SCHEMA}"))


def migrate_legacy_public(tenant_id: str) -> int:
    """把单企业版留在 public 的业务表整体迁入默认企业 schema。返回迁移的表数。"""
    moved = 0
    with engine.begin() as conn:
        if not is_postgres(conn):
            return 0
        schema = schema_for(tenant_id)
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        for table in Base.metadata.sorted_tables:
            in_public = conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=:t"),
                {"t": table.name},
            ).first()
            in_tenant = conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_schema=:s AND table_name=:t"),
                {"s": schema, "t": table.name},
            ).first()
            if in_public and not in_tenant:
                conn.execute(text(f'ALTER TABLE public."{table.name}" SET SCHEMA "{schema}"'))
                moved += 1
    if moved:
        log.warning("已把 %s 张单企业版业务表迁入企业 schema %s", moved, schema_for(tenant_id))
    return moved


def ensure_tenant_schema(tenant_id: str) -> None:
    """建企业 schema 和全部企业表，并补齐历史新增列。新建企业和每次启动都会调用。"""
    from . import models  # noqa: F401 —— 注册企业表

    schema = schema_for(tenant_id)
    with engine.begin() as conn:
        if is_postgres(conn):
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
            conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        Base.metadata.create_all(bind=conn)
        if is_postgres(conn):
            _tenant_alters(conn)


def drop_tenant_schema(tenant_id: str) -> None:
    schema = schema_for(tenant_id)
    with engine.begin() as conn:
        if is_postgres(conn):
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def ensure_schema() -> None:
    """兼容旧入口：只迁默认企业。"""
    from .tenancy import DEFAULT_TENANT

    ensure_tenant_schema(DEFAULT_TENANT)


def _tenant_alters(conn) -> None:
    """create_all 不会给已有表加列；给后续新增列做兼容补齐。search_path 已指向企业 schema。"""
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS disabled BOOLEAN DEFAULT FALSE"))
    conn.execute(text("ALTER TABLE qualification_assets ADD COLUMN IF NOT EXISTS ocr_text TEXT DEFAULT ''"))
    conn.execute(text("ALTER TABLE qualification_assets ADD COLUMN IF NOT EXISTS ocr_status VARCHAR DEFAULT ''"))
    conn.execute(text("ALTER TABLE qualification_assets ADD COLUMN IF NOT EXISTS review_status VARCHAR DEFAULT '已入库'"))
    conn.execute(text("ALTER TABLE qualification_assets ADD COLUMN IF NOT EXISTS merge_status VARCHAR DEFAULT '新增'"))
    for col, default in (
        ("aliases_json", "'[]'::json"),
        ("sources_json", "'[]'::json"),
        ("evidence_json", "'[]'::json"),
        ("field_conflict_json", "'[]'::json"),
        ("suspected_ids_json", "'[]'::json"),
        ("attrs_json", "'{}'::json"),
    ):
        conn.execute(text(f"ALTER TABLE qualification_assets ADD COLUMN IF NOT EXISTS {col} JSON DEFAULT {default}"))
    conn.execute(text("ALTER TABLE product_features ADD COLUMN IF NOT EXISTS source_text TEXT DEFAULT ''"))
    conn.execute(text("ALTER TABLE writer_drafts ADD COLUMN IF NOT EXISTS selected_product_library_id VARCHAR"))
    conn.execute(text("ALTER TABLE product_features ADD COLUMN IF NOT EXISTS parent_id VARCHAR"))
    conn.execute(text("ALTER TABLE knowledge_slices ADD COLUMN IF NOT EXISTS parent_id VARCHAR"))
    conn.execute(text("ALTER TABLE knowledge_slices ADD COLUMN IF NOT EXISTS level VARCHAR DEFAULT '一级'"))
    conn.execute(text("ALTER TABLE veto_rules ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE"))
    conn.execute(text("ALTER TABLE catalog_rules ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE"))
    conn.execute(text("ALTER TABLE bid_revisions ADD COLUMN IF NOT EXISTS layout_json JSON"))
    conn.execute(text("ALTER TABLE bid_revisions ADD COLUMN IF NOT EXISTS resolved_ids_json JSON DEFAULT '[]'::json"))
    conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS category VARCHAR DEFAULT '软件服务类'"))
    conn.execute(text("UPDATE projects SET category = '软件服务类' WHERE category IS NULL OR category = '' OR category = '产品标'"))
    conn.execute(text("UPDATE projects SET category = '工程类' WHERE category = '工程标'"))
    conn.execute(text("ALTER TABLE projects ALTER COLUMN category SET DEFAULT '软件服务类'"))
    conn.execute(text("ALTER TABLE review_runs ADD COLUMN IF NOT EXISTS tech_modules_json JSON DEFAULT '[]'::json"))
    conn.execute(text("ALTER TABLE review_runs ADD COLUMN IF NOT EXISTS tender_rules_json JSON DEFAULT '{}'::json"))
    conn.execute(text("ALTER TABLE review_runs ADD COLUMN IF NOT EXISTS custom_rules_json JSON DEFAULT '[]'::json"))
    conn.execute(
        text(
            "UPDATE qualification_assets SET kind = 'cert' "
            "WHERE kind = 'credit' AND ("
            "name ~ '荣誉|奖状|获奖' OR coalesce(detail, '') ~ '荣誉|奖状|获奖')"
        )
    )
    conn.execute(text("ALTER TABLE tender_documents ADD COLUMN IF NOT EXISTS kind VARCHAR DEFAULT 'main'"))
    conn.execute(text("UPDATE tender_documents SET kind = 'main' WHERE kind IS NULL OR kind = ''"))
    conn.execute(text("ALTER TABLE bid_documents ADD COLUMN IF NOT EXISTS kind VARCHAR DEFAULT 'combined'"))
    conn.execute(text("UPDATE bid_documents SET kind = 'combined' WHERE kind IS NULL OR kind = ''"))
    conn.execute(text("ALTER TABLE review_runs ADD COLUMN IF NOT EXISTS scope VARCHAR DEFAULT 'full'"))
    conn.execute(text("UPDATE review_runs SET scope = 'full' WHERE scope IS NULL OR scope = ''"))
    conn.execute(text("ALTER TABLE export_records ADD COLUMN IF NOT EXISTS scope VARCHAR DEFAULT ''"))
    conn.execute(text("ALTER TABLE export_records ADD COLUMN IF NOT EXISTS category VARCHAR DEFAULT ''"))
    conn.execute(text("ALTER TABLE weight_templates ADD COLUMN IF NOT EXISTS category VARCHAR DEFAULT '工程类'"))
    conn.execute(text("UPDATE weight_templates SET category = '工程类' WHERE category IS NULL OR category = ''"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER DEFAULT 0"))
    for table in ("product_source_docs", "qualification_source_docs", "knowledge_documents"):
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS content_sha256 VARCHAR DEFAULT ''"))
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_content_sha256 ON {table} (content_sha256)"))
    conn.execute(text("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS simhash VARCHAR DEFAULT ''"))
    conn.execute(text("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS duplicate_hint VARCHAR DEFAULT ''"))
    conn.execute(text("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'done'"))
    conn.execute(text("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS error TEXT"))
    conn.execute(text("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS finished_at TIMESTAMP"))
    conn.execute(text("ALTER TABLE bid_revisions ADD COLUMN IF NOT EXISTS scope VARCHAR DEFAULT 'business'"))
    conn.execute(
        text(
            "UPDATE bid_revisions r SET scope = CASE "
            "WHEN rr.scope IN ('business','tech') THEN rr.scope ELSE 'business' END "
            "FROM review_runs rr WHERE r.review_run_id = rr.id "
            "AND (r.scope IS NULL OR r.scope = '' OR r.scope = 'full')"
        )
    )
    conn.execute(text("ALTER TABLE bid_revisions DROP CONSTRAINT IF EXISTS bid_revisions_project_id_key"))
    conn.execute(text("DROP INDEX IF EXISTS bid_revisions_project_id_key"))
    conn.execute(text("DROP INDEX IF EXISTS ix_bid_revisions_project_id"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bid_revisions_project_id ON bid_revisions (project_id)"))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_bid_revisions_project_scope ON bid_revisions (project_id, scope)"))
    conn.execute(text("ALTER TABLE review_runs ADD COLUMN IF NOT EXISTS standard_review_json JSON DEFAULT '{}'::json"))
    conn.execute(text("ALTER TABLE writer_jobs ADD COLUMN IF NOT EXISTS user_id VARCHAR"))
    conn.execute(text("ALTER TABLE writer_jobs ADD COLUMN IF NOT EXISTS result_json JSON DEFAULT '{}'::json"))
    conn.execute(text("UPDATE writer_jobs SET result_json = '{}'::json WHERE result_json IS NULL"))
    conn.execute(text("ALTER TABLE writer_chat_messages ADD COLUMN IF NOT EXISTS trace_json JSON DEFAULT '[]'::json"))
    conn.execute(text("ALTER TABLE writer_chat_messages ADD COLUMN IF NOT EXISTS files_json JSON DEFAULT '[]'::json"))
    conn.execute(text("ALTER TABLE writer_drafts ADD COLUMN IF NOT EXISTS doc_kind VARCHAR DEFAULT 'tech'"))
    conn.execute(text("UPDATE writer_drafts SET doc_kind = 'tech' WHERE doc_kind IS NULL OR doc_kind = ''"))
    conn.execute(text("ALTER TABLE writer_drafts DROP CONSTRAINT IF EXISTS writer_drafts_project_id_key"))
    conn.execute(text("DROP INDEX IF EXISTS writer_drafts_project_id_key"))
    conn.execute(text("DROP INDEX IF EXISTS ix_writer_drafts_project_id"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_writer_drafts_project_id ON writer_drafts (project_id)"))
    conn.execute(
        text("CREATE UNIQUE INDEX IF NOT EXISTS uq_writer_drafts_project_doc_kind ON writer_drafts (project_id, doc_kind)")
    )
    # ---- SaaS：组织架构与协作 ----
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS department_id VARCHAR"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS custom_role_id VARCHAR"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_credit_limit INTEGER"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP"))
    conn.execute(text("ALTER TABLE project_members ADD COLUMN IF NOT EXISTS project_role VARCHAR DEFAULT '撰写'"))
    conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS department_id VARCHAR"))
    for table in ("knowledge_documents", "qualification_assets", "product_libraries"):
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS department_id VARCHAR"))
    conn.execute(text("ALTER TABLE qualification_assets ADD COLUMN IF NOT EXISTS visibility VARCHAR DEFAULT '企业'"))
    conn.execute(text("ALTER TABLE product_libraries ADD COLUMN IF NOT EXISTS visibility VARCHAR DEFAULT '企业'"))
    # ---- 工程类专业子类与工程类型：水利试点 ----
    conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS specialty VARCHAR DEFAULT ''"))
    conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS work_type VARCHAR DEFAULT ''"))
    # ---- 知识库解析失败修复：扫描进度可续跑，企业库条文补齐判定字段 ----
    conn.execute(text("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS progress_json JSON"))
    conn.execute(text("ALTER TABLE standard_clauses ADD COLUMN IF NOT EXISTS mandatory BOOLEAN DEFAULT FALSE"))
    conn.execute(text("ALTER TABLE standard_clauses ADD COLUMN IF NOT EXISTS is_commentary BOOLEAN DEFAULT FALSE"))
    conn.execute(text("ALTER TABLE standard_clauses ADD COLUMN IF NOT EXISTS topics_json JSON DEFAULT '[]'::json"))
    conn.execute(text("ALTER TABLE standard_clauses ADD COLUMN IF NOT EXISTS table_text TEXT DEFAULT ''"))


def assert_tenant_session(db: Session) -> str:
    tenant_id = db.info.get("tenant_id")
    if not tenant_id:
        raise TenantRequired("该会话不是企业会话")
    return tenant_id
