"""协作：章节分配与编辑锁、评论与 @ 提醒、项目动态、站内通知。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..collab import get_assignment, lock_alive, log_activity, notify
from ..db import get_db
from ..models import (
    ChapterAssignment,
    Notification,
    Project,
    ProjectActivity,
    ProjectComment,
    ProjectMember,
    User,
    WriterDraft,
)
from ..permissions import PERM_PROJECT_EDIT, PERM_WRITER, can_access_project, is_admin, require_perm, require_project

router = APIRouter(prefix="/api/collab", tags=["collab"])

ASSIGN_STATUSES = ("待撰写", "撰写中", "待审核", "已完成")


def _dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


def _names(db: Session) -> dict[str, str]:
    return dict(db.query(User.id, User.name).all())


def _draft(db: Session, user: User, draft_id: str) -> WriterDraft:
    draft = db.get(WriterDraft, draft_id)
    if draft is None:
        raise HTTPException(404, "草稿不存在")
    require_project(db, user, draft.project_id)
    return draft


def _project_users(db: Session, project_id: str) -> set[str]:
    return {uid for (uid,) in db.query(ProjectMember.user_id).filter(ProjectMember.project_id == project_id).all()}


def _assign_out(row: ChapterAssignment, names: dict[str, str]) -> dict:
    alive = lock_alive(row)
    return {
        "chapterId": row.chapter_id,
        "assigneeId": row.assignee_id,
        "assigneeName": names.get(row.assignee_id or "", ""),
        "reviewerId": row.reviewer_id,
        "reviewerName": names.get(row.reviewer_id or "", ""),
        "status": row.status,
        "version": row.version or 0,
        "lockedBy": row.locked_by if alive else None,
        "lockedByName": names.get(row.locked_by or "", "") if alive else "",
        "updatedAt": _dt(row.updated_at),
    }


# ---------------------------------------------------------------------------
# 章节分配与编辑锁
# ---------------------------------------------------------------------------


@router.get("/drafts/{draft_id}/assignments")
def list_assignments(draft_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[dict]:
    _draft(db, current_user, draft_id)
    names = _names(db)
    rows = db.query(ChapterAssignment).filter(ChapterAssignment.draft_id == draft_id).all()
    return [_assign_out(r, names) for r in rows]


class AssignIn(BaseModel):
    assigneeId: str | None = None
    reviewerId: str | None = None
    status: str | None = None
    version: int | None = None


@router.put("/drafts/{draft_id}/assignments/{chapter_id}")
def assign_chapter(
    draft_id: str,
    chapter_id: str,
    payload: AssignIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    draft = _draft(db, current_user, draft_id)
    row = get_assignment(db, draft_id, chapter_id, for_update=True)
    changing_people = payload.assigneeId is not None or payload.reviewerId is not None
    if changing_people:
        require_perm(current_user, PERM_PROJECT_EDIT)
    else:
        require_perm(current_user, PERM_WRITER)
    if row is None:
        row = ChapterAssignment(draft_id=draft_id, chapter_id=chapter_id, version=0)
        db.add(row)
    elif payload.version is not None and payload.version != (row.version or 0):
        raise HTTPException(409, "分配信息已被其他成员修改，请刷新")
    members = _project_users(db, draft.project_id)
    project = db.get(Project, draft.project_id)
    for uid in (payload.assigneeId, payload.reviewerId):
        if not uid or uid in members:
            continue
        target = db.get(User, uid)
        if target is None or target.disabled or not can_access_project(db, target, project):
            raise HTTPException(400, "只能分配给本项目成员")
    names = _names(db)
    if payload.assigneeId is not None and payload.assigneeId != row.assignee_id:
        row.assignee_id = payload.assigneeId or None
        if row.assignee_id:
            notify(db, [row.assignee_id], kind="assign", title="你有新的章节待撰写", body=f"章节 {chapter_id}", link=f"/writer?project={draft.project_id}", exclude=current_user.id)
        log_activity(db, draft.project_id, current_user, "分配章节", f"{chapter_id} → {names.get(row.assignee_id or '', '未分配')}")
    if payload.reviewerId is not None and payload.reviewerId != row.reviewer_id:
        row.reviewer_id = payload.reviewerId or None
        if row.reviewer_id:
            notify(db, [row.reviewer_id], kind="assign", title="你有新的章节待审核", body=f"章节 {chapter_id}", link=f"/writer?project={draft.project_id}", exclude=current_user.id)
    if payload.status is not None:
        if payload.status not in ASSIGN_STATUSES:
            raise HTTPException(400, "状态不合法")
        if payload.status == "已完成" and row.reviewer_id and row.reviewer_id != current_user.id and not is_admin(current_user):
            raise HTTPException(403, "只有审核人可以把章节标记为已完成")
        if payload.status != row.status:
            log_activity(db, draft.project_id, current_user, "章节状态", f"{chapter_id}：{row.status} → {payload.status}")
            if payload.status == "待审核" and row.reviewer_id:
                notify(db, [row.reviewer_id], kind="review", title="章节已提交审核", body=f"章节 {chapter_id}", link=f"/writer?project={draft.project_id}", exclude=current_user.id)
        row.status = payload.status
    row.version = int(row.version or 0) + 1
    db.commit()
    return _assign_out(row, _names(db))


@router.post("/drafts/{draft_id}/assignments/{chapter_id}/lock")
def lock_chapter(draft_id: str, chapter_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    """开始编辑时加锁，15 分钟无续期自动失效；前端编辑期间每几分钟续一次。"""
    _draft(db, current_user, draft_id)
    require_perm(current_user, PERM_WRITER)
    row = get_assignment(db, draft_id, chapter_id, for_update=True)
    if row is None:
        row = ChapterAssignment(draft_id=draft_id, chapter_id=chapter_id, version=0)
        db.add(row)
    if lock_alive(row) and row.locked_by != current_user.id:
        holder = db.get(User, row.locked_by)
        raise HTTPException(409, f"该章节正在由 {holder.name if holder else '其他成员'} 编辑")
    row.locked_by = current_user.id
    row.locked_at = datetime.utcnow()
    db.commit()
    return _assign_out(row, _names(db))


@router.delete("/drafts/{draft_id}/assignments/{chapter_id}/lock")
def unlock_chapter(draft_id: str, chapter_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    _draft(db, current_user, draft_id)
    row = get_assignment(db, draft_id, chapter_id, for_update=True)
    if row is None:
        return {"ok": True}
    if row.locked_by and row.locked_by != current_user.id and lock_alive(row) and not is_admin(current_user):
        raise HTTPException(403, "只能释放自己的编辑锁")
    row.locked_by = None
    row.locked_at = None
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# 评论
# ---------------------------------------------------------------------------


class CommentIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    draftId: str | None = None
    chapterId: str | None = None
    mentions: list[str] = Field(default_factory=list, max_length=30)


def _comment_out(c: ProjectComment, names: dict[str, str]) -> dict:
    return {
        "id": c.id,
        "projectId": c.project_id,
        "draftId": c.draft_id,
        "chapterId": c.chapter_id,
        "userId": c.user_id,
        "userName": names.get(c.user_id, ""),
        "content": c.content,
        "mentions": [{"id": m, "name": names.get(m, "")} for m in (c.mentions_json or [])],
        "resolved": bool(c.resolved),
        "createdAt": _dt(c.created_at),
    }


@router.get("/projects/{project_id}/comments")
def list_comments(
    project_id: str,
    draftId: str | None = None,
    chapterId: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    require_project(db, current_user, project_id)
    q = db.query(ProjectComment).filter(ProjectComment.project_id == project_id)
    if draftId:
        q = q.filter(ProjectComment.draft_id == draftId)
    if chapterId:
        q = q.filter(ProjectComment.chapter_id == chapterId)
    names = _names(db)
    return [_comment_out(c, names) for c in q.order_by(ProjectComment.created_at.asc()).limit(500).all()]


@router.post("/projects/{project_id}/comments")
def add_comment(project_id: str, payload: CommentIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    project = require_project(db, current_user, project_id)
    if payload.draftId:
        draft = db.get(WriterDraft, payload.draftId)
        if draft is None or draft.project_id != project_id:
            raise HTTPException(400, "草稿不属于该项目")
    mentions: list[str] = []
    for uid in dict.fromkeys(payload.mentions):
        target = db.get(User, uid)
        # 只能 @ 本企业里能看到这个项目的人；别家企业的人根本不在本 schema 里
        if target is None or target.disabled or not can_access_project(db, target, project):
            raise HTTPException(400, "只能 @ 本项目的成员")
        mentions.append(uid)
    comment = ProjectComment(
        project_id=project_id,
        draft_id=payload.draftId,
        chapter_id=payload.chapterId,
        user_id=current_user.id,
        content=payload.content.strip(),
        mentions_json=mentions,
    )
    db.add(comment)
    notify(
        db,
        mentions,
        kind="mention",
        title=f"{current_user.name} 在「{project.name}」中提到了你",
        body=payload.content.strip()[:200],
        link=f"/writer?project={project_id}",
        exclude=current_user.id,
    )
    log_activity(db, project_id, current_user, "发表评论", payload.content.strip()[:80])
    db.commit()
    return _comment_out(comment, _names(db))


class CommentPatch(BaseModel):
    resolved: bool


@router.patch("/comments/{comment_id}")
def resolve_comment(comment_id: str, payload: CommentPatch, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    comment = db.get(ProjectComment, comment_id)
    if comment is None:
        raise HTTPException(404, "评论不存在")
    require_project(db, current_user, comment.project_id)
    comment.resolved = payload.resolved
    db.commit()
    return _comment_out(comment, _names(db))


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    comment = db.get(ProjectComment, comment_id)
    if comment is None:
        raise HTTPException(404, "评论不存在")
    require_project(db, current_user, comment.project_id)
    if comment.user_id != current_user.id and not is_admin(current_user):
        raise HTTPException(403, "只能删除自己的评论")
    db.delete(comment)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# 项目动态
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/activities")
def list_activities(
    project_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    require_project(db, current_user, project_id)
    rows = (
        db.query(ProjectActivity)
        .filter(ProjectActivity.project_id == project_id)
        .order_by(ProjectActivity.created_at.desc())
        .limit(limit)
        .all()
    )
    return [{"id": a.id, "userName": a.user_name, "action": a.action, "detail": a.detail, "createdAt": _dt(a.created_at)} for a in rows]


# ---------------------------------------------------------------------------
# 通知（只看自己的）
# ---------------------------------------------------------------------------


@router.get("/notifications")
def list_notifications(
    unread: bool = False,
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    q = db.query(Notification).filter(Notification.user_id == current_user.id)
    unread_count = q.filter(Notification.read.is_(False)).count()
    if unread:
        q = q.filter(Notification.read.is_(False))
    rows = q.order_by(Notification.created_at.desc()).limit(limit).all()
    return {
        "unread": unread_count,
        "items": [
            {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "read": bool(n.read), "createdAt": _dt(n.created_at)}
            for n in rows
        ],
    }


class ReadIn(BaseModel):
    ids: list[str] = Field(default_factory=list)
    all: bool = False


@router.post("/notifications/read")
def mark_read(payload: ReadIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    q = db.query(Notification).filter(Notification.user_id == current_user.id, Notification.read.is_(False))
    if not payload.all:
        if not payload.ids:
            return {"updated": 0}
        q = q.filter(Notification.id.in_(payload.ids))
    updated = q.update({Notification.read: True}, synchronize_session=False)
    db.commit()
    return {"updated": updated}
