"""积分计费。

- 钱包按企业共享；积分分桶，扣费时按到期日从早到晚，永不过期的桶最后扣。
- 流水只追加。所有改余额的操作都先锁钱包行（Postgres SELECT ... FOR UPDATE），并发扣减不会超扣。
- 任务开始前预占（hold），结束按实际 token 结算，失败整笔释放。
- 大模型调用在 llm.chat_complete 里上报用量；计费上下文（Meter）用 contextvar 跟随任务和线程池。
"""

from __future__ import annotations

import logging
import math
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterator

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import platform_session
from .tenancy import current_tenant, current_user_id

logger = logging.getLogger(__name__)

# 功能编码 -> (名称, 计费方式, 单价, 预占)
DEFAULT_PRICES: dict[str, tuple[str, str, float, int]] = {
    "tender_parse": ("招标文件解析", "per_1k_tokens", 0.3, 40),
    "outline": ("目录大纲生成", "free", 0.0, 0),
    "chapter": ("正文生成", "per_1k_tokens", 1.0, 60),
    "batch_chapter": ("批量正文生成", "per_1k_tokens", 1.0, 300),
    "writer_chat": ("AI 对话改写", "per_1k_tokens", 0.8, 20),
    "prereview": ("标书预审", "per_1k_tokens", 0.6, 80),
    "product_match": ("产品功能匹配", "per_1k_tokens", 0.5, 20),
    "product_extract": ("产品库解析入库", "per_1k_tokens", 0.5, 30),
    "qualification_extract": ("资质证照识别", "per_1k_tokens", 0.5, 30),
    "knowledge_ingest": ("文档库入库", "free", 0.0, 0),
    "image": ("AI 配图", "per_call", 5.0, 5),
    "other": ("其他模型调用", "per_1k_tokens", 1.0, 0),
}

TASK_FEATURES = {
    "run_prereview_task": "prereview",
    "run_tender_parse_task": "tender_parse",
    "run_outline_generate_task": "outline",
    "run_chapter_generate_task": "chapter",
    "run_batch_generate_task": "batch_chapter",
    "run_writer_chat_task": "writer_chat",
    "run_product_match_task": "product_match",
    "run_product_extract_task": "product_extract",
    "run_qualification_extract_task": "qualification_extract",
    "run_knowledge_ingest_task": "knowledge_ingest",
}


class InsufficientCredits(HTTPException):
    def __init__(self, need: int, available: int, reason: str = "") -> None:
        detail = reason or f"积分不足：本次预计需要 {need} 积分，可用 {max(available, 0)} 积分，请充值后重试"
        super().__init__(status_code=402, detail=detail)
        self.need = need
        self.available = available


# ---------------------------------------------------------------------------
# 钱包与积分桶
# ---------------------------------------------------------------------------


def ensure_wallet(pdb: Session, tenant_id: str):
    from .platform_models import Wallet

    wallet = pdb.get(Wallet, tenant_id)
    if wallet is None:
        wallet = Wallet(tenant_id=tenant_id, balance=0, held=0, total_recharged=0, total_consumed=0)
        pdb.add(wallet)
        pdb.flush()
    return wallet


def _lock_wallet(pdb: Session, tenant_id: str):
    from .platform_models import Wallet

    ensure_wallet(pdb, tenant_id)
    return pdb.query(Wallet).filter(Wallet.tenant_id == tenant_id).with_for_update().one()


def _ledger(pdb: Session, tenant_id: str, wallet, *, kind: str, amount: int, **kw):
    from .platform_models import CreditLedger

    row = CreditLedger(
        tenant_id=tenant_id,
        kind=kind,
        amount=amount,
        balance_after=wallet.balance,
        user_id=kw.get("user_id"),
        user_name=kw.get("user_name") or "",
        feature=kw.get("feature") or "",
        ref_id=kw.get("ref_id") or "",
        idem_key=kw.get("idem_key"),
        note=kw.get("note") or "",
        operator=kw.get("operator") or "",
    )
    pdb.add(row)
    # 会话 autoflush=False：同一事务里后续的幂等检查和扣费要能查到刚写入的流水和积分桶
    pdb.flush()
    return row


def _idem_hit(pdb: Session, idem_key: str | None):
    from .platform_models import CreditLedger

    if not idem_key:
        return None
    return pdb.query(CreditLedger).filter(CreditLedger.idem_key == idem_key).first()


def grant(
    pdb: Session,
    tenant_id: str,
    amount: int,
    *,
    source: str,
    expires_at: datetime | None = None,
    note: str = "",
    operator: str = "",
    idem_key: str | None = None,
    order_id: str | None = None,
    kind: str | None = None,
):
    """入账：新建一个积分桶。idem_key 相同的入账只记一次。调用方负责 commit。"""
    from .platform_models import CreditBucket

    if amount <= 0:
        raise ValueError("入账积分必须为正数")
    hit = _idem_hit(pdb, idem_key)
    if hit is not None:
        return hit
    wallet = _lock_wallet(pdb, tenant_id)
    pdb.add(
        CreditBucket(
            tenant_id=tenant_id, source=source, amount=amount, remaining=amount, expires_at=expires_at, order_id=order_id
        )
    )
    wallet.balance += amount
    if source in ("充值", "套餐"):
        wallet.total_recharged += amount
    return _ledger(
        pdb,
        tenant_id,
        wallet,
        kind=kind or ("赠送" if source in ("试用", "赠送") else source),
        amount=amount,
        note=note,
        operator=operator,
        idem_key=idem_key,
        ref_id=order_id or "",
    )


def _spendable_buckets(pdb: Session, tenant_id: str, now: datetime):
    from .platform_models import CreditBucket

    rows = (
        pdb.query(CreditBucket)
        .filter(CreditBucket.tenant_id == tenant_id, CreditBucket.remaining > 0)
        .with_for_update()
        .all()
    )
    live = [b for b in rows if b.expires_at is None or b.expires_at > now]
    # 先到期的先扣，永不过期的排最后；同到期日按入账先后
    live.sort(key=lambda b: (b.expires_at is None, b.expires_at or datetime.max, b.created_at or now))
    return live


def _take(pdb: Session, tenant_id: str, amount: int, now: datetime) -> int:
    """从积分桶扣 amount，返回实际扣到的数量（余额不够时少于 amount）。"""
    left = amount
    for bucket in _spendable_buckets(pdb, tenant_id, now):
        if left <= 0:
            break
        part = min(bucket.remaining, left)
        bucket.remaining -= part
        left -= part
    return amount - left


def consume(
    pdb: Session,
    tenant_id: str,
    amount: int,
    *,
    feature: str = "",
    ref_id: str = "",
    user_id: str | None = None,
    user_name: str = "",
    note: str = "",
    kind: str = "消费",
    operator: str = "",
    allow_partial: bool = False,
    idem_key: str | None = None,
):
    """扣费。余额不足时：allow_partial 扣光余额并在备注里记欠额，否则抛 402。调用方负责 commit。"""
    if amount <= 0:
        return None
    hit = _idem_hit(pdb, idem_key)
    if hit is not None:
        return hit
    wallet = _lock_wallet(pdb, tenant_id)
    now = datetime.utcnow()
    _expire_locked(pdb, tenant_id, wallet, now)
    if wallet.balance < amount and not allow_partial:
        raise InsufficientCredits(amount, wallet.balance)
    taken = _take(pdb, tenant_id, amount, now)
    wallet.balance -= taken
    wallet.total_consumed += taken if kind == "消费" else 0
    if taken < amount:
        note = (note + "；" if note else "") + f"余额不足，少扣 {amount - taken} 积分"
    return _ledger(
        pdb,
        tenant_id,
        wallet,
        kind=kind,
        amount=-taken,
        feature=feature,
        ref_id=ref_id,
        user_id=user_id,
        user_name=user_name,
        note=note,
        operator=operator,
        idem_key=idem_key,
    )


def adjust(pdb: Session, tenant_id: str, delta: int, *, note: str, operator: str, expires_at: datetime | None = None):
    """后台手工加扣积分，必须写原因。"""
    if not (note or "").strip():
        raise HTTPException(400, "调整积分必须填写原因")
    if delta > 0:
        return grant(pdb, tenant_id, delta, source="调整", kind="调整", note=note, operator=operator, expires_at=expires_at)
    if delta < 0:
        return consume(pdb, tenant_id, -delta, kind="调整", note=note, operator=operator, allow_partial=True)
    raise HTTPException(400, "调整数量不能为 0")


def _expire_locked(pdb: Session, tenant_id: str, wallet, now: datetime) -> int:
    from .platform_models import CreditBucket

    expired = (
        pdb.query(CreditBucket)
        .filter(
            CreditBucket.tenant_id == tenant_id,
            CreditBucket.remaining > 0,
            CreditBucket.expires_at.isnot(None),
            CreditBucket.expires_at <= now,
        )
        .all()
    )
    total = 0
    for bucket in expired:
        total += bucket.remaining
        bucket.remaining = 0
    if total:
        wallet.balance -= total
        _ledger(pdb, tenant_id, wallet, kind="过期", amount=-total, note="积分到期作废")
    return total


def expire_credits(tenant_id: str) -> int:
    with platform_session() as pdb:
        wallet = _lock_wallet(pdb, tenant_id)
        total = _expire_locked(pdb, tenant_id, wallet, datetime.utcnow())
        pdb.commit()
        return total


def balance_of(pdb: Session, tenant_id: str) -> dict:
    from .platform_models import CreditBucket

    wallet = ensure_wallet(pdb, tenant_id)
    now = datetime.utcnow()
    soon = now + timedelta(days=30)
    expiring = (
        pdb.query(func.coalesce(func.sum(CreditBucket.remaining), 0))
        .filter(
            CreditBucket.tenant_id == tenant_id,
            CreditBucket.remaining > 0,
            CreditBucket.expires_at.isnot(None),
            CreditBucket.expires_at > now,
            CreditBucket.expires_at <= soon,
        )
        .scalar()
    )
    return {
        "balance": int(wallet.balance or 0),
        "held": int(wallet.held or 0),
        "available": int((wallet.balance or 0) - (wallet.held or 0)),
        "expiringIn30Days": int(expiring or 0),
        "totalRecharged": int(wallet.total_recharged or 0),
        "totalConsumed": int(wallet.total_consumed or 0),
    }


# ---------------------------------------------------------------------------
# 定价
# ---------------------------------------------------------------------------


def seed_prices(pdb: Session) -> None:
    from .platform_models import PriceRule

    for order, (feature, (name, mode, price, estimate)) in enumerate(DEFAULT_PRICES.items()):
        if pdb.get(PriceRule, feature) is None:
            pdb.add(PriceRule(feature=feature, name=name, mode=mode, unit_price=price, estimate=estimate, sort_order=order))
    pdb.commit()


def price_of(pdb: Session, feature: str):
    from .platform_models import PriceRule

    rule = pdb.get(PriceRule, feature)
    if rule is not None and rule.enabled:
        return rule
    name, mode, price, estimate = DEFAULT_PRICES.get(feature, DEFAULT_PRICES["other"])
    return PriceRule(feature=feature, name=name, mode=mode, unit_price=price, estimate=estimate, enabled=True)


TOKEN_REFERENCE_FEATURE = "chapter"


def tokens_per_credit(pdb: Session) -> int:
    """1 积分约合多少 Token：按「正文生成」的千 Token 单价、模型倍率 1 估算，只用于展示。"""
    rule = price_of(pdb, TOKEN_REFERENCE_FEATURE)
    price = float(rule.unit_price or 0) if rule.mode == "per_1k_tokens" else 0.0
    return int(round(1000 / price)) if price > 0 else 1000


def model_ratio(pdb: Session, *keys: str) -> float:
    from .platform_models import ModelRatio

    for key in keys:
        if not key:
            continue
        row = pdb.get(ModelRatio, key)
        if row is not None:
            return max(float(row.ratio or 0), 0.0)
    return 1.0


def credits_for_tokens(unit_price: float, ratio: float, tokens: int) -> float:
    return tokens / 1000.0 * unit_price * ratio


# ---------------------------------------------------------------------------
# 预占与结算
# ---------------------------------------------------------------------------


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def member_month_spent(pdb: Session, tenant_id: str, user_id: str) -> int:
    from .platform_models import CreditHold, CreditLedger

    start = _month_start(datetime.utcnow())
    spent = (
        pdb.query(func.coalesce(func.sum(CreditLedger.amount), 0))
        .filter(
            CreditLedger.tenant_id == tenant_id,
            CreditLedger.user_id == user_id,
            CreditLedger.kind == "消费",
            CreditLedger.created_at >= start,
        )
        .scalar()
    )
    holding = (
        pdb.query(func.coalesce(func.sum(CreditHold.amount), 0))
        .filter(CreditHold.tenant_id == tenant_id, CreditHold.user_id == user_id, CreditHold.status == "holding")
        .scalar()
    )
    return int(-(spent or 0)) + int(holding or 0)


def _member_limit(tenant_id: str, user_id: str | None) -> int | None:
    if not user_id:
        return None
    from .db import tenant_session
    from .models import User

    db = tenant_session(tenant_id)
    try:
        user = db.get(User, user_id)
        return user.monthly_credit_limit if user is not None else None
    except Exception:  # noqa: BLE001 —— 老 schema 尚无该列时不限制
        return None
    finally:
        db.close()


def _user_name(tenant_id: str, user_id: str | None) -> str:
    if not user_id:
        return ""
    from .db import tenant_session
    from .models import User

    db = tenant_session(tenant_id)
    try:
        user = db.get(User, user_id)
        return user.name if user is not None else ""
    except Exception:  # noqa: BLE001
        return ""
    finally:
        db.close()


def require_credits(feature: str, tenant_id: str | None = None, user_id: str | None = None) -> None:
    """投递任务前的快速检查：余额（扣除已预占）不够本功能的预占额时直接返回 402。"""
    tenant_id = tenant_id or current_tenant()
    if not tenant_id:
        return
    user_id = user_id or current_user_id()
    with platform_session() as pdb:
        rule = price_of(pdb, feature)
        if rule.mode == "free":
            return
        need = max(int(rule.estimate or 0), 1)
        wallet = ensure_wallet(pdb, tenant_id)
        available = int((wallet.balance or 0) - (wallet.held or 0))
        if available < need:
            raise InsufficientCredits(need, available)
        limit = _member_limit(tenant_id, user_id)
        if limit is not None and member_month_spent(pdb, tenant_id, user_id) + need > limit:
            raise InsufficientCredits(need, available, reason=f"已达到本月个人积分上限 {limit}，请联系企业管理员调整")


def open_hold(tenant_id: str, feature: str, *, user_id: str | None, ref_id: str = "") -> str | None:
    """预占积分，免费功能返回 None。"""
    from .platform_models import CreditHold

    with platform_session() as pdb:
        rule = price_of(pdb, feature)
        if rule.mode == "free":
            return None
        need = max(int(rule.estimate or 0), 1)
        wallet = _lock_wallet(pdb, tenant_id)
        _expire_locked(pdb, tenant_id, wallet, datetime.utcnow())
        available = int(wallet.balance - wallet.held)
        if available < need:
            pdb.rollback()
            raise InsufficientCredits(need, available)
        limit = _member_limit(tenant_id, user_id)
        if limit is not None and user_id and member_month_spent(pdb, tenant_id, user_id) + need > limit:
            pdb.rollback()
            raise InsufficientCredits(need, available, reason=f"已达到本月个人积分上限 {limit}，请联系企业管理员调整")
        hold = CreditHold(
            tenant_id=tenant_id,
            user_id=user_id,
            user_name=_user_name(tenant_id, user_id),
            feature=feature,
            ref_id=ref_id,
            amount=need,
        )
        pdb.add(hold)
        wallet.held += need
        pdb.commit()
        return hold.id


def _close_hold(pdb: Session, hold, *, charge: int, status: str) -> None:
    wallet = _lock_wallet(pdb, hold.tenant_id)
    wallet.held = max(0, int(wallet.held or 0) - int(hold.amount or 0))
    hold.status = status
    hold.settled_at = datetime.utcnow()
    if charge > 0:
        rule_name = DEFAULT_PRICES.get(hold.feature, (hold.feature,))[0]
        consume(
            pdb,
            hold.tenant_id,
            charge,
            feature=hold.feature,
            ref_id=hold.ref_id,
            user_id=hold.user_id,
            user_name=hold.user_name,
            note=rule_name,
            allow_partial=True,
            idem_key=f"hold:{hold.id}",
        )


def settle_hold(hold_id: str, used: float) -> int:
    """按实际用量结算，返回扣掉的积分（向上取整）。"""
    from .platform_models import CreditHold

    with platform_session() as pdb:
        hold = pdb.query(CreditHold).filter(CreditHold.id == hold_id).with_for_update().first()
        if hold is None or hold.status != "holding":
            return 0
        hold.used = used
        charge = int(math.ceil(used - 1e-9)) if used > 0 else 0
        _close_hold(pdb, hold, charge=charge, status="settled")
        pdb.commit()
        return charge


def release_hold(hold_id: str) -> None:
    from .platform_models import CreditHold

    with platform_session() as pdb:
        hold = pdb.query(CreditHold).filter(CreditHold.id == hold_id).with_for_update().first()
        if hold is None or hold.status != "holding":
            return
        _close_hold(pdb, hold, charge=0, status="released")
        pdb.commit()


def release_stale_holds(max_age_minutes: int = 180) -> int:
    from .platform_models import CreditHold

    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
    with platform_session() as pdb:
        ids = [
            row[0]
            for row in pdb.query(CreditHold.id).filter(CreditHold.status == "holding", CreditHold.created_at < cutoff).all()
        ]
    for hold_id in ids:
        release_hold(hold_id)
    return len(ids)


# ---------------------------------------------------------------------------
# 计量上下文
# ---------------------------------------------------------------------------


@dataclass
class Meter:
    tenant_id: str
    feature: str
    user_id: str | None = None
    hold_id: str | None = None
    credits: float = 0.0
    # 任务最终失败时置 True：释放预占，不收费
    refund: bool = False
    usage: dict = field(default_factory=dict)  # model -> [prompt, completion, calls, credits]
    lock: threading.Lock = field(default_factory=threading.Lock)


_meter: ContextVar[Meter | None] = ContextVar("billing_meter", default=None)


def current_meter() -> Meter | None:
    return _meter.get()


@contextmanager
def metered(feature: str, *, user_id: str | None = None, ref_id: str = "") -> Iterator[Meter | None]:
    """包住一次计费任务：开始预占，正常结束按用量结算，异常则释放预占。没有企业上下文时不计费。"""
    tenant_id = current_tenant()
    if not tenant_id:
        yield None
        return
    user_id = user_id or current_user_id()
    hold_id = open_hold(tenant_id, feature, user_id=user_id, ref_id=ref_id)
    meter = Meter(tenant_id=tenant_id, feature=feature, user_id=user_id, hold_id=hold_id)
    token = _meter.set(meter)
    ok = False
    try:
        yield meter
        ok = True
    finally:
        _meter.reset(token)
        _flush_usage(meter)
        if hold_id:
            if ok and not meter.refund:
                settle_hold(hold_id, meter.credits)
            else:
                release_hold(hold_id)


def _flush_usage(meter: Meter) -> None:
    from .platform_models import UsageRecord

    if not meter.usage:
        return
    try:
        with platform_session() as pdb:
            for model, (prompt, completion, calls, credits) in meter.usage.items():
                pdb.add(
                    UsageRecord(
                        tenant_id=meter.tenant_id,
                        user_id=meter.user_id,
                        feature=meter.feature,
                        model=model,
                        prompt_tokens=prompt,
                        completion_tokens=completion,
                        calls=calls,
                        credits=credits,
                        hold_id=meter.hold_id,
                    )
                )
            pdb.commit()
    except Exception:  # noqa: BLE001 —— 计量明细写失败不影响业务结果
        logger.exception("写用量明细失败")


def _charge_for(pdb: Session, feature: str, model_keys: tuple[str, ...], tokens: int, calls: int) -> float:
    rule = price_of(pdb, feature)
    if rule.mode == "free":
        return 0.0
    ratio = model_ratio(pdb, *model_keys)
    if rule.mode == "per_call":
        return float(rule.unit_price or 0) * ratio * calls
    return credits_for_tokens(float(rule.unit_price or 0), ratio, tokens)


def record_usage(
    *,
    model_id: str = "",
    api_model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    calls: int = 1,
    feature: str | None = None,
) -> float:
    """上报一次模型调用。处于计费任务中：累计到预占；不在任务中但有企业上下文：立即按「其他」扣费。"""
    meter = _meter.get()
    tenant_id = meter.tenant_id if meter else current_tenant()
    if not tenant_id:
        return 0.0
    model_key = model_id or api_model or "unknown"
    tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)
    try:
        with platform_session() as pdb:
            if meter is not None:
                credits = _charge_for(pdb, feature or meter.feature, (model_id, api_model), tokens, calls)
                with meter.lock:
                    meter.credits += credits
                    row = meter.usage.setdefault(model_key, [0, 0, 0, 0.0])
                    row[0] += int(prompt_tokens or 0)
                    row[1] += int(completion_tokens or 0)
                    row[2] += calls
                    row[3] += credits
                return credits
            from .platform_models import UsageRecord

            feat = feature or "other"
            credits = _charge_for(pdb, feat, (model_id, api_model), tokens, calls)
            user_id = current_user_id()
            pdb.add(
                UsageRecord(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    feature=feat,
                    model=model_key,
                    prompt_tokens=int(prompt_tokens or 0),
                    completion_tokens=int(completion_tokens or 0),
                    calls=calls,
                    credits=credits,
                )
            )
            charge = int(math.ceil(credits - 1e-9)) if credits > 0 else 0
            if charge:
                consume(
                    pdb,
                    tenant_id,
                    charge,
                    feature=feat,
                    user_id=user_id,
                    note=price_of(pdb, feat).name,
                    allow_partial=True,
                )
            pdb.commit()
            return credits
    except IntegrityError:
        logger.exception("记账冲突")
        return 0.0
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 —— 计费失败不应吞掉已经完成的模型调用结果，但要留日志
        logger.exception("记录模型用量失败")
        return 0.0
