"""角色权限：与团队页权限矩阵一致，接口级强制。

所有判断都只在本企业 schema 内进行：别家企业的用户、项目、部门根本不在这个库里。
权限 = 内置角色（或企业自定义角色）的权限点；数据范围 = 本人 / 本部门 / 全企业。
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session, object_session

from .models import CustomRole, Project, ProjectMember, User

PERM_PROJECT_EDIT = "project_edit"
PERM_WRITER = "writer"
PERM_EXPORT = "export"
PERM_MEMBERS = "members"
PERM_SETTINGS = "settings"
PERM_QUAL_EDIT = "qual_edit"
PERM_REVIEW = "review"
# 充值、套餐、发票
PERM_BILLING = "billing"
# 部门树、自定义角色、企业资料与认证
PERM_ORG = "org"

ALL_PERMS = (
    PERM_PROJECT_EDIT,
    PERM_WRITER,
    PERM_EXPORT,
    PERM_MEMBERS,
    PERM_SETTINGS,
    PERM_QUAL_EDIT,
    PERM_REVIEW,
    PERM_BILLING,
    PERM_ORG,
)

SCOPE_SELF = "本人"
SCOPE_DEPT = "本部门"
SCOPE_ALL = "全企业"
DATA_SCOPES = (SCOPE_SELF, SCOPE_DEPT, SCOPE_ALL)

ROLE_PERMS: dict[str, set[str]] = {
    "管理员": set(ALL_PERMS),
    # 项目经理可邀请、调整非管理员成员；授予或改动管理员仍只限管理员（见 users 路由）
    "项目经理": {PERM_PROJECT_EDIT, PERM_WRITER, PERM_EXPORT, PERM_MEMBERS, PERM_QUAL_EDIT, PERM_REVIEW},
    "撰写专家": {PERM_WRITER, PERM_EXPORT, PERM_REVIEW},
    "评标专家": {PERM_EXPORT, PERM_REVIEW},
    "成员": {PERM_EXPORT},
}

ROLE_SCOPES: dict[str, str] = {
    "管理员": SCOPE_ALL,
    "项目经理": SCOPE_DEPT,
    "撰写专家": SCOPE_SELF,
    "评标专家": SCOPE_SELF,
    "成员": SCOPE_SELF,
}


def normalize_role(role: str | None) -> str:
    text = (role or "").strip()
    return text if text in ROLE_PERMS else "成员"


def _custom_role(user: User) -> CustomRole | None:
    role_id = getattr(user, "custom_role_id", None)
    if not role_id:
        return None
    session = object_session(user)
    if session is None:
        return None
    try:
        return session.get(CustomRole, role_id)
    except Exception:  # noqa: BLE001 —— 老库尚无 custom_roles 表
        return None


def user_perms(user: User) -> set[str]:
    if normalize_role(user.role) == "管理员":
        return set(ALL_PERMS)
    custom = _custom_role(user)
    if custom is not None:
        # 自定义角色不能授予管理员专属的计费和组织权限之外的越级能力：直接按配置给，但 members 仍受 users 路由的管理员校验
        return {p for p in (custom.perms_json or []) if p in ALL_PERMS}
    return set(ROLE_PERMS.get(normalize_role(user.role), ROLE_PERMS["成员"]))


def data_scope(user: User) -> str:
    if normalize_role(user.role) == "管理员":
        return SCOPE_ALL
    custom = _custom_role(user)
    if custom is not None and custom.data_scope in DATA_SCOPES:
        return custom.data_scope
    return ROLE_SCOPES.get(normalize_role(user.role), SCOPE_SELF)


def has_perm(user: User, perm: str) -> bool:
    return perm in user_perms(user)


def require_perm(user: User, perm: str) -> None:
    if not has_perm(user, perm):
        raise HTTPException(403, "当前角色无权执行此操作")


def require_any_perm(user: User, *perms: str) -> None:
    if not any(has_perm(user, perm) for perm in perms):
        raise HTTPException(403, "当前角色无权执行此操作")


LIBRARY_READ_PERMS = (PERM_PROJECT_EDIT, PERM_WRITER, PERM_REVIEW, PERM_QUAL_EDIT)


def require_library_read(user: User, *extra: str) -> None:
    """资质库、产品库、规则配置的只读权限：参与撰写、评审或维护的角色可看，纯「成员」不可看。"""
    require_any_perm(user, *LIBRARY_READ_PERMS, *extra)


def is_admin(user: User) -> bool:
    return normalize_role(user.role) == "管理员"


def can_access_project(db: Session, user: User, project: Project) -> bool:
    scope = data_scope(user)
    if scope == SCOPE_ALL:
        return True
    if project.owner_id and project.owner_id == user.id:
        return True
    dept = getattr(user, "department_id", None)
    if scope == SCOPE_DEPT and dept and getattr(project, "department_id", None) == dept:
        return True
    row = (
        db.query(ProjectMember.id)
        .filter(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)
        .first()
    )
    return row is not None


def visible_project_ids(db: Session, user: User) -> set[str] | None:
    """全企业范围返回 None 表示全部；其他人返回可见项目 id 集合。"""
    scope = data_scope(user)
    if scope == SCOPE_ALL:
        return None
    owned = {p.id for p in db.query(Project.id).filter(Project.owner_id == user.id).all()}
    member_of = {
        row[0]
        for row in db.query(ProjectMember.project_id).filter(ProjectMember.user_id == user.id).all()
    }
    dept_projects: set[str] = set()
    dept = getattr(user, "department_id", None)
    if scope == SCOPE_DEPT and dept:
        dept_projects = {p.id for p in db.query(Project.id).filter(Project.department_id == dept).all()}
    return owned | member_of | dept_projects


def require_project(db: Session, user: User, project_id: str, perm: str | None = None) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    if not can_access_project(db, user, project):
        raise HTTPException(403, "无权访问该项目")
    if perm:
        require_perm(user, perm)
    return project


def project_role(db: Session, user: User, project_id: str) -> str | None:
    row = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user.id)
        .first()
    )
    return (row.project_role or "撰写") if row else None


def add_project_member(db: Session, project_id: str, user_id: str, project_role: str = "撰写") -> None:
    exists = (
        db.query(ProjectMember.id)
        .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        .first()
    )
    if exists:
        return
    db.add(ProjectMember(project_id=project_id, user_id=user_id, project_role=project_role))
