"""平台级初始数据：套餐与加油包、功能单价、平台管理员、模型目录。"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .config import get_settings

logger = logging.getLogger(__name__)

# 参考同行：年费内含积分和席位，档位越高赠送和充值比例越好；加油包永不过期
DEFAULT_PLANS = [
    {
        "code": "trial",
        "kind": "套餐",
        "name": "免费试用",
        "price_cents": 0,
        "duration_days": 14,
        "seats": 3,
        "credits": 0,
        "storage_mb": 2048,
        "recharge_bonus_pct": 0,
        "features_json": {"knowledge": True, "products": True, "qualifications": True},
        "description": "注册即送试用积分，14 天内体验全流程",
        "sort_order": 0,
    },
    {
        "code": "basic",
        "kind": "套餐",
        "name": "基础版",
        "price_cents": 800000,
        "duration_days": 365,
        "seats": 3,
        "credits": 60000,
        "storage_mb": 20 * 1024,
        "recharge_bonus_pct": 0,
        "features_json": {"knowledge": True, "products": True, "qualifications": True},
        "description": "1-3 人投标小组",
        "sort_order": 1,
    },
    {
        "code": "pro",
        "kind": "套餐",
        "name": "专业版",
        "price_cents": 1680000,
        "duration_days": 365,
        "seats": 8,
        "credits": 150000,
        "storage_mb": 100 * 1024,
        "recharge_bonus_pct": 10,
        "features_json": {"knowledge": True, "products": True, "qualifications": True, "departments": True},
        "description": "多人并行做标的投标部",
        "sort_order": 2,
    },
    {
        "code": "flagship",
        "kind": "套餐",
        "name": "旗舰版",
        "price_cents": 3680000,
        "duration_days": 365,
        "seats": 30,
        "credits": 400000,
        "storage_mb": 500 * 1024,
        "recharge_bonus_pct": 20,
        "features_json": {"knowledge": True, "products": True, "qualifications": True, "departments": True, "customRoles": True},
        "description": "集团或多业务线企业",
        "sort_order": 3,
    },
    {
        "code": "personal-month",
        "kind": "套餐",
        "audience": "个人",
        "name": "个人月卡",
        "price_cents": 19900,
        "duration_days": 30,
        "seats": 1,
        "credits": 1500,
        "storage_mb": 5 * 1024,
        "recharge_bonus_pct": 0,
        "features_json": {"knowledge": True, "products": True, "qualifications": True},
        "description": "个人投标顾问按月使用",
        "sort_order": 5,
    },
    {
        "code": "personal-year",
        "kind": "套餐",
        "audience": "个人",
        "name": "个人年卡",
        "price_cents": 168000,
        "duration_days": 365,
        "seats": 1,
        "credits": 15000,
        "storage_mb": 10 * 1024,
        "recharge_bonus_pct": 5,
        "features_json": {"knowledge": True, "products": True, "qualifications": True},
        "description": "个人全年使用，充值额外赠送 5%",
        "sort_order": 6,
    },
    {"code": "pack-100", "kind": "加油包", "name": "积分加油包 1000", "price_cents": 10000, "credits": 1000, "bonus_credits": 0, "sort_order": 10},
    {"code": "pack-500", "kind": "加油包", "name": "积分加油包 5500", "price_cents": 50000, "credits": 5000, "bonus_credits": 500, "sort_order": 11},
    {"code": "pack-2000", "kind": "加油包", "name": "积分加油包 24000", "price_cents": 200000, "credits": 20000, "bonus_credits": 4000, "sort_order": 12},
]


def seed_plans(db: Session) -> None:
    from .platform_models import Plan

    for item in DEFAULT_PLANS:
        row = db.get(Plan, item["code"])
        if row is None:
            db.add(Plan(**{"audience": default_audience(item), **item}))
        elif not row.audience:
            row.audience = default_audience(item)
    for row in db.query(Plan).filter((Plan.audience.is_(None)) | (Plan.audience == "")).all():
        row.audience = "通用" if row.kind == "加油包" else "企业"
    db.commit()


def default_audience(item: dict) -> str:
    if item.get("audience"):
        return item["audience"]
    if item["kind"] == "加油包" or item["code"] == "trial":
        return "通用"
    return "企业"


def seed_platform_admin(db: Session) -> None:
    from .auth import hash_password, random_password
    from .platform_models import PlatformAdmin

    if db.query(PlatformAdmin).count() > 0:
        return
    settings = get_settings()
    password = (settings.platform_admin_password or "").strip()
    generated = not password
    if generated:
        password = random_password(16)
    db.add(
        PlatformAdmin(
            email=settings.platform_admin_email.strip().lower(),
            name="平台超级管理员",
            password_hash=hash_password(password),
            role="超级管理员",
        )
    )
    db.commit()
    if generated:
        logger.warning(
            "已创建平台管理员 %s，初始密码：%s（仅显示这一次，登录后台后请立即修改）",
            settings.platform_admin_email,
            password,
        )


def seed_platform() -> None:
    from .billing import seed_prices
    from .db import platform_session
    from .seed import seed_llm

    with platform_session() as db:
        seed_plans(db)
        seed_prices(db)
        seed_platform_admin(db)
        seed_llm(db)
