from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..audit import format_cst, week_start_naive_utc
from ..auth import get_current_user
from ..db import get_db
from ..models import AuditLog, BidDocument, KnowledgeDocument, Project, TenderDocument, User
from ..permissions import PERM_SETTINGS, require_perm, visible_project_ids
from ..schemas import (
    AuditLogListOut,
    AuditLogOut,
    SearchDocumentHit,
    SearchMemberHit,
    SearchOut,
    SearchProjectHit,
)

router = APIRouter(prefix="/api", tags=["audit"])

VALID_ACTIONS = {"解析", "确认对标", "引用知识", "发起预审", "AI 改写", "改写接受", "导出"}


def _log_to_out(row: AuditLog) -> AuditLogOut:
    return AuditLogOut(
        id=row.id,
        time=format_cst(row.created_at),
        user=row.user_name,
        action=row.action,
        target=row.target,
        version=row.version or "—",
        detail=row.detail or "",
        result=row.result or "成功",
    )


@router.get("/audit-logs", response_model=AuditLogListOut)
def list_audit_logs(
    action: str = Query(""),
    keyword: str = Query(""),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AuditLogListOut:
    require_perm(current_user, PERM_SETTINGS)  # 与前端「审计日志」页的权限一致
    query = db.query(AuditLog)
    if action and action != "全部" and action in VALID_ACTIONS:
        query = query.filter(AuditLog.action == action)
    kw = keyword.strip()
    if kw:
        like = f"%{kw}%"
        query = query.filter(
            or_(
                AuditLog.target.ilike(like),
                AuditLog.user_name.ilike(like),
                AuditLog.detail.ilike(like),
            )
        )
    items = query.order_by(AuditLog.created_at.desc()).limit(limit).all()

    week_start = week_start_naive_utc()
    total = db.query(func.count(AuditLog.id)).scalar() or 0
    week_total = (
        db.query(func.count(AuditLog.id)).filter(AuditLog.created_at >= week_start).scalar() or 0
    )
    week_export = (
        db.query(func.count(AuditLog.id))
        .filter(AuditLog.created_at >= week_start, AuditLog.action == "导出")
        .scalar()
        or 0
    )
    ai_count = (
        db.query(func.count(AuditLog.id))
        .filter(AuditLog.action.in_(["AI 改写", "引用知识"]))
        .scalar()
        or 0
    )

    return AuditLogListOut(
        items=[_log_to_out(row) for row in items],
        total=total,
        weekTotal=week_total,
        weekExport=week_export,
        aiCount=ai_count,
    )


@router.get("/search", response_model=SearchOut)
def global_search(
    q: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SearchOut:
    keyword = q.strip()
    if not keyword:
        return SearchOut()
    like = f"%{keyword}%"

    # 项目和项目文件只搜当前用户有权访问的项目，管理员不受限
    visible = visible_project_ids(db, current_user)
    project_q = db.query(Project).filter(or_(Project.name.ilike(like), Project.code.ilike(like)))
    if visible is not None:
        project_q = project_q.filter(Project.id.in_(visible or {""}))
    projects = project_q.order_by(Project.created_at.desc()).limit(8).all()
    members = (
        db.query(User)
        .filter(
            User.disabled.isnot(True),
            or_(User.name.ilike(like), User.email.ilike(like), User.position.ilike(like)),
        )
        .limit(8)
        .all()
    )
    knowledge_q = db.query(KnowledgeDocument).filter(
        or_(KnowledgeDocument.title.ilike(like), KnowledgeDocument.filename.ilike(like))
    )
    if visible is not None:
        # 个人库只搜自己的，项目库只搜可见项目的
        knowledge_q = knowledge_q.filter(
            (KnowledgeDocument.scope == "企业库")
            | ((KnowledgeDocument.scope == "个人库") & (KnowledgeDocument.owner_id == current_user.id))
            | ((KnowledgeDocument.scope == "项目库") & (KnowledgeDocument.project_id.in_(visible or {""})))
        )
    knowledge_docs = knowledge_q.order_by(KnowledgeDocument.created_at.desc()).limit(6).all()
    tender_q = db.query(TenderDocument).filter(TenderDocument.filename.ilike(like))
    bid_q = db.query(BidDocument).filter(BidDocument.filename.ilike(like))
    if visible is not None:
        tender_q = tender_q.filter(TenderDocument.project_id.in_(visible or {""}))
        bid_q = bid_q.filter(BidDocument.project_id.in_(visible or {""}))
    tender_docs = tender_q.order_by(TenderDocument.uploaded_at.desc()).limit(4).all()
    bid_docs = bid_q.order_by(BidDocument.uploaded_at.desc()).limit(4).all()

    documents: list[SearchDocumentHit] = [
        SearchDocumentHit(
            id=d.id,
            title=d.title,
            kind="知识库",
            href="/console/knowledge",
        )
        for d in knowledge_docs
    ]
    documents.extend(
        SearchDocumentHit(
            id=d.id,
            title=d.filename,
            kind="招标文件",
            href="/console/parse",
        )
        for d in tender_docs
    )
    documents.extend(
        SearchDocumentHit(
            id=d.id,
            title=d.filename,
            kind="投标文件",
            href="/console/audit",
        )
        for d in bid_docs
    )

    return SearchOut(
        projects=[
            SearchProjectHit(id=p.id, name=p.name, code=p.code, type=p.type) for p in projects
        ],
        members=[
            SearchMemberHit(
                id=u.id,
                name=u.name,
                email=u.email,
                role=u.role or "成员",
                position=u.position or "",
            )
            for u in members
        ],
        documents=documents[:8],
    )
