from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import (
    create_access_token,
    find_user_by_account,
    get_current_user,
    hash_password,
    normalize_account,
    verify_password,
)
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
    account = normalize_account(payload.email)
    if not account or not payload.password:
        raise HTTPException(400, "账号和密码不能为空")
    if any(ch.isspace() for ch in account) or len(account) > 64:
        raise HTTPException(400, "账号不能含空格，且不超过 64 位")
    if find_user_by_account(db, account):
        raise HTTPException(409, "该账号已注册，请直接登录")

    user = User(
        name=payload.name.strip() or account,
        email=account,
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
    user = find_user_by_account(db, payload.email)
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "账号或密码不正确")
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
        new_account = normalize_account(payload.email)
        if new_account and new_account != (current_user.email or "").lower():
            if any(ch.isspace() for ch in new_account) or len(new_account) > 64:
                raise HTTPException(400, "账号不能含空格，且不超过 64 位")
            existing = find_user_by_account(db, new_account)
            if existing and existing.id != current_user.id:
                raise HTTPException(409, "该账号已被其他用户使用")
            current_user.email = new_account
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
