from __future__ import annotations

import base64
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


@dataclass
class CreateResult:
    pay_url: str = ""  # 跳转收银台（支付宝电脑网站支付）
    code_url: str = ""  # 生成二维码（微信 Native / 支付宝当面付）


@dataclass
class NotifyResult:
    order_id: str
    event_key: str
    paid: bool = False
    closed: bool = False
    trade_no: str = ""
    amount_cents: int | None = None
    raw: dict = field(default_factory=dict)


class PaymentError(RuntimeError):
    pass


class PaymentChannel:
    name = ""
    # 回调处理成功后返回给支付平台的响应
    ack_body = "success"
    ack_media = "text/plain"

    def create(self, order, notify_url: str, return_url: str = "") -> CreateResult:  # pragma: no cover - 接口
        raise NotImplementedError

    def parse_notify(self, headers: dict, body: bytes) -> NotifyResult:  # pragma: no cover - 接口
        raise NotImplementedError

    def query(self, order) -> NotifyResult | None:
        return None

    def close(self, order) -> None:
        return None

    def refund(self, order, amount_cents: int, reason: str) -> str:  # pragma: no cover - 接口
        raise PaymentError("该通道暂不支持在线退款，请走线下退款")


def load_private_key(pem_or_b64: str):
    text = (pem_or_b64 or "").strip()
    if not text:
        raise PaymentError("未配置商户私钥")
    if "BEGIN" not in text:
        text = "-----BEGIN PRIVATE KEY-----\n" + text + "\n-----END PRIVATE KEY-----"
    try:
        return serialization.load_pem_private_key(text.encode(), password=None)
    except ValueError:
        # 支付宝工具生成的可能是 PKCS#1（RSA PRIVATE KEY）
        alt = text.replace("BEGIN PRIVATE KEY", "BEGIN RSA PRIVATE KEY").replace("END PRIVATE KEY", "END RSA PRIVATE KEY")
        return serialization.load_pem_private_key(alt.encode(), password=None)


def load_public_key(pem_or_b64: str):
    text = (pem_or_b64 or "").strip()
    if not text:
        raise PaymentError("未配置平台公钥")
    if "BEGIN" not in text:
        text = "-----BEGIN PUBLIC KEY-----\n" + text + "\n-----END PUBLIC KEY-----"
    return serialization.load_pem_public_key(text.encode())


def rsa_sign(private_key, message: bytes) -> str:
    return base64.b64encode(private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())).decode()


def rsa_verify(public_key, message: bytes, signature_b64: str) -> bool:
    try:
        public_key.verify(base64.b64decode(signature_b64), message, padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception:  # noqa: BLE001 —— 任何验签异常都视为失败
        return False


def yuan(amount_cents: int) -> str:
    return f"{amount_cents // 100}.{amount_cents % 100:02d}"


def cents(amount_yuan: str | float | None) -> int | None:
    if amount_yuan is None or amount_yuan == "":
        return None
    text = str(amount_yuan).strip()
    if "." in text:
        whole, frac = text.split(".", 1)
        frac = (frac + "00")[:2]
    else:
        whole, frac = text, "00"
    return int(whole or 0) * 100 + int(frac)
