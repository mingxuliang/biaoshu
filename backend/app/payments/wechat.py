"""微信支付 APIv3 Native 支付：下单拿 code_url 生成二维码，微信和企业微信都可扫码付款。

请求签名：WECHATPAY2-SHA256-RSA2048，签名串 = 方法\\nURL路径\\n时间戳\\n随机串\\n请求体\\n。
回调：先用微信支付平台公钥验签（时间戳\\n随机串\\n报文\\n），再用 APIv3 密钥 AES-256-GCM 解密 resource。
金额单位是分。
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from datetime import timedelta, timezone

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .base import CreateResult, NotifyResult, PaymentChannel, PaymentError, load_private_key, load_public_key, rsa_sign, rsa_verify

CST = timezone(timedelta(hours=8))
MAX_CLOCK_SKEW = 300


def decrypt_resource(api_v3_key: str, resource: dict) -> dict:
    aes = AESGCM(api_v3_key.encode("utf-8"))
    plain = aes.decrypt(
        resource["nonce"].encode("utf-8"),
        base64.b64decode(resource["ciphertext"]),
        (resource.get("associated_data") or "").encode("utf-8"),
    )
    return json.loads(plain.decode("utf-8"))


class WechatChannel(PaymentChannel):
    name = "wechat"
    ack_body = '{"code":"SUCCESS","message":"成功"}'
    ack_media = "application/json"

    def __init__(self, settings) -> None:
        self.settings = settings

    def _auth(self, method: str, path: str, body: str) -> str:
        ts = str(int(time.time()))
        nonce = secrets.token_hex(16)
        message = f"{method}\n{path}\n{ts}\n{nonce}\n{body}\n"
        signature = rsa_sign(load_private_key(self.settings.wechat_private_key), message.encode("utf-8"))
        return (
            f'WECHATPAY2-SHA256-RSA2048 mchid="{self.settings.wechat_mchid}",nonce_str="{nonce}",'
            f'signature="{signature}",timestamp="{ts}",serial_no="{self.settings.wechat_serial_no}"'
        )

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if payload is not None else ""
        headers = {
            "Authorization": self._auth(method, path, body),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        resp = httpx.request(method, self.settings.wechat_api_base + path, content=body.encode("utf-8") if body else None, headers=headers, timeout=15)
        if resp.status_code == 204:
            return {}
        if resp.status_code >= 400:
            raise PaymentError(f"微信支付返回 {resp.status_code}：{resp.text[:200]}")
        return resp.json() if resp.content else {}

    def create(self, order, notify_url: str, return_url: str = "") -> CreateResult:
        if not self.settings.wechat_mchid:
            raise PaymentError("未配置微信支付商户号")
        payload = {
            "appid": self.settings.wechat_appid,
            "mchid": self.settings.wechat_mchid,
            "description": (order.subject or "积分充值")[:120],
            "out_trade_no": order.id,
            "notify_url": notify_url,
            "amount": {"total": int(order.amount_cents), "currency": "CNY"},
        }
        if order.expires_at:
            payload["time_expire"] = order.expires_at.replace(tzinfo=timezone.utc).astimezone(CST).isoformat(timespec="seconds")
        data = self._request("POST", "/v3/pay/transactions/native", payload)
        return CreateResult(code_url=data.get("code_url", ""))

    def verify_headers(self, headers: dict, body: bytes) -> None:
        lower = {k.lower(): v for k, v in headers.items()}
        ts = lower.get("wechatpay-timestamp", "")
        nonce = lower.get("wechatpay-nonce", "")
        signature = lower.get("wechatpay-signature", "")
        serial = lower.get("wechatpay-serial", "")
        if not (ts and nonce and signature):
            raise PaymentError("微信支付通知缺少签名头")
        if abs(time.time() - int(ts)) > MAX_CLOCK_SKEW:
            raise PaymentError("微信支付通知时间戳过期")
        if self.settings.wechat_platform_serial and serial and serial != self.settings.wechat_platform_serial:
            raise PaymentError("微信支付平台证书序列号不匹配")
        message = f"{ts}\n{nonce}\n{body.decode('utf-8')}\n".encode("utf-8")
        if not rsa_verify(load_public_key(self.settings.wechat_platform_public_key), message, signature):
            raise PaymentError("微信支付通知验签失败")

    def parse_notify(self, headers: dict, body: bytes) -> NotifyResult:
        self.verify_headers(headers, body)
        envelope = json.loads(body.decode("utf-8"))
        data = decrypt_resource(self.settings.wechat_api_v3_key, envelope.get("resource") or {})
        if data.get("mchid") and data.get("mchid") != self.settings.wechat_mchid:
            raise PaymentError("微信支付通知商户号不匹配")
        state = data.get("trade_state", "")
        return NotifyResult(
            order_id=data.get("out_trade_no", ""),
            event_key=f"wechat:{envelope.get('id') or data.get('transaction_id')}",
            paid=state == "SUCCESS",
            closed=state in ("CLOSED", "REVOKED", "PAYERROR"),
            trade_no=data.get("transaction_id", ""),
            amount_cents=int((data.get("amount") or {}).get("total") or 0) or None,
            raw=data,
        )

    def query(self, order) -> NotifyResult | None:
        data = self._request("GET", f"/v3/pay/transactions/out-trade-no/{order.id}?mchid={self.settings.wechat_mchid}")
        state = data.get("trade_state", "")
        return NotifyResult(
            order_id=order.id,
            event_key=f"wechat-query:{order.id}:{state}",
            paid=state == "SUCCESS",
            closed=state in ("CLOSED", "REVOKED", "PAYERROR"),
            trade_no=data.get("transaction_id", ""),
            amount_cents=int((data.get("amount") or {}).get("total") or 0) or None,
            raw=data,
        )

    def close(self, order) -> None:
        self._request("POST", f"/v3/pay/transactions/out-trade-no/{order.id}/close", {"mchid": self.settings.wechat_mchid})

    def refund(self, order, amount_cents: int, reason: str) -> str:
        refund_no = f"{order.id}-R{int(time.time())}"
        self._request(
            "POST",
            "/v3/refund/domestic/refunds",
            {
                "out_trade_no": order.id,
                "out_refund_no": refund_no,
                "reason": reason[:80],
                "amount": {"refund": amount_cents, "total": int(order.amount_cents), "currency": "CNY"},
            },
        )
        return refund_no
