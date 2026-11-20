"""模拟支付：仅开发和测试环境，用来走通下单、到账、积分入账的完整流程。"""

from __future__ import annotations

from .base import CreateResult, NotifyResult, PaymentChannel


class MockChannel(PaymentChannel):
    name = "mock"

    def create(self, order, notify_url: str, return_url: str = "") -> CreateResult:
        return CreateResult(code_url=f"mock://pay/{order.id}")

    def parse_notify(self, headers: dict, body: bytes) -> NotifyResult:
        order_id = body.decode("utf-8").strip()
        return NotifyResult(order_id=order_id, event_key=f"mock:{order_id}", paid=True, trade_no=f"MOCK-{order_id}")

    def query(self, order) -> NotifyResult | None:
        return None
