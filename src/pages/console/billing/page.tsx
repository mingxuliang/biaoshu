import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Toast from "../components/Toast";
import PaginationBar from "../components/PaginationBar";
import {
  closeOrder,
  formatBytes,
  getBillingSummary,
  getOrder,
  getUsage,
  listLedger,
  listOrders,
  tokensLabel,
  yuan,
  type BillingSummary,
  type LedgerRow,
  type Order,
  type UsageStats,
} from "@/lib/saasApi";
import RechargePanel from "./RechargePanel";
import InvoicePanel from "./InvoicePanel";
import PayModal from "./PayModal";
import { btnGhost, btnPrimary, Card, CHANNEL_LABEL, Empty, Stat, StatusTag } from "./ui";

const TABS = [
  { id: "overview", label: "概览" },
  { id: "recharge", label: "充值与套餐" },
  { id: "orders", label: "订单" },
  { id: "ledger", label: "积分明细" },
  { id: "usage", label: "用量统计" },
  { id: "invoices", label: "发票" },
] as const;
type TabId = (typeof TABS)[number]["id"];

const LEDGER_KINDS = ["", "充值", "套餐", "赠送", "消费", "调整", "过期"];

const num = (n: number) => n.toLocaleString("zh-CN");

export default function BillingPage() {
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id || "overview") as TabId;
  const setTab = (id: TabId) => setParams(id === "overview" ? {} : { tab: id }, { replace: true });

  const [summary, setSummary] = useState<BillingSummary | null>(null);
  const [payOrder, setPayOrder] = useState<Order | null>(null);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error"; visible: boolean }>({ message: "", type: "success", visible: false });

  const notify = useCallback((message: string, type: "success" | "error" = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  }, []);
  const onError = useCallback((msg: string) => notify(msg, "error"), [notify]);

  const loadSummary = useCallback(() => {
    getBillingSummary().then(setSummary).catch((e) => onError(e instanceof Error ? e.message : "加载失败"));
  }, [onError]);
  useEffect(loadSummary, [loadSummary]);

  const onPaid = useCallback(() => {
    notify("支付成功，积分已到账");
    loadSummary();
  }, [notify, loadSummary]);

  const canManage = !!summary?.canManage;
  const personal = summary?.tenant.kind === "个人";

  return (
    <div>
      <PageHeader
        title="费用中心"
        description={
          personal
            ? "个人积分钱包、套餐订阅、充值订单与发票。积分按实际 Token 用量扣减，只供本人使用。"
            : "企业积分池、套餐订阅、充值订单与发票。积分池由本企业全体成员共享，按实际 Token 用量扣减，可在团队管理中为个人设置月度额度。"
        }
        actions={
          canManage && (
            <button type="button" className={btnPrimary} onClick={() => setTab("recharge")}>
              <i className="ri-add-circle-line"></i>充值
            </button>
          )
        }
      />

      <div className="mb-4 flex gap-1 overflow-x-auto border-b border-background-300">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`-mb-px cursor-pointer whitespace-nowrap border-b-2 px-4 py-2 text-sm transition-colors ${tab === t.id ? "border-primary-500 font-medium text-primary-600" : "border-transparent text-foreground-600 hover:text-foreground-900"}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && <Overview summary={summary} onRecharge={() => setTab("recharge")} />}
      {tab === "recharge" && (
        <RechargePanel
          currentPlanCode={summary?.plan?.code}
          canManage={canManage}
          tokensPerCredit={summary?.tokensPerCredit || 1000}
          personal={personal}
          onOrder={setPayOrder}
          onError={onError}
        />
      )}
      {tab === "orders" && <OrdersPanel onPay={setPayOrder} onError={onError} refreshKey={summary} />}
      {tab === "ledger" && <LedgerPanel onError={onError} />}
      {tab === "usage" && <UsagePanel onError={onError} />}
      {tab === "invoices" && <InvoicePanel canManage={canManage} personal={personal} notify={notify} />}

      {payOrder && <PayModal order={payOrder} onClose={() => { setPayOrder(null); loadSummary(); }} onPaid={onPaid} />}
      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}

function Overview({ summary, onRecharge }: { summary: BillingSummary | null; onRecharge: () => void }) {
  if (!summary) return <Empty text="加载中…" />;
  const { wallet, plan, tenant, me } = summary;
  const personal = tenant.kind === "个人";
  const tokens = (credits: number) => tokensLabel(credits, summary.tokensPerCredit);
  const quotaBytes = tenant.storageQuotaMb * 1024 * 1024;
  const usedPct = tenant.storageUsedBytes != null && quotaBytes > 0 ? Math.min(100, (tenant.storageUsedBytes / quotaBytes) * 100) : 0;
  const endAt = tenant.status === "试用" ? tenant.trialEndsAt : tenant.expiresAt;

  return (
    <div className="space-y-4">
      {summary.lowBalance && (
        <div className="flex items-center justify-between rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <span>
            <i className="ri-error-warning-line mr-1"></i>积分余额已低于提醒阈值（{num(tenant.lowBalanceThreshold)}），AI 功能可能因余额不足暂停。
          </span>
          {summary.canManage && (
            <button type="button" className={btnPrimary} onClick={onRecharge}>
              立即充值
            </button>
          )}
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label={personal ? "可用积分" : "企业积分池可用"}
          value={num(wallet.available)}
          hint={`${tokens(wallet.available)}${wallet.held > 0 ? ` · ${num(wallet.held)} 积分冻结中` : ""}`}
          tone={summary.lowBalance ? "warn" : "default"}
        />
        <Stat label="30 天内到期积分" value={num(wallet.expiringIn30Days)} hint="优先消耗最早到期的积分" tone={wallet.expiringIn30Days > 0 ? "warn" : "default"} />
        <Stat label="累计充值 / 赠送" value={num(wallet.totalRecharged)} hint={`累计消耗 ${num(wallet.totalConsumed)}（${tokens(wallet.totalConsumed)}）`} />
        <Stat
          label="我的本月消耗"
          value={num(me.monthSpent)}
          hint={
            personal
              ? tokens(me.monthSpent)
              : me.monthlyLimit != null
                ? `个人月度额度 ${num(me.monthlyLimit)}`
                : "未设置个人额度，可用满企业积分池"
          }
          tone={me.monthlyLimit != null && me.monthSpent >= me.monthlyLimit * 0.9 ? "warn" : "default"}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="当前套餐" extra={<StatusTag status={tenant.status} />}>
          <div className="space-y-2 text-sm">
            <div className="text-lg font-semibold text-foreground-950">{plan?.name || "未订阅"}</div>
            <div className="text-foreground-600">{endAt ? `${tenant.status === "试用" ? "试用" : "服务"}到期：${endAt.slice(0, 10)}` : "长期有效"}</div>
            {plan && plan.credits > 0 && (
              <div className="text-xs text-foreground-500">
                套餐含 {num(plan.credits)} 积分（{tokens(plan.credits)}），{personal ? "本人使用" : `企业 ${plan.seats || tenant.seats} 个席位共享`}
              </div>
            )}
            {plan?.rechargeBonusPct ? <div className="text-xs text-primary-600">本套餐充值额外赠送 {plan.rechargeBonusPct}%</div> : null}
            {summary.canManage && (
              <button type="button" className={`${btnGhost} mt-2`} onClick={onRecharge}>
                续费 / 升级套餐
              </button>
            )}
          </div>
        </Card>
        <Card title="资源使用">
          <div className="space-y-4 text-sm">
            {personal ? (
              <div className="flex items-center justify-between rounded-lg bg-background-50 px-3 py-2 text-xs text-foreground-600">
                <span>个人账号，仅本人使用</span>
                <Link to="/console/org" className="text-primary-600 hover:underline">
                  升级为企业，邀请同事共享积分池
                </Link>
              </div>
            ) : (
              <div>
                <div className="flex justify-between text-foreground-700">
                  <span>成员席位</span>
                  <span>
                    {tenant.seatsUsed} / {tenant.seats}
                  </span>
                </div>
                <Bar pct={tenant.seats ? (tenant.seatsUsed / tenant.seats) * 100 : 0} />
              </div>
            )}
            <div>
              <div className="flex justify-between text-foreground-700">
                <span>存储空间（资质库、知识库、标书文件）</span>
                <span>
                  {formatBytes(tenant.storageUsedBytes)} / {formatBytes(quotaBytes)}
                </span>
              </div>
              <Bar pct={usedPct} />
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function Bar({ pct }: { pct: number }) {
  return (
    <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-background-200">
      <div className={`h-full rounded-full ${pct >= 90 ? "bg-red-500" : pct >= 75 ? "bg-amber-500" : "bg-primary-500"}`} style={{ width: `${Math.max(2, pct)}%` }} />
    </div>
  );
}

function OrdersPanel({ onPay, onError, refreshKey }: { onPay: (o: Order) => void; onError: (m: string) => void; refreshKey: unknown }) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ total: number; items: Order[] }>({ total: 0, items: [] });

  const load = useCallback(() => {
    listOrders(page).then(setData).catch((e) => onError(e instanceof Error ? e.message : "加载失败"));
  }, [page, onError]);
  useEffect(load, [load, refreshKey]);

  const act = (fn: () => Promise<unknown>) => fn().then(load).catch((e) => onError(e instanceof Error ? e.message : "操作失败"));

  return (
    <Card>
      {data.items.length ? (
        <>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-foreground-500">
              <tr>
                <th className="py-2 font-normal">下单时间</th>
                <th className="py-2 font-normal">订单号</th>
                <th className="py-2 font-normal">内容</th>
                <th className="py-2 font-normal">支付方式</th>
                <th className="py-2 text-right font-normal">金额</th>
                <th className="py-2 font-normal">状态</th>
                <th className="py-2"></th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((o) => (
                <tr key={o.id} className="border-t border-background-300">
                  <td className="py-2 text-foreground-600">{o.createdAt}</td>
                  <td className="py-2 font-mono text-xs text-foreground-700">{o.id}</td>
                  <td className="py-2 text-foreground-800">
                    {o.subject}
                    <div className="text-xs text-foreground-500">
                      {num(o.credits + o.bonusCredits)} 积分 · {o.userName}
                    </div>
                  </td>
                  <td className="py-2 text-foreground-600">{CHANNEL_LABEL[o.channel] || o.channel}</td>
                  <td className="py-2 text-right text-foreground-900">{yuan(o.amountCents)}</td>
                  <td className="py-2">
                    <StatusTag status={o.status} />
                  </td>
                  <td className="space-x-3 whitespace-nowrap py-2 text-right text-xs">
                    {o.status === "待支付" && (
                      <>
                        <button type="button" className="cursor-pointer text-primary-600 hover:underline" onClick={() => getOrder(o.id).then(onPay).catch((e) => onError(e.message))}>
                          继续支付
                        </button>
                        <button type="button" className="cursor-pointer text-foreground-500 hover:underline" onClick={() => act(() => closeOrder(o.id))}>
                          取消
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <PaginationBar page={page} pageSize={20} total={data.total} onPageChange={setPage} />
        </>
      ) : (
        <Empty text="暂无订单" />
      )}
    </Card>
  );
}

function LedgerPanel({ onError }: { onError: (m: string) => void }) {
  const [page, setPage] = useState(1);
  const [kind, setKind] = useState("");
  const [data, setData] = useState<{ total: number; items: LedgerRow[] }>({ total: 0, items: [] });

  useEffect(() => {
    listLedger(page, kind).then(setData).catch((e) => onError(e instanceof Error ? e.message : "加载失败"));
  }, [page, kind, onError]);

  return (
    <Card
      title="积分明细"
      extra={
        <div className="flex gap-1">
          {LEDGER_KINDS.map((k) => (
            <button
              key={k || "all"}
              type="button"
              onClick={() => { setKind(k); setPage(1); }}
              className={`cursor-pointer rounded-md px-2 py-1 text-xs ${kind === k ? "bg-primary-100 text-primary-700" : "text-foreground-600 hover:bg-background-200"}`}
            >
              {k || "全部"}
            </button>
          ))}
        </div>
      }
    >
      {data.items.length ? (
        <>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-foreground-500">
              <tr>
                <th className="py-2 font-normal">时间</th>
                <th className="py-2 font-normal">类型</th>
                <th className="py-2 font-normal">说明</th>
                <th className="py-2 font-normal">成员</th>
                <th className="py-2 text-right font-normal">变动</th>
                <th className="py-2 text-right font-normal">余额</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((r) => (
                <tr key={r.id} className="border-t border-background-300">
                  <td className="py-2 text-foreground-600">{r.createdAt}</td>
                  <td className="py-2 text-foreground-700">{r.kind}</td>
                  <td className="py-2 text-foreground-800">{r.note || r.feature || "—"}</td>
                  <td className="py-2 text-foreground-600">{r.userName || r.operator || "—"}</td>
                  <td className={`py-2 text-right font-medium ${r.amount >= 0 ? "text-emerald-600" : "text-foreground-900"}`}>
                    {r.amount >= 0 ? "+" : ""}
                    {num(r.amount)}
                  </td>
                  <td className="py-2 text-right text-foreground-600">{num(r.balanceAfter)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <PaginationBar page={page} pageSize={20} total={data.total} onPageChange={setPage} />
        </>
      ) : (
        <Empty text="暂无积分变动" />
      )}
    </Card>
  );
}

function UsagePanel({ onError }: { onError: (m: string) => void }) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<UsageStats | null>(null);

  useEffect(() => {
    getUsage(days).then(setData).catch((e) => onError(e instanceof Error ? e.message : "加载失败"));
  }, [days, onError]);

  const maxFeature = Math.max(1, ...(data?.byFeature.map((f) => f.credits) || [1]));
  const maxUser = Math.max(1, ...(data?.byUser.map((u) => u.credits) || [1]));

  return (
    <div className="space-y-4">
      <div className="flex gap-1">
        {[7, 30, 90].map((d) => (
          <button key={d} type="button" onClick={() => setDays(d)} className={`cursor-pointer rounded-md px-3 py-1 text-sm ${days === d ? "bg-primary-100 text-primary-700" : "text-foreground-600 hover:bg-background-200"}`}>
            近 {d} 天
          </button>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="按功能">
          {data?.byFeature.length ? (
            <div className="space-y-3">
              {data.byFeature.map((f) => (
                <div key={f.feature} className="text-sm">
                  <div className="flex justify-between">
                    <span className="text-foreground-800">{f.name}</span>
                    <span className="text-foreground-900">{num(f.credits)} 积分</span>
                  </div>
                  <div className="mt-1 h-1.5 rounded-full bg-background-200">
                    <div className="h-full rounded-full bg-primary-500" style={{ width: `${(f.credits / maxFeature) * 100}%` }} />
                  </div>
                  <div className="mt-0.5 text-[11px] text-foreground-500">
                    {num(f.calls)} 次调用 · 输入 {num(f.promptTokens)} / 输出 {num(f.completionTokens)} Token
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Empty text="暂无消耗" />
          )}
        </Card>
        <Card title="按成员">
          {data?.byUser.length ? (
            <div className="space-y-3">
              {data.byUser.map((u) => (
                <div key={u.userId} className="text-sm">
                  <div className="flex justify-between">
                    <span className="text-foreground-800">{u.userName}</span>
                    <span className="text-foreground-900">{num(u.credits)} 积分</span>
                  </div>
                  <div className="mt-1 h-1.5 rounded-full bg-background-200">
                    <div className="h-full rounded-full bg-sky-500" style={{ width: `${(u.credits / maxUser) * 100}%` }} />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Empty text="暂无消耗" />
          )}
        </Card>
      </div>
    </div>
  );
}
