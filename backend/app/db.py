from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def ensure_schema() -> None:
    """create_all 不会给已有表加列；给后续新增列做兼容补齐。"""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS disabled BOOLEAN DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE qualification_assets ADD COLUMN IF NOT EXISTS ocr_text TEXT DEFAULT ''"))
        conn.execute(text("ALTER TABLE qualification_assets ADD COLUMN IF NOT EXISTS ocr_status VARCHAR DEFAULT ''"))
        conn.execute(
            text("ALTER TABLE qualification_assets ADD COLUMN IF NOT EXISTS review_status VARCHAR DEFAULT '已入库'")
        )
        conn.execute(
            text("ALTER TABLE qualification_assets ADD COLUMN IF NOT EXISTS merge_status VARCHAR DEFAULT '新增'")
        )
        conn.execute(text("ALTER TABLE qualification_assets ADD COLUMN IF NOT EXISTS aliases_json JSON DEFAULT '[]'::json"))
        conn.execute(text("ALTER TABLE qualification_assets ADD COLUMN IF NOT EXISTS sources_json JSON DEFAULT '[]'::json"))
        conn.execute(text("ALTER TABLE qualification_assets ADD COLUMN IF NOT EXISTS evidence_json JSON DEFAULT '[]'::json"))
        conn.execute(
            text("ALTER TABLE qualification_assets ADD COLUMN IF NOT EXISTS field_conflict_json JSON DEFAULT '[]'::json")
        )
        conn.execute(
            text("ALTER TABLE qualification_assets ADD COLUMN IF NOT EXISTS suspected_ids_json JSON DEFAULT '[]'::json")
        )
        conn.execute(
            text(
                "ALTER TABLE writer_drafts ADD COLUMN IF NOT EXISTS selected_product_library_id VARCHAR"
            )
        )
        conn.execute(text("ALTER TABLE product_features ADD COLUMN IF NOT EXISTS parent_id VARCHAR"))
        conn.execute(text("ALTER TABLE knowledge_slices ADD COLUMN IF NOT EXISTS parent_id VARCHAR"))
        conn.execute(text("ALTER TABLE knowledge_slices ADD COLUMN IF NOT EXISTS level VARCHAR DEFAULT '一级'"))
        conn.execute(text("ALTER TABLE veto_rules ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE"))
        conn.execute(text("ALTER TABLE catalog_rules ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE"))
        conn.execute(text("ALTER TABLE bid_revisions ADD COLUMN IF NOT EXISTS layout_json JSON"))
        conn.execute(text("ALTER TABLE bid_revisions ADD COLUMN IF NOT EXISTS resolved_ids_json JSON DEFAULT '[]'::json"))
        conn.execute(
            text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS category VARCHAR DEFAULT '软件服务类'")
        )
        conn.execute(text("UPDATE projects SET category = '软件服务类' WHERE category IS NULL"))
        conn.execute(
            text("ALTER TABLE review_runs ADD COLUMN IF NOT EXISTS tech_modules_json JSON DEFAULT '[]'::json")
        )
        conn.execute(
            text("ALTER TABLE review_runs ADD COLUMN IF NOT EXISTS tender_rules_json JSON DEFAULT '{}'::json")
        )
        conn.execute(
            text("ALTER TABLE review_runs ADD COLUMN IF NOT EXISTS custom_rules_json JSON DEFAULT '[]'::json")
        )
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
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_bid_revisions_project_scope "
                "ON bid_revisions (project_id, scope)"
            )
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
