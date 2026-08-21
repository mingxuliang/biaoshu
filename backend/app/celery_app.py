from celery import Celery

from .config import get_settings

settings = get_settings()

celery_app = Celery(
    "prereview",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
)

# 放在文件末尾导入，注册 tasks.py 中用 @celery_app.task 装饰的任务
from . import tasks  # noqa: E402,F401
