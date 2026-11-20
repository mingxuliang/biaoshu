"""SaaS 改造回归：企业隔离、令牌分离、积分分桶与预占结算、订单入账幂等、支付验签、发票、协作锁、后台认证。

全部用内存 sqlite（企业表和平台表建在同一个库里）和桩，不接外部服务。
schema 级隔离依赖 Postgres 的 search_path，sqlite 下只能验证代码路径上的企业校验。
"""

from __future__ import annotations

import base64
import json
import os
import time
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import billing, db as db_mod, platform_models  # noqa: E402,F401
from app.db import Base, PlatformBase, ScopedSession  # noqa: E402
from app.tenancy import use_tenant  # noqa: E402

TID = "acme"
OTHER = "rival"


class SaasCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(bind=self.engine)
        PlatformBase.metadata.create_all(bind=self.engine)
        factory = sessionmaker(class_=ScopedSession, autocommit=False, autoflush=False, bind=self.engine)
        patcher = mock.patch.object(db_mod, "_factory", factory)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pdb = db_mod.platform_session()
        self.addCleanup(self.pdb.close)
        billing.seed_prices(self.pdb)
        from app.platform_models import Tenant

        for tid in (TID, OTHER):
            self.pdb.add(Tenant(id=tid, name=f"企业{tid}", status="正常", seats=5, storage_quota_mb=0))
        self.pdb.commit()

    def tdb(self, tid=TID):
        return db_mod.tenant_session(tid)

    def make_user(self, tid=TID, role="管理员", name="u"):
        from app.auth import hash_password
        from app.models import User

        s = self.tdb(tid)
        user = User(name=name, email=f"{name}@{tid}.cn", password_hash=hash_password("abc12345"), role=role)
        s.add(user)
        s.commit()
        s.refresh(user)
        s.expunge(user)
        s.close()
        return user


# ---------------------------------------------------------------------------
# 令牌与企业上下文
# ---------------------------------------------------------------------------


class TokenIsolationTests(SaasCase):
    def test_tenant_and_platform_tokens_not_interchangeable(self):
        from app.tokens import create_platform_token, create_tenant_token, decode_platform_token, decode_tenant_token

        t = create_tenant_token("u1", TID)
        p = create_platform_token("a1")
        self.assertEqual(decode_tenant_token(t)["tid"], TID)
        self.assertEqual(decode_platform_token(p)["sub"], "a1")
        with self.assertRaises(HTTPException):
            decode_platform_token(t)
        with self.assertRaises(HTTPException):
            decode_tenant_token(p)

    def test_token_of_other_tenant_rejected(self):
        """A 企业的令牌拿到 B 企业的会话上（比如伪造请求头）也不能通过。"""
        from app.auth import get_current_user, token_for

        user = self.make_user(TID, name="alice")
        token = token_for(user, TID)
        other_db = self.tdb(OTHER)
        try:
            with self.assertRaises(HTTPException) as ctx:
                get_current_user(authorization=f"Bearer {token}", db=other_db)
            self.assertEqual(ctx.exception.status_code, 401)
        finally:
            other_db.close()
        own_db = self.tdb(TID)
        try:
            self.assertEqual(get_current_user(authorization=f"Bearer {token}", db=own_db).id, user.id)
        finally:
            own_db.close()

    def test_session_requires_tenant_context(self):
        from app.db import SessionLocal
        from app.tenancy import TenantRequired

        with self.assertRaises(TenantRequired):
            SessionLocal()
        with use_tenant(TID):
            s = SessionLocal()
            self.assertEqual(s.info["tenant_id"], TID)
            self.assertEqual(s.info["schema"], "t_acme")
            s.close()

    def test_get_db_without_context_is_401(self):
        gen = db_mod.get_db()
        with self.assertRaises(HTTPException) as ctx:
            next(gen)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_storage_bucket_follows_tenant(self):
        from app import storage
        from app.tenancy import TenantRequired, bucket_for

        self.assertNotEqual(bucket_for(TID), bucket_for(OTHER))
        self.assertEqual(bucket_for("default"), storage.get_settings().minio_bucket)
        with self.assertRaises(TenantRequired):
            storage._bucket()
        with use_tenant(OTHER):
            self.assertEqual(storage._bucket(), bucket_for(OTHER))

    def test_celery_task_rejects_missing_tenant(self):
        from app.celery_app import TenantTask
        from app.tenancy import TenantRequired

        task = TenantTask()
        with self.assertRaises(TenantRequired):
            task.apply_async(args=["x"])

    def test_invalid_tenant_ids(self):
        from app.tenancy import schema_for, valid_tenant_id

        for bad in ("", "A", "a;drop", "x" * 60, "../t", "t-1"):
            self.assertFalse(valid_tenant_id(bad), bad)
        with self.assertRaises(Exception):
            schema_for("bad;id")


class AccountIndexTests(SaasCase):
    def test_login_unique_across_tenants(self):
        from app.tenants import find_account, register_account

        register_account(self.pdb, "same@x.cn", TID, "u1")
        self.pdb.commit()
        with self.assertRaises(HTTPException) as ctx:
            register_account(self.pdb, "SAME@x.cn", OTHER, "u2")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(find_account(self.pdb, "same@x.cn").tenant_id, TID)


class WriteGuardTests(SaasCase):
    def test_expired_trial_blocks_writes(self):
        from app.platform_models import Tenant
        from app.tenants import clear_block_cache, write_block_reason

        t = self.pdb.get(Tenant, TID)
        t.status = "试用"
        t.trial_ends_at = datetime.utcnow() - timedelta(days=1)
        self.pdb.commit()
        clear_block_cache()
        self.assertIn("试用已到期", write_block_reason(TID))
        self.assertIsNone(write_block_reason(OTHER))
        t.status = "停用"
        self.pdb.commit()
        clear_block_cache()
        self.assertIn("停用", write_block_reason(TID))


# ---------------------------------------------------------------------------
# 积分
# ---------------------------------------------------------------------------


class WalletTests(SaasCase):
    def test_expiring_bucket_consumed_first(self):
        from app.platform_models import CreditBucket

        billing.grant(self.pdb, TID, 100, source="充值")
        billing.grant(self.pdb, TID, 50, source="套餐", expires_at=datetime.utcnow() + timedelta(days=5))
        billing.consume(self.pdb, TID, 60, feature="chapter")
        self.pdb.commit()
        rows = {b.source: b.remaining for b in self.pdb.query(CreditBucket).filter(CreditBucket.tenant_id == TID).all()}
        self.assertEqual(rows["套餐"], 0)
        self.assertEqual(rows["充值"], 90)
        self.assertEqual(billing.balance_of(self.pdb, TID)["balance"], 90)

    def test_expired_bucket_not_spendable(self):
        billing.grant(self.pdb, TID, 100, source="套餐", expires_at=datetime.utcnow() - timedelta(seconds=1))
        self.pdb.commit()
        with self.assertRaises(billing.InsufficientCredits):
            billing.consume(self.pdb, TID, 10)
        self.pdb.rollback()
        self.assertEqual(billing.expire_credits(TID), 100)
        self.assertEqual(billing.balance_of(self.pdb, TID)["balance"], 0)

    def test_grant_and_consume_idempotent(self):
        billing.grant(self.pdb, TID, 100, source="充值", idem_key="order:1")
        billing.grant(self.pdb, TID, 100, source="充值", idem_key="order:1")
        billing.consume(self.pdb, TID, 30, idem_key="hold:1")
        billing.consume(self.pdb, TID, 30, idem_key="hold:1")
        self.pdb.commit()
        self.assertEqual(billing.balance_of(self.pdb, TID)["balance"], 70)

    def test_wallets_are_per_tenant(self):
        billing.grant(self.pdb, TID, 100, source="充值")
        self.pdb.commit()
        self.assertEqual(billing.balance_of(self.pdb, OTHER)["balance"], 0)
        with self.assertRaises(billing.InsufficientCredits):
            billing.consume(self.pdb, OTHER, 1)

    def test_adjust_requires_note(self):
        with self.assertRaises(HTTPException):
            billing.adjust(self.pdb, TID, 10, note="", operator="x")
        billing.adjust(self.pdb, TID, 10, note="补偿", operator="x")
        billing.adjust(self.pdb, TID, -50, note="扣回", operator="x")
        self.pdb.commit()
        self.assertEqual(billing.balance_of(self.pdb, TID)["balance"], 0)


class MeteringTests(SaasCase):
    def test_hold_settles_actual_usage(self):
        billing.grant(self.pdb, TID, 1000, source="充值")
        self.pdb.commit()
        with use_tenant(TID):
            with billing.metered("chapter") as meter:
                billing.record_usage(api_model="m", prompt_tokens=1500, completion_tokens=1000)
            self.assertAlmostEqual(meter.credits, 2.5)
        self.pdb.expire_all()
        bal = billing.balance_of(self.pdb, TID)
        self.assertEqual(bal["held"], 0)
        self.assertEqual(bal["balance"], 997)

    def test_failed_job_releases_hold(self):
        billing.grant(self.pdb, TID, 1000, source="充值")
        self.pdb.commit()
        with use_tenant(TID):
            with self.assertRaises(RuntimeError):
                with billing.metered("chapter"):
                    billing.record_usage(api_model="m", prompt_tokens=5000)
                    raise RuntimeError("boom")
            with billing.metered("chapter") as meter:
                billing.record_usage(api_model="m", prompt_tokens=5000)
                meter.refund = True
        self.pdb.expire_all()
        bal = billing.balance_of(self.pdb, TID)
        self.assertEqual((bal["balance"], bal["held"]), (1000, 0))

    def test_model_ratio_applies(self):
        from app.platform_models import ModelRatio

        self.pdb.add(ModelRatio(model_key="pro", ratio=3.0))
        billing.grant(self.pdb, TID, 1000, source="充值")
        self.pdb.commit()
        with use_tenant(TID):
            with billing.metered("chapter") as meter:
                billing.record_usage(api_model="pro", prompt_tokens=1000)
        self.assertAlmostEqual(meter.credits, 3.0)

    def test_insufficient_credits_blocks_before_enqueue(self):
        with use_tenant(TID):
            with self.assertRaises(billing.InsufficientCredits) as ctx:
                billing.require_credits("chapter")
            self.assertEqual(ctx.exception.status_code, 402)
            billing.require_credits("outline")  # 免费功能不拦

    def test_member_monthly_limit(self):
        from app.models import User

        user = self.make_user(TID, role="撰写专家", name="w")
        s = self.tdb()
        s.get(User, user.id).monthly_credit_limit = 10
        s.commit()
        s.close()
        billing.grant(self.pdb, TID, 1000, source="充值")
        self.pdb.commit()
        with use_tenant(TID):
            with self.assertRaises(billing.InsufficientCredits) as ctx:
                billing.require_credits("chapter", user_id=user.id)
        self.assertIn("个人积分上限", ctx.exception.detail)

    def test_ad_hoc_call_outside_task_charges_other(self):
        billing.grant(self.pdb, TID, 100, source="充值")
        self.pdb.commit()
        with use_tenant(TID):
            billing.record_usage(api_model="m", prompt_tokens=2000)
        self.pdb.expire_all()
        self.assertEqual(billing.balance_of(self.pdb, TID)["balance"], 98)

    def test_no_tenant_no_charge(self):
        self.assertEqual(billing.record_usage(api_model="m", prompt_tokens=2000), 0.0)


# ---------------------------------------------------------------------------
# 订单与支付
# ---------------------------------------------------------------------------


def _rsa_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv, pub


class OrderTests(SaasCase):
    def _order(self, **kw):
        from app.payments import orders

        settings = mock.Mock(credits_per_yuan=10, pay_order_expire_minutes=30, public_base_url="http://x", mock_payment_enabled=True)
        with mock.patch.object(orders, "get_settings", return_value=settings), mock.patch("app.config.get_settings", return_value=settings):
            return orders.create_order(self.pdb, tenant_id=TID, user_id=None, user_name="", **kw)

    def test_recharge_paid_once(self):
        from app.payments import get_channel, orders

        order = self._order(kind="充值", channel="mock", amount_cents=10000)
        self.assertEqual(order.credits, 1000)
        with mock.patch("app.config.get_settings", return_value=mock.Mock(mock_payment_enabled=True)):
            ch = get_channel("mock")
        result = ch.parse_notify({}, order.id.encode())
        orders.apply_notify(self.pdb, "mock", result)
        orders.apply_notify(self.pdb, "mock", result)
        orders.mark_paid(self.pdb, order.id)
        self.assertEqual(order.status, "已支付")
        self.assertEqual(billing.balance_of(self.pdb, TID)["balance"], 1000)

    def test_amount_mismatch_rejected(self):
        from app.payments import orders

        order = self._order(kind="充值", channel="mock", amount_cents=10000)
        with self.assertRaises(HTTPException):
            orders.mark_paid(self.pdb, order.id, amount_cents=1)
        self.pdb.rollback()
        self.assertEqual(billing.balance_of(self.pdb, TID)["balance"], 0)

    def test_min_recharge(self):
        with self.assertRaises(HTTPException):
            self._order(kind="充值", channel="mock", amount_cents=1)

    def test_plan_purchase_updates_tenant(self):
        from app.payments import orders
        from app.platform_models import Tenant
        from app.platform_seed import seed_plans

        seed_plans(self.pdb)
        order = self._order(kind="套餐", channel="mock", item_code="pro")
        orders.mark_paid(self.pdb, order.id)
        t = self.pdb.get(Tenant, TID)
        self.assertEqual((t.plan_code, t.seats), ("pro", 8))
        self.assertGreater(t.expires_at, datetime.utcnow() + timedelta(days=300))
        self.assertEqual(billing.balance_of(self.pdb, TID)["balance"], 150000)
        # 续费同套餐顺延
        order2 = self._order(kind="套餐", channel="mock", item_code="pro")
        orders.mark_paid(self.pdb, order2.id)
        self.assertGreater(self.pdb.get(Tenant, TID).expires_at, datetime.utcnow() + timedelta(days=700))

    def test_bank_transfer_confirm(self):
        from app.payments import orders
        from app.platform_models import BankTransfer

        order = self._order(kind="充值", channel="bank", amount_cents=50000)
        self.assertTrue(order.transfer_code.startswith("ZB"))
        bt = BankTransfer(order_id=order.id, tenant_id=TID, amount_cents=40000)
        self.pdb.add(bt)
        self.pdb.commit()
        with self.assertRaises(HTTPException):
            orders.confirm_transfer(self.pdb, bt.id, operator="财务")
        orders.confirm_transfer(self.pdb, bt.id, operator="财务", amount_cents=50000, bank_serial="SN1")
        self.assertEqual(billing.balance_of(self.pdb, TID)["balance"], 5000)

    def test_expired_orders_closed(self):
        from app.payments import orders

        order = self._order(kind="充值", channel="mock", amount_cents=10000)
        order.expires_at = datetime.utcnow() - timedelta(minutes=1)
        self.pdb.commit()
        self.assertEqual(orders.close_expired_orders(self.pdb), 1)
        self.assertEqual(order.status, "已关闭")


class AlipaySignatureTests(unittest.TestCase):
    def setUp(self):
        self.app_priv, self.app_pub = _rsa_pair()
        self.ali_priv, self.ali_pub = _rsa_pair()
        from app.payments.alipay import AlipayChannel

        self.settings = mock.Mock(
            alipay_app_id="2021000",
            alipay_private_key=self.app_priv,
            alipay_public_key=self.ali_pub,
            alipay_gateway="https://openapi-sandbox.dl.alipaydev.com/gateway.do",
        )
        self.ch = AlipayChannel(self.settings)

    def _notify_body(self, **override):
        import urllib.parse

        from app.payments.alipay import sign_content
        from app.payments.base import load_private_key, rsa_sign

        params = {
            "app_id": "2021000",
            "out_trade_no": "ZB1",
            "trade_no": "2024",
            "trade_status": "TRADE_SUCCESS",
            "total_amount": "100.00",
            "notify_id": "n1",
            "sign_type": "RSA2",
        }
        params["sign"] = rsa_sign(load_private_key(self.ali_priv), sign_content(params).encode())
        params.update(override)
        return urllib.parse.urlencode(params).encode()

    def test_page_pay_url_signed(self):
        import urllib.parse

        from app.payments.alipay import sign_content
        from app.payments.base import load_public_key, rsa_verify

        order = mock.Mock(id="ZB1", amount_cents=12345, subject="充值", expires_at=None)
        url = self.ch.page_pay_url(order, "http://n")
        params = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        self.assertIn('"total_amount":"123.45"', params["biz_content"])
        self.assertTrue(rsa_verify(load_public_key(self.app_pub), sign_content(params).encode(), params["sign"]))

    def test_notify_verified(self):
        res = self.ch.parse_notify({}, self._notify_body())
        self.assertTrue(res.paid)
        self.assertEqual((res.order_id, res.amount_cents), ("ZB1", 10000))

    def test_tampered_notify_rejected(self):
        from app.payments.base import PaymentError

        with self.assertRaises(PaymentError):
            self.ch.parse_notify({}, self._notify_body(total_amount="0.01"))


class WechatSignatureTests(unittest.TestCase):
    def setUp(self):
        self.mch_priv, _ = _rsa_pair()
        self.wx_priv, self.wx_pub = _rsa_pair()
        self.v3key = "0123456789abcdef0123456789abcdef"
        from app.payments.wechat import WechatChannel

        self.ch = WechatChannel(
            mock.Mock(
                wechat_mchid="1900",
                wechat_appid="wx1",
                wechat_serial_no="S",
                wechat_private_key=self.mch_priv,
                wechat_api_v3_key=self.v3key,
                wechat_platform_public_key=self.wx_pub,
                wechat_platform_serial="",
                wechat_api_base="https://api.mch.weixin.qq.com",
            )
        )

    def _envelope(self, data: dict) -> bytes:
        nonce = "abcdefghijkl"
        ct = AESGCM(self.v3key.encode()).encrypt(nonce.encode(), json.dumps(data).encode(), b"transaction")
        return json.dumps(
            {"id": "evt1", "resource": {"nonce": nonce, "ciphertext": base64.b64encode(ct).decode(), "associated_data": "transaction"}}
        ).encode()

    def _headers(self, body: bytes, ts: int | None = None) -> dict:
        from app.payments.base import load_private_key, rsa_sign

        ts = ts or int(time.time())
        sig = rsa_sign(load_private_key(self.wx_priv), f"{ts}\nn1\n{body.decode()}\n".encode())
        return {"Wechatpay-Timestamp": str(ts), "Wechatpay-Nonce": "n1", "Wechatpay-Signature": sig, "Wechatpay-Serial": "P"}

    def test_notify_verified_and_decrypted(self):
        body = self._envelope({"mchid": "1900", "out_trade_no": "ZB2", "trade_state": "SUCCESS", "transaction_id": "42", "amount": {"total": 500}})
        res = self.ch.parse_notify(self._headers(body), body)
        self.assertTrue(res.paid)
        self.assertEqual((res.order_id, res.amount_cents, res.event_key), ("ZB2", 500, "wechat:evt1"))

    def test_bad_signature_and_replay_rejected(self):
        from app.payments.base import PaymentError

        body = self._envelope({"mchid": "1900", "out_trade_no": "ZB2", "trade_state": "SUCCESS", "amount": {"total": 500}})
        headers = self._headers(body)
        with self.assertRaises(PaymentError):
            self.ch.parse_notify(headers, body.replace(b"evt1", b"evt2"))
        with self.assertRaises(PaymentError):
            self.ch.parse_notify(self._headers(body, ts=int(time.time()) - 3600), body)

    def test_request_signature_format(self):
        auth = self.ch._auth("POST", "/v3/pay/transactions/native", "{}")
        self.assertTrue(auth.startswith('WECHATPAY2-SHA256-RSA2048 mchid="1900"'))
        self.assertIn('serial_no="S"', auth)


# ---------------------------------------------------------------------------
# 发票
# ---------------------------------------------------------------------------


class InvoiceTests(SaasCase):
    def _paid_order(self, oid="ZBP1", tid=TID, cents=10000):
        from app.platform_models import RechargeOrder

        o = RechargeOrder(id=oid, tenant_id=tid, kind="充值", amount_cents=cents, channel="mock", status="已支付")
        self.pdb.add(o)
        self.pdb.commit()
        return o

    def _title(self, tid=TID):
        from app.platform_models import InvoiceTitle

        t = InvoiceTitle(tenant_id=tid, title="甲公司", tax_no="91110000XXXX")
        self.pdb.add(t)
        self.pdb.commit()
        return t

    def test_apply_once_and_reject_releases(self):
        from app import invoicing

        o = self._paid_order()
        title = self._title()
        user = SimpleNamespace(id="u", name="张三")
        inv = invoicing.apply_invoice(self.pdb, TID, title_id=title.id, order_ids=[o.id], applicant=user)
        self.assertEqual(inv.amount_cents, 10000)
        with self.assertRaises(HTTPException):
            invoicing.apply_invoice(self.pdb, TID, title_id=title.id, order_ids=[o.id], applicant=user)
        invoicing.reject(self.pdb, inv, reason="抬头有误", operator="财务")
        self.assertEqual(o.invoiced_cents, 0)
        invoicing.apply_invoice(self.pdb, TID, title_id=title.id, order_ids=[o.id], applicant=user)

    def test_cannot_invoice_other_tenant_order(self):
        from app import invoicing

        o = self._paid_order(oid="ZBX", tid=OTHER)
        title = self._title()
        with self.assertRaises(HTTPException) as ctx:
            invoicing.apply_invoice(self.pdb, TID, title_id=title.id, order_ids=[o.id], applicant=SimpleNamespace(id="u", name="x"))
        self.assertEqual(ctx.exception.status_code, 404)
        other_title = self._title(OTHER)
        with self.assertRaises(HTTPException):
            invoicing.apply_invoice(self.pdb, TID, title_id=other_title.id, order_ids=[], applicant=SimpleNamespace(id="u", name="x"))


# ---------------------------------------------------------------------------
# 协作
# ---------------------------------------------------------------------------


class CollabTests(SaasCase):
    def test_optimistic_lock_and_edit_lock(self):
        from app.collab import touch_chapter
        from app.models import ChapterAssignment, WriterDraft

        alice = self.make_user(name="alice", role="撰写专家")
        bob = self.make_user(name="bob", role="撰写专家")
        s = self.tdb()
        draft = WriterDraft(project_id="p1")
        s.add(draft)
        s.commit()
        self.assertIsNone(touch_chapter(s, draft, "c1", alice, None), "单人写标不建协作记录")
        row = touch_chapter(s, draft, "c1", alice, 0)
        s.commit()
        self.assertEqual(row.version, 1)
        with self.assertRaises(HTTPException) as ctx:
            touch_chapter(s, draft, "c1", bob, 0)
        self.assertEqual(ctx.exception.status_code, 409)
        row = s.query(ChapterAssignment).one()
        row.locked_by = alice.id
        row.locked_at = datetime.utcnow()
        s.commit()
        with self.assertRaises(HTTPException):
            touch_chapter(s, draft, "c1", bob, 1)
        row.locked_at = datetime.utcnow() - timedelta(hours=1)
        s.commit()
        self.assertEqual(touch_chapter(s, draft, "c1", bob, 1).version, 2)
        s.close()


# ---------------------------------------------------------------------------
# 平台后台认证
# ---------------------------------------------------------------------------


class PlatformAuthTests(SaasCase):
    def test_totp(self):
        from app.platform_auth import new_totp_secret, totp_now, verify_totp

        secret = new_totp_secret()
        self.assertTrue(verify_totp(secret, totp_now(secret)))
        self.assertTrue(verify_totp(secret, totp_now(secret, time.time() - 30)))
        self.assertFalse(verify_totp(secret, totp_now(secret, time.time() - 300)))
        self.assertFalse(verify_totp(secret, "abc"))

    def test_ip_allowlist(self):
        from app import platform_auth

        with mock.patch.object(platform_auth, "get_settings", return_value=mock.Mock(platform_admin_ip_allowlist="10.0.0.0/8, 1.2.3.4")):
            self.assertTrue(platform_auth.ip_allowed("10.1.2.3"))
            self.assertTrue(platform_auth.ip_allowed("1.2.3.4"))
            self.assertFalse(platform_auth.ip_allowed("8.8.8.8"))
            self.assertFalse(platform_auth.ip_allowed("not-ip"))

    def test_admin_token_version_and_roles(self):
        from app.auth import hash_password
        from app.platform_auth import ROLE_FINANCE, get_current_admin, require_roles
        from app.platform_models import PlatformAdmin
        from app.tokens import create_platform_token, create_tenant_token

        req = mock.Mock(headers={}, client=mock.Mock(host="127.0.0.1"))
        a = PlatformAdmin(email="ops@p", password_hash=hash_password("x"), role="只读")
        self.pdb.add(a)
        self.pdb.commit()
        token = create_platform_token(a.id, 0)
        self.assertEqual(get_current_admin(req, f"Bearer {token}", self.pdb).id, a.id)
        with self.assertRaises(HTTPException):
            get_current_admin(req, f"Bearer {create_tenant_token(a.id, TID)}", self.pdb)
        a.token_version = 1
        self.pdb.commit()
        with self.assertRaises(HTTPException):
            get_current_admin(req, f"Bearer {token}", self.pdb)
        with self.assertRaises(HTTPException) as ctx:
            require_roles(ROLE_FINANCE)(admin=a)
        self.assertEqual(ctx.exception.status_code, 403)
        a.role = "超级管理员"
        self.assertIs(require_roles(ROLE_FINANCE)(admin=a), a)

    def test_seed_admin_random_password(self):
        from app.platform_models import PlatformAdmin
        from app.platform_seed import seed_platform_admin

        with mock.patch("app.platform_seed.get_settings", return_value=mock.Mock(platform_admin_password="", platform_admin_email="Admin@P.local")):
            seed_platform_admin(self.pdb)
            seed_platform_admin(self.pdb)
        rows = self.pdb.query(PlatformAdmin).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].email, "admin@p.local")


class VerifyCodeTests(SaasCase):
    def test_issue_consume_and_attempt_limit(self):
        from app import verify_codes

        sent = {}
        with mock.patch.object(verify_codes, "_deliver", side_effect=lambda t, c: sent.update({t: c})):
            verify_codes.issue(self.pdb, "13800000000")
        with self.assertRaises(HTTPException):
            verify_codes.consume(self.pdb, "13800000000", "000000" if sent["13800000000"] != "000000" else "111111")
        verify_codes.consume(self.pdb, "13800000000", sent["13800000000"])
        self.pdb.commit()
        with self.assertRaises(HTTPException):
            verify_codes.consume(self.pdb, "13800000000", sent["13800000000"])


SOLO = "solo"


class PersonalModeTests(SaasCase):
    def setUp(self):
        super().setUp()
        from app.platform_models import Tenant
        from app.platform_seed import seed_plans

        self.pdb.add(Tenant(id=SOLO, name="张三的个人空间", kind="个人", status="试用", seats=1, storage_quota_mb=0))
        self.pdb.commit()
        seed_plans(self.pdb)

    def _quote(self, tid, code):
        from app.payments import orders

        return orders.quote(self.pdb, tid, "套餐", code)

    def test_plans_match_account_kind(self):
        self.assertEqual(self._quote(SOLO, "personal-month")["amountCents"], 19900)
        self.assertGreater(self._quote(TID, "pro")["credits"], 0)
        with self.assertRaises(HTTPException):
            self._quote(SOLO, "pro")
        with self.assertRaises(HTTPException):
            self._quote(TID, "personal-year")
        from app.payments import orders

        # 加油包两种账号都能买
        self.assertEqual(orders.quote(self.pdb, SOLO, "加油包", "pack-100")["credits"], 1000)
        self.assertEqual(orders.quote(self.pdb, TID, "加油包", "pack-100")["credits"], 1000)

    def test_personal_plan_keeps_single_seat(self):
        from app.payments import orders
        from app.platform_models import Tenant

        settings = mock.Mock(credits_per_yuan=10, pay_order_expire_minutes=30, public_base_url="http://x", mock_payment_enabled=True)
        with mock.patch.object(orders, "get_settings", return_value=settings), mock.patch("app.config.get_settings", return_value=settings):
            order = orders.create_order(self.pdb, tenant_id=SOLO, user_id=None, user_name="", kind="套餐", channel="mock", item_code="personal-year")
        orders.mark_paid(self.pdb, order.id)
        t = self.pdb.get(Tenant, SOLO)
        self.assertEqual((t.plan_code, t.seats, t.status), ("personal-year", 1, "正常"))
        self.assertEqual(billing.balance_of(self.pdb, SOLO)["balance"], 15000)

    def test_personal_cannot_invite_members(self):
        from app.routers.users import _check_seats

        s = self.tdb(SOLO)
        try:
            with self.assertRaises(HTTPException) as ctx:
                _check_seats(s)
            self.assertEqual(ctx.exception.status_code, 402)
            self.assertIn("个人版", ctx.exception.detail)
        finally:
            s.close()
        s = self.tdb(TID)
        try:
            _check_seats(s)
        finally:
            s.close()

    def test_upgrade_to_enterprise(self):
        from app.platform_models import Tenant
        from app.tenants import upgrade_to_enterprise

        t = self.pdb.get(Tenant, SOLO)
        with self.assertRaises(HTTPException):
            upgrade_to_enterprise(self.pdb, t, " ")
        upgrade_to_enterprise(self.pdb, t, "张三咨询有限公司")
        self.pdb.commit()
        t = self.pdb.get(Tenant, SOLO)
        self.assertEqual((t.kind, t.name, t.seats), ("企业", "张三咨询有限公司", 3))
        with self.assertRaises(HTTPException):
            upgrade_to_enterprise(self.pdb, t, "再升级一次")
        self.assertGreater(self._quote(SOLO, "pro")["credits"], 0)

    def test_personal_invoice_title(self):
        from app.routers.billing import InvoiceTitleIn, _validate_title

        _validate_title(InvoiceTitleIn(kind="普票", title="张三"), personal=True)
        with self.assertRaises(HTTPException):
            _validate_title(InvoiceTitleIn(kind="专票", title="张三", taxNo="X"), personal=True)
        with self.assertRaises(HTTPException):
            _validate_title(InvoiceTitleIn(kind="普票", title="某企业"), personal=False)

    def test_seed_backfills_audience(self):
        from app.platform_models import Plan
        from app.platform_seed import seed_plans

        from sqlalchemy import text

        self.pdb.add(Plan(code="custom-x", kind="套餐", name="自定义"))
        self.pdb.commit()
        # 模拟 ALTER TABLE 新增列后存量行为 NULL
        self.pdb.execute(text("UPDATE plans SET audience = NULL WHERE code IN ('basic', 'custom-x')"))
        self.pdb.commit()
        self.pdb.expire_all()
        seed_plans(self.pdb)
        self.assertEqual(self.pdb.get(Plan, "basic").audience, "企业")
        self.assertEqual(self.pdb.get(Plan, "pack-500").audience, "通用")
        self.assertEqual(self.pdb.get(Plan, "custom-x").audience, "企业")

    def test_tokens_per_credit(self):
        self.assertEqual(billing.tokens_per_credit(self.pdb), 1000)


class FeeStatsTests(SaasCase):
    def setUp(self):
        super().setUp()
        from app import fee_stats

        fee_stats.clear_directory_cache()
        self.addCleanup(fee_stats.clear_directory_cache)
        self.alice = self.make_user(TID, role="撰写专家", name="alice")
        self.bob = self.make_user(TID, role="撰写专家", name="bob")
        billing.grant(self.pdb, TID, 1000, source="充值")
        billing.grant(self.pdb, OTHER, 500, source="充值")
        self.pdb.commit()
        with use_tenant(TID):
            with billing.metered("chapter", user_id=self.alice.id):
                billing.record_usage(api_model="m", prompt_tokens=3000, completion_tokens=2000)
            with billing.metered("chapter", user_id=self.bob.id):
                billing.record_usage(api_model="m", prompt_tokens=1000)
        self.pdb.expire_all()

    def test_tenant_fees_aggregates_period(self):
        from app import fee_stats

        data = fee_stats.tenant_fees(self.pdb, days=30)
        rows = {r["tenantId"]: r for r in data["items"]}
        self.assertEqual(data["items"][0]["tenantId"], TID)  # 按消耗倒序
        acme = rows[TID]
        self.assertEqual(acme["periodCredits"], 6)
        self.assertEqual((acme["promptTokens"], acme["completionTokens"]), (4000, 2000))
        self.assertEqual(acme["activeUsers"], 2)
        self.assertEqual(acme["available"], 994)
        self.assertEqual(rows[OTHER]["periodCredits"], 0)
        self.assertEqual(data["summary"]["activeTenants"], 1)
        self.assertEqual(fee_stats.tenant_fees(self.pdb, kind="个人")["items"], [])
        self.assertEqual([r["tenantId"] for r in fee_stats.tenant_fees(self.pdb, q="rival")["items"]], [OTHER])

    def test_user_fees_and_detail(self):
        from app import fee_stats

        rows = fee_stats.user_fees(self.pdb, tenant_id=TID, days=30)
        by_name = {r["name"]: r for r in rows}
        self.assertEqual(rows[0]["name"], "alice")
        self.assertEqual(by_name["alice"]["periodCredits"], 5)
        self.assertEqual(by_name["alice"]["monthSpent"], 5)
        self.assertEqual(by_name["bob"]["promptTokens"], 1000)
        self.assertEqual([r["name"] for r in fee_stats.user_fees(self.pdb, tenant_id=TID, q="bob")], ["bob"])

        detail = fee_stats.user_usage(self.pdb, TID, self.alice.id, 7)
        self.assertEqual(detail["byFeature"][0]["feature"], "chapter")
        self.assertEqual(detail["byFeature"][0]["credits"], 5)
        self.assertEqual(detail["byModel"][0]["promptTokens"], 3000)
        self.assertEqual(len(detail["trend"]), 7)
        self.assertEqual(detail["trend"][-1]["tokens"], 5000)

    def test_csv_has_bom_and_header(self):
        from app import fee_stats

        data = fee_stats.to_csv(fee_stats.tenant_fees(self.pdb)["items"], fee_stats.TENANT_COLUMNS)
        self.assertTrue(data.startswith("\ufeff".encode()))
        text = data.decode("utf-8-sig")
        self.assertIn("期间消耗积分", text.splitlines()[0])
        self.assertIn(TID, text)


class AdminPlanGrantTests(SaasCase):
    def test_changing_plan_grants_included_credits_once_per_switch(self):
        from app.platform_models import Plan, Tenant
        from app.routers.admin import _assign_plan

        self.pdb.add(
            Plan(code="pro", kind="套餐", name="专业版", duration_days=365, seats=8, credits=5000, bonus_credits=200, storage_mb=2048)
        )
        tenant = self.pdb.get(Tenant, TID)
        tenant.plan_code = "trial"
        tenant.status = "试用"
        self.pdb.commit()
        _assign_plan(self.pdb, tenant, "pro", "测试管理员")
        self.pdb.commit()
        wallet = billing.ensure_wallet(self.pdb, TID)
        self.assertEqual(wallet.balance, 5200)
        self.assertEqual(tenant.plan_code, "pro")
        self.assertEqual(tenant.seats, 5)
        self.assertIsNotNone(tenant.expires_at)
        # 同一秒内重复开通同一套餐会因幂等键撞上；换一个套餐应再入账
        self.pdb.add(Plan(code="ent", kind="套餐", name="企业版", duration_days=365, seats=20, credits=1000, storage_mb=4096))
        self.pdb.commit()
        _assign_plan(self.pdb, tenant, "ent", "测试管理员")
        self.pdb.commit()
        self.assertEqual(billing.ensure_wallet(self.pdb, TID).balance, 6200)
        self.assertEqual(tenant.plan_code, "ent")


@unittest.skipUnless(os.environ.get("TEST_PG_URL"), "设置 TEST_PG_URL=postgresql://... 后在真实 Postgres 上验证 schema 隔离")
class PostgresSchemaIsolationTests(unittest.TestCase):
    def test_tenant_sessions_cannot_see_each_other(self):
        from sqlalchemy import text

        from app.models import KnowledgeDocument, User

        engine = create_engine(os.environ["TEST_PG_URL"])
        factory = sessionmaker(class_=ScopedSession, autocommit=False, autoflush=False, bind=engine)
        a, b = "isoa" + str(int(time.time()))[-5:], "isob" + str(int(time.time()))[-5:]
        with mock.patch.object(db_mod, "engine", engine), mock.patch.object(db_mod, "_factory", factory):
            try:
                db_mod.ensure_platform_schema()
                for tid in (a, b):
                    db_mod.ensure_tenant_schema(tid)
                with db_mod.tenant_session(a) as s:
                    s.add(User(name="甲", email="a@a.cn", password_hash="x"))
                    s.add(KnowledgeDocument(scope="企业库", type="t", title="甲公司机密", filename="f", storage_path="k"))
                    s.commit()
                with db_mod.tenant_session(b) as s:
                    self.assertEqual(s.query(User).count(), 0)
                    self.assertEqual(s.query(KnowledgeDocument).count(), 0)
                    path = s.execute(text("SHOW search_path")).scalar()
                    self.assertIn(f"t_{b}", path)
                    self.assertNotIn(f"t_{a}", path)
                with db_mod.tenant_session(a) as s:
                    self.assertEqual(s.query(KnowledgeDocument).one().title, "甲公司机密")
                # 平台会话里没有企业表
                with db_mod.platform_session() as s:
                    with self.assertRaises(Exception):
                        s.query(User).count()
            finally:
                for tid in (a, b):
                    db_mod.drop_tenant_schema(tid)
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
