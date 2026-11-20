import { useState } from "react";
import type { PreReviewLevel, PreReviewIssue } from "@/mocks/preReview";
import type { BidScope, CustomRuleReview, DimensionScore, StandardReview, TechModuleScore, TenderRuleReport } from "@/lib/api";
import { GRADE_BADGE_CLASS, GRADE_LABEL, GRADE_TEXT_CLASS, LIGHT_LABEL } from "@/lib/grade";
import { BID_EXCERPT_HIT_LABEL, BID_EXCERPT_MISS_LABEL, isLegacyTenderParseIssue, isTechScoreRulerItem, issueChapter, issueRuleKind, issueRuleLabel, issueRuleSourceLabel, NO_BID_EXCERPT_HINT, NO_TENDER_CLAUSE_HINT, splitBidAndTender, type IssueRuleKind } from "@/lib/excerpt";
import { isEngineeringCategory } from "@/mocks/projects";

interface PreReviewReportProps {
  projectName: string;
  projectCode: string;
  /** 项目标书类别（工程类 / 软件服务类），用于报告头部展示对应的预审版本徽标。 */
  category?: string | null;
  levels: PreReviewLevel[];
  issues: PreReviewIssue[];
  dimensions: DimensionScore[];
  techModules?: TechModuleScore[];
  light: "绿" | "橙" | "红";
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
  standardReview?: StandardReview | null;
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

const lightColor: Record<"绿" | "橙" | "红", string> = {
  绿: "#16a34a",
  橙: "#ea580c",
  红: "#dc2626",
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

const STANDARD_TABS = [
  { key: "招标书", label: "招标书规则" },
  { key: "图纸", label: "图纸" },
  { key: "清单", label: "清单" },
] as const;

function standardSourceKey(source: string) {
  if (source === "招标书" || source === "评分") return "招标书";
  if (source === "图纸") return "图纸";
  return "清单";
}

function tenderBooklet(point: { booklet?: string; name: string; detail: string }) {
  if (point.booklet === "商务标" || point.booklet === "技术标") return point.booklet;
  const blob = `${point.name}${point.detail}`;
  if (/报价|价格|商务|资信|业绩|信用|资格|投标函/.test(blob)) return "商务标";
  return "技术标";
}

function StandardReviewTabs({
  review,
  scope,
}: {
  review: StandardReview | null | undefined;
  scope: BidScope;
}) {
  const points = review?.points ?? [];
  const tenderPoints = points.filter((point) => standardSourceKey(point.source) === "招标书");
  const techRules = tenderPoints.filter((point) => tenderBooklet(point) === "技术标");
  const businessRules = tenderPoints.filter((point) => tenderBooklet(point) === "商务标");
  const counts = {
    招标书: scope === "business" ? businessRules.length : scope === "tech" ? techRules.length : tenderPoints.length,
    图纸: scope === "business" ? 0 : points.filter((point) => standardSourceKey(point.source) === "图纸").length,
    清单: scope === "business" ? 0 : points.filter((point) => standardSourceKey(point.source) === "清单").length,
  };
  const sourceTabs = scope === "business" ? STANDARD_TABS.filter((item) => item.key === "招标书") : STANDARD_TABS;
  const tabs = sourceTabs.filter((item) => item.key === "招标书" || counts[item.key] > 0);
  const [tab, setTab] = useState<(typeof STANDARD_TABS)[number]["key"]>("招标书");
  const [booklet, setBooklet] = useState<"技术标" | "商务标">(scope === "business" ? "商务标" : "技术标");
  const shown =
    tab === "招标书"
      ? booklet === "商务标"
        ? businessRules
        : techRules
      : points.filter((point) => standardSourceKey(point.source) === tab);

  return (
    <>
      <h4 className="mb-2.5 mt-6 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
        <i className="ri-book-2-line text-primary-500 text-sm"></i>
        规范对标
      </h4>
      <p className="mb-2.5 text-xs text-foreground-500">
        专业 {review?.specialty || "通用"}
        {review?.note ? ` · ${review.note}` : ""}
      </p>
      <div className="mb-2.5 inline-flex rounded-lg border border-background-300 bg-background-50 p-0.5">
        {tabs.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setTab(item.key)}
            className={`cursor-pointer rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
              tab === item.key
                ? "bg-gradient-to-r from-primary-500 to-primary-600 text-background-50"
                : "text-foreground-600 hover:text-foreground-900"
            }`}
          >
            {item.label} · {counts[item.key]}
          </button>
        ))}
      </div>
      {tab === "招标书" && scope !== "tech" && scope !== "business" && (
        <div className="mb-2.5 inline-flex rounded-lg border border-background-300 bg-background-50 p-0.5">
          {([
            ["技术标", techRules.length],
            ["商务标", businessRules.length],
          ] as const).map(([key, count]) => (
            <button
              key={key}
              type="button"
              onClick={() => setBooklet(key)}
              className={`cursor-pointer rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
                booklet === key
                  ? "bg-foreground-900 text-background-50"
                  : "text-foreground-600 hover:text-foreground-900"
              }`}
            >
              {key} · {count}
            </button>
          ))}
        </div>
      )}
      {shown.length === 0 ? (
        <p className="rounded-lg border border-dashed border-background-300 bg-background-50 px-3 py-6 text-center text-xs text-foreground-500">
          {tab === "招标书" && counts.图纸 > 0
            ? "本轮没有写出招标书查核点。图纸上的施工说明在「图纸」页签。招标书和技术评分的逐条核对只在规范对标里做。"
            : "这一类本轮没有写出查核点。招标书和技术评分的逐条核对只在规范对标里做，对上的施工图会出现在「图纸」页签。"}
        </p>
      ) : (
        <div className="space-y-2.5">
          {shown.map((point) => (
            <div key={point.id || point.name} className="rounded-lg border border-background-200 bg-background-50 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-foreground-900">{point.name}</span>
                <span className="font-label ml-auto rounded bg-primary-50 px-1.5 py-0.5 text-[11px] font-semibold text-primary-700">
                  {point.score != null
                    ? `${point.grade || ""} ${point.score} / ${point.maxScore ?? 100} 分`.trim()
                    : point.grade || point.verdict || "未评分"}
                </span>
              </div>
              {point.score != null && point.weight ? (
                <p className="mt-1 text-xs text-foreground-600">
                  权重 {point.weight}
                  {point.weightedScore != null ? ` · 折合 ${point.weightedScore} 分` : ""}
                  。按本招标文件赋分档模拟，不是评标委员会最终得分。
                </p>
              ) : null}
              {point.scoreRule ? <p className="mt-1 text-xs leading-relaxed text-foreground-800">评分规则：{point.scoreRule}</p> : null}
              {(point.checks ?? []).length > 0 ? (
                <div className="mt-2 space-y-1.5">
                  {(point.checks ?? []).map((row) => (
                    <div key={`${row.item}-${row.bid}`} className="rounded border border-background-200 bg-white px-2 py-1.5">
                      <p className="text-xs font-medium text-foreground-900">
                        {row.item}
                        <span className="ml-2 font-normal text-foreground-500">{row.result}</span>
                      </p>
                      {row.bid ? <p className="mt-0.5 text-xs leading-relaxed text-foreground-700">投标书原文：{row.bid}</p> : null}
                    </div>
                  ))}
                </div>
              ) : null}
              {point.strengths ? <p className="mt-1 text-xs leading-relaxed text-foreground-800">好的地方：{point.strengths}</p> : null}
              {point.revisions ? (
                <p className="mt-1 text-xs leading-relaxed text-foreground-800">需要修改：{point.revisions}</p>
              ) : point.problems ? (
                <p className="mt-1 text-xs leading-relaxed text-foreground-800">存在问题：{point.problems}</p>
              ) : null}
              {point.noncompliance ? (
                <p className="mt-1 text-xs leading-relaxed text-foreground-800">不符合知识库规范：{point.noncompliance}</p>
              ) : null}
              {point.strategy ? <p className="mt-1 text-xs leading-relaxed text-foreground-800">高分策略：{point.strategy}</p> : null}
              {point.drawingNo ? <p className="mt-1 text-xs text-foreground-500">图号：{point.drawingNo}</p> : null}
              {point.axis ? <p className="mt-1 text-xs text-foreground-500">判断轴：{point.axis}</p> : null}
              {point.mustWrite ? (
                <p className="mt-1 text-xs text-foreground-700">
                  {point.source === "图纸" ? "施工说明" : "必须写到"}：{point.mustWrite}
                </p>
              ) : null}
              {!point.mustWrite && point.detail ? <p className="mt-1 text-xs text-foreground-500">{point.detail}</p> : null}
              {point.parameters ? (
                <p className="mt-1 text-xs text-foreground-600">
                  {point.source === "图纸" ? "图面参数" : "参数"}：{point.parameters}
                </p>
              ) : null}
              {point.standards && point.standards.length > 0 ? (
                <p className="mt-1 text-xs text-foreground-600">标准号：{point.standards.join("、")}</p>
              ) : null}
              {point.chapter ? <p className="mt-1 text-xs text-foreground-500">应落章节：{point.chapter}</p> : null}
              {point.clauses.length > 0 && (
                <p className="mt-1 text-xs text-foreground-600">
                  依据：
                  {point.clauses.map((clause) => `${clause.code} ${clause.clauseNo}`.trim()).filter(Boolean).join("；")}
                </p>
              )}
              {(point.knowledge ?? []).length > 0 && (
                <p className="mt-1 text-xs text-foreground-600">
                  知识库：
                  {(point.knowledge ?? [])
                    .map((item) => `${item.code} ${item.clauseNo} ${item.excerpt}`.trim())
                    .filter(Boolean)
                    .join("；")}
                </p>
              )}
              {(point.excerpts ?? [])
                .filter((text) => !(point.checks ?? []).some((row) => row.bid === text))
                .map((text) => (
                  <p key={text} className="mt-1 text-xs leading-relaxed text-foreground-700">
                    投标书原文：{text}
                  </p>
                ))}
              {!(point.excerpts ?? []).length && point.excerpt ? (
                <p className="mt-1 text-xs leading-relaxed text-foreground-700">标书原文：{point.excerpt}</p>
              ) : null}
              {point.reason ? <p className="mt-1 text-xs leading-relaxed text-foreground-500">{point.reason}</p> : null}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export default function PreReviewReport({
  projectName,
  projectCode,
  category = null,
  levels,
  issues,
  dimensions,
  techModules = [],
  light,
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
  standardReview = null,
}: PreReviewReportProps) {
  const wasteCount = waste ?? issues.filter((i) => i.severity === "废标" || i.severity === "降档").length;
  const riskCount = risk ?? issues.filter((i) => i.severity === "扣分").length;
  const suggestCount = suggest ?? issues.filter((i) => i.severity === "建议").length;
  const moduleGaps = techModules.filter((m) => m.status && m.status !== "达标");
  const isSecondReview = round > 1;
  const levelKeys = scope === "business" ? ["L1", "L2"] : ["L3", "L4", "L5"];
  const isCustomIssue = (issue: PreReviewIssue) =>
    (issue.rule || "").startsWith("自定义规则") || (issue.location || "").startsWith("自定义规则");
  const shownLevels = levels.filter((level) => levelKeys.includes(level.key));
  const shownIssues = issues.filter(
    (issue) => !isLegacyTenderParseIssue(issue) && (levelKeys.includes(issue.level) || isCustomIssue(issue)),
  );
  const [issueKind, setIssueKind] = useState<IssueRuleKind>("tender");
  const isTechScoreIssue = (issue: { rule?: string; location?: string }) =>
    /技术标评分/.test(`${issue.rule || ""}\n${issue.location || ""}`);
  const tenderIssues = shownIssues.filter(
    (issue) => issueRuleKind(issue) === "tender" && !isTechScoreIssue(issue),
  );
  const reviewIssues = shownIssues.filter((issue) => issueRuleKind(issue) === "review");
  const rulerItems = (tenderRules?.groups ?? []).flatMap((group) =>
    (group.items || [])
      .filter((item) => isTechScoreRulerItem(item, group))
      .map((item) => ({ ...item, groupLabel: group.label })),
  );
  const listedIssues = issueKind === "tender" ? tenderIssues : reviewIssues;
  const tenderCount = tenderIssues.length + rulerItems.length;
  const coverage = tenderRules?.coverage;
  const scopeLabel = scope === "business" ? "商务标" : "技术标";
  const isEngineering = isEngineeringCategory(category);
  const categoryBadgeLabel = category ? (isEngineering ? "工程类标书版" : "软件服务类标书版") : null;

  return (
    <div className="mx-auto max-w-4xl overflow-hidden rounded-lg border border-background-300 bg-background-100">
      {/* 报告头 */}
      <div className="border-b border-background-300 bg-background-50 px-5 py-5 md:px-8">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
            <i className="ri-shield-check-line text-lg"></i>
          </span>
          <div>
            <h3 className="flex items-center gap-2 font-heading text-base font-semibold tracking-wide text-foreground-950">
              {scope === "business" ? "商务标预审报告" : "技术标预审报告"}
              {categoryBadgeLabel && (
                <span
                  className={`font-label inline-flex items-center rounded px-2 py-0.5 text-[11px] font-medium ${
                    isEngineering
                      ? "bg-secondary-50 text-secondary-600"
                      : "bg-primary-50 text-primary-600"
                  }`}
                >
                  {categoryBadgeLabel}
                </span>
              )}
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
              {scope === "business" ? "L1 否决 + L2 商务核验（A/B/C/D 等级）" : "L3 五维 + L4 查重 + L5 版式（A/B/C/D 等级）"}
            </span>
          </span>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span
            className="font-label inline-flex items-center rounded-lg px-3 py-1 text-xs font-semibold"
            style={{ backgroundColor: `${lightColor[light]}1a`, color: lightColor[light] }}
          >
            <span className="relative mr-1.5 flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full rounded-full opacity-50 animate-ping" style={{ backgroundColor: lightColor[light] }} />
              <span className="relative inline-flex h-2 w-2 rounded-full" style={{ backgroundColor: lightColor[light] }} />
            </span>
            风险灯 · {light}（{LIGHT_LABEL[light]}）
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
        {/* 一、分册评审结论与分层等级 */}
        <h4 className="mb-2.5 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
          <i className="ri-radio-button-line text-primary-500 text-sm"></i>
          一、{scope === "business" ? "商务标评审结论与 L1-L2" : "技术标评审结论与 L3-L5"} 分层等级
        </h4>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          <div className="flex items-center gap-3 rounded-lg border border-primary-200 bg-primary-50/40 p-3.5">
            <span className="font-heading text-3xl font-bold" style={{ color: lightColor[light] }}>{light}</span>
            <div className="text-xs text-foreground-500">
              <div className="font-medium text-foreground-700">{scopeLabel}风险灯 · {LIGHT_LABEL[light]}</div>
              <div className="mt-0.5">均为定性等级，无废标项方可锁定导出</div>
            </div>
          </div>
          <div className="rounded-lg border border-background-300 bg-background-50 p-3.5 lg:col-span-2">
            <div className="mb-2 text-xs font-medium text-foreground-700">分层预审等级汇总</div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              {shownLevels.map((level) => (
                <div key={level.key} className="flex items-center gap-2 rounded-md border border-background-200 bg-background-100 px-2 py-2">
                  <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-gradient-to-br ${levelStyle[level.key]} font-label text-[10px] font-semibold text-background-50`}>
                    {level.key}
                  </span>
                  <div className="min-w-0">
                    <div className={`font-heading text-sm font-bold ${GRADE_TEXT_CLASS[level.grade]}`}>{level.grade}</div>
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
                <th className="py-2 pr-4 text-center font-medium">等级</th>
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
                  <td className={`font-heading py-2.5 pr-4 text-center font-bold ${GRADE_TEXT_CLASS[level.grade]}`}>{level.grade}</td>
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

        {/* 三、技术标五维评审（商务标分册不展示） */}
        {scope !== "business" && dimensions.length > 0 && (
          <>
        <h4 className="mb-2.5 mt-6 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
          <i className="ri-focus-3-line text-primary-500 text-sm"></i>
          三、技术标五维评审
        </h4>
        <div className="rounded-lg border border-background-200 bg-background-50 p-3.5">
          <div className="space-y-2.5">
            {dimensions.map((dim) => (
              <div key={dim.name} className="flex items-center gap-3">
                <span className="font-label w-20 shrink-0 text-xs text-foreground-600">{dim.name}</span>
                <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold ${GRADE_BADGE_CLASS[dim.grade]}`}>
                  {dim.grade} · {GRADE_LABEL[dim.grade]}
                </span>
                <span className="font-label ml-auto shrink-0 text-right text-xs text-foreground-500">
                  权重 {dim.weight}%
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
                    <div className={`font-heading text-sm font-bold ${GRADE_TEXT_CLASS[m.grade]}`}>{m.grade}</div>
                    <div className="text-[10px] text-foreground-500">{GRADE_LABEL[m.grade]}</div>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {((scope ?? "full") !== "business" || (standardReview?.points?.length ?? 0) > 0) && (
          <StandardReviewTabs
            review={
              standardReview ?? {
                specialty: "通用",
                note: "本轮没有写出规范对标",
                points: [],
              }
            }
            scope={scope ?? "full"}
          />
        )}

        {/* 四、预审问题（有据才列出） */}
        <div className="mb-2.5 mt-6 flex flex-wrap items-center justify-between gap-2">
          <h4 className="flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
            <i className="ri-file-list-3-line text-accent-500 text-sm"></i>
            四、预审问题清单
          </h4>
          <div className="inline-flex rounded-lg border border-background-300 bg-background-50 p-0.5">
            {([
              ["tender", "招标问题", tenderCount],
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
              {issue.basis ? (
                <div className="border-b border-background-200 bg-background-50 px-3 py-2 text-xs text-foreground-700">
                  <span className="font-medium text-foreground-800">依据：</span>{issue.basis}
                </div>
              ) : null}
              <div className="grid grid-cols-1 gap-3 p-3 sm:grid-cols-2">
                <div className="rounded-md border border-accent-200 bg-accent-50/40 p-3">
                  <div className="mb-1.5 flex items-center gap-1 text-[11px] font-medium text-accent-600">
                    <i className="ri-file-text-line"></i>
                    {excerpt ? (issue.basis ? "标书现状" : BID_EXCERPT_HIT_LABEL) : BID_EXCERPT_MISS_LABEL}
                  </div>
                  <p className="text-sm leading-relaxed text-foreground-800">
                    {excerpt ? `「${excerpt}」` : NO_BID_EXCERPT_HINT}
                  </p>
                </div>
                <div className="rounded-md border border-primary-200 bg-primary-50/40 p-3">
                  <div className="mb-1.5 flex items-center gap-1 text-[11px] font-medium text-primary-600">
                    <i className="ri-file-search-line"></i>
                    {issue.basis ? "规则" : "招标书要求原文（对标条款）"}
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
          {issueKind === "tender" && rulerItems.map((item) => (
            <div key={item.id} className="overflow-hidden rounded-lg border border-background-200">
              <div className="flex flex-wrap items-center gap-2 border-b border-accent-200 bg-accent-50 px-3 py-2">
                <span className="inline-flex items-center gap-1 rounded bg-accent-500 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-background-50">
                  <i className="ri-auction-line"></i>
                  评标尺子
                </span>
                <span className="min-w-0 flex-1 text-sm font-semibold leading-snug text-accent-800">{item.name}</span>
                <span className="font-label shrink-0 rounded border border-accent-200 bg-background-50 px-1.5 py-0.5 text-[10px] text-accent-700">{item.groupLabel}</span>
              </div>
              <div className="flex flex-wrap items-center gap-2 border-b border-background-200 bg-background-50 px-3 py-2">
                <span className={`inline-flex items-center whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${severityStyle[item.status] || "bg-primary-50 text-primary-600 border-primary-200"}`}>{item.status}</span>
                <span className="font-label text-[11px] text-foreground-500">
                  {item.maxScore ? `${item.score} / ${item.maxScore} 分` : "解析字段对照，不赋分"}
                </span>
              </div>
              <div className="grid grid-cols-1 gap-3 p-3 sm:grid-cols-2">
                <div className="rounded-md border border-primary-200 bg-primary-50/40 p-3">
                  <div className="mb-1.5 text-[11px] font-medium text-primary-600">招标书要求原文（评标尺子）</div>
                  <p className="text-sm leading-relaxed text-foreground-800">{item.rule}</p>
                </div>
                <div className="rounded-md border border-accent-200 bg-accent-50/40 p-3">
                  <div className="mb-1.5 text-[11px] font-medium text-accent-600">
                    {item.evidence ? BID_EXCERPT_HIT_LABEL : BID_EXCERPT_MISS_LABEL}
                  </div>
                  <p className="text-sm leading-relaxed text-foreground-800">
                    {item.evidence ? `「${item.evidence}」` : NO_BID_EXCERPT_HINT}
                  </p>
                </div>
              </div>
              {item.reason ? (
                <div className="flex items-start gap-2 bg-background-50 px-3 py-2 text-xs text-foreground-500">
                  <i className="ri-tools-line mt-0.5 shrink-0 text-primary-500"></i>
                  <span>
                    <span className="font-medium text-foreground-700">评审说明：</span>
                    {item.reason}
                  </span>
                </div>
              ) : null}
            </div>
          ))}
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
          {listedIssues.length === 0 && !(issueKind === "tender" && rulerItems.length > 0) && !(issueKind === "review" && shownIssues.length === 0 && moduleGaps.length > 0) && (
            <p className="rounded-lg border border-dashed border-background-300 bg-background-50 px-3 py-6 text-center text-sm text-foreground-500">
              {shownIssues.length === 0 && wasteCount + riskCount + suggestCount > 0
                ? "分层等级存在扣分/降档，但问题明细未写入。请重新发起一轮预审以生成问题清单。"
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
        <div className="rounded-lg border border-primary-200 bg-primary-50/40 p-3.5">
          <p className="text-sm leading-relaxed text-foreground-600">
            {isSecondReview ? (
              <>
                本轮为<b className="text-primary-600">修改闭环后的二次评审</b>，{scopeLabel}风险灯为
                <b style={{ color: lightColor[light] }}>「{light}」</b>，共发现
                <span className="font-medium text-secondary-700">{riskCount} 项</span> 扣分/降档项、
                <span className="font-medium text-primary-600">{suggestCount} 项</span> 改进建议
                {wasteCount === 0 ? "，废标风险项已清零，达到锁定导出标准。" : "，仍有废标风险项需先清零才可锁定导出。"}
              </>
            ) : (
              <>
                本轮{scopeLabel}风险灯为<b style={{ color: lightColor[light] }}>「{light}」</b>，共发现
                <span className="font-medium text-accent-600">{wasteCount} 项</span>
                废标风险、
                <span className="font-medium text-secondary-700">{riskCount} 项</span>
                扣分/降档项、
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