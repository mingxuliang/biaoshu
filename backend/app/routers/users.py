from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import get_current_user, hash_password
from ..db import get_db
from ..models import ProjectMember, User
from ..permissions import PERM_MEMBERS, require_perm
from ..schemas import InviteUserIn, InviteUserOut, TeamMemberOut, UpdateUserIn

router = APIRouter(prefix="/api", tags=["users"])

MEMBER_ROLES = {"管理员", "项目经理", "撰写专家", "评标专家", "成员"}
DEFAULT_PASSWORD = "123456"


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


def _to_member(user: User, project_count: int) -> TeamMemberOut:
    return TeamMemberOut(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role or "成员",
        phone=user.phone or "",
        disabled=bool(getattr(user, "disabled", False)),
        projectCount=project_count,
        joinedAt=user.created_at.date().isoformat() if user.created_at else "",
    )


@router.get("/users", response_model=list[TeamMemberOut])
def list_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[TeamMemberOut]:
    users = db.query(User).order_by(User.created_at.asc()).all()
    counts = _project_counts(db, [u.id for u in users])
    return [_to_member(u, counts.get(u.id, 0)) for u in users]


@router.post("/users", response_model=InviteUserOut)
def invite_user(
    payload: InviteUserIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InviteUserOut:
    require_perm(current_user, PERM_MEMBERS)
    name = payload.name.strip()
    email = payload.email.strip().lower()
    if not name or not email:
        raise HTTPException(400, "请填写姓名与邮箱")
    role = payload.role.strip() or "撰写专家"
    if role not in MEMBER_ROLES:
        raise HTTPException(400, "角色不合法")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "该邮箱已注册")

    user = User(
        name=name,
        email=email,
        password_hash=hash_password(DEFAULT_PASSWORD),
        phone=payload.phone.strip(),
        role=role,
        position=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    member = _to_member(user, 0)
    return InviteUserOut(**member.model_dump(), initialPassword=DEFAULT_PASSWORD)


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

    if payload.name is not None:
        user.name = payload.name.strip() or user.name
    if payload.phone is not None:
        user.phone = payload.phone.strip()
    if payload.role is not None:
        role = payload.role.strip()
        if role not in MEMBER_ROLES:
            raise HTTPException(400, "角色不合法")
        user.role = role
        user.position = role
    if payload.disabled is not None:
        if user.id == current_user.id:
            raise HTTPException(400, "不能停用当前登录账号")
        user.disabled = payload.disabled

    db.commit()
    db.refresh(user)
    counts = _project_counts(db, [user.id])
    return _to_member(user, counts.get(user.id, 0))
