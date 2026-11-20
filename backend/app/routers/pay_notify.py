"""支付平台异步通知。无登录态，只认签名；处理结果幂等。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from ..db import platform_session
from ..payments import get_channel
from ..payments import orders as order_svc
from ..payments.base import PaymentError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pay", tags=["pay"])


@router.post("/notify/{channel}")
async def pay_notify(channel: str, request: Request) -> Response:
    if channel not in ("alipay", "wechat"):
        raise HTTPException(404, "未知通道")
    impl = get_channel(channel)
    body = await request.body()
    try:
        result = impl.parse_notify(dict(request.headers), body)
    except PaymentError as exc:
        logger.warning("支付回调验签失败 %s：%s", channel, exc)
        return Response("fail", status_code=400, media_type="text/plain")
    with platform_session() as pdb:
        try:
            order_svc.apply_notify(pdb, channel, result)
        except HTTPException as exc:
            logger.error("支付回调处理失败 %s %s：%s", channel, result.order_id, exc.detail)
            # 金额不一致等问题需要人工处理，返回失败让支付平台重试并留下记录
            return Response("fail", status_code=500, media_type="text/plain")
    return Response(impl.ack_body, media_type=impl.ack_media)
