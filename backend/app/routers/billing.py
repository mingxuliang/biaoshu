"""企业端费用中心：余额、套餐、充值下单、对公转账、消费明细、发票。

所有查询都按当前登录企业过滤，企业 ID 只取自登录会话，不接受前端传入。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import billing, storage
from ..auth import get_current_user
from ..config import get_settings
from ..db import assert_tenant_session, get_db, get_platform_db
from ..models import User
from ..payments import available_channels, get_channel
from ..payments import orders as order_svc
from ..permissions import PERM_BILLING, has_perm, require_perm
from ..tenants import KIND_PERSONAL, plan_fits, tenant_kind

router = APIRouter(prefix="/api/billing", tags=["billing"])

RECEIPT_EXTS = {".pdf", ".jpg", ".jpeg", ".png"}
INVOICE_KINDS = ("普票", "专票")


def _dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


def _plan_out(plan) -> dict:
    return {
        "code": plan.code,
        "kind": plan.kind,
        "audience": plan.audience or "通用",
        "name": plan.name,
        "priceCents": plan.price_cents,
        "durationDays": plan.duration_days,
        "seats": plan.seats,
        "credits": plan.credits,
        "bonusCredits": plan.bonus_credits,
        "storageMb": plan.storage_mb,
        "rechargeBonusPct": plan.recharge_bonus_pct,
        "features": plan.features_json or {},
        "description": plan.description or "",
    }


def order_out(order) -> dict:
    return {
        "id": order.id,
        "kind": order.kind,
        "itemCode": order.item_code,
        "subject": order.subject,
        "amountCents": order.amount_cents,
        "credits": order.credits,
        "bonusCredits": order.bonus_credits,
        "channel": order.channel,
        "status": order.status,
        "payUrl": order.pay_url or "",
        "codeUrl": order.code_url or "",
        "transferCode": order.transfer_code or "",
        "paidAt": _dt(order.paid_at),
        "expiresAt": _dt(order.expires_at),
        "createdAt": _dt(order.created_at),
        "invoicedCents": order.invoiced_cents or 0,
        "userName": order.user_name or "",
        "note": order.note or "",
    }


def ledger_out(row) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "amount": row.amount,
        "balanceAfter": row.balance_after,
        "feature": row.feature,
        "refId": row.ref_id,
        "note": row.note,
        "operator": row.operator,
        "userName": row.user_name,
        "createdAt": _dt(row.created_at),
    }


def invoice_out(inv) -> dict:
    return {
        "id": inv.id,
        "kind": inv.kind,
        "title": inv.title_json or {},
        "amountCents": inv.amount_cents,
        "orderIds": inv.order_ids_json or [],
        "status": inv.status,
        "invoiceNo": inv.invoice_no or "",
        "fileName": inv.file_name or "",
        "hasFile": bool(inv.file_key),
        "rejectReason": inv.reject_reason or "",
        "applicantName": inv.applicant_name or "",
        "issuedAt": _dt(inv.issued_at),
        "createdAt": _dt(inv.created_at),
    }


# ---------------------------------------------------------------------------
# 概览
# ---------------------------------------------------------------------------


@router.get("/summary")
def billing_summary(
    db: Session = Depends(get_db),
    pdb: Session = Depends(get_platform_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from ..platform_models import Plan, Tenant
    from ..tenants import seats_used

    tid = assert_tenant_session(db)
    tenant = pdb.get(Tenant, tid)
    plan = pdb.get(Plan, tenant.plan_code) if tenant and tenant.plan_code else None
    wallet = billing.balance_of(pdb, tid)
    limit = current_user.monthly_credit_limit
    out = {
        "wallet": wallet,
        "plan": _plan_out(plan) if plan else None,
        "tokensPerCredit": billing.tokens_per_credit(pdb),
        "tenant": {
            "id": tid,
            "name": tenant.name if tenant else "",
            "kind": tenant_kind(tenant),
            "status": tenant.status if tenant else "",
            "seats": tenant.seats if tenant else 0,
            "seatsUsed": seats_used(tid),
            "storageQuotaMb": tenant.storage_quota_mb if tenant else 0,
            "trialEndsAt": _dt(tenant.trial_ends_at) if tenant else "",
            "expiresAt": _dt(tenant.expires_at) if tenant else "",
            "lowBalanceThreshold": tenant.low_balance_threshold if tenant else 0,
            "verifyStatus": tenant.verify_status if tenant else "",
        },
        "me": {
            "monthSpent": billing.member_month_spent(pdb, tid, current_user.id),
            "monthlyLimit": limit,
        },
        "lowBalance": bool(tenant and wallet["available"] < (tenant.low_balance_threshold or 0)),
        "canManage": has_perm(current_user, PERM_BILLING),
    }
    try:
        out["tenant"]["storageUsedBytes"] = storage.tenant_usage_bytes(tid)
    except Exception:  # noqa: BLE001 —— MinIO 不可用时不影响页面
        out["tenant"]["storageUsedBytes"] = None
    return out


@router.get("/plans")
def list_plans(
    db: Session = Depends(get_db),
    pdb: Session = Depends(get_platform_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    from ..platform_models import Plan, Tenant

    kind = tenant_kind(pdb.get(Tenant, assert_tenant_session(db)))
    rows = pdb.query(Plan).filter(Plan.enabled.is_(True), Plan.price_cents > 0).order_by(Plan.sort_order.asc()).all()
    return [_plan_out(p) for p in rows if plan_fits(p, kind)]


@router.get("/prices")
def list_prices(pdb: Session = Depends(get_platform_db), current_user: User = Depends(get_current_user)) -> dict:
    from ..platform_models import PriceRule

    rows = pdb.query(PriceRule).filter(PriceRule.enabled.is_(True)).order_by(PriceRule.sort_order.asc()).all()
    return {
        "creditsPerYuan": get_settings().credits_per_yuan,
        "tokensPerCredit": billing.tokens_per_credit(pdb),
        "rules": [
            {"feature": r.feature, "name": r.name, "mode": r.mode, "unitPrice": r.unit_price, "estimate": r.estimate}
            for r in rows
        ],
    }


@router.get("/channels")
def list_channels(current_user: User = Depends(get_current_user)) -> list[dict]:
    return available_channels()


@router.get("/bank-account")
def bank_account(current_user: User = Depends(get_current_user)) -> dict:
    s = get_settings()
    return {"accountName": s.bank_account_name, "accountNo": s.bank_account_no, "bankName": s.bank_name}


# ---------------------------------------------------------------------------
# 流水与用量
# ---------------------------------------------------------------------------


@router.get("/ledger")
def list_ledger(
    kind: str = "",
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    pdb: Session = Depends(get_platform_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from ..platform_models import CreditLedger

    tid = assert_tenant_session(db)
    q = pdb.query(CreditLedger).filter(CreditLedger.tenant_id == tid)
    # 普通成员只看自己产生的消费
    if not has_perm(current_user, PERM_BILLING):
        q = q.filter(CreditLedger.user_id == current_user.id)
    if kind:
        q = q.filter(CreditLedger.kind == kind)
    total = q.count()
    rows = q.order_by(CreditLedger.created_at.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "items": [ledger_out(r) for r in rows]}


@router.get("/usage")
def usage_stats(
    days: int = Query(30, ge=1, le=366),
    db: Session = Depends(get_db),
    pdb: Session = Depends(get_platform_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """按功能、按成员汇总积分和 token，供企业管理员核对谁用了多少。"""
    from ..platform_models import CreditLedger, PriceRule, UsageRecord

    tid = assert_tenant_session(db)
    since = datetime.utcnow() - timedelta(days=days)
    manage = has_perm(current_user, PERM_BILLING)
    names = {r.feature: r.name for r in pdb.query(PriceRule).all()}

    lq = pdb.query(CreditLedger.feature, func.sum(CreditLedger.amount)).filter(
        CreditLedger.tenant_id == tid, CreditLedger.kind == "消费", CreditLedger.created_at >= since
    )
    uq = pdb.query(
        UsageRecord.feature,
        func.sum(UsageRecord.prompt_tokens),
        func.sum(UsageRecord.completion_tokens),
        func.sum(UsageRecord.calls),
    ).filter(UsageRecord.tenant_id == tid, UsageRecord.created_at >= since)
    if not manage:
        lq = lq.filter(CreditLedger.user_id == current_user.id)
        uq = uq.filter(UsageRecord.user_id == current_user.id)
    credits = {f or "other": -int(v or 0) for f, v in lq.group_by(CreditLedger.feature).all()}
    tokens = {f or "other": (int(p or 0), int(c or 0), int(n or 0)) for f, p, c, n in uq.group_by(UsageRecord.feature).all()}
    features = sorted(set(credits) | set(tokens), key=lambda f: -credits.get(f, 0))
    by_feature = [
        {
            "feature": f,
            "name": names.get(f, f),
            "credits": credits.get(f, 0),
            "promptTokens": tokens.get(f, (0, 0, 0))[0],
            "completionTokens": tokens.get(f, (0, 0, 0))[1],
            "calls": tokens.get(f, (0, 0, 0))[2],
        }
        for f in features
    ]
    by_user: list[dict] = []
    if manage:
        rows = (
            pdb.query(CreditLedger.user_id, CreditLedger.user_name, func.sum(CreditLedger.amount))
            .filter(CreditLedger.tenant_id == tid, CreditLedger.kind == "消费", CreditLedger.created_at >= since)
            .group_by(CreditLedger.user_id, CreditLedger.user_name)
            .all()
        )
        by_user = sorted(
            [{"userId": uid or "", "userName": name or "系统", "credits": -int(v or 0)} for uid, name, v in rows],
            key=lambda r: -r["credits"],
        )
    return {"days": days, "byFeature": by_feature, "byUser": by_user}


# ---------------------------------------------------------------------------
# 订单
# ---------------------------------------------------------------------------


class QuoteIn(BaseModel):
    kind: str = Field(pattern="^(充值|套餐|加油包)$")
    itemCode: str = ""
    amountCents: int = 0


class OrderIn(QuoteIn):
    channel: str = Field(pattern="^(alipay|wechat|bank|mock)$")


@router.post("/quote")
def quote_order(
    payload: QuoteIn,
    db: Session = Depends(get_db),
    pdb: Session = Depends(get_platform_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return order_svc.quote(pdb, assert_tenant_session(db), payload.kind, payload.itemCode, payload.amountCents)


@router.post("/orders")
def create_order(
    payload: OrderIn,
    db: Session = Depends(get_db),
    pdb: Session = Depends(get_platform_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    require_perm(current_user, PERM_BILLING)
    tid = assert_tenant_session(db)
    if payload.channel == "mock":
        get_channel("mock")  # 生产环境直接拒绝
    if payload.channel == "bank" and not get_settings().bank_account_no:
        raise HTTPException(400, "平台尚未配置对公收款账户")
    order = order_svc.create_order(
        pdb,
        tenant_id=tid,
        user_id=current_user.id,
        user_name=current_user.name or "",
        kind=payload.kind,
        channel=payload.channel,
        item_code=payload.itemCode,
        amount_cents=payload.amountCents,
    )
    return order_out(order)


def _own_order(pdb: Session, tid: str, order_id: str):
    from ..platform_models import RechargeOrder

    order = pdb.get(RechargeOrder, order_id)
    if order is None or order.tenant_id != tid:
        raise HTTPException(404, "订单不存在")
    return order


@router.get("/orders")
def list_orders(
    status: str = "",
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    pdb: Session = Depends(get_platform_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from ..platform_models import RechargeOrder

    require_perm(current_user, PERM_BILLING)
    tid = assert_tenant_session(db)
    q = pdb.query(RechargeOrder).filter(RechargeOrder.tenant_id == tid)
    if status:
        q = q.filter(RechargeOrder.status == status)
    total = q.count()
    rows = q.order_by(RechargeOrder.created_at.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "items": [order_out(o) for o in rows]}


@router.get("/orders/{order_id}")
def get_order(
    order_id: str,
    db: Session = Depends(get_db),
    pdb: Session = Depends(get_platform_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    require_perm(current_user, PERM_BILLING)
    order = _own_order(pdb, assert_tenant_session(db), order_id)
    order_svc.sync_order(pdb, order)
    pdb.refresh(order)
    return order_out(order)


@router.post("/orders/{order_id}/close")
def close_order(
    order_id: str,
    db: Session = Depends(get_db),
    pdb: Session = Depends(get_platform_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    require_perm(current_user, PERM_BILLING)
    order = _own_order(pdb, assert_tenant_session(db), order_id)
    order_svc.close_order(pdb, order, "用户取消")
    return order_out(order)


@router.post("/orders/{order_id}/mock-pay")
def mock_pay(
    order_id: str,
    db: Session = Depends(get_db),
    pdb: Session = Depends(get_platform_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """测试环境模拟支付成功，走与真实回调相同的入账路径。"""
    require_perm(current_user, PERM_BILLING)
    order = _own_order(pdb, assert_tenant_session(db), order_id)
    if order.channel != "mock":
        raise HTTPException(400, "只有模拟支付订单可以这样付款")
    channel = get_channel("mock")
    order_svc.apply_notify(pdb, "mock", channel.parse_notify({}, order.id.encode()))
    pdb.refresh(order)
    return order_out(order)


@router.post("/orders/{order_id}/transfer")
async def submit_transfer(
    order_id: str,
    payerName: str = Form(...),
    payerAccount: str = Form(""),
    bankSerial: str = Form(""),
    amountCents: int = Form(...),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    pdb: Session = Depends(get_platform_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """对公转账后提交付款信息和回单，平台财务核对到账后入账。"""
    import os

    from ..platform_models import BankTransfer

    require_perm(current_user, PERM_BILLING)
    tid = assert_tenant_session(db)
    order = _own_order(pdb, tid, order_id)
    if order.channel != "bank":
        raise HTTPException(400, "该订单不是对公转账订单")
    if order.status not in ("待支付", "待确认"):
        raise HTTPException(400, "订单状态不允许提交回单")
    receipt_key = ""
    receipt_name = ""
    if file is not None and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in RECEIPT_EXTS:
            raise HTTPException(400, "回单仅支持 PDF 或图片")
        data = await file.read()
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(413, "回单文件不能超过 10 MB")
        receipt_key = storage.put_bytes(f"transfers/{tid}/{order.id}", data, ext, bucket=storage.platform_bucket())
        receipt_name = file.filename
    pdb.add(
        BankTransfer(
            order_id=order.id,
            tenant_id=tid,
            payer_name=payerName.strip()[:120],
            payer_account=payerAccount.strip()[:60],
            amount_cents=int(amountCents),
            bank_serial=bankSerial.strip()[:80],
            receipt_key=receipt_key,
            receipt_name=receipt_name,
        )
    )
    order.status = "待确认"
    pdb.commit()
    return order_out(order)


# ---------------------------------------------------------------------------
# 发票
# ---------------------------------------------------------------------------


class InvoiceTitleIn(BaseModel):
    kind: str = Field("普票", pattern="^(普票|专票)$")
    title: str = Field(min_length=2, max_length=120)
    taxNo: str = Field("", max_length=30)
    address: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    bankName: str = Field("", max_length=120)
    bankAccount: str = Field("", max_length=60)
    email: str = Field("", max_length=120)
    isDefault: bool = False


def title_out(t) -> dict:
    return {
        "id": t.id,
        "kind": t.kind,
        "title": t.title,
        "taxNo": t.tax_no,
        "address": t.address,
        "phone": t.phone,
        "bankName": t.bank_name,
        "bankAccount": t.bank_account,
        "email": t.email,
        "isDefault": bool(t.is_default),
    }


def _validate_title(payload: InvoiceTitleIn, personal: bool = False) -> None:
    if personal:
        # 个人抬头只能开普票，纳税人识别号可不填
        if payload.kind != "普票":
            raise HTTPException(400, "个人账号只能开具普通发票，升级为企业后可开专票")
        return
    if payload.kind == "专票":
        missing = [n for n, v in (("税号", payload.taxNo), ("地址", payload.address), ("电话", payload.phone), ("开户行", payload.bankName), ("账号", payload.bankAccount)) if not v.strip()]
        if missing:
            raise HTTPException(400, "增值税专用发票需填写：" + "、".join(missing))
    elif not payload.taxNo.strip():
        raise HTTPException(400, "企业抬头需填写纳税人识别号")


@router.get("/invoice-titles")
def list_titles(db: Session = Depends(get_db), pdb: Session = Depends(get_platform_db), current_user: User = Depends(get_current_user)) -> list[dict]:
    from ..platform_models import InvoiceTitle

    require_perm(current_user, PERM_BILLING)
    tid = assert_tenant_session(db)
    rows = pdb.query(InvoiceTitle).filter(InvoiceTitle.tenant_id == tid).order_by(InvoiceTitle.created_at.asc()).all()
    return [title_out(t) for t in rows]


def _save_title(pdb: Session, tid: str, t, payload: InvoiceTitleIn) -> None:
    from ..platform_models import InvoiceTitle, Tenant

    _validate_title(payload, personal=tenant_kind(pdb.get(Tenant, tid)) == KIND_PERSONAL)
    t.kind = payload.kind
    t.title = payload.title.strip()
    t.tax_no = payload.taxNo.strip().upper()
    t.address = payload.address.strip()
    t.phone = payload.phone.strip()
    t.bank_name = payload.bankName.strip()
    t.bank_account = payload.bankAccount.strip()
    t.email = payload.email.strip()
    if payload.isDefault:
        pdb.query(InvoiceTitle).filter(InvoiceTitle.tenant_id == tid).update({InvoiceTitle.is_default: False}, synchronize_session=False)
    t.is_default = payload.isDefault


@router.post("/invoice-titles")
def create_title(payload: InvoiceTitleIn, db: Session = Depends(get_db), pdb: Session = Depends(get_platform_db), current_user: User = Depends(get_current_user)) -> dict:
    from ..platform_models import InvoiceTitle

    require_perm(current_user, PERM_BILLING)
    tid = assert_tenant_session(db)
    t = InvoiceTitle(tenant_id=tid, title=payload.title)
    _save_title(pdb, tid, t, payload)
    pdb.add(t)
    pdb.commit()
    return title_out(t)


@router.put("/invoice-titles/{title_id}")
def update_title(title_id: str, payload: InvoiceTitleIn, db: Session = Depends(get_db), pdb: Session = Depends(get_platform_db), current_user: User = Depends(get_current_user)) -> dict:
    from ..platform_models import InvoiceTitle

    require_perm(current_user, PERM_BILLING)
    tid = assert_tenant_session(db)
    t = pdb.get(InvoiceTitle, title_id)
    if t is None or t.tenant_id != tid:
        raise HTTPException(404, "抬头不存在")
    _save_title(pdb, tid, t, payload)
    pdb.commit()
    return title_out(t)


@router.delete("/invoice-titles/{title_id}")
def delete_title(title_id: str, db: Session = Depends(get_db), pdb: Session = Depends(get_platform_db), current_user: User = Depends(get_current_user)) -> dict:
    from ..platform_models import InvoiceTitle

    require_perm(current_user, PERM_BILLING)
    tid = assert_tenant_session(db)
    t = pdb.get(InvoiceTitle, title_id)
    if t is None or t.tenant_id != tid:
        raise HTTPException(404, "抬头不存在")
    pdb.delete(t)
    pdb.commit()
    return {"ok": True}


class InvoiceApplyIn(BaseModel):
    titleId: str
    orderIds: list[str] = Field(min_length=1, max_length=50)
    note: str = Field("", max_length=200)


@router.get("/invoices")
def list_invoices(db: Session = Depends(get_db), pdb: Session = Depends(get_platform_db), current_user: User = Depends(get_current_user)) -> list[dict]:
    from ..platform_models import Invoice

    require_perm(current_user, PERM_BILLING)
    tid = assert_tenant_session(db)
    rows = pdb.query(Invoice).filter(Invoice.tenant_id == tid).order_by(Invoice.created_at.desc()).all()
    return [invoice_out(i) for i in rows]


@router.post("/invoices")
def apply_invoice(payload: InvoiceApplyIn, db: Session = Depends(get_db), pdb: Session = Depends(get_platform_db), current_user: User = Depends(get_current_user)) -> dict:
    """按已支付订单申请发票，一张订单只能开一次；赠送积分不开票。"""
    from ..invoicing import apply_invoice as do_apply

    require_perm(current_user, PERM_BILLING)
    tid = assert_tenant_session(db)
    inv = do_apply(pdb, tid, title_id=payload.titleId, order_ids=payload.orderIds, applicant=current_user)
    return invoice_out(inv)


@router.get("/invoices/{invoice_id}/file")
def download_invoice(invoice_id: str, db: Session = Depends(get_db), pdb: Session = Depends(get_platform_db), current_user: User = Depends(get_current_user)):
    from ..platform_models import Invoice

    require_perm(current_user, PERM_BILLING)
    tid = assert_tenant_session(db)
    inv = pdb.get(Invoice, invoice_id)
    if inv is None or inv.tenant_id != tid or not inv.file_key:
        raise HTTPException(404, "发票文件不存在")
    return storage.http_response(inv.file_key, filename=inv.file_name or f"{inv.invoice_no or inv.id}.pdf", bucket=storage.platform_bucket())
