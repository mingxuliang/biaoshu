from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pathlib import Path
from sqlalchemy.orm import Session

from ..audit import actor_from_request, project_label, write_audit
from ..auth import get_current_user
from ..db import get_db
from ..engines.docx_extract import extract_paragraphs
from ..engines.revision_build import anchor_findings, blocks_to_docx, build_sections, writeback_docx
from ..engines.tender_style import extract_bid_typography
from ..models import BidDocument, BidRevision, BidRevisionVersion, ReviewFinding, ReviewRun, User
from ..permissions import PERM_WRITER, require_project
from .. import storage
from ..schemas import (
    BidRevisionOut,
    BidRevisionVersionOut,
    CreateVersionIn,
    PatchIssueResolvedIn,
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
        .order_by(ReviewRun.round.desc(), ReviewRun.finished_at.desc(), ReviewRun.started_at.desc())
        .first()
    )
    if not run:
        raise HTTPException(404, "该项目暂无已完成的预审记录，请先在「AI 预审中心」完成一次预审")
    return run


def _sync_revision_to_run(revision: BidRevision, run: ReviewRun, sections: list[dict], issues: list[dict], layout: dict) -> bool:
    """把修改闭环草稿对齐到指定预审轮次。换轮次时清掉旧编辑器状态与已修复标记。"""
    switched = revision.review_run_id != run.id
    revision.bid_document_id = run.bid_document_id
    revision.review_run_id = run.id
    revision.sections_json = sections
    revision.issues_json = issues
    revision.layout_json = layout
    if switched:
        revision.content_state_json = None
        revision.resolved_ids_json = []
    else:
        keep = {i.get("id") for i in issues if i.get("id")}
        revision.resolved_ids_json = [x for x in (revision.resolved_ids_json or []) if x in keep]
    return switched


def _build_revision_content(db: Session, run: ReviewRun) -> tuple[list[dict], list[dict], dict]:
    bid_doc = db.get(BidDocument, run.bid_document_id)
    if not bid_doc:
        raise HTTPException(404, "预审对应的投标文件不存在")
    try:
        with storage.as_local(bid_doc.storage_path) as path:
            paragraphs = extract_paragraphs(path)
            try:
                layout = extract_bid_typography(path)
            except Exception:
                layout = {}
    except FileNotFoundError:
        raise HTTPException(404, "预审对应的投标文件不存在")
    issues = [_finding_to_issue_dict(f) for f in run.findings]
    _SEV = {"废标": 0, "降档": 1, "扣分": 2, "建议": 3}
    issues.sort(key=lambda x: _SEV.get(x.get("severity") or "", 9))
    sections = build_sections(paragraphs)
    sections = anchor_findings(sections, issues)
    return sections, issues, layout


def _revision_to_out(revision: BidRevision, run: ReviewRun | None = None, run_switched: bool = False) -> BidRevisionOut:
    resolved = [x for x in (revision.resolved_ids_json or []) if isinstance(x, str)]
    resolved_set = set(resolved)
    issues = []
    for raw in revision.issues_json or []:
        item = dict(raw)
        item["resolved"] = item.get("id") in resolved_set
        issues.append(item)
    return BidRevisionOut(
        id=revision.id,
        projectId=revision.project_id,
        bidDocumentId=revision.bid_document_id,
        reviewRunId=revision.review_run_id,
        reviewRound=run.round if run is not None else None,
        sections=revision.sections_json or [],
        issues=issues,
        contentState=revision.content_state_json,
        layout=revision.layout_json,
        resolvedIds=resolved,
        runSwitched=run_switched,
    )


def _require_revision(db, user: User, revision_id: str) -> BidRevision:
    revision = db.get(BidRevision, revision_id)
    if not revision:
        raise HTTPException(404, "修改闭环草稿不存在")
    require_project(db, user, revision.project_id, PERM_WRITER)
    return revision


@router.get("/projects/{project_id}/bid-revision", response_model=BidRevisionOut)
def get_or_create_bid_revision(
    project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> BidRevisionOut:
    require_project(db, current_user, project_id, PERM_WRITER)
    run = _latest_done_run(db, project_id)
    sections, issues, layout = _build_revision_content(db, run)

    revision = db.query(BidRevision).filter(BidRevision.project_id == project_id).first()
    switched = False
    if revision:
        switched = _sync_revision_to_run(revision, run, sections, issues, layout)
        db.commit()
        db.refresh(revision)
        return _revision_to_out(revision, run, switched)

    revision = BidRevision(
        project_id=project_id,
        bid_document_id=run.bid_document_id,
        review_run_id=run.id,
        sections_json=sections,
        issues_json=issues,
        layout_json=layout,
    )
    db.add(revision)
    db.commit()
    db.refresh(revision)
    return _revision_to_out(revision, run)


@router.post("/bid-revisions/{revision_id}/regenerate", response_model=BidRevisionOut)
def regenerate_bid_revision(
    revision_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BidRevisionOut:
    revision = _require_revision(db, current_user, revision_id)

    run = _latest_done_run(db, revision.project_id)
    sections, issues, layout = _build_revision_content(db, run)
    switched = _sync_revision_to_run(revision, run, sections, issues, layout)
    revision.content_state_json = None
    revision.resolved_ids_json = []
    write_audit(
        db,
        action="AI 改写",
        user_name=actor_from_request(db, request),
        target=project_label(db, revision.project_id),
        version="—",
        detail=f"根据第 {run.round} 轮预审结果重新生成对照稿，待编写人确认",
    )
    db.commit()
    db.refresh(revision)
    return _revision_to_out(revision, run, switched)


@router.patch("/bid-revisions/{revision_id}/content", response_model=BidRevisionOut)
def autosave_bid_revision_content(
    revision_id: str,
    payload: PatchRevisionContentIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BidRevisionOut:
    revision = _require_revision(db, current_user, revision_id)
    revision.content_state_json = payload.contentState
    db.commit()
    db.refresh(revision)
    return _revision_to_out(revision)


@router.patch("/bid-revisions/{revision_id}/issues/{issue_id}/resolve", response_model=BidRevisionOut)
def patch_issue_resolved(
    revision_id: str,
    issue_id: str,
    payload: PatchIssueResolvedIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BidRevisionOut:
    revision = _require_revision(db, current_user, revision_id)
    known = {i.get("id") for i in (revision.issues_json or []) if i.get("id")}
    if issue_id not in known:
        raise HTTPException(404, "问题项不存在")
    resolved = [x for x in (revision.resolved_ids_json or []) if isinstance(x, str)]
    if payload.resolved and issue_id not in resolved:
        resolved.append(issue_id)
    if not payload.resolved:
        resolved = [x for x in resolved if x != issue_id]
    revision.resolved_ids_json = resolved
    db.commit()
    db.refresh(revision)
    run = db.get(ReviewRun, revision.review_run_id)
    return _revision_to_out(revision, run)


@router.post("/bid-revisions/{revision_id}/versions", response_model=BidRevisionVersionOut)
def create_bid_revision_version(
    revision_id: str,
    payload: CreateVersionIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BidRevisionVersionOut:
    revision = _require_revision(db, current_user, revision_id)

    blocks = [b.model_dump() for b in payload.blocks]
    docx_bytes: bytes | None = None
    base_doc = db.get(BidDocument, revision.bid_document_id)
    if base_doc and storage.exists(base_doc.storage_path):
        try:
            with storage.as_local(base_doc.storage_path) as path:
                if blocks:
                    docx_bytes = writeback_docx(path, blocks)
                else:
                    docx_bytes = Path(path).read_bytes()
        except Exception:
            docx_bytes = None
    if docx_bytes is None:
        if not blocks:
            raise HTTPException(400, "没有可保存的正文，请先在「改写」中编辑或保留原文后重试")
        docx_bytes = blocks_to_docx(blocks)
    key = storage.put_bytes(f"bid-documents/{revision.project_id}", docx_bytes, ".docx")

    new_doc = BidDocument(
        project_id=revision.project_id,
        filename="投标书修改版.docx",
        storage_path=key,
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
    write_audit(
        db,
        action="改写接受",
        user_name=actor_from_request(db, request),
        target=project_label(db, revision.project_id),
        version=version.label,
        detail=payload.note or f"保存修改版本 {version.label}，作者：{version.author}",
    )
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
def list_bid_revision_versions(
    revision_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[BidRevisionVersionOut]:
    _require_revision(db, current_user, revision_id)
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
    revision_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RestoreVersionOut:
    revision = _require_revision(db, current_user, revision_id)
    version = db.get(BidRevisionVersion, version_id)
    if not version or version.revision_id != revision_id:
        raise HTTPException(404, "版本记录不存在")

    revision.content_state_json = version.content_state_json
    db.commit()
    return RestoreVersionOut(contentState=version.content_state_json or {})


@router.get("/bid-revisions/{revision_id}/export")
def export_bid_revision_docx(
    revision_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> Response:
    revision = _require_revision(db, current_user, revision_id)

    latest_version = (
        db.query(BidRevisionVersion)
        .filter(BidRevisionVersion.revision_id == revision_id, BidRevisionVersion.bid_document_id.isnot(None))
        .order_by(BidRevisionVersion.created_at.desc())
        .first()
    )
    if not latest_version:
        raise HTTPException(400, "暂无已保存的版本，请先点击「保存版本」")

    doc = db.get(BidDocument, latest_version.bid_document_id)
    if not doc or not storage.exists(doc.storage_path):
        raise HTTPException(404, "导出文件不存在")
    try:
        return storage.http_response(doc.storage_path, filename=doc.filename)
    except FileNotFoundError:
        raise HTTPException(404, "导出文件不存在")
