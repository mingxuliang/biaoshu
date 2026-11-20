import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import Modal from "../components/Modal";
import { closeOrder, getBankAccount, getOrder, mockPay, submitTransfer, yuan, type Order } from "@/lib/saasApi";
import { btnGhost, btnPrimary, inputCls, CHANNEL_LABEL } from "./ui";

interface Props {
  order: Order | null;
  onClose: () => void;
  onPaid: (order: Order) => void;
}

/** 支付弹窗：支付宝跳收银台、微信扫码、对公转账填回单、测试环境模拟支付；轮询订单状态直到到账。 */
export default function PayModal({ order: initial, onClose, onPaid }: Props) {
  const [order, setOrder] = useState<Order | null>(initial);
  const [qr, setQr] = useState("");
  const [bank, setBank] = useState<{ accountName: string; accountNo: string; bankName: string } | null>(null);
  const [form, setForm] = useState({ payerName: "", payerAccount: "", bankSerial: "" });
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const paidRef = useRef(false);

  useEffect(() => {
    setOrder(initial);
    setError("");
    paidRef.current = false;
    if (initial?.codeUrl && !initial.codeUrl.startsWith("mock://")) {
      QRCode.toDataURL(initial.codeUrl, { width: 220, margin: 1 }).then(setQr).catch(() => setQr(""));
    } else {
      setQr("");
    }
    if (initial?.channel === "bank") getBankAccount().then(setBank).catch(() => setBank(null));
  }, [initial]);

  const pending = !!order && order.status === "待支付" && order.channel !== "bank";
  const orderId = order?.id;
  useEffect(() => {
    if (!pending || !orderId) return;
    const timer = window.setInterval(() => {
      getOrder(orderId)
        .then((next) => {
          setOrder(next);
          if (next.status === "已支付" && !paidRef.current) {
            paidRef.current = true;
            onPaid(next);
          }
        })
        .catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [pending, orderId, onPaid]);

  if (!order) return null;

  const run = async (fn: () => Promise<Order>) => {
    setBusy(true);
    setError("");
    try {
      const next = await fn();
      setOrder(next);
      if (next.status === "已支付" && !paidRef.current) {
        paidRef.current = true;
        onPaid(next);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const paid = order.status === "已支付";

  return (
    <Modal open onClose={onClose} title={`${CHANNEL_LABEL[order.channel] || order.channel} · ${yuan(order.amountCents)}`} subtitle={`订单号 ${order.id}`} width="max-w-md">
      <div className="space-y-4 text-sm">
        <div className="rounded-lg bg-background-50 px-3 py-2.5 text-foreground-700">
          <div>{order.subject}</div>
          <div className="mt-1 text-xs text-foreground-500">
            到账 {order.credits.toLocaleString("zh-CN")} 积分
            {order.bonusCredits > 0 && <>，另赠 {order.bonusCredits.toLocaleString("zh-CN")} 积分</>}
          </div>
        </div>

        {paid ? (
          <div className="flex flex-col items-center gap-2 py-4 text-emerald-700">
            <i className="ri-checkbox-circle-fill text-4xl"></i>
            <div className="font-medium">支付成功，积分已到账</div>
          </div>
        ) : order.status === "已关闭" ? (
          <p className="py-4 text-center text-foreground-500">订单已关闭，请重新下单</p>
        ) : order.channel === "alipay" ? (
          <div className="space-y-3 text-center">
            <p className="text-foreground-600">将在新窗口打开支付宝收银台，完成付款后本页面自动刷新。</p>
            <a href={order.payUrl} target="_blank" rel="noreferrer" className={btnPrimary}>
              <i className="ri-alipay-line"></i>前往支付宝付款
            </a>
          </div>
        ) : order.channel === "wechat" ? (
          <div className="flex flex-col items-center gap-2">
            {qr ? <img src={qr} alt="微信支付二维码" className="h-52 w-52 rounded-lg border border-background-300" /> : <p className="text-foreground-500">二维码生成中…</p>}
            <p className="text-xs text-foreground-500">请使用微信或企业微信扫码付款，付款后自动到账</p>
          </div>
        ) : order.channel === "mock" ? (
          <div className="space-y-3 text-center">
            <p className="text-xs text-foreground-500">当前为测试环境，点击下方按钮模拟支付成功（走与真实回调相同的入账流程）。</p>
            <button type="button" disabled={busy} onClick={() => run(() => mockPay(order.id))} className={btnPrimary}>
              模拟支付成功
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs leading-5 text-amber-800">
              请向以下账户转账 <b>{yuan(order.amountCents)}</b>，并在<b>转账附言 / 用途</b>中填写识别码
              <b className="mx-1 font-mono text-sm">{order.transferCode}</b>
              ，财务核对到账后积分自动入账（一般 1 个工作日内）。
            </div>
            {bank && (
              <dl className="grid grid-cols-[72px_1fr] gap-y-1 text-xs">
                <dt className="text-foreground-500">户名</dt>
                <dd className="text-foreground-900">{bank.accountName || "—"}</dd>
                <dt className="text-foreground-500">账号</dt>
                <dd className="font-mono text-foreground-900">{bank.accountNo || "—"}</dd>
                <dt className="text-foreground-500">开户行</dt>
                <dd className="text-foreground-900">{bank.bankName || "—"}</dd>
              </dl>
            )}
            {order.status === "待确认" ? (
              <p className="rounded-lg bg-background-50 px-3 py-2 text-xs text-foreground-600">已提交付款信息，等待财务确认到账。</p>
            ) : (
              <div className="space-y-2">
                <input className={inputCls} placeholder="付款单位名称（必填）" value={form.payerName} onChange={(e) => setForm({ ...form, payerName: e.target.value })} />
                <input className={inputCls} placeholder="付款账号（选填）" value={form.payerAccount} onChange={(e) => setForm({ ...form, payerAccount: e.target.value })} />
                <input className={inputCls} placeholder="银行流水号（选填）" value={form.bankSerial} onChange={(e) => setForm({ ...form, bankSerial: e.target.value })} />
                <label className="flex cursor-pointer items-center gap-2 text-xs text-foreground-600">
                  <i className="ri-attachment-2"></i>
                  {file ? file.name : "上传转账回单（PDF / 图片，选填）"}
                  <input type="file" accept=".pdf,.jpg,.jpeg,.png" className="hidden" onChange={(e) => setFile(e.target.files?.[0] || null)} />
                </label>
                <button
                  type="button"
                  disabled={busy || !form.payerName.trim()}
                  onClick={() => run(() => submitTransfer(order.id, { ...form, amountCents: order.amountCents, file }))}
                  className={`${btnPrimary} w-full`}
                >
                  我已转账，提交付款信息
                </button>
              </div>
            )}
          </div>
        )}

        {error && <p className="text-xs text-red-600">{error}</p>}

        <div className="flex justify-end gap-2 border-t border-background-300 pt-3">
          {!paid && order.status === "待支付" && (
            <button type="button" disabled={busy} onClick={() => run(() => closeOrder(order.id))} className={btnGhost}>
              取消订单
            </button>
          )}
          <button type="button" onClick={onClose} className={btnGhost}>
            {paid ? "完成" : "稍后支付"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
