import { useMemo } from "react";
import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
} from "recharts";
import type { Project } from "@/mocks/projects";

function cssColor(name: string) {
  return `oklch(${getComputedStyle(document.documentElement).getPropertyValue(name).trim()})`;
}

const riskMeta: Record<string, { icon: string; cls: string }> = {
  未出分: { icon: "ri-flag-2-line", cls: "bg-accent-50 text-accent-600" },
  进度偏低: { icon: "ri-speed-line", cls: "bg-secondary-100 text-secondary-700" },
  未中标: { icon: "ri-error-warning-line", cls: "bg-accent-50 text-accent-600" },
  待提交: { icon: "ri-time-line", cls: "bg-primary-50 text-primary-600" },
};

export default function MonitorPanel({ projects }: { projects: Project[] }) {
  const colors = useMemo<Record<string, string>>(
    () => ({
      primary: cssColor("--primary-500"),
      accent: cssColor("--accent-500"),
      secondary400: cssColor("--secondary-400"),
      bg300: cssColor("--background-300"),
      fg500: cssColor("--foreground-500"),
      fg700: cssColor("--foreground-700"),
    }),
    [],
  );

  const chartData = useMemo(
    () =>
      projects.map((p) => ({
        name: p.name.length > 8 ? `${p.name.slice(0, 8)}…` : p.name,
        进度: p.progress,
        预测得分: p.score > 0 ? p.score : null,
      })),
    [projects],
  );

  const risks = useMemo(() => {
    const items: { id: string; label: string; desc: string; key: string }[] = [];
    const notScored = projects.filter((p) => p.score === 0 && p.status === "撰写中");
    notScored.forEach((p) =>
      items.push({ id: `s-${p.id}`, label: p.name, desc: "尚未生成 AI 预测得分", key: "未出分" }),
    );
    const slow = projects.filter((p) => p.progress < 40 && p.status === "撰写中");
    slow.forEach((p) =>
      items.push({ id: `p-${p.id}`, label: p.name, desc: `撰写进度仅 ${p.progress}%，需提速`, key: "进度偏低" }),
    );
    const lost = projects.filter((p) => p.status === "未中标");
    lost.forEach((p) =>
      items.push({ id: `l-${p.id}`, label: p.name, desc: "未能中标，建议复盘优化投标策略", key: "未中标" }),
    );
    const submitting = projects.filter((p) => p.status === "评标中");
    submitting.forEach((p) =>
      items.push({ id: `t-${p.id}`, label: p.name, desc: "已进入评标预演，跟踪排名与风险项", key: "待提交" }),
    );
    return items;
  }, [projects]);

  const chartTipStyle = {
    backgroundColor: "oklch(var(--background-100))",
    border: `1px solid ${colors.bg300}`,
    borderRadius: 8,
    fontSize: 12,
    color: colors.fg700,
  };

  return (
    <div className="mb-5 grid grid-cols-1 items-start gap-4 xl:grid-cols-3">
      <div className="flex flex-col rounded-lg border border-background-300 bg-background-100 p-5 xl:col-span-2">
        <div className="mb-1 flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
            <i className="ri-line-chart-line text-primary-500 text-sm"></i>
            整体进程与 AI 评审评分
          </h3>
          <span className="rounded-full border border-background-300 bg-background-50 px-2.5 py-1 text-[11px] text-foreground-500">
            柱状=撰写进度 · 折线=预测得分
          </span>
        </div>
        <p className="mb-3 text-xs text-foreground-500">
          横向对比各项目撰写进度与 AI 预测得分，虚线为 85 分中标参考线
        </p>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={colors.bg300} vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: colors.fg500 }} axisLine={false} tickLine={false} interval={0} angle={-12} height={40} textAnchor="end" />
              <YAxis yAxisId="left" tick={{ fontSize: 11, fill: colors.fg500 }} axisLine={false} tickLine={false} domain={[0, 100]} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11, fill: colors.fg500 }} axisLine={false} tickLine={false} domain={[0, 100]} hide />
              <Tooltip contentStyle={chartTipStyle} labelStyle={{ color: colors.fg700 }} cursor={{ fill: "oklch(var(--background-50))" }} />
              <Legend wrapperStyle={{ fontSize: 11, color: colors.fg700 }} />
              <Bar yAxisId="left" dataKey="进度" fill={colors.primary} radius={[4, 4, 0, 0]} barSize={20} name="撰写进度" />
              <Line
                yAxisId="right"
                dataKey="预测得分"
                stroke={colors.accent}
                strokeWidth={2}
                dot={{ r: 3, fill: colors.accent, strokeWidth: 0 }}
                activeDot={{ r: 5 }}
                connectNulls
                name="预测得分"
              />
              <ReferenceLine yAxisId="right" y={85} stroke={colors.secondary400} strokeDasharray="6 4" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="flex h-auto min-h-0 flex-col rounded-lg border border-background-300 bg-background-100 p-5 xl:h-[22.5rem]">
        <h3 className="mb-2 flex shrink-0 items-center gap-1.5 text-sm font-semibold text-foreground-900">
          <i className="ri-notification-3-line text-accent-500 text-sm"></i>
          进程风险提示
        </h3>
        <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto">
          {risks.map((risk) => (
            <li key={risk.id} className="flex items-start gap-2.5 rounded-md bg-background-50 px-2.5 py-2">
              <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${riskMeta[risk.key].cls}`}>
                <i className={`${riskMeta[risk.key].icon} text-xs`}></i>
              </span>
              <div className="min-w-0">
                <div className="truncate text-xs font-medium text-foreground-900">{risk.label}</div>
                <div className="text-[11px] text-foreground-500">{risk.desc}</div>
              </div>
            </li>
          ))}
          {risks.length === 0 && (
            <li className="text-xs text-foreground-500">暂无风险项，所有项目进程健康。</li>
          )}
        </ul>
      </div>
    </div>
  );
}
