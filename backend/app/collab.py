"""协作写标：章节编辑锁与版本号、项目动态、站内通知。"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import ChapterAssignment, Notification, ProjectActivity, User

LOCK_TTL = timedelta(minutes=15)


def lock_alive(row: ChapterAssignment | None, now: datetime | None = None) -> bool:
    if row is None or not row.locked_by or not row.locked_at:
        return False
    return (now or datetime.utcnow()) - row.locked_at < LOCK_TTL


def get_assignment(db: Session, draft_id: str, chapter_id: str, *, for_update: bool = False) -> ChapterAssignment | None:
    q = db.query(ChapterAssignment).filter(ChapterAssignment.draft_id == draft_id, ChapterAssignment.chapter_id == chapter_id)
    if for_update:
        q = q.with_for_update()
    return q.first()


def touch_chapter(db: Session, draft, chapter_id: str, user: User, base_version: int | None) -> ChapterAssignment | None:
    """保存章节前调用：别人持有编辑锁或版本已变时拒绝，否则版本号 +1。调用方 commit。

    没分配过、也没人锁过的章节（单人写标）不建记录，保持原有行为。
    """
    row = get_assignment(db, draft.id, chapter_id, for_update=True)
    if row is None:
        if base_version is None:
            return None
        row = ChapterAssignment(draft_id=draft.id, chapter_id=chapter_id, version=0)
        db.add(row)
    if lock_alive(row) and row.locked_by != user.id:
        holder = db.get(User, row.locked_by)
        raise HTTPException(409, f"该章节正在由 {holder.name if holder else '其他成员'} 编辑，请稍后再试")
    if base_version is not None and int(row.version or 0) != int(base_version):
        raise HTTPException(409, "该章节已被其他成员修改，请刷新后再编辑")
    row.version = int(row.version or 0) + 1
    if row.status == "待撰写":
        row.status = "撰写中"
    return row


def log_activity(db: Session, project_id: str, user: User | None, action: str, detail: str = "") -> None:
    db.add(
        ProjectActivity(
            project_id=project_id,
            user_id=getattr(user, "id", None),
            user_name=getattr(user, "name", "") or "",
            action=action,
            detail=detail[:500],
        )
    )


def notify(db: Session, user_ids, *, kind: str, title: str, body: str = "", link: str = "", exclude: str | None = None) -> None:
    for uid in dict.fromkeys(u for u in user_ids if u and u != exclude):
        db.add(Notification(user_id=uid, kind=kind, title=title[:120], body=body[:500], link=link))
