"""在线支付通道。统一接口见 base.PaymentChannel。"""

from __future__ import annotations

from fastapi import HTTPException

from .base import PaymentChannel


def get_channel(name: str) -> PaymentChannel:
    from ..config import get_settings
    from .alipay import AlipayChannel
    from .mock import MockChannel
    from .wechat import WechatChannel

    settings = get_settings()
    if name == "alipay":
        return AlipayChannel(settings)
    if name == "wechat":
        return WechatChannel(settings)
    if name == "mock":
        if not settings.mock_payment_enabled:
            raise HTTPException(400, "生产环境不支持模拟支付")
        return MockChannel()
    raise HTTPException(400, "不支持的支付方式")


def available_channels() -> list[dict]:
    from ..config import get_settings

    settings = get_settings()
    out = [
        {"id": "alipay", "name": "支付宝", "ready": bool(settings.alipay_app_id and settings.alipay_private_key)},
        {"id": "wechat", "name": "微信支付（微信 / 企业微信扫码）", "ready": bool(settings.wechat_mchid and settings.wechat_private_key)},
        {"id": "bank", "name": "对公转账", "ready": bool(settings.bank_account_no)},
    ]
    if settings.mock_payment_enabled:
        out.append({"id": "mock", "name": "模拟支付（仅测试环境）", "ready": True})
    return out
