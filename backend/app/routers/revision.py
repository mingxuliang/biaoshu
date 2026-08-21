import os
import urllib.parse
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..engines.docx_extract import extract_paragraphs
from ..engines.revision_build import anchor_findings, blocks_to_docx, build_sections
from ..models import BidDocument, BidRevision, BidRevisionVersion, ReviewFinding, ReviewRun
from ..schemas import (
    BidRevisionOut,
    BidRevisionVersionOut,
    CreateVersionIn,
    PatchRevisionContentIn,
    RestoreVersionOut,
)

router = APIRouter(prefix="/api", tags=["revision"])


def _finding_to_issue_dict(f: ReviewFinding) -> dict:
    return {
        "id": f.id,
        "level": f.level,
        "severity": f.severity,
        "location": f.location,
        "excerpt": f.excerpt,
        "rule": f.rule,
        "tenderQuote": f.tender_quote,
        "suggestion": f.suggestion,
    }


def _latest_done_run(db: Session, project_id: str) -> ReviewRun:
    run = (
        db.query(ReviewRun)
        .filter(ReviewRun.project_id == project_id, ReviewRun.status == "done")
        .order_by(ReviewRun.round.desc())
        .first()
    )
    if not run:
        raise HTTPException(404, "该项目暂无已完成的预审记录，请先在「AI 预审中心」完成一次预审")
    return run


def _build_revision_content(db: Session, run: ReviewRun) -> tuple[list[dict], list[dict]]:
    bid_doc = db.get(BidDocument, run.bid_document_id)
    if not bid_doc:
        raise HTTPException(404, "预审对应的投标文件不存在")
    paragraphs = extract_paragraphs(bid_doc.storage_path)
    issues = [_finding_to_issue_dict(f) for f in run.findings]
    sections = build_sections(paragraphs)
    sections = anchor_findings(sections, issues)
    return sections, issues


def _revision_to_out(revision: BidRevision) -> BidRevisionOut:
    return BidRevisionOut(
        id=revision.id,
        projectId=revision.project_id,
        bidDocumentId=revision.bid_document_id,
        reviewRunId=revision.review_run_id,
        sections=revision.sections_json or [],
        issues=revision.issues_json or [],
        contentState=revision.content_state_json,
    )


@router.get("/projects/{project_id}/bid-revision", response_model=BidRevisionOut)
def get_or_create_bid_revision(project_id: str, db: Session = Depends(get_db)) -> BidRevisionOut:
    revision = db.query(BidRevision).filter(BidRevision.project_id == project_id).first()
    if revision:
        return _revision_to_out(revision)

    run = _latest_done_run(db, project_id)
    sections, issues = _build_revision_content(db, run)

    revision = BidRevision(
        project_id=project_id,
        bid_document_id=run.bid_document_id,
        review_run_id=run.id,
        sections_json=sections,
        issues_json=issues,
    )
    db.add(revision)
    db.commit()
    db.refresh(revision)
    return _revision_to_out(revision)


@router.post("/bid-revisions/{revision_id}/regenerate", response_model=BidRevisionOut)
def regenerate_bid_revision(revision_id: str, db: Session = Depends(get_db)) -> BidRevisionOut:
    revision = db.get(BidRevision, revision_id)
    if not revision:
        raise HTTPException(404, "修改闭环草稿不存在")

    run = _latest_done_run(db, revision.project_id)
    sections, issues = _build_revision_content(db, run)

    revision.bid_document_id = run.bid_document_id
    revision.review_run_id = run.id
    revision.sections_json = sections
    revision.issues_json = issues
    revision.content_state_json = None
    db.commit()
    db.refresh(revision)
    return _revision_to_out(revision)


@router.patch("/bid-revisions/{revision_id}/content", response_model=BidRevisionOut)
def autosave_bid_revision_content(
    revision_id: str, payload: PatchRevisionContentIn, db: Session = Depends(get_db)
) -> BidRevisionOut:
    revision = db.get(BidRevision, revision_id)
    if not revision:
        raise HTTPException(404, "修改闭环草稿不存在")
    revision.content_state_json = payload.contentState
    db.commit()
    db.refresh(revision)
    return _revision_to_out(revision)


@router.post("/bid-revisions/{revision_id}/versions", response_model=BidRevisionVersionOut)
def create_bid_revision_version(
    revision_id: str, payload: CreateVersionIn, db: Session = Depends(get_db)
) -> BidRevisionVersionOut:
    revision = db.get(BidRevision, revision_id)
    if not revision:
        raise HTTPException(404, "修改闭环草稿不存在")

    settings = get_settings()
    os.makedirs(settings.upload_dir, exist_ok=True)
    docx_bytes = blocks_to_docx([b.model_dump() for b in payload.blocks])
    stored_name = f"{uuid.uuid4().hex}.docx"
    storage_path = os.path.join(settings.upload_dir, stored_name)
    with open(storage_path, "wb") as f:
        f.write(docx_bytes)

    new_doc = BidDocument(
        project_id=revision.project_id,
        filename=f"投标书修改版-{stored_name}",
        storage_path=storage_path,
        size_bytes=len(docx_bytes),
        source="revision",
    )
    db.add(new_doc)

    existing_count = (
        db.query(BidRevisionVersion).filter(BidRevisionVersion.revision_id == revision.id).count()
    )
    version = BidRevisionVersion(
        revision_id=revision.id,
        label=f"V{existing_count + 1}",
        note=payload.note,
        author=payload.author or "未署名",
        word_count=payload.wordCount,
        content_state_json=payload.contentState,
    )
    db.add(version)
    revision.content_state_json = payload.contentState
    db.commit()
    db.refresh(new_doc)
    db.refresh(version)

    version.bid_document_id = new_doc.id
    db.commit()
    db.refresh(version)

    return BidRevisionVersionOut(
        id=version.id,
        label=version.label,
        note=version.note,
        author=version.author,
        wordCount=version.word_count,
        bidDocumentId=version.bid_document_id,
        createdAt=version.created_at.isoformat(),
    )


@router.get("/bid-revisions/{revision_id}/versions", response_model=list[BidRevisionVersionOut])
def list_bid_revision_versions(revision_id: str, db: Session = Depends(get_db)) -> list[BidRevisionVersionOut]:
    versions = (
        db.query(BidRevisionVersion)
        .filter(BidRevisionVersion.revision_id == revision_id)
        .order_by(BidRevisionVersion.created_at.desc())
        .all()
    )
    return [
        BidRevisionVersionOut(
            id=v.id,
            label=v.label,
            note=v.note,
            author=v.author,
            wordCount=v.word_count,
            bidDocumentId=v.bid_document_id,
            createdAt=v.created_at.isoformat(),
        )
        for v in versions
    ]


@router.post("/bid-revisions/{revision_id}/versions/{version_id}/restore", response_model=RestoreVersionOut)
def restore_bid_revision_version(
    revision_id: str, version_id: str, db: Session = Depends(get_db)
) -> RestoreVersionOut:
    revision = db.get(BidRevision, revision_id)
    if not revision:
        raise HTTPException(404, "修改闭环草稿不存在")
    version = db.get(BidRevisionVersion, version_id)
    if not version or version.revision_id != revision_id:
        raise HTTPException(404, "版本记录不存在")

    revision.content_state_json = version.content_state_json
    db.commit()
    return RestoreVersionOut(contentState=version.content_state_json or {})


@router.get("/bid-revisions/{revision_id}/export")
def export_bid_revision_docx(revision_id: str, db: Session = Depends(get_db)) -> Response:
    revision = db.get(BidRevision, revision_id)
    if not revision:
        raise HTTPException(404, "修改闭环草稿不存在")

    latest_version = (
        db.query(BidRevisionVersion)
        .filter(BidRevisionVersion.revision_id == revision_id, BidRevisionVersion.bid_document_id.isnot(None))
        .order_by(BidRevisionVersion.created_at.desc())
        .first()
    )
    if not latest_version:
        raise HTTPException(400, "暂无已保存的版本，请先点击「保存版本」")

    doc = db.get(BidDocument, latest_version.bid_document_id)
    if not doc or not os.path.exists(doc.storage_path):
        raise HTTPException(404, "导出文件不存在")

    with open(doc.storage_path, "rb") as f:
        content = f.read()

    # 文件名可能含中文，Content-Disposition 头只能是 latin-1，用 RFC 5987 的 filename* 承载 UTF-8 名称
    encoded_name = urllib.parse.quote(doc.filename)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=\"bid-revision.docx\"; filename*=UTF-8''{encoded_name}"},
    )
