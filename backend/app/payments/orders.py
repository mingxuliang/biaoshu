"""订单：下单、到账入账（幂等）、关单、对公转账认领。所有积分入账只从 mark_paid 进入。"""

from __future__ import annotations

import logging
import secrets
import string
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import billing
from ..config import get_settings
from .base import NotifyResult, PaymentError

logger = logging.getLogger(__name__)

MIN_RECHARGE_CENTS = 1000  # 自由充值最低 10 元
MAX_RECHARGE_CENTS = 100_000_000


def new_order_id() -> str:
    return datetime.utcnow().strftime("ZB%Y%m%d%H%M%S") + secrets.token_hex(4).upper()


def new_transfer_code(pdb: Session) -> str:
    from ..platform_models import RechargeOrder

    alphabet = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"
    for _ in range(20):
        code = "ZB" + "".join(secrets.choice(alphabet) for _ in range(6))
        if not pdb.query(RechargeOrder).filter(RechargeOrder.transfer_code == code).first():
            return code
    raise HTTPException(500, "生成转账识别码失败，请重试")


def _tenant_bonus_pct(pdb: Session, tenant_id: str) -> int:
    from ..platform_models import Plan, Tenant

    tenant = pdb.get(Tenant, tenant_id)
    plan = pdb.get(Plan, tenant.plan_code) if tenant and tenant.plan_code else None
    return int(plan.recharge_bonus_pct or 0) if plan else 0


def quote(pdb: Session, tenant_id: str, kind: str, item_code: str = "", amount_cents: int = 0) -> dict:
    """计算订单金额和到账积分，下单和前端预览共用。"""
    from ..platform_models import Plan

    settings = get_settings()
    if kind == "充值":
        if amount_cents < MIN_RECHARGE_CENTS or amount_cents > MAX_RECHARGE_CENTS:
            raise HTTPException(400, f"充值金额需在 {MIN_RECHARGE_CENTS // 100} 元到 {MAX_RECHARGE_CENTS // 100} 元之间")
        credits = amount_cents * settings.credits_per_yuan // 100
        bonus = credits * _tenant_bonus_pct(pdb, tenant_id) // 100
        return {"amountCents": amount_cents, "credits": credits, "bonusCredits": bonus, "subject": f"积分充值 {credits} 积分"}
    if kind in ("套餐", "加油包"):
        plan = pdb.get(Plan, item_code)
        if plan is None or not plan.enabled or plan.kind != kind or plan.price_cents <= 0:
            raise HTTPException(400, "所选套餐不存在或已下架")
        from ..platform_models import Tenant
        from ..tenants import plan_fits, tenant_kind

        space = tenant_kind(pdb.get(Tenant, tenant_id))
        if not plan_fits(plan, space):
            raise HTTPException(400, f"「{plan.name}」不适用于{space}账号")
        return {
            "amountCents": int(plan.price_cents),
            "credits": int(plan.credits or 0),
            "bonusCredits": int(plan.bonus_credits or 0),
            "subject": f"{plan.name}" + (f"（{plan.duration_days} 天）" if kind == "套餐" else ""),
        }
    raise HTTPException(400, "订单类型不合法")


def create_order(
    pdb: Session,
    *,
    tenant_id: str,
    user_id: str | None,
    user_name: str,
    kind: str,
    channel: str,
    item_code: str = "",
    amount_cents: int = 0,
):
    from ..platform_models import RechargeOrder

    settings = get_settings()
    q = quote(pdb, tenant_id, kind, item_code, amount_cents)
    order = RechargeOrder(
        id=new_order_id(),
        tenant_id=tenant_id,
        user_id=user_id,
        user_name=user_name,
        kind=kind,
        item_code=item_code,
        subject=q["subject"],
        amount_cents=q["amountCents"],
        credits=q["credits"],
        bonus_credits=q["bonusCredits"],
        channel=channel,
        status="待支付",
        # 对公转账到账慢，给 15 天
        expires_at=datetime.utcnow()
        + (timedelta(days=15) if channel == "bank" else timedelta(minutes=settings.pay_order_expire_minutes)),
    )
    if channel == "bank":
        order.transfer_code = new_transfer_code(pdb)
    pdb.add(order)
    pdb.flush()
    if channel != "bank":
        from . import get_channel

        base = settings.public_base_url.rstrip("/")
        try:
            result = get_channel(channel).create(
                order,
                notify_url=f"{base}/api/pay/notify/{channel}",
                return_url=f"{base}/billing?order={order.id}",
            )
        except PaymentError as exc:
            pdb.rollback()
            raise HTTPException(502, f"支付下单失败：{exc}") from exc
        order.pay_url = result.pay_url
        order.code_url = result.code_url
    pdb.commit()
    return order


def _apply_plan(pdb: Session, order, now: datetime) -> datetime:
    from ..platform_models import Plan, Subscription, Tenant

    plan = pdb.get(Plan, order.item_code)
    tenant = pdb.get(Tenant, order.tenant_id)
    if plan is None or tenant is None:
        raise HTTPException(500, "套餐或企业不存在")
    current = (
        pdb.query(Subscription)
        .filter(Subscription.tenant_id == tenant.id, Subscription.status == "生效", Subscription.ends_at > now)
        .order_by(Subscription.ends_at.desc())
        .first()
    )
    # 同套餐续费顺延；换套餐立即生效
    starts = current.ends_at if current is not None and current.plan_code == plan.code else now
    ends = starts + timedelta(days=int(plan.duration_days or 365))
    if current is not None and current.plan_code != plan.code:
        current.status = "已取消"
    pdb.add(Subscription(tenant_id=tenant.id, plan_code=plan.code, starts_at=starts, ends_at=ends, order_id=order.id))
    tenant.plan_code = plan.code
    from ..tenants import KIND_PERSONAL, tenant_kind

    tenant.seats = 1 if tenant_kind(tenant) == KIND_PERSONAL else max(int(plan.seats or 0), 1)
    tenant.storage_quota_mb = int(plan.storage_mb or tenant.storage_quota_mb or 0)
    tenant.features_json = dict(plan.features_json or {})
    tenant.expires_at = ends
    if tenant.status == "试用":
        tenant.status = "正常"
    return ends


def mark_paid(
    pdb: Session,
    order_id: str,
    *,
    trade_no: str = "",
    amount_cents: int | None = None,
    operator: str = "",
):
    """到账入账。重复调用只入账一次；金额对不上直接拒绝。调用方无需 commit。"""
    from ..platform_models import RechargeOrder

    order = pdb.query(RechargeOrder).filter(RechargeOrder.id == order_id).with_for_update().first()
    if order is None:
        raise HTTPException(404, "订单不存在")
    if order.status == "已支付":
        return order
    if order.status == "已退款":
        raise HTTPException(409, "订单已退款")
    if amount_cents is not None and int(amount_cents) != int(order.amount_cents):
        logger.error("订单 %s 金额不一致：应付 %s 实付 %s", order.id, order.amount_cents, amount_cents)
        raise HTTPException(409, "支付金额与订单不一致，已转人工核对")
    now = datetime.utcnow()
    expires_at = None
    if order.kind == "套餐":
        expires_at = _apply_plan(pdb, order, now)
    order.status = "已支付"
    order.paid_at = now
    order.channel_trade_no = trade_no or order.channel_trade_no
    if order.credits > 0:
        billing.grant(
            pdb,
            order.tenant_id,
            order.credits,
            source="套餐" if order.kind == "套餐" else "充值",
            expires_at=expires_at,
            note=order.subject,
            operator=operator,
            idem_key=f"order:{order.id}",
            order_id=order.id,
        )
    if order.bonus_credits > 0:
        billing.grant(
            pdb,
            order.tenant_id,
            order.bonus_credits,
            source="赠送",
            expires_at=expires_at,
            note=f"{order.subject} 赠送",
            operator=operator,
            idem_key=f"order-bonus:{order.id}",
            order_id=order.id,
        )
    pdb.commit()
    from ..tenants import clear_block_cache

    clear_block_cache(order.tenant_id)
    _notify_tenant_paid(order)
    return order


def _notify_tenant_paid(order) -> None:
    try:
        from ..db import tenant_session
        from ..models import Notification

        if not order.user_id:
            return
        with tenant_session(order.tenant_id) as db:
            db.add(
                Notification(
                    user_id=order.user_id,
                    kind="billing",
                    title="支付成功",
                    body=f"{order.subject}，已到账 {order.credits + order.bonus_credits} 积分",
                    link="/billing",
                )
            )
            db.commit()
    except Exception:  # noqa: BLE001 —— 通知失败不影响入账
        logger.exception("写入支付通知失败")


def record_event(pdb: Session, channel: str, result: NotifyResult) -> bool:
    """登记回调事件，返回 False 表示这个事件已经处理过。"""
    from ..platform_models import PaymentEvent

    pdb.add(PaymentEvent(channel=channel, order_id=result.order_id, event_key=result.event_key, verified=True, payload_json=result.raw))
    try:
        pdb.flush()
        return True
    except IntegrityError:
        pdb.rollback()
        return False


def apply_notify(pdb: Session, channel: str, result: NotifyResult) -> None:
    from ..platform_models import RechargeOrder

    order = pdb.get(RechargeOrder, result.order_id)
    if order is None or order.channel != channel:
        raise HTTPException(404, "订单不存在")
    if not record_event(pdb, channel, result):
        return
    if result.paid:
        mark_paid(pdb, order.id, trade_no=result.trade_no, amount_cents=result.amount_cents, operator=f"{channel} 回调")
    elif result.closed and order.status == "待支付":
        order.status = "已关闭"
        pdb.commit()
    else:
        pdb.commit()


def sync_order(pdb: Session, order) -> None:
    """主动查单：前端轮询或回调丢失时兜底。"""
    if order.status != "待支付" or order.channel in ("bank", "mock"):
        return
    from . import get_channel

    try:
        result = get_channel(order.channel).query(order)
    except (PaymentError, Exception) as exc:  # noqa: BLE001 —— 查单失败不影响页面
        logger.warning("查单失败 %s：%s", order.id, exc)
        return
    if result is None:
        return
    if result.paid:
        mark_paid(pdb, order.id, trade_no=result.trade_no, amount_cents=result.amount_cents, operator="主动查单")
    elif result.closed:
        order.status = "已关闭"
        pdb.commit()


def close_order(pdb: Session, order, reason: str = "") -> None:
    if order.status not in ("待支付", "待确认"):
        raise HTTPException(400, "只有待支付的订单可以关闭")
    if order.channel in ("alipay", "wechat"):
        from . import get_channel

        try:
            get_channel(order.channel).close(order)
        except Exception as exc:  # noqa: BLE001
            logger.warning("关单失败 %s：%s", order.id, exc)
    order.status = "已关闭"
    order.note = reason or order.note
    pdb.commit()


def close_expired_orders(pdb: Session) -> int:
    from ..platform_models import RechargeOrder

    now = datetime.utcnow()
    rows = (
        pdb.query(RechargeOrder)
        .filter(RechargeOrder.status == "待支付", RechargeOrder.expires_at.isnot(None), RechargeOrder.expires_at < now)
        .all()
    )
    for order in rows:
        order.status = "已关闭"
        order.note = "超时未支付"
    pdb.commit()
    return len(rows)


def confirm_transfer(pdb: Session, transfer_id: str, *, operator: str, bank_serial: str = "", amount_cents: int | None = None):
    """财务核对银行流水后认领转账，积分随即到账。"""
    from ..platform_models import BankTransfer, RechargeOrder

    transfer = pdb.get(BankTransfer, transfer_id)
    if transfer is None:
        raise HTTPException(404, "转账记录不存在")
    if transfer.status == "已确认":
        return transfer
    order = pdb.get(RechargeOrder, transfer.order_id)
    if order is None:
        raise HTTPException(404, "订单不存在")
    received = int(amount_cents if amount_cents is not None else transfer.amount_cents or 0)
    if received != int(order.amount_cents):
        raise HTTPException(400, f"到账金额 {received / 100:.2f} 元与订单金额 {order.amount_cents / 100:.2f} 元不一致")
    transfer.status = "已确认"
    transfer.operator = operator
    transfer.bank_serial = bank_serial or transfer.bank_serial
    transfer.confirmed_at = datetime.utcnow()
    mark_paid(pdb, order.id, trade_no=transfer.bank_serial, amount_cents=received, operator=operator)
    return transfer
