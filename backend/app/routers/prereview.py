from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import BidDocument, ReviewFinding, ReviewRun
from ..schemas import CreateJobIn, JobStatusOut, ReviewReportOut, TrendPointOut
from ..tasks import run_prereview_task

router = APIRouter(prefix="/api", tags=["prereview"])


@router.post("/projects/{project_id}/prereview-jobs", response_model=JobStatusOut)
def create_prereview_job(project_id: str, payload: CreateJobIn, db: Session = Depends(get_db)) -> JobStatusOut:
    doc = db.get(BidDocument, payload.bid_document_id)
    if not doc:
        raise HTTPException(404, "投标文件不存在，请重新选择/上传")

    last_round = (
        db.query(func.max(ReviewRun.round)).filter(ReviewRun.project_id == project_id).scalar()
    ) or 0

    run = ReviewRun(
        project_id=project_id,
        bid_document_id=doc.id,
        round=last_round + 1,
        status="queued",
        started_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    run_prereview_task.delay(run.id)

    return JobStatusOut(job_id=run.id, status=run.status, round=run.round)


@router.get("/prereview-jobs/{job_id}", response_model=JobStatusOut)
def get_job_status(job_id: str, db: Session = Depends(get_db)) -> JobStatusOut:
    run = db.get(ReviewRun, job_id)
    if not run:
        raise HTTPException(404, "任务不存在")
    return JobStatusOut(job_id=run.id, status=run.status, round=run.round, error=run.error_message)


@router.get("/projects/{project_id}/review-runs/latest", response_model=ReviewReportOut)
def get_latest_review_run(project_id: str, db: Session = Depends(get_db)) -> ReviewReportOut:
    run = (
        db.query(ReviewRun)
        .filter(ReviewRun.project_id == project_id, ReviewRun.status == "done")
        .order_by(ReviewRun.round.desc())
        .first()
    )
    if not run:
        raise HTTPException(404, "该项目暂无已完成的预审报告")

    findings = db.query(ReviewFinding).filter(ReviewFinding.run_id == run.id).all()
    issues = [
        {
            "id": f.id,
            "level": f.level,
            "severity": f.severity,
            "location": f.location,
            "excerpt": f.excerpt,
            "rule": f.rule,
            "tenderQuote": f.tender_quote,
            "suggestion": f.suggestion,
        }
        for f in findings
    ]

    return ReviewReportOut(
        round=run.round,
        overall=run.overall,
        waste=run.waste,
        risk=run.risk,
        suggest=run.suggest,
        light=run.light,
        levels=run.levels_json,
        dimensions=run.dimensions_json,
        issues=issues,
    )


@router.get("/projects/{project_id}/review-runs", response_model=list[TrendPointOut])
def list_review_runs(project_id: str, db: Session = Depends(get_db)) -> list[TrendPointOut]:
    runs = (
        db.query(ReviewRun)
        .filter(ReviewRun.project_id == project_id, ReviewRun.status == "done")
        .order_by(ReviewRun.round.asc())
        .all()
    )
    return [
        TrendPointOut(round=r.round, score=r.overall, issues=(r.waste + r.risk + r.suggest)) for r in runs
    ]
