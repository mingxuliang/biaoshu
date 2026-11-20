"""平台级数据（platform schema）：企业、登录账号索引、平台管理员、套餐、积分、订单、发票、审计。

这些表只保存企业的元数据和账务数据，不保存任何企业业务文件或知识库内容。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String, Text

from .db import PlatformBase
from .models import gen_id
from .secret_box import EncryptedText


class Tenant(PlatformBase):
    __tablename__ = "tenants"

    id = Column(String, primary_key=True)  # 小写字母数字，对应 schema t_<id>
    name = Column(String, nullable=False)
    # 企业：多成员共享一个积分池；个人：只有本人一个账号，可升级为企业
    kind = Column(String, default="企业")
    status = Column(String, default="试用")  # 试用 | 正常 | 停用 | 已注销
    plan_code = Column(String, default="trial")
    seats = Column(Integer, default=3)
    storage_quota_mb = Column(Integer, default=2048)
    features_json = Column(JSON, default=dict)
    verify_status = Column(String, default="未认证")  # 未认证 | 待审核 | 已认证 | 已驳回
    verify_note = Column(String, default="")
    license_no = Column(String, default="")  # 统一社会信用代码
    license_key = Column(String, default="")  # 营业执照在企业 bucket 内的对象键
    contact_name = Column(String, default="")
    contact_phone = Column(String, default="")
    contact_email = Column(String, default="")
    trial_ends_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    low_balance_threshold = Column(Integer, default=200)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Account(PlatformBase):
    """登录名到企业的索引：登录时据此定位企业 schema。登录名全平台唯一。"""

    __tablename__ = "accounts"

    login = Column(String, primary_key=True)
    tenant_id = Column(String, index=True, nullable=False)
    user_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class PlatformAdmin(PlatformBase):
    __tablename__ = "platform_admins"

    id = Column(String, primary_key=True, default=lambda: gen_id("padm"))
    email = Column(String, unique=True, nullable=False)
    name = Column(String, default="")
    password_hash = Column(String, nullable=False)
    role = Column(String, default="运营")  # 超级管理员 | 运营 | 财务 | 只读
    totp_secret = Column(EncryptedText, default="")
    disabled = Column(Boolean, default=False)
    token_version = Column(Integer, default=0)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Plan(PlatformBase):
    """套餐（按年）与加油包（一次性积分）。"""

    __tablename__ = "plans"

    code = Column(String, primary_key=True)
    kind = Column(String, default="套餐")  # 套餐 | 加油包
    audience = Column(String, default="通用")  # 企业 | 个人 | 通用
    name = Column(String, nullable=False)
    price_cents = Column(Integer, default=0)
    duration_days = Column(Integer, default=365)
    seats = Column(Integer, default=0)
    credits = Column(Integer, default=0)
    bonus_credits = Column(Integer, default=0)
    storage_mb = Column(Integer, default=0)
    # 后续自由充值的赠送比例（%），档位越高越优惠
    recharge_bonus_pct = Column(Integer, default=0)
    features_json = Column(JSON, default=dict)
    description = Column(Text, default="")
    enabled = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)


class Subscription(PlatformBase):
    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True, default=lambda: gen_id("sub"))
    tenant_id = Column(String, index=True, nullable=False)
    plan_code = Column(String, nullable=False)
    starts_at = Column(DateTime, nullable=False)
    ends_at = Column(DateTime, nullable=False)
    order_id = Column(String, nullable=True)
    status = Column(String, default="生效")  # 生效 | 已过期 | 已取消
    created_at = Column(DateTime, default=datetime.utcnow)


class Wallet(PlatformBase):
    """企业共享钱包。balance = 各积分桶 remaining 之和（冗余，便于展示和加锁）。"""

    __tablename__ = "wallets"

    tenant_id = Column(String, primary_key=True)
    balance = Column(Integer, default=0)
    held = Column(Integer, default=0)
    total_recharged = Column(Integer, default=0)
    total_consumed = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CreditBucket(PlatformBase):
    """积分桶：套餐积分有到期日，充值积分默认不过期。扣费按到期日从早到晚。"""

    __tablename__ = "credit_buckets"

    id = Column(String, primary_key=True, default=lambda: gen_id("cb"))
    tenant_id = Column(String, index=True, nullable=False)
    source = Column(String, nullable=False)  # 试用 | 套餐 | 充值 | 赠送 | 调整
    amount = Column(Integer, nullable=False)
    remaining = Column(Integer, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    order_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class CreditLedger(PlatformBase):
    """积分流水，只追加不修改。"""

    __tablename__ = "credit_ledger"

    id = Column(String, primary_key=True, default=lambda: gen_id("cl"))
    tenant_id = Column(String, index=True, nullable=False)
    user_id = Column(String, nullable=True, index=True)
    user_name = Column(String, default="")
    kind = Column(String, nullable=False)  # 充值 | 套餐 | 赠送 | 消费 | 退回 | 调整 | 过期
    amount = Column(Integer, nullable=False)  # 正数入账，负数出账
    balance_after = Column(Integer, nullable=False)
    feature = Column(String, default="")
    ref_id = Column(String, default="")
    idem_key = Column(String, unique=True, nullable=True)
    note = Column(String, default="")
    operator = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class CreditHold(PlatformBase):
    """任务开始前的预占。结算时按实际用量扣，多余部分释放；任务失败整笔释放。"""

    __tablename__ = "credit_holds"

    id = Column(String, primary_key=True, default=lambda: gen_id("ch"))
    tenant_id = Column(String, index=True, nullable=False)
    user_id = Column(String, nullable=True)
    user_name = Column(String, default="")
    feature = Column(String, nullable=False)
    ref_id = Column(String, default="", index=True)
    amount = Column(Integer, nullable=False)
    used = Column(Float, default=0)
    status = Column(String, default="holding")  # holding | settled | released
    created_at = Column(DateTime, default=datetime.utcnow)
    settled_at = Column(DateTime, nullable=True)


class UsageRecord(PlatformBase):
    """每次模型调用的计量明细，供后台按企业/模型/功能统计 token。"""

    __tablename__ = "usage_records"

    id = Column(String, primary_key=True, default=lambda: gen_id("use"))
    tenant_id = Column(String, index=True, nullable=False)
    user_id = Column(String, nullable=True, index=True)
    feature = Column(String, default="", index=True)
    model = Column(String, default="", index=True)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    calls = Column(Integer, default=1)
    credits = Column(Float, default=0)
    hold_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class PriceRule(PlatformBase):
    """功能单价。mode=per_1k_tokens 按千 token；per_call 按次；free 不扣费。"""

    __tablename__ = "price_rules"

    feature = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    mode = Column(String, default="per_1k_tokens")
    unit_price = Column(Float, default=1.0)
    estimate = Column(Integer, default=20)  # 预占积分
    enabled = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)


class ModelRatio(PlatformBase):
    """模型倍率：贵的模型扣得多。key 为 LlmModel.id 或接口模型名。"""

    __tablename__ = "model_ratios"

    model_key = Column(String, primary_key=True)
    ratio = Column(Float, default=1.0)
    note = Column(String, default="")


class RechargeOrder(PlatformBase):
    __tablename__ = "recharge_orders"

    id = Column(String, primary_key=True)  # 即 out_trade_no
    tenant_id = Column(String, index=True, nullable=False)
    user_id = Column(String, nullable=True)
    user_name = Column(String, default="")
    kind = Column(String, nullable=False)  # 充值 | 套餐 | 加油包
    item_code = Column(String, default="")
    subject = Column(String, default="")
    amount_cents = Column(Integer, nullable=False)
    credits = Column(Integer, default=0)
    bonus_credits = Column(Integer, default=0)
    channel = Column(String, nullable=False)  # alipay | wechat | bank | mock
    status = Column(String, default="待支付")  # 待支付 | 待确认 | 已支付 | 已关闭 | 已退款
    pay_url = Column(Text, default="")
    code_url = Column(Text, default="")
    transfer_code = Column(String, default="", index=True)
    channel_trade_no = Column(String, default="")
    paid_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    invoiced_cents = Column(Integer, default=0)
    refunded_cents = Column(Integer, default=0)
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class PaymentEvent(PlatformBase):
    """支付回调原文，event_key 唯一，重复回调不会重复入账。"""

    __tablename__ = "payment_events"

    id = Column(String, primary_key=True, default=lambda: gen_id("pev"))
    channel = Column(String, nullable=False)
    order_id = Column(String, index=True, default="")
    event_key = Column(String, unique=True, nullable=False)
    verified = Column(Boolean, default=False)
    payload_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class BankTransfer(PlatformBase):
    """对公转账回单，后台核对到账后认领。"""

    __tablename__ = "bank_transfers"

    id = Column(String, primary_key=True, default=lambda: gen_id("bt"))
    order_id = Column(String, index=True, nullable=False)
    tenant_id = Column(String, index=True, nullable=False)
    payer_name = Column(String, default="")
    payer_account = Column(String, default="")
    amount_cents = Column(Integer, default=0)
    bank_serial = Column(String, default="")
    receipt_key = Column(String, default="")
    receipt_name = Column(String, default="")
    status = Column(String, default="待认领")  # 待认领 | 已确认 | 已驳回
    note = Column(String, default="")
    operator = Column(String, default="")
    confirmed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class InvoiceTitle(PlatformBase):
    __tablename__ = "invoice_titles"

    id = Column(String, primary_key=True, default=lambda: gen_id("ivt"))
    tenant_id = Column(String, index=True, nullable=False)
    kind = Column(String, default="普票")  # 普票 | 专票
    title = Column(String, nullable=False)
    tax_no = Column(String, default="")
    address = Column(String, default="")
    phone = Column(String, default="")
    bank_name = Column(String, default="")
    bank_account = Column(String, default="")
    email = Column(String, default="")
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Invoice(PlatformBase):
    __tablename__ = "invoices"

    id = Column(String, primary_key=True, default=lambda: gen_id("inv"))
    tenant_id = Column(String, index=True, nullable=False)
    applicant_id = Column(String, nullable=True)
    applicant_name = Column(String, default="")
    kind = Column(String, default="普票")
    title_json = Column(JSON, default=dict)
    amount_cents = Column(Integer, nullable=False)
    order_ids_json = Column(JSON, default=list)
    status = Column(String, default="待审核")  # 待审核 | 开具中 | 已开具 | 已驳回 | 已红冲
    invoice_no = Column(String, default="")
    file_key = Column(String, default="")
    file_name = Column(String, default="")
    reject_reason = Column(String, default="")
    operator = Column(String, default="")
    issued_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PlatformAudit(PlatformBase):
    __tablename__ = "platform_audit"

    id = Column(String, primary_key=True, default=lambda: gen_id("pa"))
    admin_id = Column(String, nullable=True)
    admin_name = Column(String, default="")
    action = Column(String, nullable=False)
    tenant_id = Column(String, default="", index=True)
    target = Column(String, default="")
    detail = Column(Text, default="")
    ip = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class SystemSetting(PlatformBase):
    __tablename__ = "system_settings"

    key = Column(String, primary_key=True)
    value_json = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Announcement(PlatformBase):
    __tablename__ = "announcements"

    id = Column(String, primary_key=True, default=lambda: gen_id("ann"))
    title = Column(String, nullable=False)
    body = Column(Text, default="")
    level = Column(String, default="info")  # info | warning
    published = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class SupportGrant(PlatformBase):
    """企业管理员授予平台运维的限时查看权限；没有有效授权时后台看不到企业文件内容。"""

    __tablename__ = "support_grants"

    id = Column(String, primary_key=True, default=lambda: gen_id("sg"))
    tenant_id = Column(String, index=True, nullable=False)
    granted_by = Column(String, default="")
    reason = Column(String, default="")
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class StdCatalog(PlatformBase):
    """平台公共规范目录。各企业只读，不进企业知识库切片。"""

    __tablename__ = "std_catalog"

    id = Column(String, primary_key=True, default=lambda: gen_id("stdc"))
    code = Column(String, default="", index=True)
    name = Column(String, default="")
    specialty = Column(String, default="通用", index=True)
    implement_date = Column(String, default="")
    status = Column(String, default="未知")  # 现行 | 废止 | 未知 | 入库中 | 失败
    replaced_by = Column(String, default="")
    source_file = Column(String, default="")
    storage_path = Column(String, default="")
    clause_count = Column(Integer, default=0)
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class StdClause(PlatformBase):
    """平台公共规范条文。"""

    __tablename__ = "std_clauses"

    id = Column(String, primary_key=True, default=lambda: gen_id("stdcl"))
    catalog_id = Column(String, index=True, nullable=False)
    code = Column(String, default="", index=True)
    clause_no = Column(String, default="", index=True)
    text = Column(Text, default="")
    mandatory = Column(Boolean, default=False)
    is_commentary = Column(Boolean, default=False)
    topics_json = Column(JSON, default=list)
    table_text = Column(Text, default="")
    specialty = Column(String, default="通用", index=True)
    source_file = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class VerifyCode(PlatformBase):
    __tablename__ = "verify_codes"

    id = Column(String, primary_key=True, default=lambda: gen_id("vc"))
    target = Column(String, index=True, nullable=False)
    purpose = Column(String, default="signup")
    code_hash = Column(String, nullable=False)
    attempts = Column(Integer, default=0)
    used = Column(Boolean, default=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
