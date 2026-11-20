"""平台后台的费用统计：按企业、按人员汇总充值、积分消耗和 Token 用量。

只返回统计数字和人员名单（姓名、账号、部门），不读取任何企业业务内容。
计费数据都在 platform schema，人员名单需要逐个企业 schema 读取，做短时缓存。
"""

from __future__ import annotations

import csv
import io
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from .db import tenant_session
from .tenancy import use_tenant, valid_tenant_id

DIRECTORY_TTL = 60
_directory_cache: dict = {"at": 0.0, "rows": []}
_directory_lock = threading.Lock()


def _dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


def period_start(days: int) -> datetime | None:
    return datetime.utcnow() - timedelta(days=days) if days and days > 0 else None


def month_start() -> datetime:
    return datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _since(query, column, since: datetime | None):
    return query.filter(column >= since) if since is not None else query


# ---------------------------------------------------------------------------
# 人员名单
# ---------------------------------------------------------------------------


def user_directory(pdb: Session, *, refresh: bool = False) -> list[dict]:
    """全平台人员名单（未注销的企业和个人账号）。"""
    with _directory_lock:
        if not refresh and time.time() - _directory_cache["at"] < DIRECTORY_TTL:
            return _directory_cache["rows"]
    from .models import Department, User
    from .platform_models import Tenant
    from .tenants import tenant_kind

    rows: list[dict] = []
    tenants = pdb.query(Tenant).filter(Tenant.status != "已注销").all()
    for t in tenants:
        if not valid_tenant_id(t.id):
            continue
        try:
            with use_tenant(t.id), tenant_session(t.id) as db:
                depts = {d.id: d.name for d in db.query(Department.id, Department.name).all()}
                for u in db.query(User).all():
                    rows.append(
                        {
                            "tenantId": t.id,
                            "tenantName": t.name,
                            "tenantKind": tenant_kind(t),
                            "userId": u.id,
                            "name": u.name or "",
                            "account": u.email or "",
                            "role": u.role or "成员",
                            "departmentName": depts.get(getattr(u, "department_id", None) or "", ""),
                            "monthlyCreditLimit": getattr(u, "monthly_credit_limit", None),
                            "disabled": bool(u.disabled),
                            "lastLoginAt": _dt(getattr(u, "last_login_at", None)),
                        }
                    )
        except Exception:  # noqa: BLE001 —— 个别企业 schema 异常不影响整体统计
            continue
    with _directory_lock:
        _directory_cache.update(at=time.time(), rows=rows)
    return rows


def clear_directory_cache() -> None:
    with _directory_lock:
        _directory_cache.update(at=0.0, rows=[])


# ---------------------------------------------------------------------------
# 企业费用
# ---------------------------------------------------------------------------


def _spent_by(pdb: Session, keys: tuple, since: datetime | None, tenant_id: str = "") -> dict:
    from .platform_models import CreditLedger

    q = pdb.query(*keys, func.sum(CreditLedger.amount)).filter(CreditLedger.kind == "消费")
    if tenant_id:
        q = q.filter(CreditLedger.tenant_id == tenant_id)
    q = _since(q, CreditLedger.created_at, since)
    return {tuple(row[:-1]) if len(keys) > 1 else row[0]: -int(row[-1] or 0) for row in q.group_by(*keys).all()}


def _usage_by(pdb: Session, keys: tuple, since: datetime | None, tenant_id: str = "") -> dict:
    from .platform_models import UsageRecord

    q = pdb.query(
        *keys,
        func.sum(UsageRecord.prompt_tokens),
        func.sum(UsageRecord.completion_tokens),
        func.sum(UsageRecord.calls),
        func.max(UsageRecord.created_at),
    )
    if tenant_id:
        q = q.filter(UsageRecord.tenant_id == tenant_id)
    q = _since(q, UsageRecord.created_at, since)
    out = {}
    for row in q.group_by(*keys).all():
        key = tuple(row[: len(keys)]) if len(keys) > 1 else row[0]
        p, c, n, last = row[len(keys) :]
        out[key] = {"promptTokens": int(p or 0), "completionTokens": int(c or 0), "calls": int(n or 0), "lastUsedAt": last}
    return out


TENANT_SORTS = {
    "spent": lambda r: -r["periodCredits"],
    "tokens": lambda r: -(r["promptTokens"] + r["completionTokens"]),
    "balance": lambda r: -r["available"],
    "paid": lambda r: -r["paidCents"],
    "lastUsed": lambda r: r["lastUsedAt"] or "",
}


def tenant_fees(pdb: Session, *, q: str = "", kind: str = "", days: int = 30, sort: str = "spent") -> dict:
    """返回 {"items": [...], "summary": {...}}；items 已排序，未分页。"""
    from .platform_models import CreditLedger, Plan, RechargeOrder, Tenant, UsageRecord, Wallet
    from .tenants import tenant_kind

    since = period_start(days)
    query = pdb.query(Tenant).filter(Tenant.status != "已注销")
    if kind:
        query = query.filter(Tenant.kind == kind)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter((Tenant.name.ilike(like)) | (Tenant.id.ilike(like)))
    tenants = query.all()
    wallets = {w.tenant_id: w for w in pdb.query(Wallet).all()}
    plans = dict(pdb.query(Plan.code, Plan.name).all())

    paid_q = pdb.query(RechargeOrder.tenant_id, func.sum(RechargeOrder.amount_cents), func.sum(RechargeOrder.refunded_cents)).filter(
        RechargeOrder.status.in_(("已支付", "已退款"))
    )
    paid_q = _since(paid_q, RechargeOrder.paid_at, since)
    paid = {tid: (int(a or 0), int(r or 0)) for tid, a, r in paid_q.group_by(RechargeOrder.tenant_id).all()}
    spent = _spent_by(pdb, (CreditLedger.tenant_id,), since)
    usage = _usage_by(pdb, (UsageRecord.tenant_id,), since)
    last_any = dict(pdb.query(UsageRecord.tenant_id, func.max(UsageRecord.created_at)).group_by(UsageRecord.tenant_id).all())
    active_q = pdb.query(UsageRecord.tenant_id, func.count(func.distinct(UsageRecord.user_id))).filter(UsageRecord.user_id.isnot(None))
    active = dict(_since(active_q, UsageRecord.created_at, since).group_by(UsageRecord.tenant_id).all())

    items = []
    for t in tenants:
        w = wallets.get(t.id)
        balance, held = (int(w.balance or 0), int(w.held or 0)) if w else (0, 0)
        u = usage.get(t.id, {})
        paid_cents, refunded_cents = paid.get(t.id, (0, 0))
        items.append(
            {
                "tenantId": t.id,
                "tenantName": t.name,
                "kind": tenant_kind(t),
                "status": t.status,
                "planCode": t.plan_code or "",
                "planName": plans.get(t.plan_code or "", t.plan_code or ""),
                "expiresAt": _dt(t.trial_ends_at if t.status == "试用" else t.expires_at),
                "seats": int(t.seats or 0),
                "members": None,
                "balance": balance,
                "held": held,
                "available": balance - held,
                "lowBalance": balance - held < int(t.low_balance_threshold or 0),
                "totalRecharged": int(w.total_recharged or 0) if w else 0,
                "totalConsumed": int(w.total_consumed or 0) if w else 0,
                "paidCents": paid_cents,
                "refundedCents": refunded_cents,
                "periodCredits": spent.get(t.id, 0),
                "promptTokens": u.get("promptTokens", 0),
                "completionTokens": u.get("completionTokens", 0),
                "calls": u.get("calls", 0),
                "activeUsers": int(active.get(t.id) or 0),
                "lastUsedAt": _dt(last_any.get(t.id)),
            }
        )
    key = TENANT_SORTS.get(sort, TENANT_SORTS["spent"])
    items.sort(key=key, reverse=(sort == "lastUsed"))
    summary = {
        "tenants": len(items),
        "activeTenants": sum(1 for r in items if r["periodCredits"] > 0 or r["calls"] > 0),
        "activeUsers": sum(r["activeUsers"] for r in items),
        "paidCents": sum(r["paidCents"] for r in items),
        "refundedCents": sum(r["refundedCents"] for r in items),
        "periodCredits": sum(r["periodCredits"] for r in items),
        "promptTokens": sum(r["promptTokens"] for r in items),
        "completionTokens": sum(r["completionTokens"] for r in items),
        "available": sum(r["available"] for r in items),
    }
    return {"days": days, "items": items, "summary": summary}


def fill_members(items: list[dict]) -> None:
    from .tenants import seats_used

    for row in items:
        try:
            row["members"] = seats_used(row["tenantId"])
        except Exception:  # noqa: BLE001
            row["members"] = None


# ---------------------------------------------------------------------------
# 人员费用
# ---------------------------------------------------------------------------

USER_SORTS = {
    "spent": lambda r: -r["periodCredits"],
    "month": lambda r: -r["monthSpent"],
    "tokens": lambda r: -(r["promptTokens"] + r["completionTokens"]),
    "total": lambda r: -r["totalSpent"],
    "lastUsed": lambda r: r["lastUsedAt"] or "",
}


def user_fees(pdb: Session, *, q: str = "", tenant_id: str = "", kind: str = "", days: int = 30, sort: str = "spent") -> list[dict]:
    from .platform_models import CreditLedger, UsageRecord

    since = period_start(days)
    keys = (CreditLedger.tenant_id, CreditLedger.user_id)
    period = _spent_by(pdb, keys, since, tenant_id)
    month = _spent_by(pdb, keys, month_start(), tenant_id)
    total = _spent_by(pdb, keys, None, tenant_id)
    usage = _usage_by(pdb, (UsageRecord.tenant_id, UsageRecord.user_id), since, tenant_id)
    last_q = pdb.query(UsageRecord.tenant_id, UsageRecord.user_id, func.max(UsageRecord.created_at))
    if tenant_id:
        last_q = last_q.filter(UsageRecord.tenant_id == tenant_id)
    last_any = {(t, u): v for t, u, v in last_q.group_by(UsageRecord.tenant_id, UsageRecord.user_id).all()}

    needle = q.strip().lower()
    out = []
    for person in user_directory(pdb):
        if tenant_id and person["tenantId"] != tenant_id:
            continue
        if kind and person["tenantKind"] != kind:
            continue
        if needle and not any(needle in (person[f] or "").lower() for f in ("name", "account", "tenantName", "departmentName")):
            continue
        k = (person["tenantId"], person["userId"])
        u = usage.get(k, {})
        out.append(
            {
                **person,
                "periodCredits": period.get(k, 0),
                "monthSpent": month.get(k, 0),
                "totalSpent": total.get(k, 0),
                "promptTokens": u.get("promptTokens", 0),
                "completionTokens": u.get("completionTokens", 0),
                "calls": u.get("calls", 0),
                "lastUsedAt": _dt(last_any.get(k)),
            }
        )
    out.sort(key=USER_SORTS.get(sort, USER_SORTS["spent"]), reverse=(sort == "lastUsed"))
    return out


def user_usage(pdb: Session, tenant_id: str, user_id: str, days: int = 30) -> dict:
    """单个人员：按功能、按模型的消耗和按日趋势。"""
    from . import billing
    from .platform_models import CreditLedger, PriceRule, UsageRecord

    days = days if days and days > 0 else 90
    since = period_start(days)
    names = {f: v[0] for f, v in billing.DEFAULT_PRICES.items()}
    names.update(dict(pdb.query(PriceRule.feature, PriceRule.name).all()))

    lq = pdb.query(CreditLedger).filter(
        CreditLedger.tenant_id == tenant_id, CreditLedger.user_id == user_id, CreditLedger.kind == "消费", CreditLedger.created_at >= since
    )
    uq = pdb.query(UsageRecord).filter(UsageRecord.tenant_id == tenant_id, UsageRecord.user_id == user_id, UsageRecord.created_at >= since)

    credits_by_feature: dict[str, int] = {}
    daily: dict[str, dict] = {}
    for row in lq.all():
        f = row.feature or "other"
        credits_by_feature[f] = credits_by_feature.get(f, 0) - int(row.amount or 0)
        d = daily.setdefault(row.created_at.strftime("%Y-%m-%d"), {"credits": 0, "tokens": 0})
        d["credits"] -= int(row.amount or 0)
    tokens_by_feature: dict[str, list[int]] = {}
    by_model: dict[str, list[float]] = {}
    for row in uq.all():
        f = row.feature or "other"
        slot = tokens_by_feature.setdefault(f, [0, 0, 0])
        slot[0] += int(row.prompt_tokens or 0)
        slot[1] += int(row.completion_tokens or 0)
        slot[2] += int(row.calls or 0)
        m = by_model.setdefault(row.model or "", [0, 0, 0, 0.0])
        m[0] += int(row.prompt_tokens or 0)
        m[1] += int(row.completion_tokens or 0)
        m[2] += int(row.calls or 0)
        m[3] += float(row.credits or 0)
        d = daily.setdefault(row.created_at.strftime("%Y-%m-%d"), {"credits": 0, "tokens": 0})
        d["tokens"] += int(row.prompt_tokens or 0) + int(row.completion_tokens or 0)

    features = sorted(set(credits_by_feature) | set(tokens_by_feature), key=lambda f: -credits_by_feature.get(f, 0))
    today = datetime.utcnow().date()
    trend_days = min(days, 90)
    trend = []
    for i in range(trend_days - 1, -1, -1):
        day = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        trend.append({"date": day, **daily.get(day, {"credits": 0, "tokens": 0})})
    return {
        "days": days,
        "byFeature": [
            {
                "feature": f,
                "name": names.get(f, f),
                "credits": credits_by_feature.get(f, 0),
                "promptTokens": tokens_by_feature.get(f, [0, 0, 0])[0],
                "completionTokens": tokens_by_feature.get(f, [0, 0, 0])[1],
                "calls": tokens_by_feature.get(f, [0, 0, 0])[2],
            }
            for f in features
        ],
        "byModel": sorted(
            (
                {"model": k, "promptTokens": v[0], "completionTokens": v[1], "calls": v[2], "credits": round(v[3], 2)}
                for k, v in by_model.items()
            ),
            key=lambda r: -(r["promptTokens"] + r["completionTokens"]),
        ),
        "trend": trend,
    }


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------

TENANT_COLUMNS = [
    ("类型", "kind"),
    ("名称", "tenantName"),
    ("编号", "tenantId"),
    ("状态", "status"),
    ("套餐", "planName"),
    ("到期", "expiresAt"),
    ("成员数", "members"),
    ("席位", "seats"),
    ("可用积分", "available"),
    ("冻结积分", "held"),
    ("充值金额(元)", "paidYuan"),
    ("退款金额(元)", "refundedYuan"),
    ("期间消耗积分", "periodCredits"),
    ("期间输入Token", "promptTokens"),
    ("期间输出Token", "completionTokens"),
    ("期间调用次数", "calls"),
    ("期间活跃人数", "activeUsers"),
    ("累计充值积分", "totalRecharged"),
    ("累计消耗积分", "totalConsumed"),
    ("最近使用", "lastUsedAt"),
]

USER_COLUMNS = [
    ("账号类型", "tenantKind"),
    ("企业/个人空间", "tenantName"),
    ("姓名", "name"),
    ("账号", "account"),
    ("角色", "role"),
    ("部门", "departmentName"),
    ("停用", "disabledText"),
    ("月度额度", "monthlyCreditLimit"),
    ("本月已用积分", "monthSpent"),
    ("期间消耗积分", "periodCredits"),
    ("期间输入Token", "promptTokens"),
    ("期间输出Token", "completionTokens"),
    ("期间调用次数", "calls"),
    ("累计消耗积分", "totalSpent"),
    ("最近使用", "lastUsedAt"),
    ("最近登录", "lastLoginAt"),
]


def to_csv(rows: list[dict], columns: list[tuple[str, str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for label, _ in columns])
    for row in rows:
        extra = {
            "paidYuan": f"{row.get('paidCents', 0) / 100:.2f}",
            "refundedYuan": f"{row.get('refundedCents', 0) / 100:.2f}",
            "disabledText": "是" if row.get("disabled") else "",
        }
        writer.writerow(["" if (v := {**row, **extra}.get(key)) is None else v for _, key in columns])
    # Excel 打开中文 CSV 需要 BOM
    return ("\ufeff" + buf.getvalue()).encode("utf-8")
