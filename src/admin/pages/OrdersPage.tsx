import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import PageHeader from "@/pages/console/components/PageHeader";
import { yuan } from "@/lib/saasApi";
import {
  closeAdminOrder,
  confirmTransfer,
  getReconcile,
  listAdminOrders,
  listTransfers,
  markOrderPaid,
  refundOrder,
  rejectTransfer,
  syncAdminOrder,
  transferReceipt,
  type AdminOrder,
  type Paged,
  type Transfer,
} from "../api";
import { useCan } from "../auth";
import { CHANNEL_LABEL, Card, dangerLink, Empty, Filter, inputCls, linkBtn, num, openBlob, PaginationBar, StatusTag, Tabs, tdCls, theadCls, thCls, trCls, useUi } from "../ui";

const TABS = [
  { id: "orders", label: "订单" },
  { id: "transfers", label: "对公转账" },
  { id: "reconcile", label: "对账" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export default function OrdersPage() {
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id || "orders") as TabId;
  return (
    <div>
      <PageHeader title="订单与对公转账" description="在线支付以支付平台异步通知为准；对公转账由财务核对银行流水后认领入账。" />
      <Tabs tabs={TABS} value={tab} onChange={(t) => setParams(t === "orders" ? {} : { tab: t }, { replace: true })} />
      {tab === "orders" && <Orders />}
      {tab === "transfers" && <Transfers />}
      {tab === "reconcile" && <Reconcile />}
    </div>
  );
}

const STATUS = [
  { id: "", label: "全部" },
  { id: "待支付", label: "待支付" },
  { id: "待确认", label: "待确认" },
  { id: "已支付", label: "已支付" },
  { id: "已关闭", label: "已关闭" },
  { id: "已退款", label: "已退款" },
] as const;

const CHANNELS = [
  { id: "", label: "全部通道" },
  { id: "alipay", label: "支付宝" },
  { id: "wechat", label: "微信" },
  { id: "bank", label: "对公" },
  { id: "mock", label: "模拟" },
] as const;

function Orders() {
  const { notify, fail, ask } = useUi();
  const can = useCan();
  const [status, setStatus] = useState<(typeof STATUS)[number]["id"]>("");
  const [channel, setChannel] = useState<(typeof CHANNELS)[number]["id"]>("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Paged<AdminOrder>>({ total: 0, items: [] });

  const load = useCallback(() => {
    listAdminOrders({ status, channel, q, page }).then(setData).catch(fail);
  }, [status, channel, q, page, fail]);
  useEffect(() => {
    const t = window.setTimeout(load, 250);
    return () => window.clearTimeout(t);
  }, [load]);

  const run = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn();
      notify(done);
      load();
    } catch (e) {
      fail(e);
    }
  };

  const withReason = async (title: string, fn: (reason: string) => Promise<unknown>, done: string, danger = false) => {
    const reason = await ask({ title, placeholder: "原因（记入审计）", danger });
    if (reason) run(() => fn(reason), done);
  };

  const refund = async (o: AdminOrder) => {
    const amount = await ask({ title: `退款 ${o.id}`, message: `订单金额 ${yuan(o.amountCents)}。按退款比例扣回积分；在线支付将原路退回。`, initial: (o.amountCents / 100).toFixed(2), inputType: "number" });
    if (amount === null) return;
    const cents = Math.round(Number(amount) * 100);
    if (!(cents > 0)) return fail(new Error("退款金额不正确"));
    const reason = await ask({ title: "退款原因", placeholder: "记入审计并展示在订单备注", danger: true, confirmText: "确认退款" });
    if (reason) run(() => refundOrder(o.id, cents, reason), "退款已完成");
  };

  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <input className={`${inputCls} max-w-xs`} placeholder="订单号、转账识别码或交易号" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <Filter options={STATUS} value={status} onChange={(v) => { setStatus(v); setPage(1); }} />
        <Filter options={CHANNELS} value={channel} onChange={(v) => { setChannel(v); setPage(1); }} />
      </div>
      {data.items.length ? (
        <>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1000px]">
              <thead className={theadCls}>
                <tr>
                  <th className={thCls}>下单时间</th>
                  <th className={thCls}>订单号</th>
                  <th className={thCls}>企业</th>
                  <th className={thCls}>内容</th>
                  <th className={thCls}>通道</th>
                  <th className={`${thCls} text-right`}>金额</th>
                  <th className={thCls}>状态</th>
                  <th className={thCls}></th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((o) => (
                  <tr key={o.id} className={trCls}>
                    <td className={`${tdCls} text-xs`}>{o.createdAt}</td>
                    <td className={`${tdCls} font-mono text-xs`}>
                      {o.id}
                      {o.transferCode && <div className="text-foreground-500">识别码 {o.transferCode}</div>}
                    </td>
                    <td className={tdCls}>
                      <Link to={`/tenants/${o.tenantId}`} className="text-primary-700 hover:underline">
                        {o.tenantName || o.tenantId}
                      </Link>
                      <div className="text-[11px] text-foreground-500">{o.userName}</div>
                    </td>
                    <td className={tdCls}>
                      {o.subject}
                      <div className="text-[11px] text-foreground-500">
                        {num(o.credits + o.bonusCredits)} 积分{o.invoicedCents > 0 && ` · 已开票 ${yuan(o.invoicedCents)}`}
                      </div>
                      {o.note && <div className="text-[11px] text-amber-700">{o.note}</div>}
                    </td>
                    <td className={tdCls}>{CHANNEL_LABEL[o.channel] || o.channel}</td>
                    <td className={`${tdCls} text-right font-medium`}>{yuan(o.amountCents)}</td>
                    <td className={tdCls}>
                      <StatusTag status={o.status} />
                      {o.paidAt && <div className="text-[11px] text-foreground-500">{o.paidAt}</div>}
                    </td>
                    <td className={`${tdCls} space-x-2 whitespace-nowrap text-right`}>
                      {can.finance && (o.channel === "alipay" || o.channel === "wechat") && o.status === "待支付" && (
                        <button type="button" className={linkBtn} onClick={() => run(() => syncAdminOrder(o.id), "已向支付平台查询")}>
                          查单
                        </button>
                      )}
                      {can.finance && (o.status === "待支付" || o.status === "待确认") && (
                        <button type="button" className={linkBtn} onClick={() => withReason("关闭订单", (r) => closeAdminOrder(o.id, r), "订单已关闭")}>
                          关闭
                        </button>
                      )}
                      {can.isSuper && o.status !== "已支付" && o.status !== "已退款" && (
                        <button type="button" className={dangerLink} onClick={() => withReason("人工补单（确认已收款）", (r) => markOrderPaid(o.id, r), "已补单入账", true)}>
                          补单
                        </button>
                      )}
                      {can.isSuper && o.status === "已支付" && (
                        <button type="button" className={dangerLink} onClick={() => refund(o)}>
                          退款
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <PaginationBar page={page} pageSize={20} total={data.total} onPageChange={setPage} />
        </>
      ) : (
        <Empty text="没有符合条件的订单" />
      )}
    </Card>
  );
}

const TRANSFER_STATUS = [
  { id: "待认领", label: "待认领" },
  { id: "已确认", label: "已确认" },
  { id: "已驳回", label: "已驳回" },
  { id: "", label: "全部" },
] as const;

function Transfers() {
  const { notify, fail, ask } = useUi();
  const can = useCan();
  const [status, setStatus] = useState<(typeof TRANSFER_STATUS)[number]["id"]>("待认领");
  const [rows, setRows] = useState<Transfer[]>([]);

  const load = useCallback(() => {
    listTransfers(status).then(setRows).catch(fail);
  }, [status, fail]);
  useEffect(load, [load]);

  const confirm = async (t: Transfer) => {
    const serial = await ask({
      title: "认领入账",
      message: `请核对银行流水：付款方「${t.payerName}」，附言识别码 ${t.transferCode}，订单金额 ${t.orderAmountCents != null ? yuan(t.orderAmountCents) : "—"}。`,
      placeholder: "银行流水号",
      initial: t.bankSerial,
    });
    if (!serial) return;
    const amount = await ask({ title: "实际到账金额（元）", initial: ((t.orderAmountCents ?? t.amountCents) / 100).toFixed(2), inputType: "number", confirmText: "确认入账" });
    if (amount === null) return;
    try {
      await confirmTransfer(t.id, serial, Math.round(Number(amount) * 100));
      notify("已认领，积分已到账");
      load();
    } catch (e) {
      fail(e);
    }
  };

  const reject = async (t: Transfer) => {
    const reason = await ask({ title: "驳回对公转账", placeholder: "原因（如：未查到到账、金额不符）", danger: true });
    if (!reason) return;
    try {
      await rejectTransfer(t.id, reason);
      notify("已驳回，订单恢复为待支付");
      load();
    } catch (e) {
      fail(e);
    }
  };

  return (
    <Card>
      <div className="mb-3">
        <Filter<(typeof TRANSFER_STATUS)[number]["id"]> options={TRANSFER_STATUS} value={status} onChange={setStatus} />
      </div>
      {rows.length ? (
        <table className="w-full">
          <thead className={theadCls}>
            <tr>
              <th className={thCls}>提交时间</th>
              <th className={thCls}>企业</th>
              <th className={thCls}>付款方</th>
              <th className={thCls}>识别码 / 流水号</th>
              <th className={`${thCls} text-right`}>申报 / 订单金额</th>
              <th className={thCls}>状态</th>
              <th className={thCls}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.id} className={trCls}>
                <td className={`${tdCls} text-xs`}>{t.createdAt}</td>
                <td className={tdCls}>{t.tenantName || t.tenantId}</td>
                <td className={tdCls}>
                  {t.payerName}
                  <div className="font-mono text-[11px] text-foreground-500">{t.payerAccount}</div>
                </td>
                <td className={`${tdCls} font-mono text-xs`}>
                  {t.transferCode}
                  <div className="text-foreground-500">{t.bankSerial || "—"}</div>
                </td>
                <td className={`${tdCls} text-right`}>
                  {yuan(t.amountCents)}
                  {t.orderAmountCents != null && t.orderAmountCents !== t.amountCents && <div className="text-[11px] text-red-600">订单 {yuan(t.orderAmountCents)}</div>}
                </td>
                <td className={tdCls}>
                  <StatusTag status={t.status} />
                  {t.note && <div className="text-[11px] text-foreground-500">{t.note}</div>}
                  {t.operator && <div className="text-[11px] text-foreground-500">{t.operator} {t.confirmedAt}</div>}
                </td>
                <td className={`${tdCls} space-x-2 whitespace-nowrap text-right`}>
                  {t.hasReceipt && can.finance && (
                    <button type="button" className={linkBtn} onClick={() => transferReceipt(t.id).then(openBlob).catch(fail)}>
                      回单
                    </button>
                  )}
                  {t.status === "待认领" && can.finance && (
                    <>
                      <button type="button" className={linkBtn} onClick={() => confirm(t)}>
                        认领入账
                      </button>
                      <button type="button" className={dangerLink} onClick={() => reject(t)}>
                        驳回
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <Empty text="没有对公转账记录" />
      )}
    </Card>
  );
}

function Reconcile() {
  const { fail } = useUi();
  const can = useCan();
  const yesterday = new Date(Date.now() - 86400_000).toISOString().slice(0, 10);
  const [date, setDate] = useState(yesterday);
  const [data, setData] = useState<Awaited<ReturnType<typeof getReconcile>> | null>(null);

  useEffect(() => {
    if (!can.finance) return;
    getReconcile(date).then(setData).catch(fail);
  }, [date, can.finance, fail]);

  if (!can.finance) return <Empty text="对账仅限财务和超级管理员" />;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-sm text-foreground-600">对账日期</span>
        <input type="date" className={`${inputCls} max-w-[180px]`} value={date} onChange={(e) => setDate(e.target.value)} />
        <span className="text-xs text-foreground-500">与支付宝 / 微信商户后台的当日账单逐笔核对交易号与金额</span>
      </div>
      {data && (
        <>
          <div className="grid gap-3 sm:grid-cols-4">
            {Object.entries(data.summary).map(([ch, s]) => (
              <div key={ch} className="rounded-xl border border-background-300 bg-background-100 px-4 py-3">
                <div className="text-xs text-foreground-500">{CHANNEL_LABEL[ch] || ch}</div>
                <div className="mt-1 text-lg font-semibold">{yuan(s.amountCents)}</div>
                <div className="text-xs text-foreground-500">
                  {s.count} 笔{s.refunded > 0 && `，其中退款 ${s.refunded}`}
                </div>
              </div>
            ))}
          </div>
          <Card title={`${data.date} 明细`}>
            {data.orders.length ? (
              <table className="w-full">
                <thead className={theadCls}>
                  <tr>
                    <th className={thCls}>支付时间</th>
                    <th className={thCls}>订单号</th>
                    <th className={thCls}>通道</th>
                    <th className={thCls}>交易号</th>
                    <th className={`${thCls} text-right`}>金额</th>
                    <th className={thCls}>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {data.orders.map((o) => (
                    <tr key={o.id} className={trCls}>
                      <td className={`${tdCls} text-xs`}>{o.paidAt}</td>
                      <td className={`${tdCls} font-mono text-xs`}>{o.id}</td>
                      <td className={tdCls}>{CHANNEL_LABEL[o.channel] || o.channel}</td>
                      <td className={`${tdCls} font-mono text-xs`}>{o.tradeNo}</td>
                      <td className={`${tdCls} text-right`}>{yuan(o.amountCents)}</td>
                      <td className={tdCls}>
                        <StatusTag status={o.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty text="当日没有已支付订单" />
            )}
          </Card>
        </>
      )}
    </div>
  );
}
