"""数据库里的第三方密钥（大模型 API Key）加密存储。

密钥由 SECRET_KEY 派生，换 SECRET_KEY 后旧密文无法解开，需要在模型配置页重新填写。
历史明文照常可读，下次保存或启动迁移时转成密文。
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.types import Text, TypeDecorator

from .config import get_settings

logger = logging.getLogger(__name__)

PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    digest = hashlib.sha256(("llm-key|" + get_settings().secret_key).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def is_encrypted(value: str | None) -> bool:
    return bool(value) and str(value).startswith(PREFIX)


def encrypt(value: str | None) -> str:
    text = value or ""
    if not text or is_encrypted(text):
        return text
    return PREFIX + _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(value: str | None) -> str:
    text = value or ""
    if not is_encrypted(text):
        return text
    try:
        return _fernet().decrypt(text[len(PREFIX) :].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.warning("API Key 解密失败（SECRET_KEY 可能已更换），请在模型配置页重新填写")
        return ""


class EncryptedText(TypeDecorator):
    """写库时加密、读出时解密；读到旧明文原样返回。"""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value) if value else value

    def process_result_value(self, value, dialect):
        return decrypt(value) if value else value
