import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import PageHeader from "@/pages/console/components/PageHeader";
import { yuan } from "@/lib/saasApi";
import { getDashboard, type Dashboard } from "../api";
import { Card, Empty, num, Stat, useUi } from "../ui";

export default function DashboardPage() {
  const { fail } = useUi();
  const [data, setData] = useState<Dashboard | null>(null);

  useEffect(() => {
    getDashboard().then(setData).catch(fail);
  }, [fail]);

  if (!data) return <Empty text="加载中…" />;
  const maxCredits = Math.max(1, ...data.trend.map((t) => t.credits));
  const maxRevenue = Math.max(1, ...data.trend.map((t) => t.revenueCents));

  return (
    <div>
      <PageHeader title="平台概览" description="全部企业的运营与收入情况。时间按服务器 UTC 计。" />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="企业总数" value={num(data.tenants.total)} hint={Object.entries(data.tenants.byStatus).map(([k, v]) => `${k} ${v}`).join(" · ")} />
        <Stat label="登录账号" value={num(data.accounts)} />
        <Stat label="本月收入" value={yuan(data.revenueMonthCents)} />
        <Stat label="今日消耗积分" value={num(data.creditsConsumedToday)} />
        <Stat label="今日 Token" value={num(data.tokensToday)} />
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        {[
          { label: "待处理发票", value: data.pending.invoices, to: "/invoices" },
          { label: "待认领对公转账", value: data.pending.transfers, to: "/orders?tab=transfers" },
          { label: "待审核企业认证", value: data.pending.verifications, to: "/tenants?verify=待审核" },
        ].map((p) => (
          <Link key={p.label} to={p.to} className={`rounded-xl border px-4 py-3 transition-colors hover:border-primary-300 ${p.value ? "border-amber-200 bg-amber-50" : "border-background-300 bg-background-100"}`}>
            <div className="text-xs text-foreground-500">{p.label}</div>
            <div className={`mt-1 text-xl font-semibold ${p.value ? "text-amber-700" : "text-foreground-950"}`}>{p.value}</div>
          </Link>
        ))}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="近 14 天积分消耗">
          <Bars data={data.trend.map((t) => ({ label: t.date, value: t.credits, text: num(t.credits) }))} max={maxCredits} tone="bg-primary-500" />
        </Card>
        <Card title="近 14 天收入">
          <Bars data={data.trend.map((t) => ({ label: t.date, value: t.revenueCents, text: yuan(t.revenueCents) }))} max={maxRevenue} tone="bg-emerald-500" />
        </Card>
      </div>
    </div>
  );
}

function Bars({ data, max, tone }: { data: { label: string; value: number; text: string }[]; max: number; tone: string }) {
  return (
    <div className="flex h-44 items-end gap-1.5">
      {data.map((d) => (
        <div key={d.label} className="group flex flex-1 flex-col items-center gap-1" title={`${d.label}：${d.text}`}>
          <div className="flex w-full flex-1 items-end">
            <div className={`w-full rounded-t ${tone} opacity-80 group-hover:opacity-100`} style={{ height: `${Math.max(2, (d.value / max) * 100)}%` }} />
          </div>
          <span className="text-[10px] text-foreground-500">{d.label.slice(3)}</span>
        </div>
      ))}
    </div>
  );
}
