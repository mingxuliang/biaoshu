"""带 contextvars 的线程池：企业上下文和计费上下文要跟着并发的大模型调用走。"""

from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor


class ContextThreadPoolExecutor(ThreadPoolExecutor):
    def submit(self, fn, /, *args, **kwargs):
        ctx = contextvars.copy_context()
        return super().submit(ctx.run, fn, *args, **kwargs)
