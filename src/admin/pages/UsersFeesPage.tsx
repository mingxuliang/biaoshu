import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { Link, useSearchParams } from "react-router-dom";
import PageHeader from "@/pages/console/components/PageHeader";
import Modal from "@/pages/console/components/Modal";
import { saveBlob } from "@/lib/saasApi";
import { exportPeopleFees, getPersonUsage, listPeopleFees, type PersonFeeRow, type PersonSort, type PersonUsage } from "../api";
import { useCan } from "../auth";
import {
  ACCOUNT_KINDS,
  btnGhost,
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
  tableWrap,
  tdCls,
  theadCls,
  thCls,
  tokens,
  trCls,
  useUi,
  type AccountKindFilter,
  type PeriodId,
} from "../ui";

export default function UsersFeesPage() {
  const { fail } = useUi();
  const { finance } = useCan();
  const [params, setParams] = useSearchParams();
  const tenantId = params.get("tenantId") || "";
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<AccountKindFilter>("");
  const [days, setDays] = useState<PeriodId>("30");
  const [sort, setSort] = useState<PersonSort>("spent");
  const [page, setPage] = useState(1);
  const [refreshTick, setRefreshTick] = useState(0);
  const [data, setData] = useState<Awaited<ReturnType<typeof listPeopleFees>> | null>(null);
  const [exporting, setExporting] = useState(false);
  const [detail, setDetail] = useState<PersonFeeRow | null>(null);

  const sentTick = useRef(0);

  useEffect(() => {
    const t = window.setTimeout(() => {
      const refresh = refreshTick !== sentTick.current;
      sentTick.current = refreshTick;
      listPeopleFees({ q, kind, tenantId, days: Number(days), sort, page, refresh }).then(setData).catch(fail);
    }, 250);
    return () => window.clearTimeout(t);
  }, [q, kind, tenantId, days, sort, page, refreshTick, fail]);

  const reset = <T,>(set: Dispatch<SetStateAction<T>>) => (v: T) => {
    set(v);
    setPage(1);
  };
  const doExport = () => {
    setExporting(true);
    exportPeopleFees({ q, kind, tenantId, days: Number(days), sort })
      .then((b) => saveBlob(b, `全员费用-${periodLabel(days)}.csv`))
      .catch(fail)
      .finally(() => setExporting(false));
  };
  const s = data?.summary;
  const period = periodLabel(days);
  const scopedName = tenantId ? data?.items[0]?.tenantName || tenantId : "";

  return (
    <div className="space-y-4">
      <PageHeader title="全员费用" description="平台上每一位使用者的积分消耗、Token 用量和最近使用时间，企业成员与个人用户一并列出。" />

      {tenantId && (
        <div className="flex items-center gap-2 rounded-lg border border-primary-200 bg-primary-50 px-3 py-2 text-sm text-primary-800">
          <i className="ri-filter-3-line" />
          只看「{scopedName}」的成员
          <button type="button" className={`${linkBtn} ml-auto`} onClick={() => setParams({}, { replace: true })}>
            查看全部人员
          </button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Filter options={PERIODS} value={days} onChange={reset(setDays)} />
        {!tenantId && (
          <>
            <span className="h-4 w-px bg-background-300" />
            <Filter options={ACCOUNT_KINDS} value={kind} onChange={reset(setKind)} />
          </>
        )}
        <div className="ml-auto flex items-center gap-2">
          <input className={`${inputCls} w-56`} placeholder="姓名、账号、部门或企业" value={q} onChange={(e) => reset(setQ)(e.target.value)} />
          <button type="button" className={btnGhost} title="重新读取人员名单" onClick={() => setRefreshTick((n) => n + 1)}>
            <i className="ri-refresh-line" />
          </button>
          {finance && (
            <button type="button" className={btnGhost} onClick={doExport} disabled={exporting}>
              <i className="ri-download-2-line mr-1" />
              {exporting ? "导出中…" : "导出 CSV"}
            </button>
          )}
        </div>
      </div>

      {s && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="人员总数" value={num(s.users)} />
          <Stat label={`${period}有消耗的人员`} value={num(s.activeUsers)} />
          <Stat label={`${period}消耗积分`} value={num(s.periodCredits)} />
          <Stat label={`${period} Token`} value={tokens(s.promptTokens + s.completionTokens)} hint={`输入 ${tokens(s.promptTokens)} · 输出 ${tokens(s.completionTokens)}`} />
        </div>
      )}

      <div className={tableWrap}>
        {data?.items.length ? (
          <table className="w-full min-w-[1100px]">
            <thead className={theadCls}>
              <tr>
                <th className={thCls}>人员</th>
                <th className={thCls}>所属企业 / 个人空间</th>
                <th className={thCls}>角色 · 部门</th>
                <SortTh id="month" label="本月已用 / 额度" sort={sort} onSort={reset(setSort)} />
                <SortTh id="spent" label="期间积分" sort={sort} onSort={reset(setSort)} />
                <SortTh id="tokens" label="Token" sort={sort} onSort={reset(setSort)} />
                <th className={`${thCls} text-right`}>调用</th>
                <SortTh id="total" label="累计积分" sort={sort} onSort={reset(setSort)} />
                <SortTh id="lastUsed" label="最近使用" sort={sort} onSort={reset(setSort)} />
                <th className={thCls} />
              </tr>
            </thead>
            <tbody>
              {data.items.map((u) => (
                <tr key={`${u.tenantId}/${u.userId}`} className={trCls}>
                  <td className={tdCls}>
                    <div className="font-medium text-foreground-900">
                      {u.name || "—"}
                      {u.disabled && <span className="ml-1.5 rounded bg-background-200 px-1 text-[11px] text-foreground-500">已停用</span>}
                    </div>
                    <div className="text-[11px] text-foreground-500">{u.account}</div>
                  </td>
                  <td className={tdCls}>
                    <Link to={`/tenants/${u.tenantId}?tab=credits`} className="text-primary-700 hover:underline">
                      {u.tenantName}
                    </Link>
                    <KindTag kind={u.tenantKind} />
                  </td>
                  <td className={`${tdCls} text-xs`}>
                    {u.role}
                    {u.departmentName && <span className="text-foreground-500"> · {u.departmentName}</span>}
                  </td>
                  <td className={`${tdCls} text-right`}>
                    {num(u.monthSpent)}
                    <span className="text-foreground-400"> / {u.monthlyCreditLimit ? num(u.monthlyCreditLimit) : "不限"}</span>
                  </td>
                  <td className={`${tdCls} text-right font-medium`}>{num(u.periodCredits)}</td>
                  <td className={`${tdCls} text-right`} title={`输入 ${num(u.promptTokens)} / 输出 ${num(u.completionTokens)}`}>
                    {tokens(u.promptTokens + u.completionTokens)}
                  </td>
                  <td className={`${tdCls} text-right`}>{num(u.calls)}</td>
                  <td className={`${tdCls} text-right`}>{num(u.totalSpent)}</td>
                  <td className={`${tdCls} text-right text-xs text-foreground-500`}>{u.lastUsedAt || "—"}</td>
                  <td className={`${tdCls} text-right`}>
                    <button type="button" className={linkBtn} onClick={() => setDetail(u)}>
                      明细
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty text={data ? "没有符合条件的人员" : "加载中…"} />
        )}
      </div>
      {data && data.total > 20 && <PaginationBar page={page} pageSize={20} total={data.total} onPageChange={setPage} />}

      {detail && <PersonDetail person={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}

const DETAIL_DAYS = [
  { id: "7", label: "近 7 天" },
  { id: "30", label: "近 30 天" },
  { id: "90", label: "近 90 天" },
] as const;

function PersonDetail({ person, onClose }: { person: PersonFeeRow; onClose: () => void }) {
  const { fail } = useUi();
  const [days, setDays] = useState<(typeof DETAIL_DAYS)[number]["id"]>("30");
  const [data, setData] = useState<PersonUsage | null>(null);

  useEffect(() => {
    setData(null);
    getPersonUsage(person.tenantId, person.userId, Number(days)).then(setData).catch(fail);
  }, [person.tenantId, person.userId, days, fail]);

  const peak = Math.max(1, ...(data?.trend.map((d) => d.credits) || [0]));
  const totalCredits = data?.byFeature.reduce((a, r) => a + r.credits, 0) || 0;
  const totalTokens = data?.byFeature.reduce((a, r) => a + r.promptTokens + r.completionTokens, 0) || 0;

  return (
    <Modal open onClose={onClose} title={`${person.name || person.account} 的使用明细`} subtitle={`${person.tenantName} · ${person.account}`} width="max-w-3xl">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <Filter options={DETAIL_DAYS} value={days} onChange={(v) => setDays(v)} />
          <span className="text-xs text-foreground-500">
            合计 {num(totalCredits)} 积分 · {tokens(totalTokens)} Token
          </span>
        </div>
        {!data ? (
          <Empty text="加载中…" />
        ) : (
          <>
            <div>
              <div className="mb-2 text-xs font-medium text-foreground-600">每日积分消耗</div>
              <div className="flex h-24 items-end gap-px rounded-lg border border-background-300 bg-background-50 px-2 pb-1 pt-2">
                {data.trend.map((d) => (
                  <div key={d.date} className="group relative flex-1" title={`${d.date}：${num(d.credits)} 积分，${num(d.tokens)} Token`}>
                    <div className="w-full rounded-t-sm bg-primary-400 group-hover:bg-primary-600" style={{ height: `${Math.max(d.credits ? 4 : 1, (d.credits / peak) * 80)}px` }} />
                  </div>
                ))}
              </div>
              <div className="mt-1 flex justify-between text-[11px] text-foreground-400">
                <span>{data.trend[0]?.date}</span>
                <span>{data.trend[data.trend.length - 1]?.date}</span>
              </div>
            </div>

            <div className={tableWrap}>
              {data.byFeature.length ? (
                <table className="w-full">
                  <thead className={theadCls}>
                    <tr>
                      <th className={thCls}>功能</th>
                      <th className={`${thCls} text-right`}>调用</th>
                      <th className={`${thCls} text-right`}>输入 Token</th>
                      <th className={`${thCls} text-right`}>输出 Token</th>
                      <th className={`${thCls} text-right`}>积分</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.byFeature.map((r) => (
                      <tr key={r.feature} className={trCls}>
                        <td className={tdCls}>{r.name}</td>
                        <td className={`${tdCls} text-right`}>{num(r.calls)}</td>
                        <td className={`${tdCls} text-right`}>{num(r.promptTokens)}</td>
                        <td className={`${tdCls} text-right`}>{num(r.completionTokens)}</td>
                        <td className={`${tdCls} text-right font-medium`}>{num(r.credits)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <Empty text="这段时间没有使用记录" />
              )}
            </div>

            {data.byModel.length > 0 && (
              <div className={tableWrap}>
                <table className="w-full">
                  <thead className={theadCls}>
                    <tr>
                      <th className={thCls}>模型</th>
                      <th className={`${thCls} text-right`}>调用</th>
                      <th className={`${thCls} text-right`}>输入 Token</th>
                      <th className={`${thCls} text-right`}>输出 Token</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.byModel.map((r) => (
                      <tr key={r.model} className={trCls}>
                        <td className={`${tdCls} font-mono text-xs`}>{r.model || "—"}</td>
                        <td className={`${tdCls} text-right`}>{num(r.calls)}</td>
                        <td className={`${tdCls} text-right`}>{num(r.promptTokens)}</td>
                        <td className={`${tdCls} text-right`}>{num(r.completionTokens)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
