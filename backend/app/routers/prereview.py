from datetime import datetime
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..audit import actor_from_request, project_label, write_audit
from ..auth import get_current_user
from ..db import get_db
from .. import storage
from ..engines import e_tender_score, rules_config
from ..engines.excerpt_guard import chapter_from_location, display_rule, split_bid_and_tender
from ..engines.e_business_vision import is_transport_stub_finding
from ..engines.docx_extract import extract_document_plain_text, extract_full_text, extract_paragraphs
from ..engines.bid_kind import filter_tender_rules, normalize_kind, normalize_scope, project_booklet_payload, booklet_overall, BOOKLET_LEVELS
from ..engines.review_export import review_run_to_docx
from ..models import BidDocument, Project, ReviewFinding, ReviewRun, User
from ..permissions import PERM_REVIEW, require_project
from ..schemas import CreateJobIn, JobStatusOut, ReviewReportOut, ReviewReportPairOut, TrendPointOut
from ..tasks import run_prereview_task

router = APIRouter(prefix="/api", tags=["prereview"])

_SEVERITIES = {"废标", "降档", "扣分", "建议"}


def _finding_to_issue(f: ReviewFinding) -> dict:
    severity = f.severity if f.severity in _SEVERITIES else "建议"
    excerpt, quote = split_bid_and_tender(f.excerpt or "", f.tender_quote or "", f.rule or "")
    extra = f.evidence_json if isinstance(f.evidence_json, dict) else {}
    return {
        "id": f.id,
        "level": f.level or "",
        "severity": severity,
        "location": chapter_from_location(f.location or ""),
        "excerpt": excerpt,
        "rule": display_rule(f.rule or "", f.suggestion or "", str(extra.get("strategyKey") or "")),
        "tenderQuote": quote,
        "suggestion": f.suggestion or "",
        "strategyKey": str(extra.get("strategyKey") or ""),
    }


@router.post("/projects/{project_id}/prereview-jobs", response_model=JobStatusOut)
def create_prereview_job(
    project_id: str,
    payload: CreateJobIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobStatusOut:
    require_project(db, current_user, project_id, PERM_REVIEW)
    doc = db.get(BidDocument, payload.bid_document_id)
    if not doc:
        raise HTTPException(404, "投标文件不存在，请重新选择/上传")
    if doc.project_id != project_id:
        raise HTTPException(404, "投标文件不属于该项目")

    kind = normalize_kind(getattr(doc, "kind", None), doc.filename)
    scope = normalize_scope(payload.scope, kind)
    if scope == "full":
        raise HTTPException(400, "请分别发起商务标或技术标预审，系统不再做综合评分")

    last_round = (
        db.query(func.max(ReviewRun.round))
        .filter(ReviewRun.project_id == project_id, ReviewRun.scope == scope)
        .scalar()
    ) or 0

    run = ReviewRun(
        project_id=project_id,
        bid_document_id=doc.id,
        round=last_round + 1,
        status="queued",
        scope=scope,
        started_at=datetime.utcnow(),
    )
    db.add(run)
    scope_label = {"business": "商务标", "tech": "技术标", "full": "合订全量"}.get(scope) or scope
    write_audit(
        db,
        action="发起预审",
        user_name=actor_from_request(db, request),
        target=f"{project_label(db, project_id)}（{scope_label}第 {run.round} 轮）",
        version="—",
        detail=f"{scope_label}预审，文件：{doc.filename}",
    )
    db.commit()
    db.refresh(run)

    run_prereview_task.delay(run.id)

    return JobStatusOut(job_id=run.id, status=run.status, round=run.round)


@router.get("/prereview-jobs/{job_id}", response_model=JobStatusOut)
def get_job_status(
    job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> JobStatusOut:
    run = db.get(ReviewRun, job_id)
    if not run:
        raise HTTPException(404, "任务不存在")
    require_project(db, current_user, run.project_id)
    return JobStatusOut(job_id=run.id, status=run.status, round=run.round, error=run.error_message)


@router.get("/projects/{project_id}/review-runs/latest-pair", response_model=ReviewReportPairOut)
def get_latest_review_pair(
    project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> ReviewReportPairOut:
    require_project(db, current_user, project_id)
    return ReviewReportPairOut(
        business=_booklet_report(db, project_id, "business"),
        tech=_booklet_report(db, project_id, "tech"),
        full=None,
    )


@router.get("/projects/{project_id}/review-runs/latest", response_model=ReviewReportOut)
def get_latest_review_run(
    project_id: str,
    scope: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReviewReportOut:
    require_project(db, current_user, project_id)
    if scope in ("business", "tech"):
        report = _booklet_report(db, project_id, scope)
        if not report:
            raise HTTPException(404, "该项目暂无已完成的预审报告")
        return report
    run = _latest_done_run(db, project_id, scope)
    return _run_to_report(db, run)


@router.get("/projects/{project_id}/review-runs", response_model=list[TrendPointOut])
def list_review_runs(
    project_id: str,
    scope: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TrendPointOut]:
    require_project(db, current_user, project_id)
    q = db.query(ReviewRun).filter(ReviewRun.project_id == project_id, ReviewRun.status == "done")
    if scope in ("business", "tech"):
        q = q.filter(ReviewRun.scope.in_([scope, "full"]))
    elif scope == "full":
        q = q.filter(ReviewRun.scope == "full")
    runs = q.order_by(ReviewRun.scope.asc(), ReviewRun.round.asc()).all()
    points: list[TrendPointOut] = []
    for r in runs:
        run_scope = getattr(r, "scope", None) or "full"
        if run_scope == "full" and scope not in ("business", "tech", "full"):
            levels = r.levels_json or []
            for booklet in ("business", "tech"):
                overall = booklet_overall(levels, booklet)
                keys = set(BOOKLET_LEVELS[booklet])
                issues_n = sum(int(lv.get("issues") or 0) for lv in levels if isinstance(lv, dict) and lv.get("key") in keys)
                points.append(TrendPointOut(round=r.round, score=overall, issues=issues_n, scope=booklet))
            continue
        if run_scope == "full" and scope in ("business", "tech"):
            overall = booklet_overall(r.levels_json or [], scope)
            keys = set(BOOKLET_LEVELS[scope])
            issues_n = sum(int(lv.get("issues") or 0) for lv in (r.levels_json or []) if isinstance(lv, dict) and lv.get("key") in keys)
            points.append(TrendPointOut(round=r.round, score=overall, issues=issues_n, scope=scope))
            continue
        points.append(
            TrendPointOut(
                round=r.round,
                score=r.overall,
                issues=(r.waste + r.risk + r.suggest),
                scope=run_scope,
            )
        )
    return points


def _backfill_tender_rules(db: Session, run: ReviewRun) -> dict:
    """旧轮次没有招标规则报告时，用已锁定/最新解析结果 + 投标书正文补算并落库。"""
    checklist = rules_config.load_project_checklist(db, run.project_id)
    if not checklist.score_rules and not checklist.dimensions:
        return {}
    text = ""
    headings: list[str] = []
    doc = db.get(BidDocument, run.bid_document_id) if run.bid_document_id else None
    if doc and doc.storage_path and storage.exists(doc.storage_path):
        try:
            with storage.as_local(doc.storage_path) as path:
                try:
                    paras = extract_paragraphs(path)
                    headings = [(p.get("text") or "") for p in paras]
                except Exception:
                    paras = []
                try:
                    text = extract_document_plain_text(path)
                except Exception:
                    text = extract_full_text(path)
        except Exception:
            text = ""
    strategy_keys = rules_config.load_enabled_catalog_keys(db, "strategy")
    report = e_tender_score.run(
        text,
        checklist.score_rules,
        checklist.dimensions,
        headings=headings,
        strategy_keys=strategy_keys,
    )
    report = filter_tender_rules(report, getattr(run, "scope", None) or "full")
    run.tender_rules_json = report
    db.commit()
    return report


def _latest_done_run(db: Session, project_id: str, scope: str | None = None, *, required: bool = True) -> ReviewRun | None:
    q = db.query(ReviewRun).filter(ReviewRun.project_id == project_id, ReviewRun.status == "done")
    if scope in ("business", "tech", "full"):
        q = q.filter(ReviewRun.scope == scope)
    run = q.order_by(ReviewRun.round.desc(), ReviewRun.finished_at.desc()).first()
    if not run and required:
        raise HTTPException(404, "该项目暂无已完成的预审报告")
    return run


def _issues_from_findings(findings) -> list[dict]:
    return [
        _finding_to_issue(f)
        for f in findings
        if not is_transport_stub_finding(f.location or "", f.suggestion or "")
    ]


def _run_to_report(db: Session, run: ReviewRun, as_scope: str | None = None) -> ReviewReportOut:
    tender_rules = run.tender_rules_json or {}
    if not (isinstance(tender_rules, dict) and tender_rules.get("groups")):
        tender_rules = _backfill_tender_rules(db, run)
    issues = _issues_from_findings(db.query(ReviewFinding).filter(ReviewFinding.run_id == run.id).all())
    light = run.light if run.light in ("绿", "橙", "红") else "橙"
    payload = {
        "round": run.round,
        "overall": run.overall,
        "waste": run.waste,
        "risk": run.risk,
        "suggest": run.suggest,
        "light": light,
        "scope": getattr(run, "scope", None) or "full",
        "levels": run.levels_json or [],
        "dimensions": run.dimensions_json or [],
        "techModules": run.tech_modules_json or [],
        "tenderRules": tender_rules or None,
        "issues": issues,
    }
    run_scope = payload["scope"]
    if as_scope in ("business", "tech") and run_scope == "full":
        payload = project_booklet_payload(payload, as_scope)
    return ReviewReportOut(**payload)


def _booklet_report(db: Session, project_id: str, scope: str) -> ReviewReportOut | None:
    run = _latest_done_run(db, project_id, scope, required=False)
    if run:
        return _run_to_report(db, run)
    full = _latest_done_run(db, project_id, "full", required=False)
    if full:
        return _run_to_report(db, full, as_scope=scope)
    return None


def _report_or_none(db: Session, run: ReviewRun | None) -> ReviewReportOut | None:
    if not run:
        return None
    return _run_to_report(db, run)


def _findings_as_issue_dicts(db: Session, run_id: str) -> list[dict]:
    findings = db.query(ReviewFinding).filter(ReviewFinding.run_id == run_id).all()
    return _issues_from_findings(findings)


@router.get("/projects/{project_id}/review-runs/latest/export")
def export_latest_review_report(
    project_id: str,
    request: Request,
    scope: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    require_project(db, current_user, project_id)
    export_scope = scope if scope in ("business", "tech") else None
    if not export_scope:
        raise HTTPException(400, "请指定商务标或技术标分册后再导出，系统不再导出综合评分报告")
    run = _latest_done_run(db, project_id, export_scope, required=False)
    if not run:
        run = _latest_done_run(db, project_id, "full", required=False)
    if not run:
        raise HTTPException(404, "该项目暂无已完成的预审报告")
    project = db.get(Project, project_id)
    issues = _findings_as_issue_dicts(db, run.id)
    payload = {
        "overall": run.overall or 0,
        "light": run.light or "",
        "waste": run.waste or 0,
        "risk": run.risk or 0,
        "suggest": run.suggest or 0,
        "levels": run.levels_json or [],
        "dimensions": run.dimensions_json or [],
        "techModules": run.tech_modules_json or [],
        "issues": issues,
        "scope": getattr(run, "scope", None) or "full",
    }
    payload = project_booklet_payload(payload, export_scope)
    run_scope = export_scope
    docx_bytes = review_run_to_docx(
        project_name=project.name if project else "",
        project_code=project.code if project else "",
        round_no=run.round,
        overall=payload["overall"],
        light=payload["light"],
        waste=payload["waste"],
        risk=payload["risk"],
        suggest=payload["suggest"],
        levels=payload["levels"],
        dimensions=payload.get("dimensions") or [],
        issues=payload["issues"],
        tech_modules=payload.get("techModules") or [],
        finished_at=run.finished_at,
        scope=run_scope,
    )
    scope_label = {"business": "商务标", "tech": "技术标", "full": "全量"}.get(run_scope) or run_scope
    write_audit(
        db,
        action="导出预审报告",
        user_name=actor_from_request(db, request),
        target=f"{project_label(db, project_id)}（{scope_label}第 {run.round} 轮）",
        version=f"第 {run.round} 轮",
        detail=f"导出{scope_label}预审报告 Word，共 {len(payload['issues'])} 项问题",
    )
    db.commit()
    code = (project.code if project else "") or "prereview"
    encoded_name = urllib.parse.quote(f"{code}-{scope_label}-第{run.round}轮-预审报告.docx")
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=\"prereview-report.docx\"; filename*=UTF-8''{encoded_name}"
        },
    )
