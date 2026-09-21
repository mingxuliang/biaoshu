import type { PreReviewIssue } from "@/mocks/preReview";
import { sourceVisibleText, issueRuleLabel, NO_BID_EXCERPT_HINT, splitBidAndTender } from "@/lib/excerpt";
import type { IssueChapterGroup } from "@/lib/reviewChapters";

interface IssuePanelProps {
  issues: PreReviewIssue[];
  groups: IssueChapterGroup[];
  activeIssueId: string | null;
  filterHeading?: string | null;
  applyingIssueId?: string | null;
  anchoredIds?: string[];
  onIssueClick: (issueId: string) => void;
  onJumpAll: () => void;
  onClearFilter?: () => void;
  onToggleResolved?: (issueId: string, resolved: boolean) => void;
  onApplySuggestion?: (issueId: string) => void;
}

const severityStyle: Record<string, string> = {
  废标: "bg-accent-50 text-accent-600 border-accent-200",
  降档: "bg-accent-50 text-accent-600 border-accent-200",
  扣分: "bg-secondary-100 text-secondary-600 border-secondary-200",
  建议: "bg-primary-50 text-primary-600 border-primary-200",
};

function IssueCard({
  issue,
  active,
  resolved,
  anchored,
  applying,
  onIssueClick,
  onToggleResolved,
  onApplySuggestion,
}: {
  issue: PreReviewIssue;
  active: boolean;
  resolved: boolean;
  anchored: boolean;
  applying: boolean;
  onIssueClick: (issueId: string) => void;
  onToggleResolved?: (issueId: string, resolved: boolean) => void;
  onApplySuggestion?: (issueId: string) => void;
}) {
  const { excerpt: rawExcerpt, tenderQuote } = splitBidAndTender(issue.excerpt, issue.tenderQuote, issue.rule);
  const excerpt = sourceVisibleText(rawExcerpt) || rawExcerpt;
  return (
    <div
      className={`rounded-lg border p-3 transition-all duration-200 ${
        resolved
          ? "border-background-200 bg-background-50/70 opacity-70"
          : active
            ? "border-primary-300 bg-primary-50/70 ring-1 ring-primary-300"
            : "border-background-300 bg-background-50 hover:border-background-400"
      }`}
    >
      <div className="flex items-start gap-2">
        <label
          className="mt-0.5 flex shrink-0 cursor-pointer items-center gap-1"
          onClick={(e) => e.stopPropagation()}
          title={resolved ? "取消已修复" : "标记为已修复"}
        >
          <input
            type="checkbox"
            checked={resolved}
            onChange={(e) => onToggleResolved?.(issue.id, e.target.checked)}
            className="h-3.5 w-3.5 cursor-pointer accent-primary-500"
          />
          <span className="sr-only">已修复</span>
        </label>
        <button
          type="button"
          onClick={() => onIssueClick(issue.id)}
          className="min-w-0 flex-1 cursor-pointer text-left"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="flex flex-wrap items-center gap-1">
              <span className="inline-flex items-center whitespace-nowrap rounded-md border border-secondary-200 bg-secondary-50 px-1.5 py-0.5 text-[10px] font-medium text-secondary-600">
                {issue.level || "—"}
              </span>
              <span className={`inline-flex items-center whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${severityStyle[issue.severity]}`}>
                {issue.severity}
              </span>
              {anchored ? (
                <span className="inline-flex items-center whitespace-nowrap rounded-md border border-primary-200 bg-primary-50 px-1.5 py-0.5 text-[10px] text-primary-600">
                  已锚定
                </span>
              ) : (
                <span className="inline-flex items-center whitespace-nowrap rounded-md border border-background-300 bg-background-100 px-1.5 py-0.5 text-[10px] text-foreground-500">
                  未锚定
                </span>
              )}
              {resolved ? <span className="text-[10px] text-primary-600">已修复</span> : null}
            </span>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 rounded border border-accent-200 bg-accent-50 px-1.5 py-1">
            <span className="inline-flex items-center rounded bg-accent-500 px-1 py-0.5 text-[10px] font-semibold text-background-50">命中规则</span>
            <span className="text-[11px] font-semibold leading-relaxed text-accent-800">{issueRuleLabel(issue)}</span>
          </div>
          <p className={`mt-1.5 text-xs leading-relaxed ${resolved ? "text-foreground-400 line-through" : active ? "text-primary-800" : "text-foreground-700"}`}>
            {excerpt ? `「${excerpt}」` : NO_BID_EXCERPT_HINT}
          </p>
          {tenderQuote ? (
            <p className="mt-1 text-[10px] leading-relaxed text-primary-700">
              对标条款：「{tenderQuote}」
            </p>
          ) : null}
          <div className="mt-1.5 text-[11px] leading-relaxed text-foreground-500">
            AI 修改建议：{issue.suggestion || "请按本条预审规则补全可核验的响应内容"}
          </div>
          <div className="mt-1.5 flex items-center justify-end">
            <span
              className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md transition-all ${
                active ? "bg-primary-500 text-background-50" : "bg-background-200 text-foreground-500"
              }`}
            >
              <i className="ri-corner-down-right-line text-xs"></i>
            </span>
          </div>
        </button>
      </div>
      {onApplySuggestion && !resolved && (
        <button
          type="button"
          disabled={applying}
          onClick={(e) => {
            e.stopPropagation();
            onApplySuggestion(issue.id);
          }}
          className="mt-2 flex w-full cursor-pointer items-center justify-center gap-1 rounded-md border border-primary-200 bg-primary-50 px-2 py-1 text-[11px] font-medium text-primary-600 transition-colors hover:bg-primary-100 disabled:cursor-wait disabled:opacity-60"
        >
          <i className={applying ? "ri-loader-4-line animate-spin" : "ri-magic-line"}></i>
          {applying ? "正在写入原文…" : "将整改建议写入原文"}
        </button>
      )}
    </div>
  );
}

export default function IssuePanel({
  issues,
  groups,
  activeIssueId,
  filterHeading = null,
  applyingIssueId,
  anchoredIds,
  onIssueClick,
  onJumpAll,
  onClearFilter,
  onToggleResolved,
  onApplySuggestion,
}: IssuePanelProps) {
  const pending = issues.filter((i) => !i.resolved).length;
  const anchored = new Set(anchoredIds || []);
  const l3 = issues.filter((i) => i.level === "L3").length;
  const filtered = Boolean(filterHeading);

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-background-300 bg-background-100">
      <div className="border-b border-background-300 bg-background-50 px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0 flex items-center gap-2 text-sm font-medium text-foreground-800">
            <i className="ri-list-check-3 text-accent-500"></i>
            <span className="truncate">{filtered ? "本章节问题" : "发现问题清单"}</span>
          </div>
          <span className="font-label shrink-0 text-[11px] text-foreground-500">
            待处理 {pending} / 共 {issues.length}
            {l3 > 0 ? ` · L3 ${l3}` : ""}
            {` · 已锚定 ${anchored.size}`}
          </span>
        </div>
        {filtered ? (
          <div className="mt-2 flex items-start justify-between gap-2 rounded-md border border-primary-200 bg-primary-50/70 px-2 py-1.5">
            <p className="min-w-0 text-[11px] leading-relaxed text-primary-700">
              <span className="font-medium">当前章节</span>
              {`：${filterHeading}`}
            </p>
            <button
              type="button"
              onClick={onClearFilter}
              className="shrink-0 cursor-pointer whitespace-nowrap text-[11px] font-medium text-primary-600 hover:underline"
            >
              显示全部
            </button>
          </div>
        ) : (
          <p className="mt-2 text-[11px] leading-relaxed text-foreground-500">
            点击左侧目录，按该章及子节筛选问题。
          </p>
        )}
        <button
          type="button"
          onClick={onJumpAll}
          className="mt-2 flex w-full cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-3 py-1.5 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
        >
          <i className="ri-focus-3-line text-sm"></i>
          一键锚定全部问题章节
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2.5">
        {issues.length === 0 ? (
          <p className="rounded-lg border border-dashed border-background-300 bg-background-50 px-3 py-8 text-center text-sm text-foreground-500">
            {filtered ? "本章节没有预审问题。" : "本册暂无预审问题。"}
          </p>
        ) : (
          <div className="space-y-3">
            {groups.map((group) => (
              <div key={group.id}>
                <div className="mb-1.5 flex items-center gap-1.5 px-0.5">
                  <i className="ri-bookmark-line text-xs text-primary-500"></i>
                  <span className="min-w-0 truncate text-[11px] font-medium text-foreground-700">{group.heading}</span>
                  <span className="font-label shrink-0 rounded-full bg-background-200 px-1.5 text-[10px] text-foreground-500">
                    {group.issues.length}
                  </span>
                </div>
                <div className="space-y-2">
                  {group.issues.map((issue) => (
                    <IssueCard
                      key={issue.id}
                      issue={issue}
                      active={activeIssueId === issue.id}
                      resolved={!!issue.resolved}
                      anchored={anchored.has(issue.id)}
                      applying={applyingIssueId === issue.id}
                      onIssueClick={onIssueClick}
                      onToggleResolved={onToggleResolved}
                      onApplySuggestion={onApplySuggestion}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="border-t border-background-300 bg-background-50 px-4 py-2.5">
        <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-foreground-500">
          <i className="ri-lightbulb-flash-line mt-0.5 shrink-0 text-primary-500"></i>
          点击问题跳到正文（不落目录）。规则与建议均来自本册最新一轮 AI 预审；「写入原文」会按该条预审规则改写对应段落。勾选已修复并保存版本后，再进入二次评审。
        </p>
      </div>
    </div>
  );
}
