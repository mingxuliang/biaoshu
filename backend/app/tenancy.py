"""租户上下文。

每家企业一个 Postgres schema（t_<租户ID>）和一个 MinIO bucket。请求依赖和 Celery 任务在入口处
设置 current_tenant，数据库会话、对象存储和计费都从这里取企业身份；取不到就报错，绝不回退到公共数据。
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

DEFAULT_TENANT = "default"
PLATFORM_SCHEMA = "platform"
TENANT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{1,39}$")

_current: ContextVar[str | None] = ContextVar("current_tenant", default=None)
# 发起操作的企业成员，用于计费归属和个人限额；系统任务为空
_user: ContextVar[str | None] = ContextVar("current_user_id", default=None)


def current_user_id() -> str | None:
    return _user.get()


def set_user_id(user_id: str | None):
    return _user.set(user_id)


def reset_user_id(token) -> None:
    _user.reset(token)


class TenantRequired(RuntimeError):
    """没有企业上下文时访问企业数据。"""


def valid_tenant_id(tenant_id: str | None) -> bool:
    return bool(tenant_id) and bool(TENANT_ID_RE.match(tenant_id or ""))


def schema_for(tenant_id: str) -> str:
    if not valid_tenant_id(tenant_id):
        raise TenantRequired(f"非法企业标识：{tenant_id!r}")
    return f"t_{tenant_id}"


def current_tenant() -> str | None:
    return _current.get()


def require_tenant() -> str:
    tenant_id = _current.get()
    if not tenant_id:
        raise TenantRequired("缺少企业上下文")
    return tenant_id


def set_tenant(tenant_id: str | None):
    if tenant_id is not None and not valid_tenant_id(tenant_id):
        raise TenantRequired(f"非法企业标识：{tenant_id!r}")
    return _current.set(tenant_id)


def reset_tenant(token) -> None:
    _current.reset(token)


@contextmanager
def use_tenant(tenant_id: str) -> Iterator[str]:
    token = set_tenant(tenant_id)
    try:
        yield tenant_id
    finally:
        _current.reset(token)


def bucket_for(tenant_id: str) -> str:
    """默认企业沿用历史 bucket，存量对象不用搬迁；其余企业各自一个 bucket。"""
    from .config import get_settings

    settings = get_settings()
    if tenant_id == DEFAULT_TENANT:
        return settings.minio_bucket
    schema_for(tenant_id)
    return f"{settings.minio_bucket_prefix}-{tenant_id.replace('_', '-')}"
