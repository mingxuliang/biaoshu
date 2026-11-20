"""回收卡在 running 的后台任务。

worker 重启、被强杀或硬超时后，任务不会再回写状态，界面会一直转圈。
- worker 启动时：本 worker 没有任何在跑的任务，库里仍是 running 的都是上一次中断留下的，直接置 failed。
- 后端启动时：只回收超过阈值的，避免误伤另一台 worker 上正在跑的任务。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

INTERRUPTED = "任务被中断（服务重启或超时），请重新发起"


def reap_stuck_jobs(db: Session, older_than_minutes: int = 0) -> dict[str, int]:
    from .models import (
        EvaluationChecklist,
        KnowledgeDocument,
        ProductSourceDoc,
        QualificationSourceDoc,
        ReviewRun,
        WriterJob,
    )

    now = datetime.utcnow()
    cutoff = now - timedelta(minutes=older_than_minutes) if older_than_minutes else None
    counts: dict[str, int] = {}
    # (模型, 错误字段, 起算时间字段)
    targets = (
        (ReviewRun, "error_message", "created_at"),
        (EvaluationChecklist, "error", "created_at"),
        (WriterJob, "error", "created_at"),
        (QualificationSourceDoc, "error", "created_at"),
        (ProductSourceDoc, "error", "created_at"),
        (KnowledgeDocument, "error", "created_at"),
    )
    for model, error_field, stamp_field in targets:
        query = db.query(model).filter(model.status == "running")
        rows = query.all()
        n = 0
        for row in rows:
            stamp = getattr(row, stamp_field, None)
            if cutoff is not None and stamp is not None and stamp > cutoff:
                continue
            row.status = "failed"
            setattr(row, error_field, INTERRUPTED)
            if hasattr(row, "finished_at"):
                row.finished_at = now
            if hasattr(row, "note"):
                row.note = "任务中断"
            n += 1
        if n:
            counts[model.__name__] = n
    if counts:
        db.commit()
        logger.warning("reaped stuck jobs: %s", counts)
    return counts


def reap_all_tenants(older_than_minutes: int = 0) -> dict[str, dict[str, int]]:
    """逐个企业 schema 回收；同时释放超时未结算的积分预占。"""
    from .billing import release_stale_holds
    from .db import tenant_session
    from .tenancy import use_tenant
    from .tenants import active_tenant_ids

    result: dict[str, dict[str, int]] = {}
    for tenant_id in active_tenant_ids():
        with use_tenant(tenant_id):
            db = tenant_session(tenant_id)
            try:
                counts = reap_stuck_jobs(db, older_than_minutes=older_than_minutes)
                if counts:
                    result[tenant_id] = counts
            except Exception:  # noqa: BLE001 —— 一家企业出错不影响其他企业
                logger.exception("reap tenant %s failed", tenant_id)
            finally:
                db.close()
    try:
        release_stale_holds(max_age_minutes=max(older_than_minutes, 180))
    except Exception:  # noqa: BLE001
        logger.exception("release stale credit holds failed")
    return result
