from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import Base, SessionLocal, engine, ensure_schema
from .routers import (
    auditlog,
    auth,
    documents,
    export,
    knowledge,
    prereview,
    products,
    projects,
    qualifications,
    revision,
    rules,
    tender,
    users,
    writer,
)
from .seed import purge_demo_data, seed_defaults, seed_rules

settings = get_settings()

Base.metadata.create_all(bind=engine)
ensure_schema()

with SessionLocal() as _seed_db:
    purge_demo_data(_seed_db)
    seed_defaults(_seed_db)
    seed_rules(_seed_db)

app = FastAPI(title="智标云 AI 预审引擎")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(documents.router)
app.include_router(prereview.router)
app.include_router(tender.router)
app.include_router(writer.router)
app.include_router(revision.router)
app.include_router(knowledge.router)
app.include_router(products.router)
app.include_router(export.router)
app.include_router(rules.router)
app.include_router(users.router)
app.include_router(qualifications.router)
app.include_router(auditlog.router)


@app.on_event("startup")
def _ensure_object_storage() -> None:
    from .storage import ensure_ready

    ensure_ready()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
