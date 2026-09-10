from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pathlib import Path
from sqlalchemy.orm import Session

from ..audit import actor_from_request, project_label, write_audit
from ..auth import get_current_user
from ..db import get_db
from ..engines.bid_kind import BOOKLET_LEVELS, SCOPE_BUSINESS, SCOPE_TECH, normalize_scope
from ..engines.docx_extract import extract_paragraphs
from ..engines.revision_build import (
    anchor_findings,
    build_sections,
    clear_problems,
    patch_docx_paragraph,
    writeback_docx,
)
from ..engines.excerpt_guard import chapter_from_location, display_rule, source_visible_text, split_bid_and_tender
from ..engines.e_business_vision import is_transport_stub_finding
from ..engines.revision_suggest import (
    apply_text_to_paragraph,
    enrich_issue,
    fallback_suggestion,
    heuristic_apply_text,
    llm_rewrite_paragraph,
    llm_write_suggestion,
    patch_lexical_text,
    strip_strategy_overlay,
)
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
    extra = f.evidence_json if isinstance(f.evidence_json, dict) else {}
    excerpt, quote = split_bid_and_tender(f.excerpt or "", f.tender_quote or "", f.rule or "")
    excerpt = source_visible_text(excerpt) or excerpt
    return enrich_issue(
        {
            "id": f.id,
            "level": f.level,
            "severity": f.severity,
            "location": chapter_from_location(f.location or ""),
            "excerpt": excerpt,
            "rule": display_rule(f.rule or "", f.suggestion or "", extra.get("strategyKey") or ""),
            "tenderQuote": quote,
            "suggestion": f.suggestion or "",
            "applyText": extra.get("applyText") or "",
            "strategyKey": extra.get("strategyKey") or "",
        }
    )


def _enrich_stored_issues(raw_issues: list) -> list[dict]:
    return [enrich_issue(dict(item)) for item in raw_issues if isinstance(item, dict)]


def _reanchor_sections(sections: list[dict], issues: list[dict]) -> list[dict]:
    clear_problems(sections)
    return anchor_findings(sections, issues)


def _latest_done_run(db: Session, project_id: str, scope: str | None = None) -> ReviewRun:
    q = db.query(ReviewRun).filter(ReviewRun.project_id == project_id, ReviewRun.status == "done")
    if scope in (SCOPE_BUSINESS, SCOPE_TECH):
        run = q.filter(ReviewRun.scope == scope).order_by(
            ReviewRun.round.desc(), ReviewRun.finished_at.desc(), ReviewRun.started_at.desc()
        ).first()
        if run:
            return run
        full = q.filter(ReviewRun.scope == "full").order_by(
            ReviewRun.round.desc(), ReviewRun.finished_at.desc(), ReviewRun.started_at.desc()
        ).first()
        if full:
            return full
        label = "技术标" if scope == SCOPE_TECH else "商务标"
        raise HTTPException(404, f"该项目暂无已完成的{label}预审，请先在「AI 预审中心」完成该分册预审")
    run = q.order_by(ReviewRun.round.desc(), ReviewRun.finished_at.desc(), ReviewRun.started_at.desc()).first()
    if not run:
        raise HTTPException(404, "该项目暂无已完成的预审记录，请先在「AI 预审中心」完成一次预审")
    return run


def _findings_for_scope(run: ReviewRun, scope: str) -> list[ReviewFinding]:
    rows = list(run.findings or [])
    if scope in BOOKLET_LEVELS and (getattr(run, "scope", None) or "full") == "full":
        keys = set(BOOKLET_LEVELS[scope])
        rows = [f for f in rows if (f.level or "") in keys]
    return rows


def _revision_kind(revision: BidRevision) -> str:
    raw = (getattr(revision, "scope", None) or SCOPE_BUSINESS).strip().lower()
    return raw if raw in (SCOPE_BUSINESS, SCOPE_TECH) else SCOPE_BUSINESS


def _revision_filename(revision: BidRevision, suffix: str) -> str:
    label = "技术标" if _revision_kind(revision) == SCOPE_TECH else "商务标"
    return f"{label}{suffix}"


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


def _build_revision_content(db: Session, run: ReviewRun, scope: str) -> tuple[list[dict], list[dict], dict]:
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
    issues = [
        _finding_to_issue_dict(f)
        for f in _findings_for_scope(run, scope)
        if not is_transport_stub_finding(f.location or "", f.suggestion or "")
    ]
    _SEV = {"废标": 0, "降档": 1, "扣分": 2, "建议": 3}
    issues.sort(key=lambda x: _SEV.get(x.get("severity") or "", 9))
    sections = build_sections(paragraphs)
    sections = anchor_findings(sections, issues)
    return sections, issues, layout


def _revision_to_out(
    revision: BidRevision,
    run: ReviewRun | None = None,
    run_switched: bool = False,
    db: Session | None = None,
) -> BidRevisionOut:
    resolved = [x for x in (revision.resolved_ids_json or []) if isinstance(x, str)]
    resolved_set = set(resolved)
    issues = []
    for raw in revision.issues_json or []:
        item = dict(raw)
        item["resolved"] = item.get("id") in resolved_set
        issues.append(item)
    source_id = (run.bid_document_id if run is not None else "") or revision.bid_document_id
    source_name = ""
    if db is not None and source_id:
        src = db.get(BidDocument, source_id)
        if src:
            source_name = src.filename or ""
    return BidRevisionOut(
        id=revision.id,
        projectId=revision.project_id,
        scope=_revision_kind(revision),
        bidDocumentId=revision.bid_document_id,
        sourceBidDocumentId=source_id,
        sourceFileName=source_name,
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
    project_id: str,
    scope: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BidRevisionOut:
    require_project(db, current_user, project_id, PERM_WRITER)
    booklet = normalize_scope(scope, SCOPE_BUSINESS)
    if booklet not in (SCOPE_BUSINESS, SCOPE_TECH):
        booklet = SCOPE_BUSINESS
    run = _latest_done_run(db, project_id, booklet)
    revision = (
        db.query(BidRevision)
        .filter(BidRevision.project_id == project_id, BidRevision.scope == booklet)
        .first()
    )
    sections, issues, layout = _build_revision_content(db, run, booklet)
    switched = False
    if revision:
        switched = _sync_revision_to_run(revision, run, sections, issues, layout)
        db.commit()
        db.refresh(revision)
        return _revision_to_out(revision, run, switched, db)

    revision = BidRevision(
        project_id=project_id,
        scope=booklet,
        bid_document_id=run.bid_document_id,
        review_run_id=run.id,
        sections_json=sections,
        issues_json=issues,
        layout_json=layout,
    )
    db.add(revision)
    db.commit()
    db.refresh(revision)
    return _revision_to_out(revision, run, db=db)


@router.post("/bid-revisions/{revision_id}/regenerate", response_model=BidRevisionOut)
def regenerate_bid_revision(
    revision_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BidRevisionOut:
    revision = _require_revision(db, current_user, revision_id)

    booklet = _revision_kind(revision)
    run = _latest_done_run(db, revision.project_id, booklet)
    sections, issues, layout = _build_revision_content(db, run, booklet)
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
    return _revision_to_out(revision, run, switched, db)


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
    return _revision_to_out(revision, db=db)


@router.post("/bid-revisions/{revision_id}/issues/{issue_id}/apply", response_model=BidRevisionOut)
def apply_issue_suggestion(
    revision_id: str,
    issue_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BidRevisionOut:
    """把该条 AI 整改建议写回正文段落（跳过目录），并尽量同步编辑器状态与工作稿。"""
    revision = _require_revision(db, current_user, revision_id)
    issues = _enrich_stored_issues(revision.issues_json or [])
    issue = next((i for i in issues if i.get("id") == issue_id), None)
    if not issue:
        raise HTTPException(404, "问题项不存在")

    sections = _reanchor_sections(list(revision.sections_json or []), issues)
    target = None
    for sec in sections:
        if sec.get("isToc"):
            continue
        for para in sec.get("paragraphs") or []:
            problem = para.get("problem") or {}
            if problem.get("issueId") == issue_id and not para.get("isToc"):
                target = para
                break
        if target:
            break
    if not target:
        raise HTTPException(400, "未能定位到正文段落（锚点不在目录或该条为全篇级检查），请在原文中核对后手工修改源文件")

    old_text = target.get("text") or ""
    old_highlight = (target.get("problem") or {}).get("highlight") or issue.get("excerpt") or ""
    suggestion = strip_strategy_overlay(issue.get("suggestion") or "")
    if len(suggestion) < 8:
        suggestion = llm_write_suggestion(issue) or fallback_suggestion(issue)
        issue["suggestion"] = suggestion
    apply_text = (issue.get("applyText") or "").strip() or heuristic_apply_text(old_highlight, suggestion)
    new_text = apply_text_to_paragraph(old_text, old_highlight, suggestion, apply_text)
    if new_text.strip() == old_text.strip() or not new_text.strip():
        rewritten = llm_rewrite_paragraph(old_text, old_highlight, suggestion, issue)
        if rewritten:
            new_text = rewritten
    if not new_text.strip() or new_text.strip() == old_text.strip():
        raise HTTPException(400, "未能生成可写入原文的改写句，请核对建议后手工修改源文件")

    target["text"] = new_text
    new_highlight = apply_text if apply_text and apply_text in new_text else new_text
    target["problem"] = {"issueId": issue_id, "highlight": new_highlight}
    issue["applyText"] = apply_text or new_highlight
    issue["excerpt"] = new_highlight if new_highlight in new_text else issue.get("excerpt") or new_highlight

    if isinstance(revision.content_state_json, dict):
        state = revision.content_state_json
        if not patch_lexical_text(state, old_highlight, new_highlight if new_highlight in new_text else new_text):
            patch_lexical_text(state, old_text, new_text)
        revision.content_state_json = state

    resolved = [x for x in (revision.resolved_ids_json or []) if isinstance(x, str)]
    if issue_id not in resolved:
        resolved.append(issue_id)
    revision.resolved_ids_json = resolved
    revision.sections_json = sections
    revision.issues_json = issues

    base_doc = db.get(BidDocument, revision.bid_document_id)
    if base_doc and storage.exists(base_doc.storage_path):
        try:
            with storage.as_local(base_doc.storage_path) as path:
                docx_bytes = patch_docx_paragraph(path, old_text, new_text)
            key = storage.put_bytes(f"bid-documents/{revision.project_id}", docx_bytes, ".docx")
            new_doc = BidDocument(
                project_id=revision.project_id,
                filename=_revision_filename(revision, "修改稿.docx"),
                storage_path=key,
                size_bytes=len(docx_bytes),
                source="revision",
                kind=_revision_kind(revision),
            )
            db.add(new_doc)
            db.flush()
            revision.bid_document_id = new_doc.id
        except Exception:
            pass

    write_audit(
        db,
        action="改写接受",
        user_name=actor_from_request(db, request),
        target=project_label(db, revision.project_id),
        version="—",
        detail=f"已将问题 {issue_id} 的整改建议写入正文",
    )
    db.commit()
    db.refresh(revision)
    run = db.get(ReviewRun, revision.review_run_id)
    return _revision_to_out(revision, run, db=db)


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
    return _revision_to_out(revision, run, db=db)


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
        if base_doc and storage.exists(base_doc.storage_path):
            docx_bytes = storage.get_bytes(base_doc.storage_path)
        else:
            raise HTTPException(400, "没有可保存的原文，请确认已上传投标文件")
    key = storage.put_bytes(f"bid-documents/{revision.project_id}", docx_bytes, ".docx")

    new_doc = BidDocument(
        project_id=revision.project_id,
        filename=_revision_filename(revision, "修改版.docx"),
        storage_path=key,
        size_bytes=len(docx_bytes),
        source="revision",
        kind=_revision_kind(revision),
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
