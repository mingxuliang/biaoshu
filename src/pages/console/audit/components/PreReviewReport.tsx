import { useState } from "react";
import type { PreReviewLevel, PreReviewIssue } from "@/mocks/preReview";
import type { BidScope, CustomRuleReview, TechModuleScore, TenderRuleReport } from "@/lib/api";
import { BID_EXCERPT_HIT_LABEL, BID_EXCERPT_MISS_LABEL, issueChapter, issueRuleKind, issueRuleLabel, issueRuleSourceLabel, NO_BID_EXCERPT_HINT, NO_TENDER_CLAUSE_HINT, splitBidAndTender, type IssueRuleKind } from "@/lib/excerpt";

interface PreReviewReportProps {
  projectName: string;
  projectCode: string;
  levels: PreReviewLevel[];
  issues: PreReviewIssue[];
  dimensions: { name: string; weight: number; score: number }[];
  techModules?: TechModuleScore[];
  overall: number;
  round: number;
  waste?: number;
  risk?: number;
  suggest?: number;
  onExport: () => void;
  onCopy: () => void;
  exporting?: boolean;
  scope?: BidScope;
  tenderRules?: TenderRuleReport | null;
  customRules?: CustomRuleReview[] | null;
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

export function CustomRulesReviewBlock({ rules }: { rules?: CustomRuleReview[] | null }) {
  const rows = rules || [];
  if (!rows.length) {
    return (
      <p className="rounded-lg border border-dashed border-background-300 bg-background-50 px-3 py-5 text-center text-sm text-foreground-500">
        本轮预审尚未纳入自定义规则对照。若解析页已添加规则，请再跑一轮预审。
      </p>
    );
  }
  const unanswered = rows.filter((r) => r.status === "未响应").length;
  return (
    <div>
      <p className="mb-3 text-xs leading-relaxed text-foreground-500">
        来自招标解析页人工补充的规则，逐条对照投标书是否响应。共 {rows.length} 条，未响应 {unanswered} 条。
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead>
            <tr className="font-label border-b border-background-300 text-xs text-foreground-500">
              <th className="py-2 pr-3 font-medium">规则</th>
              <th className="py-2 pr-3 font-medium">来源</th>
              <th className="py-2 pr-3 text-center font-medium">严重程度</th>
              <th className="py-2 pr-3 text-center font-medium">对照结果</th>
              <th className="py-2 font-medium">说明</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((rule, idx) => (
              <tr key={rule.id || `${rule.title}-${idx}`} className="border-b border-background-200 last:border-0 align-top">
                <td className="py-2.5 pr-3">
                  <div className="font-medium text-foreground-900">{rule.title || "未命名规则"}</div>
                  {rule.content ? (
                    <div className="mt-0.5 text-[11px] leading-relaxed text-foreground-500">{rule.content}</div>
                  ) : null}
                </td>
                <td className="py-2.5 pr-3 whitespace-nowrap text-xs text-foreground-600">{rule.sourceLabel || "—"}</td>
                <td className="py-2.5 pr-3 text-center">
                  <span className={`inline-flex items-center whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${severityStyle[rule.severity] || severityStyle["扣分"]}`}>
                    {rule.severity || "扣分"}
                  </span>
                </td>
                <td className="py-2.5 pr-3 text-center">
                  <span
                    className={`font-label inline-flex rounded-md px-2 py-0.5 text-xs font-medium ${
                      rule.status === "已响应" ? "bg-primary-50 text-primary-600" : "bg-accent-50 text-accent-600"
                    }`}
                  >
                    {rule.status}
                  </span>
                </td>
                <td className="py-2.5 text-xs leading-relaxed text-foreground-600">
                  {rule.reason || (rule.status === "已响应" ? "投标书已覆盖该规则。" : "投标书未确认对应表述。")}
                  {rule.excerpt ? ` 对应内容：「${rule.excerpt}」` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function PreReviewReport({
  projectName,
  projectCode,
  levels,
  issues,
  dimensions,
  techModules = [],
  overall,
  round,
  waste,
  risk,
  suggest,
  onExport,
  onCopy,
  exporting = false,
  scope = "full",
  tenderRules = null,
  customRules = null,
}: PreReviewReportProps) {
  const wasteCount = waste ?? issues.filter((i) => i.severity === "废标" || i.severity === "降档").length;
  const riskCount = risk ?? issues.filter((i) => i.severity === "扣分").length;
  const suggestCount = suggest ?? issues.filter((i) => i.severity === "建议").length;
  const moduleGaps = techModules.filter((m) => m.status && m.status !== "达标");
  const isSecondReview = round >= 4;
  const levelKeys = scope === "business" ? ["L1", "L2"] : ["L3", "L4", "L5"];
  const isCustomIssue = (issue: PreReviewIssue) =>
    (issue.rule || "").startsWith("自定义规则") || (issue.location || "").startsWith("自定义规则");
  const shownLevels = levels.filter((level) => levelKeys.includes(level.key));
  const shownIssues = issues.filter((issue) => levelKeys.includes(issue.level) || isCustomIssue(issue));
  const [issueKind, setIssueKind] = useState<IssueRuleKind>("tender");
  const tenderIssues = shownIssues.filter((issue) => issueRuleKind(issue) === "tender");
  const reviewIssues = shownIssues.filter((issue) => issueRuleKind(issue) === "review");
  const listedIssues = issueKind === "tender" ? tenderIssues : reviewIssues;
  const coverage = tenderRules?.coverage;
  const scoreLabel = scope === "business" ? "商务标得分" : "技术标得分";

  return (
    <div className="mx-auto max-w-4xl overflow-hidden rounded-lg border border-background-300 bg-background-100">
      {/* 报告头 */}
      <div className="border-b border-background-300 bg-background-50 px-5 py-5 md:px-8">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
            <i className="ri-shield-check-line text-lg"></i>
          </span>
          <div>
            <h3 className="font-heading text-base font-semibold tracking-wide text-foreground-950">
              {scope === "business" ? "商务标预审报告" : "技术标预审报告"}
            </h3>
            <p className="text-xs text-foreground-500">
              智标云 AI · {scope === "business" ? "商务分册" : "技术分册"} · 第 {round} 轮预审{isSecondReview ? "（修改后）" : ""}
              {coverage?.checklistVersion ? ` · 尺子 v${coverage.checklistVersion}` : ""}
              {coverage?.weightName ? ` · ${coverage.weightName}` : ""}
            </p>
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
            预审方法：<span className="text-foreground-700">
              {scope === "business" ? "L1 否决 + L2 商务核验（满分 100）" : "L3 五维 + L4 查重 + L5 版式（满分 100）"}
            </span>
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
        {/* 一、分册得分与分层指标 */}
        <h4 className="mb-2.5 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
          <i className="ri-radio-button-line text-primary-500 text-sm"></i>
          一、{scope === "business" ? "商务标得分与 L1-L2" : "技术标得分与 L3-L5"} 分层指标
        </h4>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          <div className="flex items-center gap-3 rounded-lg border border-primary-200 bg-primary-50/40 p-3.5">
            <span className="font-heading text-gradient text-3xl font-bold">{overall}</span>
            <div className="text-xs text-foreground-500">
              <div className="font-medium text-foreground-700">{scope === "business" ? "商务标得分" : "技术标得分"}</div>
              <div className="mt-0.5">满分 100 · 达 90 方可锁定导出</div>
            </div>
          </div>
          <div className="rounded-lg border border-background-300 bg-background-50 p-3.5 lg:col-span-2">
            <div className="mb-2 text-xs font-medium text-foreground-700">分层预审得分汇总</div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              {shownLevels.map((level) => (
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
          二、{scope === "business" ? "L1-L2" : "L3-L5"} 分层预审明细
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
              {shownLevels.map((level) => (
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

        {/* 三、技术标五维打分（商务标分册不展示） */}
        {scope !== "business" && dimensions.length > 0 && (
          <>
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
          </>
        )}

        {/* 技术评分模块核验：与规则页「技术评分」tab 一一对应 */}
        {scope !== "business" && techModules.length > 0 && (
          <>
            <h4 className="mb-2.5 mt-6 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
              <i className="ri-cpu-line text-primary-500 text-sm"></i>
              技术评分模块核验
            </h4>
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              {techModules.map((m) => (
                <div key={m.key} className="flex items-start justify-between gap-3 rounded-lg border border-background-200 bg-background-50 p-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-foreground-900">{m.module}</span>
                      <span
                        className={`font-label whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium ${
                          m.status === "达标"
                            ? "bg-primary-50 text-primary-600"
                            : m.status === "建议" || m.status === "无法比对"
                              ? "bg-secondary-100 text-secondary-600"
                              : "bg-accent-50 text-accent-600"
                        }`}
                      >
                        {m.status}
                      </span>
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-foreground-500">{m.summary}</p>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="font-heading text-sm font-bold text-foreground-900">{m.score}</div>
                    <div className="text-[10px] text-foreground-500">满分 {m.maxScore}</div>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {/* 四、预审问题（有据才列出） */}
        <div className="mb-2.5 mt-6 flex flex-wrap items-center justify-between gap-2">
          <h4 className="flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
            <i className="ri-file-list-3-line text-accent-500 text-sm"></i>
            四、预审问题清单
          </h4>
          <div className="inline-flex rounded-lg border border-background-300 bg-background-50 p-0.5">
            {([
              ["tender", "招标问题", tenderIssues.length],
              ["review", "预审规则问题", reviewIssues.length],
            ] as const).map(([key, label, count]) => (
              <button
                key={key}
                type="button"
                onClick={() => setIssueKind(key)}
                className={`cursor-pointer rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  issueKind === key
                    ? "bg-gradient-to-r from-primary-500 to-primary-600 text-background-50"
                    : "text-foreground-600 hover:text-foreground-900"
                }`}
              >
                {label} · {count}
              </button>
            ))}
          </div>
        </div>
        <div className="space-y-3">
          {listedIssues.map((issue) => {
            const { excerpt, tenderQuote } = splitBidAndTender(issue.excerpt, issue.tenderQuote, issue.rule);
            const chapter = issueChapter(issue.location);
            const ruleLabel = issueRuleLabel(issue);
            const ruleSource = issueRuleSourceLabel(issue);
            return (
            <div key={issue.id} className="overflow-hidden rounded-lg border border-background-200">
              <div className="flex flex-wrap items-center gap-2 border-b border-accent-200 bg-accent-50 px-3 py-2">
                <span className="inline-flex items-center gap-1 rounded bg-accent-500 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-background-50">
                  <i className="ri-price-tag-3-line"></i>
                  命中规则
                </span>
                <span className="min-w-0 flex-1 text-sm font-semibold leading-snug text-accent-800">{ruleLabel}</span>
                <span className="font-label shrink-0 rounded border border-accent-200 bg-background-50 px-1.5 py-0.5 text-[10px] text-accent-700">{ruleSource}</span>
              </div>
              <div className="flex flex-wrap items-center gap-2 border-b border-background-200 bg-background-50 px-3 py-2">
                <span className="font-label inline-flex items-center rounded bg-background-200 px-1.5 py-0.5 text-[10px] text-foreground-600">{issue.level}</span>
                <span className={`inline-flex items-center whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${severityStyle[issue.severity]}`}>{issue.severity}</span>
                <span className="font-label text-[11px] text-foreground-500">章节：{chapter || "未标注章节"}</span>
              </div>
              <div className="grid grid-cols-1 gap-3 p-3 sm:grid-cols-2">
                <div className="rounded-md border border-accent-200 bg-accent-50/40 p-3">
                  <div className="mb-1.5 flex items-center gap-1 text-[11px] font-medium text-accent-600">
                    <i className="ri-file-text-line"></i>
                    {excerpt ? BID_EXCERPT_HIT_LABEL : BID_EXCERPT_MISS_LABEL}
                  </div>
                  <p className="text-sm leading-relaxed text-foreground-800">
                    {excerpt ? `「${excerpt}」` : NO_BID_EXCERPT_HINT}
                  </p>
                </div>
                <div className="rounded-md border border-primary-200 bg-primary-50/40 p-3">
                  <div className="mb-1.5 flex items-center gap-1 text-[11px] font-medium text-primary-600">
                    <i className="ri-file-search-line"></i>
                    招标书要求原文（对标条款）
                  </div>
                  <p className="text-sm leading-relaxed text-foreground-800">
                    {tenderQuote ? `「${tenderQuote}」` : NO_TENDER_CLAUSE_HINT}
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
            );
          })}
          {listedIssues.length === 0 && issueKind === "review" && shownIssues.length === 0 && moduleGaps.length > 0 && moduleGaps.map((m) => (
            <div key={m.key} className="overflow-hidden rounded-lg border border-background-200">
              <div className="flex flex-wrap items-center gap-2 border-b border-background-200 bg-background-50 px-3 py-2">
                <span className="font-label inline-flex items-center rounded bg-background-200 px-1.5 py-0.5 text-[10px] text-foreground-600">L3</span>
                <span className={`inline-flex items-center whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${severityStyle[m.status] || severityStyle["扣分"]}`}>{m.status}</span>
                <span className="font-label text-[11px] text-foreground-500">章节：{m.module}</span>
                <span className="font-label ml-auto rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">{m.module}</span>
              </div>
              <div className="px-3 py-2 text-xs leading-relaxed text-foreground-600">{m.summary}</div>
            </div>
          ))}
          {listedIssues.length === 0 && !(issueKind === "review" && shownIssues.length === 0 && moduleGaps.length > 0) && (
            <p className="rounded-lg border border-dashed border-background-300 bg-background-50 px-3 py-6 text-center text-sm text-foreground-500">
              {shownIssues.length === 0 && wasteCount + riskCount + suggestCount > 0
                ? "分层得分已扣分，但问题明细未写入。请重新发起一轮预审以生成问题清单。"
                : issueKind === "tender"
                  ? "当前暂无招标问题。"
                  : "当前暂无预审规则问题。"}
            </p>
          )}
        </div>

        {/* 五、自定义规则对照 */}
        <h4 className="mb-2.5 mt-6 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
          <i className="ri-list-check-3 text-primary-500 text-sm"></i>
          五、自定义规则对照
        </h4>
        <CustomRulesReviewBlock rules={customRules} />

        {/* 六、预审结论 */}
        <h4 className="mb-2.5 mt-6 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
          <i className="ri-check-double-line text-primary-500 text-sm"></i>
          六、预审结论
        </h4>
        <div className={`rounded-lg p-3.5 ${isSecondReview ? "border border-primary-300 bg-primary-50/40" : "border border-primary-200 bg-primary-50/40"}`}>
          <p className="text-sm leading-relaxed text-foreground-600">
            {isSecondReview ? (
              <>
                本轮为<b className="text-primary-600">修改闭环后的二次评审</b>，{scoreLabel}
                <span className="font-heading font-bold text-primary-600">{overall}</span> 分，较上一轮明显提升，
                共发现 <span className="font-medium text-secondary-700">{riskCount} 项</span> 扣分项、
                <span className="font-medium text-primary-600">{suggestCount} 项</span> 改进建议，
                废标/降档风险项已清零，达到锁定导出标准。
              </>
            ) : (
              <>
                本轮{scoreLabel} <span className="font-heading font-bold text-primary-600">{overall}</span> 分，共发现
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
            disabled={exporting}
            className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-gradient-to-r from-primary-500 to-primary-600 px-3 text-xs font-semibold text-background-50 transition-all hover:from-primary-600 hover:to-primary-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <i className={`${exporting ? "ri-loader-4-line animate-spin" : "ri-download-2-line"} text-xs`}></i>
            {exporting ? "正在导出…" : "导出完整报告"}
          </button>
        </div>
      </div>
    </div>
  );
}