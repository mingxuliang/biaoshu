"""密码哈希与 JWT 会话（P0：项目/认证真正落库）。"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def _decode_token(token: str) -> str:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "登录状态已失效，请重新登录") from exc
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(401, "登录状态已失效，请重新登录")
    return user_id


def get_current_user(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "缺少登录凭证，请先登录")
    token = authorization.split(" ", 1)[1].strip()
    user_id = _decode_token(token)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(401, "用户不存在，请重新登录")
    if getattr(user, "disabled", False):
        raise HTTPException(401, "账号已停用，请联系管理员")
    return user
