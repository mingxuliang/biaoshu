from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import create_access_token, get_current_user, hash_password, verify_password
from ..db import get_db
from ..models import User
from ..schemas import AuthOut, LoginIn, RegisterIn, UpdateProfileIn, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _to_user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        name=user.name,
        email=user.email,
        phone=user.phone or "",
        company=user.company or "",
        position=user.position or "",
        role=user.role or "成员",
    )


@router.post("/register", response_model=AuthOut)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> AuthOut:
    email = payload.email.strip().lower()
    if not email or not payload.password:
        raise HTTPException(400, "邮箱和密码不能为空")
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(409, "该邮箱已注册，请直接登录")

    user = User(
        name=payload.name.strip() or email,
        email=email,
        password_hash=hash_password(payload.password),
        phone=payload.phone,
        company=payload.company,
        position=payload.position,
        role="管理员" if db.query(User).count() == 0 else "成员",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id)
    return AuthOut(token=token, user=_to_user_out(user))


@router.post("/login", response_model=AuthOut)
def login(payload: LoginIn, db: Session = Depends(get_db)) -> AuthOut:
    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "邮箱或密码不正确")
    if getattr(user, "disabled", False):
        raise HTTPException(401, "账号已停用，请联系管理员")

    token = create_access_token(user.id)
    return AuthOut(token=token, user=_to_user_out(user))


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)) -> UserOut:
    return _to_user_out(current_user)


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: UpdateProfileIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    if payload.name is not None:
        current_user.name = payload.name.strip() or current_user.name
    if payload.email is not None:
        new_email = payload.email.strip().lower()
        if new_email and new_email != current_user.email:
            existing = db.query(User).filter(User.email == new_email).first()
            if existing and existing.id != current_user.id:
                raise HTTPException(409, "该邮箱已被其他账号使用")
            current_user.email = new_email
    if payload.phone is not None:
        current_user.phone = payload.phone
    if payload.company is not None:
        current_user.company = payload.company
    if payload.position is not None:
        current_user.position = payload.position
    if payload.password:
        current_user.password_hash = hash_password(payload.password)

    db.commit()
    db.refresh(current_user)
    return _to_user_out(current_user)
