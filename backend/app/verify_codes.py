"""注册验证码。短信/邮件通道未接入时（VERIFY_CODE_CHANNEL=mock）验证码写日志，开发联调用。"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .config import get_settings

logger = logging.getLogger(__name__)

CODE_TTL_MINUTES = 10
MAX_ATTEMPTS = 5


def _hash(target: str, code: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"{target}|{code}".encode(), hashlib.sha256).hexdigest()


def _deliver(target: str, code: str) -> None:
    channel = (get_settings().verify_code_channel or "mock").lower()
    if channel == "mock":
        logger.warning("验证码（mock 通道）%s -> %s", target, code)
        return
    # 正式通道（阿里云短信 / 企业邮箱 SMTP）在此接入
    raise HTTPException(503, "验证码通道未配置，请联系平台客服")


def issue(db: Session, target: str, purpose: str = "signup") -> None:
    from .platform_models import VerifyCode

    code = f"{secrets.randbelow(1_000_000):06d}"
    db.query(VerifyCode).filter(VerifyCode.target == target, VerifyCode.purpose == purpose, VerifyCode.used.is_(False)).update(
        {VerifyCode.used: True}, synchronize_session=False
    )
    db.add(
        VerifyCode(
            target=target,
            purpose=purpose,
            code_hash=_hash(target, code),
            expires_at=datetime.utcnow() + timedelta(minutes=CODE_TTL_MINUTES),
        )
    )
    db.commit()
    _deliver(target, code)


def required() -> bool:
    return (get_settings().verify_code_channel or "mock").lower() != "off"


def consume(db: Session, target: str, code: str, purpose: str = "signup") -> None:
    """校验并作废验证码。VERIFY_CODE_CHANNEL=off 时不校验（仅限内网测试环境）。"""
    from .platform_models import VerifyCode

    if not required():
        return
    row = (
        db.query(VerifyCode)
        .filter(VerifyCode.target == target, VerifyCode.purpose == purpose, VerifyCode.used.is_(False))
        .order_by(VerifyCode.created_at.desc())
        .first()
    )
    if row is None or row.expires_at < datetime.utcnow():
        raise HTTPException(400, "验证码已失效，请重新获取")
    if row.attempts >= MAX_ATTEMPTS:
        row.used = True
        db.commit()
        raise HTTPException(400, "验证码错误次数过多，请重新获取")
    if not hmac.compare_digest(row.code_hash, _hash(target, (code or "").strip())):
        row.attempts += 1
        db.commit()
        raise HTTPException(400, "验证码不正确")
    row.used = True
