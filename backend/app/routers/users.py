from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..auth import find_user_by_account, get_current_user, hash_password, normalize_account, random_password, revoke_tokens
from ..db import get_db, platform_session
from ..models import CustomRole, Department, KnowledgeDocument, Project, ProjectMember, User
from ..permissions import PERM_MEMBERS, add_project_member, has_perm, is_admin, normalize_role, require_perm
from ..schemas import InviteUserIn, InviteUserOut, TeamMemberOut, UpdateUserIn
from ..tenants import login_taken, register_account

router = APIRouter(prefix="/api", tags=["users"])

MEMBER_ROLES = {"管理员", "项目经理", "撰写专家", "评标专家", "成员"}
ADMIN_ROLE = "管理员"


def _project_counts(db: Session, user_ids: list[str]) -> dict[str, int]:
    if not user_ids:
        return {}
    rows = (
        db.query(ProjectMember.user_id, func.count(ProjectMember.id))
        .filter(ProjectMember.user_id.in_(user_ids))
        .group_by(ProjectMember.user_id)
        .all()
    )
    return {uid: int(cnt) for uid, cnt in rows}


def _mask_phone(phone: str) -> str:
    if len(phone) < 7:
        return "***" if phone else ""
    return phone[:3] + "****" + phone[-4:]


def _dept_names(db: Session) -> dict[str, str]:
    return {d.id: d.name for d in db.query(Department).all()}


def _to_member(user: User, project_count: int, *, full: bool = True, depts: dict[str, str] | None = None) -> TeamMemberOut:
    phone = user.phone or ""
    dept_id = getattr(user, "department_id", None)
    return TeamMemberOut(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role or "成员",
        phone=phone if full else _mask_phone(phone),
        disabled=bool(getattr(user, "disabled", False)),
        projectCount=project_count,
        joinedAt=user.created_at.date().isoformat() if user.created_at else "",
        departmentId=dept_id,
        departmentName=(depts or {}).get(dept_id or "", ""),
        customRoleId=getattr(user, "custom_role_id", None),
        monthlyCreditLimit=getattr(user, "monthly_credit_limit", None) if full else None,
        lastLoginAt=user.last_login_at.isoformat(timespec="minutes") if getattr(user, "last_login_at", None) else "",
    )


def _tenant_id(db: Session) -> str | None:
    return db.info.get("tenant_id")


def _check_seats(db: Session) -> None:
    from ..platform_models import Tenant

    tenant_id = _tenant_id(db)
    if not tenant_id:
        return
    from ..tenants import KIND_PERSONAL, tenant_kind

    with platform_session() as pdb:
        tenant = pdb.get(Tenant, tenant_id)
        seats = int(tenant.seats or 0) if tenant else 0
        personal = tenant_kind(tenant) == KIND_PERSONAL
    if personal:
        raise HTTPException(402, "个人版只有本人一个账号，升级为企业后可邀请成员共享积分池")
    used = db.query(func.count(User.id)).filter(User.disabled.is_(False)).scalar() or 0
    if seats and used >= seats:
        raise HTTPException(402, f"席位已满（{used}/{seats}），请升级套餐或停用不再使用的账号")


def _check_department(db: Session, department_id: str | None) -> None:
    if department_id and not db.get(Department, department_id):
        raise HTTPException(400, "部门不存在")


def _check_custom_role(db: Session, role_id: str | None) -> None:
    if role_id and not db.get(CustomRole, role_id):
        raise HTTPException(400, "自定义角色不存在")


@router.get("/users", response_model=list[TeamMemberOut])
def list_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[TeamMemberOut]:
    # 只会列出本企业 schema 内的成员；没有成员管理权限的人只看脱敏手机号
    full = has_perm(current_user, PERM_MEMBERS)
    users = db.query(User).order_by(User.created_at.asc()).all()
    counts = _project_counts(db, [u.id for u in users])
    depts = _dept_names(db)
    return [_to_member(u, counts.get(u.id, 0), full=full or u.id == current_user.id, depts=depts) for u in users]


@router.post("/users", response_model=InviteUserOut)
def invite_user(
    payload: InviteUserIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InviteUserOut:
    require_perm(current_user, PERM_MEMBERS)
    name = payload.name.strip()
    account = normalize_account(payload.email)
    if not name or not account:
        raise HTTPException(400, "请填写姓名与账号")
    if any(ch.isspace() for ch in account) or len(account) > 64:
        raise HTTPException(400, "账号不能含空格，且不超过 64 位")
    role = payload.role.strip() or "撰写专家"
    if role not in MEMBER_ROLES:
        raise HTTPException(400, "角色不合法")
    if role == ADMIN_ROLE and not is_admin(current_user):
        raise HTTPException(403, "只有管理员可以添加管理员")
    if find_user_by_account(db, account):
        raise HTTPException(409, "该账号已存在")
    tenant_id = _tenant_id(db)
    if tenant_id:
        with platform_session() as pdb:
            if login_taken(pdb, account):
                raise HTTPException(409, "该账号已被占用")
    _check_seats(db)
    _check_department(db, payload.departmentId)
    _check_custom_role(db, payload.customRoleId)

    password = (payload.password or "").strip() or random_password()
    if len(password) < 8:
        raise HTTPException(400, "密码至少 8 位")

    user = User(
        name=name,
        email=account,
        password_hash=hash_password(password),
        phone=payload.phone.strip(),
        role=role,
        position=role,
        department_id=payload.departmentId,
        custom_role_id=payload.customRoleId,
        monthly_credit_limit=payload.monthlyCreditLimit,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    if tenant_id:
        with platform_session() as pdb:
            register_account(pdb, account, tenant_id, user.id)
            pdb.commit()
    member = _to_member(user, 0, depts=_dept_names(db))
    return InviteUserOut(**member.model_dump(), initialPassword=password)


def handover(db: Session, source: User, target: User, operator: User) -> dict:
    """成员离职交接：名下项目、个人库文档和项目成员身份转给 target。"""
    projects = db.query(Project).filter(Project.owner_id == source.id).all()
    for project in projects:
        project.owner_id = target.id
        project.owner = target.name
        add_project_member(db, project.id, target.id)
    member_of = [row[0] for row in db.query(ProjectMember.project_id).filter(ProjectMember.user_id == source.id).all()]
    for project_id in member_of:
        add_project_member(db, project_id, target.id)
    docs = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.owner_id == source.id, KnowledgeDocument.scope == "个人库")
        .all()
    )
    for doc in docs:
        doc.owner_id = target.id
    write_audit(
        db,
        action="成员交接",
        user_name=operator.name,
        target=source.name,
        detail=f"交接给 {target.name}：项目 {len(projects)} 个、参与项目 {len(member_of)} 个、个人库文档 {len(docs)} 份",
    )
    return {"projects": len(projects), "memberOf": len(member_of), "documents": len(docs)}


@router.patch("/users/{user_id}", response_model=TeamMemberOut)
def update_user(
    user_id: str,
    payload: UpdateUserIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TeamMemberOut:
    require_perm(current_user, PERM_MEMBERS)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "成员不存在")
    if not is_admin(current_user) and normalize_role(user.role) == ADMIN_ROLE:
        raise HTTPException(403, "只有管理员可以调整管理员账号")

    if payload.name is not None:
        user.name = payload.name.strip() or user.name
    if payload.phone is not None:
        user.phone = payload.phone.strip()
    if payload.role is not None:
        role = payload.role.strip()
        if role not in MEMBER_ROLES:
            raise HTTPException(400, "角色不合法")
        if role != (user.role or "") and user.id == current_user.id:
            raise HTTPException(400, "不能修改自己的角色")
        if role == ADMIN_ROLE and not is_admin(current_user):
            raise HTTPException(403, "只有管理员可以授予管理员角色")
        user.role = role
        user.position = role
    if payload.departmentId is not None:
        _check_department(db, payload.departmentId or None)
        user.department_id = payload.departmentId or None
    if payload.customRoleId is not None:
        if user.id == current_user.id:
            raise HTTPException(400, "不能修改自己的角色")
        _check_custom_role(db, payload.customRoleId or None)
        user.custom_role_id = payload.customRoleId or None
    if payload.monthlyCreditLimit is not None:
        user.monthly_credit_limit = None if payload.monthlyCreditLimit < 0 else payload.monthlyCreditLimit
    if payload.disabled is not None:
        if user.id == current_user.id:
            raise HTTPException(400, "不能停用当前登录账号")
        if not payload.disabled and user.disabled:
            _check_seats(db)
        user.disabled = payload.disabled
        if payload.disabled:
            revoke_tokens(user)
    if payload.handoverTo:
        target = db.get(User, payload.handoverTo)
        if not target or target.id == user.id or target.disabled:
            raise HTTPException(400, "交接对象不存在或已停用")
        handover(db, user, target, current_user)

    db.commit()
    db.refresh(user)
    counts = _project_counts(db, [user.id])
    return _to_member(user, counts.get(user.id, 0), depts=_dept_names(db))
