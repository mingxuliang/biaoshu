from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import Base, SessionLocal, engine
from .routers import auth, documents, knowledge, prereview, projects, revision, tender, writer
from .seed import seed_defaults

settings = get_settings()

Base.metadata.create_all(bind=engine)

with SessionLocal() as _seed_db:
    seed_defaults(_seed_db)

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


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
