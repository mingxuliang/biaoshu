"""支付宝开放平台：电脑网站支付 alipay.trade.page.pay、当面付扫码 alipay.trade.precreate。RSA2 签名。

异步通知是 application/x-www-form-urlencoded；处理成功必须返回纯文本 success，否则支付宝会重发。
TRADE_CLOSED 也是终态（超时未付），要一并处理。
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timedelta, timezone

import httpx

from .base import (
    CreateResult,
    NotifyResult,
    PaymentChannel,
    PaymentError,
    cents,
    load_private_key,
    load_public_key,
    rsa_sign,
    rsa_verify,
    yuan,
)

CST = timezone(timedelta(hours=8))


def sign_content(params: dict) -> str:
    items = sorted((k, v) for k, v in params.items() if k not in ("sign", "sign_type") and v not in (None, ""))
    return "&".join(f"{k}={v}" for k, v in items)


class AlipayChannel(PaymentChannel):
    name = "alipay"
    ack_body = "success"

    def __init__(self, settings) -> None:
        self.settings = settings

    def _common(self, method: str, biz: dict, notify_url: str = "", return_url: str = "") -> dict:
        params = {
            "app_id": self.settings.alipay_app_id,
            "method": method,
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "biz_content": json.dumps(biz, ensure_ascii=False, separators=(",", ":")),
        }
        if notify_url:
            params["notify_url"] = notify_url
        if return_url:
            params["return_url"] = return_url
        params["sign"] = rsa_sign(load_private_key(self.settings.alipay_private_key), sign_content(params).encode("utf-8"))
        return params

    def _biz(self, order) -> dict:
        biz = {
            "out_trade_no": order.id,
            "total_amount": yuan(order.amount_cents),
            "subject": (order.subject or "积分充值")[:120],
        }
        if order.expires_at:
            biz["time_expire"] = order.expires_at.replace(tzinfo=timezone.utc).astimezone(CST).strftime("%Y-%m-%d %H:%M:%S")
        return biz

    def page_pay_url(self, order, notify_url: str, return_url: str = "") -> str:
        biz = {**self._biz(order), "product_code": "FAST_INSTANT_TRADE_PAY"}
        params = self._common("alipay.trade.page.pay", biz, notify_url, return_url)
        return f"{self.settings.alipay_gateway}?{urllib.parse.urlencode(params)}"

    def _call(self, method: str, biz: dict, notify_url: str = "") -> dict:
        params = self._common(method, biz, notify_url)
        resp = httpx.post(self.settings.alipay_gateway, data=params, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        key = method.replace(".", "_") + "_response"
        data = body.get(key) or {}
        if data.get("code") != "10000":
            raise PaymentError(f"支付宝返回 {data.get('code')}：{data.get('sub_msg') or data.get('msg')}")
        return data

    def create(self, order, notify_url: str, return_url: str = "") -> CreateResult:
        if not self.settings.alipay_app_id:
            raise PaymentError("未配置支付宝 APPID")
        return CreateResult(pay_url=self.page_pay_url(order, notify_url, return_url))

    def create_qr(self, order, notify_url: str) -> CreateResult:
        data = self._call("alipay.trade.precreate", self._biz(order), notify_url)
        return CreateResult(code_url=data.get("qr_code", ""))

    def parse_notify(self, headers: dict, body: bytes) -> NotifyResult:
        params = {k: v[0] for k, v in urllib.parse.parse_qs(body.decode("utf-8"), keep_blank_values=True).items()}
        signature = params.get("sign", "")
        if not signature or not rsa_verify(
            load_public_key(self.settings.alipay_public_key), sign_content(params).encode("utf-8"), signature
        ):
            raise PaymentError("支付宝通知验签失败")
        if params.get("app_id") and params.get("app_id") != self.settings.alipay_app_id:
            raise PaymentError("支付宝通知 app_id 不匹配")
        status = params.get("trade_status", "")
        order_id = params.get("out_trade_no", "")
        return NotifyResult(
            order_id=order_id,
            event_key=f"alipay:{params.get('notify_id') or order_id + ':' + status}",
            paid=status in ("TRADE_SUCCESS", "TRADE_FINISHED"),
            closed=status == "TRADE_CLOSED",
            trade_no=params.get("trade_no", ""),
            amount_cents=cents(params.get("total_amount")),
            raw=params,
        )

    def query(self, order) -> NotifyResult | None:
        data = self._call("alipay.trade.query", {"out_trade_no": order.id})
        status = data.get("trade_status", "")
        return NotifyResult(
            order_id=order.id,
            event_key=f"alipay-query:{order.id}:{status}",
            paid=status in ("TRADE_SUCCESS", "TRADE_FINISHED"),
            closed=status == "TRADE_CLOSED",
            trade_no=data.get("trade_no", ""),
            amount_cents=cents(data.get("total_amount")),
            raw=data,
        )

    def close(self, order) -> None:
        try:
            self._call("alipay.trade.close", {"out_trade_no": order.id})
        except PaymentError:
            # 用户从未扫码时支付宝侧没有交易，关单返回 ACQ.TRADE_NOT_EXIST，可以忽略
            pass

    def refund(self, order, amount_cents: int, reason: str) -> str:
        request_no = f"{order.id}-R{int(datetime.now().timestamp())}"
        self._call(
            "alipay.trade.refund",
            {"out_trade_no": order.id, "refund_amount": yuan(amount_cents), "refund_reason": reason[:60], "out_request_no": request_no},
        )
        return request_no
