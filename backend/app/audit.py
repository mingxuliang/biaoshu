"""操作审计：从请求里解析操作者，写入 AuditLog（由调用方一并 commit）。"""

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Request
from sqlalchemy.orm import Session

from .auth import ALGORITHM
from .config import get_settings
from .models import AuditLog, Project, User

CST = timezone(timedelta(hours=8))


def actor_from_request(db: Session, request: Request | None) -> str:
    if request is None:
        return "系统"
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return "系统"
    token = auth.split(" ", 1)[1].strip()
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return "系统"
    user_id = payload.get("sub")
    if not user_id:
        return "系统"
    user = db.get(User, user_id)
    if not user:
        return "系统"
    return user.name


def project_label(db: Session, project_id: str) -> str:
    project = db.get(Project, project_id)
    if not project:
        return project_id
    return f"{project.name}（{project.code}）"


def write_audit(
    db: Session,
    *,
    action: str,
    user_name: str,
    target: str,
    detail: str = "",
    version: str = "—",
    result: str = "成功",
    extra: dict | None = None,
) -> AuditLog:
    row = AuditLog(
        action=action,
        user_name=user_name or "系统",
        target=target,
        version=version or "—",
        detail=detail,
        result=result,
        extra_json=extra or {},
    )
    db.add(row)
    return row


def week_start_naive_utc() -> datetime:
    now = datetime.now(CST)
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday.astimezone(timezone.utc).replace(tzinfo=None)


def format_cst(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CST).strftime("%Y-%m-%d %H:%M:%S")
