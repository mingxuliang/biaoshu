"""登录失败计数与锁定。

优先用 Redis（多进程、多实例共享计数），Redis 不可用时退回进程内计数，保证单机也有防爆破。
"""

from __future__ import annotations

import logging
import threading
import time

from .config import get_settings

logger = logging.getLogger(__name__)

_PREFIX = "login-fail:"
_lock = threading.Lock()
_memory: dict[str, tuple[int, float]] = {}
_redis_client = None
_redis_failed_at = 0.0


def _redis():
    global _redis_client, _redis_failed_at
    if _redis_client is not None:
        return _redis_client
    # Redis 连不上时 60 秒内不再重试，避免每次登录都卡在连接超时
    if _redis_failed_at and time.time() - _redis_failed_at < 60:
        return None
    try:
        import redis

        client = redis.Redis.from_url(get_settings().redis_url, socket_timeout=0.5, socket_connect_timeout=0.5)
        client.ping()
        _redis_client = client
        return client
    except Exception:  # noqa: BLE001
        _redis_failed_at = time.time()
        return None


def _window() -> int:
    return max(1, int(get_settings().login_lock_minutes or 15)) * 60


def _limit() -> int:
    return max(1, int(get_settings().login_max_failures or 5))


def failures(key: str) -> int:
    client = _redis()
    if client is not None:
        try:
            value = client.get(_PREFIX + key)
            return int(value or 0)
        except Exception:  # noqa: BLE001
            pass
    with _lock:
        count, expires = _memory.get(key, (0, 0.0))
        if expires and expires < time.time():
            _memory.pop(key, None)
            return 0
        return count


def is_locked(*keys: str) -> bool:
    limit = _limit()
    return any(key and failures(key) >= limit for key in keys)


def record_failure(*keys: str) -> None:
    window = _window()
    client = _redis()
    for key in keys:
        if not key:
            continue
        if client is not None:
            try:
                pipe = client.pipeline()
                pipe.incr(_PREFIX + key)
                pipe.expire(_PREFIX + key, window)
                pipe.execute()
                continue
            except Exception:  # noqa: BLE001
                pass
        with _lock:
            count, expires = _memory.get(key, (0, 0.0))
            if expires and expires < time.time():
                count = 0
            _memory[key] = (count + 1, time.time() + window)


def reset(*keys: str) -> None:
    client = _redis()
    for key in keys:
        if not key:
            continue
        if client is not None:
            try:
                client.delete(_PREFIX + key)
            except Exception:  # noqa: BLE001
                pass
        with _lock:
            _memory.pop(key, None)
