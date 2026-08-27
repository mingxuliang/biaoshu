"""角色权限：与团队页权限矩阵一致，接口级强制。"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import Project, ProjectMember, User

PERM_PROJECT_EDIT = "project_edit"
PERM_WRITER = "writer"
PERM_EXPORT = "export"
PERM_MEMBERS = "members"
PERM_SETTINGS = "settings"
PERM_QUAL_EDIT = "qual_edit"
PERM_REVIEW = "review"

ROLE_PERMS: dict[str, set[str]] = {
    "管理员": {
        PERM_PROJECT_EDIT,
        PERM_WRITER,
        PERM_EXPORT,
        PERM_MEMBERS,
        PERM_SETTINGS,
        PERM_QUAL_EDIT,
        PERM_REVIEW,
    },
    "项目经理": {PERM_PROJECT_EDIT, PERM_WRITER, PERM_EXPORT, PERM_QUAL_EDIT, PERM_REVIEW},
    "撰写专家": {PERM_WRITER, PERM_EXPORT, PERM_REVIEW},
    "评标专家": {PERM_EXPORT, PERM_REVIEW},
    "成员": {PERM_EXPORT},
}


def normalize_role(role: str | None) -> str:
    text = (role or "").strip()
    return text if text in ROLE_PERMS else "成员"


def has_perm(user: User, perm: str) -> bool:
    return perm in ROLE_PERMS.get(normalize_role(user.role), ROLE_PERMS["成员"])


def require_perm(user: User, perm: str) -> None:
    if not has_perm(user, perm):
        raise HTTPException(403, "当前角色无权执行此操作")


def require_any_perm(user: User, *perms: str) -> None:
    if not any(has_perm(user, perm) for perm in perms):
        raise HTTPException(403, "当前角色无权执行此操作")


def is_admin(user: User) -> bool:
    return normalize_role(user.role) == "管理员"


def can_access_project(db: Session, user: User, project: Project) -> bool:
    if is_admin(user):
        return True
    if project.owner_id and project.owner_id == user.id:
        return True
    row = (
        db.query(ProjectMember.id)
        .filter(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)
        .first()
    )
    return row is not None


def visible_project_ids(db: Session, user: User) -> set[str] | None:
    """管理员返回 None 表示全部；其他人返回可见项目 id 集合。"""
    if is_admin(user):
        return None
    owned = {p.id for p in db.query(Project.id).filter(Project.owner_id == user.id).all()}
    member_of = {
        row[0]
        for row in db.query(ProjectMember.project_id).filter(ProjectMember.user_id == user.id).all()
    }
    return owned | member_of


def require_project(db: Session, user: User, project_id: str, perm: str | None = None) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    if not can_access_project(db, user, project):
        raise HTTPException(403, "无权访问该项目")
    if perm:
        require_perm(user, perm)
    return project


def add_project_member(db: Session, project_id: str, user_id: str) -> None:
    exists = (
        db.query(ProjectMember.id)
        .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        .first()
    )
    if exists:
        return
    db.add(ProjectMember(project_id=project_id, user_id=user_id))
