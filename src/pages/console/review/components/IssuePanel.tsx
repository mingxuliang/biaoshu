import type { PreReviewIssue } from "@/mocks/preReview";

interface IssuePanelProps {
  issues: PreReviewIssue[];
  activeIssueId: string | null;
  applyingIssueId?: string | null;
  anchoredIds?: string[];
  onIssueClick: (issueId: string) => void;
  onJumpAll: () => void;
  onToggleResolved?: (issueId: string, resolved: boolean) => void;
  onApplySuggestion?: (issueId: string) => void;
}

const severityStyle: Record<string, string> = {
  废标: "bg-accent-50 text-accent-600 border-accent-200",
  降档: "bg-accent-50 text-accent-600 border-accent-200",
  扣分: "bg-secondary-100 text-secondary-600 border-secondary-200",
  建议: "bg-primary-50 text-primary-600 border-primary-200",
};

const dot: Record<string, string> = {
  废标: "bg-accent-500",
  降档: "bg-accent-400",
  扣分: "bg-secondary-500",
  建议: "bg-primary-500",
};

export default function IssuePanel({
  issues,
  activeIssueId,
  applyingIssueId,
  anchoredIds,
  onIssueClick,
  onJumpAll,
  onToggleResolved,
  onApplySuggestion,
}: IssuePanelProps) {
  const pending = issues.filter((i) => !i.resolved).length;
  const anchored = new Set(anchoredIds || []);
  const l3 = issues.filter((i) => i.level === "L3").length;

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-background-300 bg-background-100">
      <div className="border-b border-background-300 bg-background-50 px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
            <i className="ri-list-check-3 text-accent-500"></i>
            发现问题清单
          </div>
          <span className="font-label text-[11px] text-foreground-500">
            待处理 {pending} / 共 {issues.length}
            {l3 > 0 ? ` · L3 ${l3}` : ""}
            {` · 已锚定 ${anchored.size}`}
          </span>
        </div>
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
        <div className="space-y-2">
          {issues.map((issue) => {
            const active = activeIssueId === issue.id;
            const resolved = !!issue.resolved;
            return (
              <div
                key={issue.id}
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
                        {anchored.has(issue.id) ? (
                          <span className="inline-flex items-center whitespace-nowrap rounded-md border border-primary-200 bg-primary-50 px-1.5 py-0.5 text-[10px] text-primary-600">
                            已锚定
                          </span>
                        ) : (
                          <span className="inline-flex items-center whitespace-nowrap rounded-md border border-background-300 bg-background-100 px-1.5 py-0.5 text-[10px] text-foreground-500">
                            未锚定
                          </span>
                        )}
                      </span>
                      <span className="font-label flex items-center gap-1 text-[10px] text-foreground-500">
                        <span className={`h-1.5 w-1.5 rounded-full ${dot[issue.severity]}`}></span>
                        {issue.location}
                        {resolved && <span className="text-primary-600">已修复</span>}
                      </span>
                    </div>
                    <p className={`mt-1.5 text-xs leading-relaxed ${resolved ? "text-foreground-400 line-through" : active ? "text-primary-800" : "text-foreground-700"}`}>
                      「{issue.excerpt}」
                    </p>
                    {(issue.strategyCategory || issue.strategyPoint) && (
                      <div className="mt-1.5 rounded border border-primary-100 bg-primary-50/70 px-1.5 py-1 text-[10px] leading-relaxed text-primary-700">
                        <span className="font-medium">预审规则 · 高分策略 · {issue.strategyCategory || "高分条款"}</span>
                        {issue.strategyPoint ? `：${issue.strategyPoint}` : ""}
                        {issue.strategyClauses && issue.strategyClauses.length > 0 ? (
                          <span className="block text-primary-600/90">条款：{issue.strategyClauses.slice(0, 3).join("；")}</span>
                        ) : null}
                        <span className="block">按此写法可拿高分</span>
                      </div>
                    )}
                    <div className="mt-1.5 text-[11px] leading-relaxed text-foreground-500">
                      建议：{issue.suggestion}
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
                    disabled={applyingIssueId === issue.id}
                    onClick={(e) => {
                      e.stopPropagation();
                      onApplySuggestion(issue.id);
                    }}
                    className="mt-2 flex w-full cursor-pointer items-center justify-center gap-1 rounded-md border border-primary-200 bg-primary-50 px-2 py-1 text-[11px] font-medium text-primary-600 transition-colors hover:bg-primary-100 disabled:cursor-wait disabled:opacity-60"
                  >
                    <i className={applyingIssueId === issue.id ? "ri-loader-4-line animate-spin" : "ri-magic-line"}></i>
                    {applyingIssueId === issue.id ? "正在写入原文…" : "将整改建议写入原文"}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </div>
      <div className="border-t border-background-300 bg-background-50 px-4 py-2.5">
        <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-foreground-500">
          <i className="ri-lightbulb-flash-line mt-0.5 shrink-0 text-primary-500"></i>
          点击问题跳到正文（不落目录）。建议已标明高分策略条款；「写入原文」会按该条款改写对应段落。勾选已修复并保存版本后，再进入二次评审。
        </p>
      </div>
    </div>
  );
}
