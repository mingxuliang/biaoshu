from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import (
    BidDocument,
    BidRevision,
    BidRevisionVersion,
    EvaluationChecklist,
    ExportRecord,
    Project,
    ProjectMember,
    ReviewRun,
    TenderDocument,
    User,
    WriterDraft,
    gen_id,
)
from ..permissions import (
    PERM_PROJECT_EDIT,
    add_project_member,
    require_perm,
    require_project,
    visible_project_ids,
)
from ..project_ops import delete_project_cascade
from ..schemas import (
    CreateProjectIn,
    ProjectDocumentsOut,
    ProjectOut,
    SetProjectMembersIn,
    TeamMemberOut,
    TenderDocumentSummaryOut,
    TenderUploadMetaOut,
    TimelineStageOut,
    UpdateProjectIn,
)
from .documents import _bid_doc_to_summary

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024 * 1024:
        return f"{max(size_bytes / 1024, 0.1):.1f} KB"
    return f"{size_bytes / 1024 / 1024:.1f} MB"


def _latest_tender_doc(db: Session, project_id: str) -> TenderDocument | None:
    return (
        db.query(TenderDocument)
        .filter(TenderDocument.project_id == project_id)
        .order_by(TenderDocument.uploaded_at.desc())
        .first()
    )


def _teams_for_projects(db: Session, project_ids: list[str]) -> dict[str, list[TeamMemberOut]]:
    """批量查询多个项目的团队成员，避免逐项目查询（N+1）。"""
    if not project_ids:
        return {}
    rows = (
        db.query(ProjectMember, User)
        .join(User, ProjectMember.user_id == User.id)
        .filter(ProjectMember.project_id.in_(project_ids))
        .order_by(ProjectMember.created_at.asc())
        .all()
    )
    result: dict[str, list[TeamMemberOut]] = {pid: [] for pid in project_ids}
    for member, user in rows:
        result.setdefault(member.project_id, []).append(
            TeamMemberOut(id=user.id, name=user.name, email=user.email, role=user.role or "成员")
        )
    return result


def _to_project_out(
    project: Project,
    team: list[TeamMemberOut],
    tender_doc: TenderDocument | None,
    progress: int | None = None,
    score: float | None = None,
) -> ProjectOut:
    tender_doc_out = None
    if tender_doc:
        ext = tender_doc.filename.rsplit(".", 1)[-1].upper() if "." in tender_doc.filename else "文件"
        tender_doc_out = TenderUploadMetaOut(name=tender_doc.filename, size=_format_size(tender_doc.size_bytes), format=ext)

    return ProjectOut(
        id=project.id,
        code=project.code,
        name=project.name,
        type=project.type,
        owner=project.owner or "",
        budget=project.budget or "待定",
        deadline=project.deadline or "",
        progress=progress if progress is not None else (project.progress or 0),
        score=score if score is not None else (project.score or 0),
        status=project.status or "撰写中",
        createdAt=project.created_at.strftime("%Y-%m-%d") if project.created_at else "",
        tenderDoc=tender_doc_out,
        team=team,
    )


def _outline_progress(outline: list[dict]) -> tuple[int, int]:
    total = len(outline or [])
    done = sum(1 for n in (outline or []) if n.get("status") == "已完成")
    return done, total


def _live_metrics(db: Session, project_ids: list[str]) -> dict[str, tuple[int, float]]:
    """进度来自真实流程节点，预测得分取最新一轮已完成预审 overall。"""
    if not project_ids:
        return {}
    metrics: dict[str, tuple[int, float]] = {pid: (0, 0.0) for pid in project_ids}

    tender_ids = {
        row[0]
        for row in db.query(TenderDocument.project_id)
        .filter(TenderDocument.project_id.in_(project_ids))
        .distinct()
        .all()
    }
    locked_ids = {
        row[0]
        for row in db.query(EvaluationChecklist.project_id)
        .filter(EvaluationChecklist.project_id.in_(project_ids), EvaluationChecklist.locked.is_(True))
        .distinct()
        .all()
    }
    drafts = db.query(WriterDraft).filter(WriterDraft.project_id.in_(project_ids)).all()
    draft_by = {d.project_id: d for d in drafts}

    runs = (
        db.query(ReviewRun)
        .filter(ReviewRun.project_id.in_(project_ids), ReviewRun.status == "done")
        .order_by(ReviewRun.round.desc())
        .all()
    )
    scores: dict[str, float] = {}
    for run in runs:
        scores.setdefault(run.project_id, float(run.overall or 0))

    revision_ids = {
        row[0]
        for row in db.query(BidRevision.project_id)
        .join(BidRevisionVersion, BidRevisionVersion.revision_id == BidRevision.id)
        .filter(BidRevision.project_id.in_(project_ids))
        .distinct()
        .all()
    }
    export_ids = {
        row[0]
        for row in db.query(ExportRecord.project_id)
        .filter(ExportRecord.project_id.in_(project_ids), ExportRecord.check_status == "通过")
        .distinct()
        .all()
    }

    for pid in project_ids:
        progress = 0
        if pid in tender_ids:
            progress += 15
        if pid in locked_ids:
            progress += 20
        draft = draft_by.get(pid)
        if draft:
            done, total = _outline_progress(draft.outline_json or [])
            if total:
                progress += 10 + int(40 * done / total)
            elif (draft.step or 1) > 1:
                progress += 10
        if pid in scores:
            progress += 10
        if pid in revision_ids:
            progress += 5
        if pid in export_ids:
            progress += 5
        metrics[pid] = (min(100, progress), scores.get(pid, 0.0))
    return metrics


@router.get("", response_model=list[ProjectOut])
def list_projects(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[ProjectOut]:
    query = db.query(Project)
    ids_filter = visible_project_ids(db, current_user)
    if ids_filter is not None:
        query = query.filter(Project.id.in_(ids_filter or ["__none__"]))
    projects = query.order_by(Project.created_at.desc()).all()
    ids = [p.id for p in projects]
    teams = _teams_for_projects(db, ids)

    tender_docs = (
        db.query(TenderDocument).filter(TenderDocument.project_id.in_(ids)).order_by(TenderDocument.uploaded_at.desc()).all()
        if ids
        else []
    )
    latest_tender_by_project: dict[str, TenderDocument] = {}
    for doc in tender_docs:
        latest_tender_by_project.setdefault(doc.project_id, doc)

    metrics = _live_metrics(db, ids)
    return [
        _to_project_out(
            p,
            teams.get(p.id, []),
            latest_tender_by_project.get(p.id),
            metrics.get(p.id, (0, 0.0))[0],
            metrics.get(p.id, (0, 0.0))[1],
        )
        for p in projects
    ]


@router.post("", response_model=ProjectOut)
def create_project(
    payload: CreateProjectIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectOut:
    require_perm(current_user, PERM_PROJECT_EDIT)
    project = Project(
        id=gen_id("proj"),
        code=payload.code.strip(),
        name=payload.name.strip(),
        type=payload.type,
        owner=payload.owner or current_user.name,
        owner_id=current_user.id,
        budget=f"¥ {payload.budget} 万" if payload.budget else "待定",
        deadline=payload.deadline or "2026-12-31",
        progress=0,
        score=0,
        status="撰写中",
    )
    db.add(project)
    db.flush()
    add_project_member(db, project.id, current_user.id)
    db.commit()
    db.refresh(project)
    team = _teams_for_projects(db, [project.id]).get(project.id, [])
    return _to_project_out(project, team, None, 0, 0.0)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> ProjectOut:
    require_project(db, current_user, project_id)
    project = db.get(Project, project_id)
    team = _teams_for_projects(db, [project_id]).get(project_id, [])
    progress, score = _live_metrics(db, [project_id]).get(project_id, (0, 0.0))
    return _to_project_out(project, team, _latest_tender_doc(db, project_id), progress, score)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    payload: UpdateProjectIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectOut:
    project = require_project(db, current_user, project_id, PERM_PROJECT_EDIT)

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(project, field, value)

    db.commit()
    db.refresh(project)
    team = _teams_for_projects(db, [project_id]).get(project_id, [])
    progress, score = _live_metrics(db, [project_id]).get(project_id, (0, 0.0))
    return _to_project_out(project, team, _latest_tender_doc(db, project_id), progress, score)


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> None:
    require_project(db, current_user, project_id, PERM_PROJECT_EDIT)
    delete_project_cascade(db, project_id)
    db.commit()


# ---------------------------------------------------------------------------
# 团队分配（项目级）
# ---------------------------------------------------------------------------


@router.get("/{project_id}/members", response_model=list[TeamMemberOut])
def get_project_members(
    project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[TeamMemberOut]:
    require_project(db, current_user, project_id)
    return _teams_for_projects(db, [project_id]).get(project_id, [])


@router.put("/{project_id}/members", response_model=list[TeamMemberOut])
def set_project_members(
    project_id: str,
    payload: SetProjectMembersIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TeamMemberOut]:
    require_project(db, current_user, project_id, PERM_PROJECT_EDIT)

    unique_ids = list(dict.fromkeys(payload.user_ids))
    if unique_ids:
        users = db.query(User).filter(User.id.in_(unique_ids)).all()
        existing = {u.id for u in users}
        missing = [uid for uid in unique_ids if uid not in existing]
        if missing:
            raise HTTPException(400, "部分用户不存在，请刷新后重选")
        if any(getattr(u, "disabled", False) for u in users):
            raise HTTPException(400, "不能将已停用账号分配到项目")

    db.query(ProjectMember).filter(ProjectMember.project_id == project_id).delete()
    for user_id in unique_ids:
        db.add(ProjectMember(project_id=project_id, user_id=user_id))
    db.commit()
    return _teams_for_projects(db, [project_id]).get(project_id, [])


# ---------------------------------------------------------------------------
# 招标文件（真实落库列表）
# ---------------------------------------------------------------------------


@router.get("/{project_id}/tender-documents", response_model=list[TenderDocumentSummaryOut])
def list_project_tender_documents(
    project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[TenderDocumentSummaryOut]:
    require_project(db, current_user, project_id)
    docs = (
        db.query(TenderDocument)
        .filter(TenderDocument.project_id == project_id)
        .order_by(TenderDocument.uploaded_at.desc())
        .all()
    )
    return [
        TenderDocumentSummaryOut(
            id=d.id, filename=d.filename, sizeBytes=d.size_bytes, uploadedAt=d.uploaded_at.isoformat()
        )
        for d in docs
    ]


# ---------------------------------------------------------------------------
# 文件归档（聚合招标文件 + 投标文件/工作台产出）
# ---------------------------------------------------------------------------


@router.get("/{project_id}/documents", response_model=ProjectDocumentsOut)
def get_project_documents(
    project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> ProjectDocumentsOut:
    require_project(db, current_user, project_id)
    tender_docs = (
        db.query(TenderDocument)
        .filter(TenderDocument.project_id == project_id)
        .order_by(TenderDocument.uploaded_at.desc())
        .all()
    )
    bid_docs = (
        db.query(BidDocument)
        .filter(BidDocument.project_id == project_id)
        .order_by(BidDocument.uploaded_at.desc())
        .all()
    )
    return ProjectDocumentsOut(
        tenderDocuments=[
            TenderDocumentSummaryOut(
                id=d.id, filename=d.filename, sizeBytes=d.size_bytes, uploadedAt=d.uploaded_at.isoformat()
            )
            for d in tender_docs
        ],
        bidDocuments=[_bid_doc_to_summary(d) for d in bid_docs],
    )


# ---------------------------------------------------------------------------
# 投标进度时间线（真实派生，不再是固定文案）
# ---------------------------------------------------------------------------


@router.get("/{project_id}/timeline", response_model=list[TimelineStageOut])
def get_project_timeline(
    project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[TimelineStageOut]:
    project = require_project(db, current_user, project_id)

    stages: list[TimelineStageOut] = []

    stages.append(
        TimelineStageOut(
            id="created",
            label="项目创建",
            date=project.created_at.strftime("%Y-%m-%d") if project.created_at else "",
            status="已完成",
            desc="项目已创建",
        )
    )

    tender_doc = _latest_tender_doc(db, project_id)
    locked_checklist = (
        db.query(EvaluationChecklist)
        .filter(EvaluationChecklist.project_id == project_id, EvaluationChecklist.locked.is_(True))
        .order_by(EvaluationChecklist.version.desc())
        .first()
    )
    any_checklist = (
        db.query(EvaluationChecklist)
        .filter(EvaluationChecklist.project_id == project_id)
        .order_by(EvaluationChecklist.created_at.desc())
        .first()
    )
    if locked_checklist:
        data = locked_checklist.checklist_json or {}
        score_count = len(data.get("scoreRules", []))
        must_count = len(data.get("mustRespond", []))
        stages.append(
            TimelineStageOut(
                id="tender_parse",
                label="上传并解析招标文件",
                date=(locked_checklist.finished_at or locked_checklist.created_at).strftime("%Y-%m-%d")
                if (locked_checklist.finished_at or locked_checklist.created_at)
                else "",
                status="已完成",
                desc=f"评标尺子已锁定，共 {score_count} 项评分点、{must_count} 项须响应条款",
            )
        )
    elif any_checklist or tender_doc:
        date_src = (any_checklist.created_at if any_checklist else tender_doc.uploaded_at) if (any_checklist or tender_doc) else None
        stages.append(
            TimelineStageOut(
                id="tender_parse",
                label="上传并解析招标文件",
                date=date_src.strftime("%Y-%m-%d") if date_src else "",
                status="进行中",
                desc="已上传招标文件，评标尺子尚未锁定" if not any_checklist else "解析进行中，尚未锁定评标尺子",
            )
        )
    else:
        stages.append(
            TimelineStageOut(id="tender_parse", label="上传并解析招标文件", date="", status="待开始", desc="")
        )

    draft = db.query(WriterDraft).filter(WriterDraft.project_id == project_id).first()
    if draft:
        done, total = _outline_progress(draft.outline_json or [])
        if total > 0 and done == total:
            stages.append(
                TimelineStageOut(
                    id="writer",
                    label="AI 撰写标书",
                    date=draft.updated_at.strftime("%Y-%m-%d") if draft.updated_at else "",
                    status="已完成",
                    desc=f"全部 {total} 个章节已完成撰写",
                )
            )
        elif any((draft.chapter_contents_json or {}).values()) or done > 0:
            stages.append(
                TimelineStageOut(
                    id="writer",
                    label="AI 撰写标书",
                    date=draft.updated_at.strftime("%Y-%m-%d") if draft.updated_at else "",
                    status="进行中",
                    desc=f"已完成 {done}/{total} 个章节" if total else "撰写进行中",
                )
            )
        else:
            stages.append(TimelineStageOut(id="writer", label="AI 撰写标书", date="", status="待开始", desc=""))
    else:
        stages.append(TimelineStageOut(id="writer", label="AI 撰写标书", date="", status="待开始", desc=""))

    latest_run = (
        db.query(ReviewRun).filter(ReviewRun.project_id == project_id).order_by(ReviewRun.started_at.desc()).first()
    )
    if latest_run and latest_run.status == "done":
        stages.append(
            TimelineStageOut(
                id="prereview",
                label="AI 预审",
                date=(latest_run.finished_at or latest_run.started_at).strftime("%Y-%m-%d")
                if (latest_run.finished_at or latest_run.started_at)
                else "",
                status="已完成",
                desc=f"综合得分 {latest_run.overall} 分，{latest_run.waste} 项废标风险",
            )
        )
    elif latest_run and latest_run.status in ("queued", "running"):
        stages.append(
            TimelineStageOut(
                id="prereview",
                label="AI 预审",
                date=latest_run.started_at.strftime("%Y-%m-%d") if latest_run.started_at else "",
                status="进行中",
                desc="预审任务正在执行",
            )
        )
    else:
        stages.append(TimelineStageOut(id="prereview", label="AI 预审", date="", status="待开始", desc=""))

    latest_version = (
        db.query(BidRevisionVersion)
        .join(BidRevision, BidRevisionVersion.revision_id == BidRevision.id)
        .filter(BidRevision.project_id == project_id)
        .order_by(BidRevisionVersion.created_at.desc())
        .first()
    )
    if latest_version:
        stages.append(
            TimelineStageOut(
                id="revision",
                label="修改闭环保存版本",
                date=latest_version.created_at.strftime("%Y-%m-%d") if latest_version.created_at else "",
                status="已完成",
                desc=f"已保存「{latest_version.label}」，共 {latest_version.word_count} 字",
            )
        )
    else:
        stages.append(TimelineStageOut(id="revision", label="修改闭环保存版本", date="", status="待开始", desc=""))

    latest_export = (
        db.query(ExportRecord)
        .filter(ExportRecord.project_id == project_id)
        .order_by(ExportRecord.created_at.desc())
        .first()
    )
    if latest_export:
        stages.append(
            TimelineStageOut(
                id="export",
                label="Word 导出",
                date=latest_export.created_at.strftime("%Y-%m-%d") if latest_export.created_at else "",
                status="已完成",
                desc=f"{latest_export.mode}导出，检查结果：{latest_export.check_status}",
            )
        )
    else:
        stages.append(TimelineStageOut(id="export", label="Word 导出", date="", status="待开始", desc=""))

    return stages
