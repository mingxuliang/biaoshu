import type { PreReviewLevel, PreReviewIssue } from "@/mocks/preReview";

interface PreReviewReportProps {
  projectName: string;
  projectCode: string;
  levels: PreReviewLevel[];
  issues: PreReviewIssue[];
  dimensions: { name: string; weight: number; score: number }[];
  overall: number;
  round: number;
  onExport: () => void;
  onCopy: () => void;
}

const levelStyle: Record<string, string> = {
  L1: "bg-gradient-to-br from-primary-400 to-primary-600",
  L2: "bg-gradient-to-br from-accent-400 to-accent-500",
  L3: "bg-gradient-to-br from-primary-400 to-primary-600",
  L4: "bg-gradient-to-br from-accent-400 to-accent-500",
  L5: "bg-gradient-to-br from-secondary-400 to-secondary-500",
};

const severityStyle: Record<string, string> = {
  废标: "bg-accent-50 text-accent-600 border-accent-200",
  降档: "bg-accent-50 text-accent-600 border-accent-200",
  扣分: "bg-secondary-100 text-secondary-600 border-secondary-200",
  建议: "bg-primary-50 text-primary-600 border-primary-200",
};

export default function PreReviewReport({
  projectName,
  projectCode,
  levels,
  issues,
  dimensions,
  overall,
  round,
  onExport,
  onCopy,
}: PreReviewReportProps) {
  const wasteCount = issues.filter((i) => i.severity === "废标" || i.severity === "降档").length;
  const riskCount = issues.filter((i) => i.severity === "扣分").length;
  const suggestCount = issues.filter((i) => i.severity === "建议").length;
  const isSecondReview = round >= 4;

  return (
    <div className="mx-auto max-w-4xl overflow-hidden rounded-lg border border-background-300 bg-background-100">
      {/* 报告头 */}
      <div className="border-b border-background-300 bg-background-50 px-5 py-5 md:px-8">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
            <i className="ri-shield-check-line text-lg"></i>
          </span>
          <div>
            <h3 className="font-heading text-base font-semibold tracking-wide text-foreground-950">AI 智能预审报告</h3>
            <p className="text-xs text-foreground-500">智标云 AI · 自动生成于 2026-08-17 15:40 · 第 {round} 轮预审{isSecondReview ? "（修改后）" : ""}</p>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-foreground-500">
          <span>
            项目名称：<span className="text-foreground-700">{projectName}</span>
          </span>
          <span>
            招标编号：<span className="text-foreground-700">{projectCode}</span>
          </span>
          <span>
            预审方法：<span className="text-foreground-700">L1-L5 分层预审</span>
          </span>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className={`font-label inline-flex items-center rounded-lg px-3 py-1 text-xs font-semibold ${
            isSecondReview ? "bg-primary-50 text-primary-700" : "bg-accent-50 text-accent-700"
          }`}>
            <span className="relative mr-1.5 flex h-2 w-2">
              <span className={`absolute inline-flex h-full w-full rounded-full opacity-50 animate-ping ${isSecondReview ? "bg-primary-500" : "bg-accent-500"}`} />
              <span className={`relative inline-flex h-2 w-2 rounded-full ${isSecondReview ? "bg-primary-500" : "bg-accent-500"}`} />
            </span>
            风险灯 · {isSecondReview ? "绿" : "橙"}
          </span>
          {isSecondReview && (
            <span className="font-label inline-flex items-center rounded-lg bg-primary-500 px-3 py-1 text-xs font-semibold text-background-50">
              <i className="ri-refresh-line mr-1"></i>
              二次评审生效
            </span>
          )}
          <span className="font-label inline-flex items-center rounded-lg bg-secondary-100 px-3 py-1 text-xs font-medium text-secondary-700">
            <i className="ri-close-circle-line mr-1 text-accent-600"></i>
            废标风险 {wasteCount} 项
          </span>
          <span className="font-label inline-flex items-center rounded-lg bg-secondary-100 px-3 py-1 text-xs font-medium text-secondary-700">
            <i className="ri-error-warning-line mr-1 text-secondary-600"></i>
            扣分 {riskCount} 项
          </span>
          <span className="font-label inline-flex items-center rounded-lg bg-secondary-100 px-3 py-1 text-xs font-medium text-secondary-700">
            <i className="ri-information-line mr-1 text-primary-500"></i>
            建议 {suggestCount} 项
          </span>
        </div>
      </div>

      <div className="px-5 py-5 md:px-8">
        {/* 一、综合得分与分层指标 */}
        <h4 className="mb-2.5 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
          <i className="ri-radio-button-line text-primary-500 text-sm"></i>
          一、综合预审得分与 L1-L5 分层指标
        </h4>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          <div className="flex items-center gap-3 rounded-lg border border-primary-200 bg-primary-50/40 p-3.5">
            <span className="font-heading text-gradient text-3xl font-bold">{overall}</span>
            <div className="text-xs text-foreground-500">
              <div className="font-medium text-foreground-700">综合预审得分</div>
              <div className="mt-0.5">满分 100 · 达 90 方可锁定导出</div>
            </div>
          </div>
          <div className="rounded-lg border border-background-300 bg-background-50 p-3.5 lg:col-span-2">
            <div className="mb-2 text-xs font-medium text-foreground-700">分层预审得分汇总</div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-5">
              {levels.map((level) => (
                <div key={level.key} className="flex items-center gap-2 rounded-md border border-background-200 bg-background-100 px-2 py-2">
                  <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-gradient-to-br ${levelStyle[level.key]} font-label text-[10px] font-semibold text-background-50`}>
                    {level.key}
                  </span>
                  <div className="min-w-0">
                    <div className={`font-heading text-sm font-bold ${level.status === "风险" ? "text-accent-600" : "text-primary-600"}`}>{level.score}</div>
                    <div className="font-label text-[9px] text-foreground-500">{level.issues} 项</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 二、分层预审明细 */}
        <h4 className="mb-2.5 mt-6 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
          <i className="ri-stack-line text-primary-500 text-sm"></i>
          二、L1-L5 分层预审明细
        </h4>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead>
              <tr className="font-label border-b border-background-300 text-xs text-foreground-500">
                <th className="py-2 pr-4 font-medium">层级</th>
                <th className="py-2 pr-4 font-medium">审查内容</th>
                <th className="py-2 pr-4 text-center font-medium">得分</th>
                <th className="py-2 pr-4 text-center font-medium">问题数</th>
                <th className="py-2 text-center font-medium">结论</th>
              </tr>
            </thead>
            <tbody>
              {levels.map((level) => (
                <tr key={level.key} className="border-b border-background-200 last:border-0">
                  <td className="py-2.5 pr-4">
                    <span className={`flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br ${levelStyle[level.key]} font-label text-[11px] font-semibold text-background-50`}>
                      {level.key}
                    </span>
                  </td>
                  <td className="py-2.5 pr-4">
                    <div className="font-medium text-foreground-900">{level.name}</div>
                    <div className="text-[11px] text-foreground-500">{level.desc}</div>
                  </td>
                  <td className="font-heading py-2.5 pr-4 text-center font-bold text-primary-600">{level.score}</td>
                  <td className="py-2.5 pr-4 text-center text-foreground-600">{level.issues}</td>
                  <td className="py-2.5 text-center">
                    <span
                      className={`font-label inline-flex rounded-md px-2 py-0.5 text-xs font-medium ${
                        level.status === "风险" ? "bg-accent-50 text-accent-600" : "bg-primary-50 text-primary-600"
                      }`}
                    >
                      {level.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 三、技术标五维打分 */}
        <h4 className="mb-2.5 mt-6 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
          <i className="ri-focus-3-line text-primary-500 text-sm"></i>
          三、技术标五维打分
        </h4>
        <div className="rounded-lg border border-background-200 bg-background-50 p-3.5">
          <div className="space-y-2.5">
            {dimensions.map((dim) => (
              <div key={dim.name} className="flex items-center gap-3">
                <span className="font-label w-20 shrink-0 text-xs text-foreground-600">{dim.name}</span>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-background-200">
                  <div className="h-full rounded-full bg-gradient-to-r from-primary-500 to-primary-400" style={{ width: `${dim.score}%` }} />
                </div>
                <span className="font-label w-28 shrink-0 text-right text-xs text-foreground-500">
                  {dim.score} / 权重 {dim.weight}%
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* 四、预审问题与原文对照 */}
        <h4 className="mb-2.5 mt-6 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
          <i className="ri-file-list-3-line text-accent-500 text-sm"></i>
          四、预审问题清单（投标书原文 ↔ 招标书要求原文）
        </h4>
        <p className="mb-3 text-xs leading-relaxed text-foreground-500">
          以下问题均定位到投标书与招标书原文，可直接核对偏差，作为修改闭环的输入。
        </p>
        <div className="space-y-3">
          {issues.map((issue) => (
            <div key={issue.id} className="overflow-hidden rounded-lg border border-background-200">
              <div className="flex flex-wrap items-center gap-2 border-b border-background-200 bg-background-50 px-3 py-2">
                <span className="font-label inline-flex items-center rounded bg-background-200 px-1.5 py-0.5 text-[10px] text-foreground-600">{issue.level}</span>
                <span className={`inline-flex items-center whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${severityStyle[issue.severity]}`}>{issue.severity}</span>
                <span className="font-label text-[11px] text-foreground-500">定位：{issue.location}</span>
                <span className="font-label ml-auto rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">{issue.rule}</span>
              </div>
              <div className="grid grid-cols-1 gap-3 p-3 sm:grid-cols-2">
                <div className="rounded-md border border-accent-200 bg-accent-50/40 p-3">
                  <div className="mb-1.5 flex items-center gap-1 text-[11px] font-medium text-accent-600">
                    <i className="ri-file-text-line"></i>
                    投标书原文（命中句）
                  </div>
                  <p className="text-sm leading-relaxed text-foreground-800">「{issue.excerpt}」</p>
                </div>
                <div className="rounded-md border border-primary-200 bg-primary-50/40 p-3">
                  <div className="mb-1.5 flex items-center gap-1 text-[11px] font-medium text-primary-600">
                    <i className="ri-file-search-line"></i>
                    招标书要求原文（对标条款）
                  </div>
                  <p className="text-sm leading-relaxed text-foreground-800">「{issue.tenderQuote}」</p>
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
        </div>

        {/* 五、预审结论 */}
        <h4 className="mb-2.5 mt-6 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
          <i className="ri-check-double-line text-primary-500 text-sm"></i>
          五、预审结论
        </h4>
        <div className={`rounded-lg p-3.5 ${isSecondReview ? "border border-primary-300 bg-primary-50/40" : "border border-primary-200 bg-primary-50/40"}`}>
          <p className="text-sm leading-relaxed text-foreground-600">
            {isSecondReview ? (
              <>
                本轮为<b className="text-primary-600">修改闭环后的二次评审</b>，综合得分
                <span className="font-heading font-bold text-primary-600">{overall}</span> 分，较上一轮明显提升，
                共发现 <span className="font-medium text-secondary-700">{riskCount} 项</span> 扣分项、
                <span className="font-medium text-primary-600">{suggestCount} 项</span> 改进建议，
                废标/降档风险项已清零，达到锁定导出标准。
              </>
            ) : (
              <>
                本轮预审综合得分 <span className="font-heading font-bold text-primary-600">{overall}</span> 分，共发现
                <span className="font-medium text-accent-600">{wasteCount} 项</span>
                废标/降档风险、
                <span className="font-medium text-secondary-700">{riskCount} 项</span>
                扣分项、
                <span className="font-medium text-primary-600">{suggestCount} 项</span>
                改进建议。废标风险项须在投标截止前全部清零后方可锁定导出；建议进入「修改闭环」按原文定位逐项改写并复审。
              </>
            )}
          </p>
        </div>
      </div>

      {/* 报告操作 */}
      <div className="flex flex-col gap-2 border-t border-background-300 bg-background-50 px-5 py-3 sm:flex-row sm:items-center sm:justify-between md:px-8">
        <p className="text-[11px] text-foreground-500">
          <i className="ri-shield-check-line mr-1 text-primary-500"></i>
          本报告由 AI 基于本项目招标文件与投标文件原文自动生成，供投标前自查参考
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onCopy}
            className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 px-3 text-xs font-medium text-foreground-600 transition-colors hover:bg-background-200"
          >
            <i className="ri-file-copy-line text-xs"></i>
            复制摘要
          </button>
          <button
            type="button"
            onClick={onExport}
            className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-gradient-to-r from-primary-500 to-primary-600 px-3 text-xs font-semibold text-background-50 transition-all hover:from-primary-600 hover:to-primary-700"
          >
            <i className="ri-download-2-line text-xs"></i>
            导出完整报告
          </button>
        </div>
      </div>
    </div>
  );
}