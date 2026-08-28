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
        conn.execute(
            text(
                "UPDATE qualification_assets SET kind = 'cert' "
                "WHERE kind = 'credit' AND ("
                "name ~ '荣誉|奖状|获奖' OR coalesce(detail, '') ~ '荣誉|奖状|获奖')"
            )
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
