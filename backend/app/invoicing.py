"""发票：企业按已支付订单申请，平台财务审核后开具（当前为手工上传数电票 PDF）。

InvoiceProvider 是对接税控 / 乐企 / 第三方开票服务的预留接口。接入后 issue() 自动开具并回填票号和文件，
不接入时使用 ManualProvider，由财务在后台上传。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session


class InvoiceProvider:
    name = "manual"
    automatic = False

    def issue(self, invoice) -> dict | None:
        """自动开票：返回 {"invoice_no", "pdf_bytes"}；手工模式返回 None。"""
        return None

    def red_flush(self, invoice, reason: str) -> dict | None:
        return None


class ManualProvider(InvoiceProvider):
    pass


def get_provider() -> InvoiceProvider:
    return ManualProvider()


def apply_invoice(pdb: Session, tenant_id: str, *, title_id: str, order_ids: list[str], applicant) -> object:
    from .platform_models import Invoice, InvoiceTitle, RechargeOrder

    title = pdb.get(InvoiceTitle, title_id)
    if title is None or title.tenant_id != tenant_id:
        raise HTTPException(404, "发票抬头不存在")
    ids = list(dict.fromkeys(order_ids))
    orders = (
        pdb.query(RechargeOrder)
        .filter(RechargeOrder.id.in_(ids), RechargeOrder.tenant_id == tenant_id)
        .with_for_update()
        .all()
    )
    if len(orders) != len(ids):
        raise HTTPException(404, "部分订单不存在")
    for order in orders:
        if order.status != "已支付":
            raise HTTPException(400, f"订单 {order.id} 未支付，不能开票")
        if (order.invoiced_cents or 0) >= order.amount_cents:
            raise HTTPException(400, f"订单 {order.id} 已开过发票")
    amount = sum(o.amount_cents - (o.invoiced_cents or 0) for o in orders)
    for order in orders:
        order.invoiced_cents = order.amount_cents
    inv = Invoice(
        tenant_id=tenant_id,
        applicant_id=getattr(applicant, "id", None),
        applicant_name=getattr(applicant, "name", "") or "",
        kind=title.kind,
        title_json={
            "title": title.title,
            "taxNo": title.tax_no,
            "address": title.address,
            "phone": title.phone,
            "bankName": title.bank_name,
            "bankAccount": title.bank_account,
            "email": title.email,
        },
        amount_cents=amount,
        order_ids_json=ids,
        status="待审核",
    )
    pdb.add(inv)
    pdb.commit()
    return inv


def _release_orders(pdb: Session, inv) -> None:
    from .platform_models import RechargeOrder

    for order in pdb.query(RechargeOrder).filter(RechargeOrder.id.in_(inv.order_ids_json or [])).all():
        order.invoiced_cents = 0


def approve(pdb: Session, inv, operator: str) -> None:
    if inv.status != "待审核":
        raise HTTPException(400, "只有待审核的发票可以通过")
    inv.status = "开具中"
    inv.operator = operator
    result = get_provider().issue(inv)
    if result:
        _store_issued(pdb, inv, result["invoice_no"], result["pdf_bytes"], f"{result['invoice_no']}.pdf", operator)
    pdb.commit()


def _store_issued(pdb: Session, inv, invoice_no: str, data: bytes, filename: str, operator: str) -> None:
    import os

    from . import storage

    ext = os.path.splitext(filename)[1].lower() or ".pdf"
    inv.file_key = storage.put_bytes(f"invoices/{inv.tenant_id}", data, ext, bucket=storage.platform_bucket())
    inv.file_name = filename
    inv.invoice_no = invoice_no
    inv.status = "已开具"
    inv.issued_at = datetime.utcnow()
    inv.operator = operator


def upload_issued(pdb: Session, inv, *, invoice_no: str, data: bytes, filename: str, operator: str) -> None:
    if inv.status not in ("待审核", "开具中", "已开具"):
        raise HTTPException(400, "当前状态不能上传发票")
    if not invoice_no.strip():
        raise HTTPException(400, "请填写发票号码")
    _store_issued(pdb, inv, invoice_no.strip(), data, filename, operator)
    pdb.commit()
    _notify(inv, "发票已开具", f"发票号码 {inv.invoice_no}，可在费用中心下载")


def reject(pdb: Session, inv, *, reason: str, operator: str) -> None:
    if inv.status not in ("待审核", "开具中"):
        raise HTTPException(400, "当前状态不能驳回")
    if not reason.strip():
        raise HTTPException(400, "请填写驳回原因")
    inv.status = "已驳回"
    inv.reject_reason = reason.strip()
    inv.operator = operator
    _release_orders(pdb, inv)
    pdb.commit()
    _notify(inv, "发票申请被驳回", inv.reject_reason)


def red_flush(pdb: Session, inv, *, reason: str, operator: str) -> None:
    """红冲：作废已开发票，订单恢复可开票。"""
    if inv.status != "已开具":
        raise HTTPException(400, "只有已开具的发票可以红冲")
    get_provider().red_flush(inv, reason)
    inv.status = "已红冲"
    inv.reject_reason = reason.strip()
    inv.operator = operator
    _release_orders(pdb, inv)
    pdb.commit()


def _notify(inv, title: str, body: str) -> None:
    if not inv.applicant_id:
        return
    try:
        from .db import tenant_session
        from .models import Notification

        with tenant_session(inv.tenant_id) as db:
            db.add(Notification(user_id=inv.applicant_id, kind="invoice", title=title, body=body, link="/billing"))
            db.commit()
    except Exception:  # noqa: BLE001
        pass
