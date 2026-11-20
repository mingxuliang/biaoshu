import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { Link, useSearchParams } from "react-router-dom";
import PageHeader from "@/pages/console/components/PageHeader";
import { saveBlob, yuan } from "@/lib/saasApi";
import { exportWallets, getPlatformUsage, listPlatformLedger, listWallets, type UsageGroup, type WalletSort } from "../api";
import { useCan } from "../auth";
import {
  ACCOUNT_KINDS,
  btnGhost,
  Card,
  Empty,
  Filter,
  inputCls,
  KindTag,
  linkBtn,
  num,
  PaginationBar,
  periodLabel,
  PERIODS,
  SortTh,
  Stat,
  StatusTag,
  tableWrap,
  Tabs,
  tdCls,
  theadCls,
  thCls,
  tokens,
  trCls,
  useUi,
  type AccountKindFilter,
  type PeriodId,
} from "../ui";

const TABS = [
  { id: "wallets", label: "企业费用" },
  { id: "usage", label: "Token 与用量" },
  { id: "ledger", label: "全平台流水" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export default function CreditsPage() {
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id || "wallets") as TabId;
  return (
    <div>
      <PageHeader
        title="企业费用"
        description="所有企业和个人账号的充值、积分消耗、Token 用量和活跃人数。调整积分请进入企业详情，看每个人的消耗请到「全员费用」。"
      />
      <Tabs tabs={TABS} value={tab} onChange={(t) => setParams(t === "wallets" ? {} : { tab: t }, { replace: true })} />
      {tab === "wallets" && <Wallets />}
      {tab === "usage" && <Usage />}
      {tab === "ledger" && <Ledger />}
    </div>
  );
}

function Wallets() {
  const { fail } = useUi();
  const { finance } = useCan();
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<AccountKindFilter>("");
  const [days, setDays] = useState<PeriodId>("30");
  const [sort, setSort] = useState<WalletSort>("spent");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Awaited<ReturnType<typeof listWallets>> | null>(null);
  const [exporting, setExporting] = useState(false);
  const query = { q, kind, days: Number(days), sort };

  useEffect(() => {
    const t = window.setTimeout(() => listWallets({ q, kind, days: Number(days), sort, page }).then(setData).catch(fail), 250);
    return () => window.clearTimeout(t);
  }, [q, kind, days, sort, page, fail]);

  const reset = <T,>(set: Dispatch<SetStateAction<T>>) => (v: T) => {
    set(v);
    setPage(1);
  };
  const doExport = () => {
    setExporting(true);
    exportWallets(query)
      .then((b) => saveBlob(b, `企业费用-${periodLabel(days)}.csv`))
      .catch(fail)
      .finally(() => setExporting(false));
  };
  const s = data?.summary;
  const period = periodLabel(days);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Filter options={PERIODS} value={days} onChange={reset(setDays)} />
        <span className="h-4 w-px bg-background-300" />
        <Filter options={ACCOUNT_KINDS} value={kind} onChange={reset(setKind)} />
        <div className="ml-auto flex items-center gap-2">
          <input className={`${inputCls} w-56`} placeholder="搜索企业或个人空间" value={q} onChange={(e) => reset(setQ)(e.target.value)} />
          {finance && (
            <button type="button" className={btnGhost} onClick={doExport} disabled={exporting}>
              <i className="ri-download-2-line mr-1" />
              {exporting ? "导出中…" : "导出 CSV"}
            </button>
          )}
        </div>
      </div>

      {s && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <Stat label={`${period}充值`} value={yuan(s.paidCents - s.refundedCents)} hint={s.refundedCents ? `已扣退款 ${yuan(s.refundedCents)}` : `${num(s.tenants)} 个账号`} />
          <Stat label={`${period}消耗积分`} value={num(s.periodCredits)} />
          <Stat label={`${period} Token`} value={tokens(s.promptTokens + s.completionTokens)} hint={`输入 ${tokens(s.promptTokens)} · 输出 ${tokens(s.completionTokens)}`} />
          <Stat label="有消耗的账号" value={num(s.activeTenants)} hint={`活跃人员 ${num(s.activeUsers)}`} />
          <Stat label="全平台可用积分" value={num(s.available)} />
        </div>
      )}

      <div className={tableWrap}>
        {data?.items.length ? (
          <table className="w-full min-w-[1100px]">
            <thead className={theadCls}>
              <tr>
                <th className={thCls}>企业 / 个人空间</th>
                <th className={thCls}>套餐</th>
                <th className={`${thCls} text-right`}>成员</th>
                <SortTh id="balance" label="可用积分" sort={sort} onSort={reset(setSort)} />
                <SortTh id="paid" label="充值金额" sort={sort} onSort={reset(setSort)} />
                <SortTh id="spent" label="消耗积分" sort={sort} onSort={reset(setSort)} />
                <SortTh id="tokens" label="Token" sort={sort} onSort={reset(setSort)} />
                <th className={`${thCls} text-right`}>调用</th>
                <th className={`${thCls} text-right`}>活跃人数</th>
                <SortTh id="lastUsed" label="最近使用" sort={sort} onSort={reset(setSort)} />
                <th className={thCls} />
              </tr>
            </thead>
            <tbody>
              {data.items.map((w) => (
                <tr key={w.tenantId} className={trCls}>
                  <td className={tdCls}>
                    <Link to={`/tenants/${w.tenantId}?tab=credits`} className="font-medium text-primary-700 hover:underline">
                      {w.tenantName}
                    </Link>
                    <KindTag kind={w.kind} />
                    {w.lowBalance && <span className="ml-1.5 rounded bg-amber-50 px-1 text-[11px] text-amber-700">余额低</span>}
                    <div className="mt-0.5 flex items-center gap-1.5 font-mono text-[11px] text-foreground-400">
                      {w.tenantId}
                      <StatusTag status={w.status} />
                    </div>
                  </td>
                  <td className={tdCls}>
                    <div>{w.planName || "—"}</div>
                    {w.expiresAt && <div className="text-[11px] text-foreground-500">至 {w.expiresAt.slice(0, 10)}</div>}
                  </td>
                  <td className={`${tdCls} text-right`}>{w.kind === "个人" ? "本人" : `${num(w.members)} / ${num(w.seats)}`}</td>
                  <td className={`${tdCls} text-right font-medium`}>
                    {num(w.available)}
                    {w.held > 0 && <div className="text-[11px] font-normal text-foreground-500">冻结 {num(w.held)}</div>}
                  </td>
                  <td className={`${tdCls} text-right`}>
                    {w.paidCents ? yuan(w.paidCents) : "—"}
                    {w.refundedCents > 0 && <div className="text-[11px] text-red-600">退 {yuan(w.refundedCents)}</div>}
                  </td>
                  <td className={`${tdCls} text-right font-medium`}>{num(w.periodCredits)}</td>
                  <td className={`${tdCls} text-right`} title={`输入 ${num(w.promptTokens)} / 输出 ${num(w.completionTokens)}`}>
                    {tokens(w.promptTokens + w.completionTokens)}
                  </td>
                  <td className={`${tdCls} text-right`}>{num(w.calls)}</td>
                  <td className={`${tdCls} text-right`}>{num(w.activeUsers)}</td>
                  <td className={`${tdCls} text-right text-xs text-foreground-500`}>{w.lastUsedAt || "—"}</td>
                  <td className={`${tdCls} text-right`}>
                    <Link to={`/users?tenantId=${w.tenantId}`} className={linkBtn}>
                      人员费用
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty text={data ? "没有符合条件的账号" : "加载中…"} />
        )}
      </div>
      {data && data.total > 20 && <PaginationBar page={page} pageSize={20} total={data.total} onPageChange={setPage} />}
    </div>
  );
}

function UsageTable({ title, rows, nameOf }: { title: string; rows: UsageGroup[]; nameOf: (r: UsageGroup) => React.ReactNode }) {
  return (
    <Card title={title}>
      {rows.length ? (
        <table className="w-full">
          <thead className={theadCls}>
            <tr>
              <th className={thCls}>名称</th>
              <th className={`${thCls} text-right`}>调用</th>
              <th className={`${thCls} text-right`}>输入 Token</th>
              <th className={`${thCls} text-right`}>输出 Token</th>
              <th className={`${thCls} text-right`}>积分</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className={trCls}>
                <td className={tdCls}>{nameOf(r)}</td>
                <td className={`${tdCls} text-right`}>{num(r.calls)}</td>
                <td className={`${tdCls} text-right`}>{num(r.promptTokens)}</td>
                <td className={`${tdCls} text-right`}>{num(r.completionTokens)}</td>
                <td className={`${tdCls} text-right font-medium`}>{num(Math.round(r.credits))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <Empty text="暂无数据" />
      )}
    </Card>
  );
}

function Usage() {
  const { fail } = useUi();
  const [days, setDays] = useState<"7" | "30" | "90">("30");
  const [data, setData] = useState<Awaited<ReturnType<typeof getPlatformUsage>> | null>(null);

  useEffect(() => {
    getPlatformUsage(Number(days)).then(setData).catch(fail);
  }, [days, fail]);

  return (
    <div className="space-y-4">
      <Filter<"7" | "30" | "90">
        options={[
          { id: "7", label: "近 7 天" },
          { id: "30", label: "近 30 天" },
          { id: "90", label: "近 90 天" },
        ]}
        value={days}
        onChange={setDays}
      />
      {data ? (
        <>
          <UsageTable
            title="按企业"
            rows={data.byTenant}
            nameOf={(r) => (
              <Link to={`/tenants/${r.key}`} className="text-primary-700 hover:underline">
                {r.name || r.key}
              </Link>
            )}
          />
          <div className="grid gap-4 lg:grid-cols-2">
            <UsageTable title="按模型" rows={data.byModel} nameOf={(r) => <span className="font-mono text-xs">{r.key || "—"}</span>} />
            <UsageTable title="按功能" rows={data.byFeature} nameOf={(r) => r.key || "—"} />
          </div>
        </>
      ) : (
        <Empty text="加载中…" />
      )}
    </div>
  );
}

const KINDS = [
  { id: "", label: "全部" },
  { id: "充值", label: "充值" },
  { id: "套餐", label: "套餐" },
  { id: "赠送", label: "赠送" },
  { id: "消费", label: "消费" },
  { id: "调整", label: "调整" },
  { id: "过期", label: "过期" },
] as const;

function Ledger() {
  const { fail } = useUi();
  const [kind, setKind] = useState<(typeof KINDS)[number]["id"]>("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Awaited<ReturnType<typeof listPlatformLedger>>>({ total: 0, items: [] });

  const load = useCallback(() => {
    listPlatformLedger({ kind, page }).then(setData).catch(fail);
  }, [kind, page, fail]);
  useEffect(load, [load]);

  return (
    <Card extra={null}>
      <div className="mb-3">
        <Filter options={KINDS} value={kind} onChange={(k) => { setKind(k); setPage(1); }} />
      </div>
      {data.items.length ? (
        <>
          <table className="w-full">
            <thead className={theadCls}>
              <tr>
                <th className={thCls}>时间</th>
                <th className={thCls}>企业</th>
                <th className={thCls}>类型</th>
                <th className={thCls}>说明</th>
                <th className={thCls}>成员 / 操作人</th>
                <th className={`${thCls} text-right`}>变动</th>
                <th className={`${thCls} text-right`}>余额</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((r) => (
                <tr key={r.id} className={trCls}>
                  <td className={`${tdCls} text-xs`}>{r.createdAt}</td>
                  <td className={tdCls}>{r.tenantName || r.tenantId}</td>
                  <td className={tdCls}>{r.kind}</td>
                  <td className={`${tdCls} text-xs`}>{r.note || r.feature}</td>
                  <td className={`${tdCls} text-xs`}>{r.userName || r.operator || "—"}</td>
                  <td className={`${tdCls} text-right ${r.amount >= 0 ? "text-emerald-600" : ""}`}>
                    {r.amount >= 0 ? "+" : ""}
                    {num(r.amount)}
                  </td>
                  <td className={`${tdCls} text-right text-foreground-500`}>{num(r.balanceAfter)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <PaginationBar page={page} pageSize={50} total={data.total} onPageChange={setPage} />
        </>
      ) : (
        <Empty text="暂无流水" />
      )}
    </Card>
  );
}
