import logging

from celery import Celery, Task
from celery.signals import worker_process_init, worker_ready

from .config import get_settings
from .tenancy import (
    TenantRequired,
    current_tenant,
    current_user_id,
    reset_user_id,
    set_user_id,
    use_tenant,
    valid_tenant_id,
)

settings = get_settings()
logger = logging.getLogger(__name__)

TENANT_HEADER = "tenant_id"
USER_HEADER = "user_id"


class TenantTask(Task):
    """投递时把当前企业 ID 和操作人放进消息头；执行时恢复企业上下文并按功能计费。
    缺企业 ID 的任务直接拒绝执行。"""

    def apply_async(self, args=None, kwargs=None, **options):
        tenant_id = current_tenant()
        if not tenant_id:
            raise TenantRequired(f"任务 {self.name} 投递时缺少企业上下文")
        headers = dict(options.pop("headers", None) or {})
        headers[TENANT_HEADER] = tenant_id
        headers[USER_HEADER] = current_user_id() or ""
        return super().apply_async(args=args, kwargs=kwargs, headers=headers, **options)

    def _header(self, name: str) -> str | None:
        request = self.request
        value = getattr(request, name, None)
        if not value:
            value = (getattr(request, "headers", None) or {}).get(name)
        return value or None

    def __call__(self, *args, **kwargs):
        from .billing import TASK_FEATURES, InsufficientCredits, metered

        tenant_id = self._header(TENANT_HEADER) or current_tenant()
        if not valid_tenant_id(tenant_id):
            raise TenantRequired(f"任务 {self.name} 缺少企业上下文，拒绝执行")
        user_id = self._header(USER_HEADER) or current_user_id()
        feature = TASK_FEATURES.get(self.name)
        with use_tenant(tenant_id):
            user_token = set_user_id(user_id)
            try:
                if not feature:
                    return super().__call__(*args, **kwargs)
                ref_id = str(args[0]) if args else ""
                try:
                    with metered(feature, user_id=user_id, ref_id=ref_id) as meter:
                        result = super().__call__(*args, **kwargs)
                        # 任务体自己捕获异常并把记录置为 failed；失败的任务不收费
                        if meter is not None and job_failed(self.name, ref_id):
                            meter.refund = True
                        return result
                except InsufficientCredits as exc:
                    mark_job_failed(self.name, ref_id, exc.detail)
                    return None
            finally:
                reset_user_id(user_token)


def _job_target(task_name: str):
    from .models import (
        EvaluationChecklist,
        KnowledgeDocument,
        ProductSourceDoc,
        QualificationSourceDoc,
        ReviewRun,
        WriterJob,
    )

    targets = {
        "run_prereview_task": (ReviewRun, "error_message"),
        "run_tender_parse_task": (EvaluationChecklist, "error"),
        "run_product_extract_task": (ProductSourceDoc, "error"),
        "run_qualification_extract_task": (QualificationSourceDoc, "error"),
        "run_knowledge_ingest_task": (KnowledgeDocument, "error"),
    }
    return targets.get(task_name, (WriterJob, "error"))


def job_failed(task_name: str, ref_id: str) -> bool:
    from .db import SessionLocal

    model, _field = _job_target(task_name)
    db = SessionLocal()
    try:
        row = db.get(model, ref_id)
        return row is not None and getattr(row, "status", "") == "failed"
    except Exception:  # noqa: BLE001
        return False
    finally:
        db.close()


def mark_job_failed(task_name: str, ref_id: str, message: str) -> None:
    """余额不足等原因没能开始的任务，把对应记录标记失败，界面不会一直排队。"""
    from datetime import datetime

    from .db import SessionLocal

    model, field = _job_target(task_name)
    db = SessionLocal()
    try:
        row = db.get(model, ref_id)
        if row is None:
            return
        row.status = "failed"
        setattr(row, field, message)
        if hasattr(row, "finished_at"):
            row.finished_at = datetime.utcnow()
        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("标记任务失败出错 %s %s", task_name, ref_id)
    finally:
        db.close()


celery_app = Celery(
    "prereview",
    broker=settings.redis_url,
    backend=settings.redis_url,
    task_cls=TenantTask,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    # 没有单独声明时限的任务也要有上限，避免异常任务一直占着 worker；预审、招标解析在 tasks.py 里各自更短
    task_soft_time_limit=2 * 60 * 60,
    task_time_limit=2 * 60 * 60 + 600,
    worker_prefetch_multiplier=1,
)


@worker_process_init.connect
def _ensure_object_storage(**kwargs) -> None:
    from .storage import ensure_ready

    ensure_ready()


@worker_ready.connect
def _reap_interrupted_jobs(**kwargs) -> None:
    """worker 刚启动时没有在跑的任务，各企业库里残留的 running 都是上次中断的。"""
    from .job_reaper import reap_all_tenants

    reap_all_tenants()


# 放在文件末尾导入，注册 tasks.py 中用 @celery_app.task 装饰的任务
from . import platform_tasks, tasks  # noqa: E402,F401
