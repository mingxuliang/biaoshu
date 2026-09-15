import type { DuplicateCheckReport } from "@/lib/api";

interface DuplicateReportProps {
  report: DuplicateCheckReport;
  onCopy: () => void;
}

const severityStyle: Record<string, string> = {
  废标: "bg-accent-50 text-accent-600 border-accent-200",
  降档: "bg-accent-50 text-accent-600 border-accent-200",
  扣分: "bg-secondary-100 text-secondary-600 border-secondary-200",
  建议: "bg-primary-50 text-primary-600 border-primary-200",
};

const lightLabel: Record<string, string> = { 绿: "绿", 橙: "橙", 红: "红" };

export default function DuplicateReport({ report, onCopy }: DuplicateReportProps) {
  const triggered = report.checks.filter((c) => c.triggered);
  const wasteCount = report.waste;
  const riskCount = report.risk;
  const suggestCount = report.suggest;

  return (
    <div className="mx-auto max-w-4xl overflow-hidden rounded-lg border border-background-300 bg-background-100">
      <div className="border-b border-background-300 bg-background-50 px-5 py-5 md:px-8">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
            <i className="ri-file-copy-2-line text-lg"></i>
          </span>
          <div>
            <h3 className="font-heading text-base font-semibold tracking-wide text-foreground-950">技术标查重报告</h3>
            <p className="text-xs text-foreground-500">慧投标 AI · 两份技术标相似度比对 · 青天查重阈值</p>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-foreground-500">
          <span>
            技术标甲：<span className="text-foreground-700">{report.fileA.name}</span>
          </span>
          <span>
            技术标乙：<span className="text-foreground-700">{report.fileB.name}</span>
          </span>
          <span>
            比对方法：<span className="text-foreground-700">{report.method}</span>
          </span>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span
            className={`font-label inline-flex items-center rounded-lg px-3 py-1 text-xs font-semibold ${
              report.light === "绿" ? "bg-primary-50 text-primary-700" : "bg-accent-50 text-accent-700"
            }`}
          >
            <span className="relative mr-1.5 flex h-2 w-2">
              <span
                className={`absolute inline-flex h-full w-full rounded-full opacity-50 animate-ping ${
                  report.light === "绿" ? "bg-primary-500" : "bg-accent-500"
                }`}
              />
              <span
                className={`relative inline-flex h-2 w-2 rounded-full ${
                  report.light === "绿" ? "bg-primary-500" : "bg-accent-500"
                }`}
              />
            </span>
            风险灯 · {lightLabel[report.light]}
          </span>
          <span className="font-label inline-flex items-center rounded-lg bg-secondary-100 px-3 py-1 text-xs font-medium text-secondary-700">
            <i className="ri-close-circle-line mr-1 text-accent-600"></i>
            降档 {wasteCount} 项
          </span>
          <span className="font-label inline-flex items-center rounded-lg bg-secondary-100 px-3 py-1 text-xs font-medium text-secondary-700">
            <i className="ri-error-warning-line mr-1 text-secondary-600"></i>
            扣分 {riskCount} 项
          </span>
          <span className="font-label inline-flex items-center rounded-lg bg-secondary-100 px-3 py-1 text-xs font-medium text-secondary-700">
            <i className="ri-information-line mr-1 text-primary-500"></i>
            建议 {suggestCount} 项
          </span>
          <button
            type="button"
            onClick={onCopy}
            className="ml-auto inline-flex h-8 cursor-pointer items-center gap-1 rounded-md border border-background-300 bg-background-50 px-2.5 text-xs font-medium text-foreground-600 hover:bg-background-200"
          >
            <i className="ri-file-copy-line"></i>
            复制摘要
          </button>
        </div>
      </div>

      <div className="px-5 py-5 md:px-8">
        <h4 className="mb-2.5 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
          <i className="ri-radio-button-line text-primary-500 text-sm"></i>
          一、两文件相似度与青天阈值
        </h4>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <MetricCard label="整体相似度" value={report.wholePct} />
          <MetricCard label="最高段落相似度" value={report.paragraphPct} />
          <MetricCard
            label="重难点/四新"
            value={report.keySectionPct}
            empty="未检出该类段落"
          />
        </div>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead>
              <tr className="font-label border-b border-background-300 text-xs text-foreground-500">
                <th className="py-2 pr-4 font-medium">阈值规则</th>
                <th className="py-2 pr-4 text-center font-medium">实测</th>
                <th className="py-2 pr-4 text-center font-medium">青天线</th>
                <th className="py-2 text-center font-medium">结论</th>
              </tr>
            </thead>
            <tbody>
              {report.checks.map((item) => (
                <tr key={item.key} className="border-b border-background-200 last:border-0">
                  <td className="py-2.5 pr-4">
                    <div className="font-medium text-foreground-900">{item.label}</div>
                    <div className="text-[11px] text-foreground-500">{item.meaning}</div>
                  </td>
                  <td className="font-heading py-2.5 pr-4 text-center font-bold text-primary-600">
                    {item.applicable && item.value != null ? `${item.value}%` : "—"}
                  </td>
                  <td className="py-2.5 pr-4 text-center text-foreground-600">{item.threshold}%</td>
                  <td className="py-2.5 text-center">
                    {!item.applicable ? (
                      <span className="font-label inline-flex rounded-md bg-background-200 px-2 py-0.5 text-xs font-medium text-foreground-500">
                        不适用
                      </span>
                    ) : (
                      <span
                        className={`font-label inline-flex rounded-md px-2 py-0.5 text-xs font-medium ${
                          item.triggered ? "bg-accent-50 text-accent-600" : "bg-primary-50 text-primary-600"
                        }`}
                      >
                        {item.triggered ? `触发${item.severity}` : "未触发"}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h4 className="mb-2.5 mt-6 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
          <i className="ri-file-list-3-line text-accent-500 text-sm"></i>
          二、相似段落对照（技术标甲 ↔ 技术标乙）
        </h4>
        <p className="mb-3 text-xs leading-relaxed text-foreground-500">
          以下为超过查重安全线的段落配对，可直接对照改写。本页只比两份技术标，不审商务标。
        </p>
        <div className="space-y-3">
          {report.issues.map((issue) => (
            <div key={issue.id} className="overflow-hidden rounded-lg border border-background-200">
              <div className="flex flex-wrap items-center gap-2 border-b border-background-200 bg-background-50 px-3 py-2">
                <span className="font-label inline-flex items-center rounded bg-background-200 px-1.5 py-0.5 text-[10px] text-foreground-600">
                  {issue.level}
                </span>
                <span
                  className={`inline-flex items-center whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${severityStyle[issue.severity]}`}
                >
                  {issue.severity}
                </span>
                <span className="font-label text-[11px] text-foreground-500">{issue.location}</span>
                <span className="font-label ml-auto rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">
                  {issue.rule}
                </span>
              </div>
              <div className="grid grid-cols-1 gap-3 p-3 sm:grid-cols-2">
                <div className="rounded-md border border-accent-200 bg-accent-50/40 p-3">
                  <div className="mb-1.5 flex items-center gap-1 text-[11px] font-medium text-accent-600">
                    <i className="ri-file-text-line"></i>
                    技术标甲原文
                  </div>
                  <p className="text-sm leading-relaxed text-foreground-800">
                    {issue.excerpt ? `「${issue.excerpt}」` : "未能定位到对应句"}
                  </p>
                </div>
                <div className="rounded-md border border-primary-200 bg-primary-50/40 p-3">
                  <div className="mb-1.5 flex items-center gap-1 text-[11px] font-medium text-primary-600">
                    <i className="ri-file-search-line"></i>
                    技术标乙原文
                  </div>
                  <p className="text-sm leading-relaxed text-foreground-800">
                    {issue.tenderQuote ? `「${issue.tenderQuote}」` : "未能定位到对应句"}
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-2 bg-background-50 px-3 py-2 text-xs text-foreground-500">
                <i className="ri-tools-line mt-0.5 shrink-0 text-primary-500"></i>
                <span>
                  <span className="font-medium text-foreground-700">修改建议：</span>
                  {issue.suggestion}
                </span>
              </div>
            </div>
          ))}
          {report.issues.length === 0 && (
            <p className="rounded-lg border border-dashed border-background-300 bg-background-50 px-3 py-6 text-center text-sm text-foreground-500">
              {triggered.length > 0
                ? "已触发阈值，但未抽出可对照的段落原文。请更换文件或改用 Word 后再比。"
                : "未检出超过安全线的相似段落。"}
            </p>
          )}
        </div>

        <h4 className="mb-2.5 mt-6 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
          <i className="ri-check-double-line text-primary-500 text-sm"></i>
          三、查重结论
        </h4>
        <div className="rounded-lg border border-primary-200 bg-primary-50/40 p-3.5">
          <p className="text-sm leading-relaxed text-foreground-600">{report.conclusion}</p>
        </div>
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  empty,
}: {
  label: string;
  value: number | null;
  empty?: string;
}) {
  return (
    <div className="rounded-lg border border-background-300 bg-background-50 p-3.5">
      <div className="font-label text-[11px] text-foreground-500">{label}</div>
      {value == null ? (
        <div className="mt-1 text-xs text-foreground-500">{empty || "—"}</div>
      ) : (
        <div className="font-heading text-gradient mt-0.5 text-2xl font-bold">
          {value}
          <span className="ml-0.5 text-sm text-foreground-500">%</span>
        </div>
      )}
    </div>
  );
}
