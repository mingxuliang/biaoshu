"""平台定时任务（不属于任何企业）：关闭超时订单、释放过期预占、积分到期、套餐到期与余额提醒。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from celery import Task

from .celery_app import celery_app

logger = logging.getLogger(__name__)


class PlatformTask(Task):
    """平台任务不带企业上下文，绕过 TenantTask 的企业检查。"""

    def apply_async(self, args=None, kwargs=None, **options):
        return Task.apply_async(self, args=args, kwargs=kwargs, **options)

    def __call__(self, *args, **kwargs):
        return self.run(*args, **kwargs)


def _remind_once(pdb, key: str) -> bool:
    """同一提醒每天最多一次。"""
    from .platform_models import SystemSetting

    today = datetime.utcnow().strftime("%Y-%m-%d")
    row = pdb.get(SystemSetting, key)
    if row is not None and (row.value_json or {}).get("date") == today:
        return False
    if row is None:
        row = SystemSetting(key=key)
        pdb.add(row)
    row.value_json = {"date": today}
    return True


def _notify_admins(tenant_id: str, *, kind: str, title: str, body: str, link: str = "/billing") -> None:
    from .collab import notify
    from .db import tenant_session
    from .models import User
    from .permissions import PERM_BILLING, has_perm
    from .tenancy import use_tenant

    with use_tenant(tenant_id), tenant_session(tenant_id) as db:
        ids = [u.id for u in db.query(User).filter(User.disabled.is_(False)).all() if has_perm(u, PERM_BILLING)]
        notify(db, ids, kind=kind, title=title, body=body, link=link)
        db.commit()


def run_maintenance() -> dict:
    from . import billing
    from .db import platform_session
    from .payments.orders import close_expired_orders
    from .platform_models import Subscription, Tenant

    stats = {"closedOrders": 0, "releasedHolds": 0, "expiredCredits": 0, "reminders": 0}
    with platform_session() as pdb:
        stats["closedOrders"] = close_expired_orders(pdb)
    stats["releasedHolds"] = billing.release_stale_holds(180)

    now = datetime.utcnow()
    with platform_session() as pdb:
        tenants = pdb.query(Tenant).filter(Tenant.status.in_(("试用", "正常"))).all()
        tenant_rows = [(t.id, t.name, t.low_balance_threshold or 0, t.expires_at, t.trial_ends_at, t.status) for t in tenants]
        for sub in pdb.query(Subscription).filter(Subscription.status == "生效", Subscription.ends_at <= now).all():
            sub.status = "已过期"
        pdb.commit()

    for tid, name, threshold, expires_at, trial_ends_at, status in tenant_rows:
        try:
            stats["expiredCredits"] += billing.expire_credits(tid)
            with platform_session() as pdb:
                wallet = billing.balance_of(pdb, tid)
                messages = []
                if threshold and wallet["available"] < threshold and _remind_once(pdb, f"remind:lowbal:{tid}"):
                    messages.append(("余额不足提醒", f"企业可用积分仅剩 {wallet['available']}，低于预警值 {threshold}，请及时充值"))
                end = expires_at if status == "正常" else trial_ends_at
                if end and now < end <= now + timedelta(days=7) and _remind_once(pdb, f"remind:expire:{tid}"):
                    what = "套餐" if status == "正常" else "试用"
                    messages.append((f"{what}即将到期", f"{what}将于 {end.strftime('%Y-%m-%d')} 到期，到期后只能查看不能新建，请及时续费"))
                if wallet["expiringIn30Days"] > 0 and _remind_once(pdb, f"remind:credit-expire:{tid}"):
                    messages.append(("积分即将过期", f"有 {wallet['expiringIn30Days']} 积分将在 30 天内过期，请尽快使用"))
                pdb.commit()
            for title, body in messages:
                _notify_admins(tid, kind="billing", title=title, body=body)
                stats["reminders"] += 1
        except Exception:  # noqa: BLE001 —— 一家企业出错不影响其他企业
            logger.exception("企业 %s 定时维护失败", tid)
    return stats


@celery_app.task(name="platform_maintenance", base=PlatformTask)
def platform_maintenance() -> dict:
    return run_maintenance()


celery_app.conf.beat_schedule = {
    "platform-maintenance": {"task": "platform_maintenance", "schedule": 15 * 60},
}
