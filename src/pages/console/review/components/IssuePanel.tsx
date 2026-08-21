import type { PreReviewIssue } from "@/mocks/preReview";

interface IssuePanelProps {
  issues: PreReviewIssue[];
  activeIssueId: string | null;
  onIssueClick: (issueId: string) => void;
  onJumpAll: () => void;
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

export default function IssuePanel({ issues, activeIssueId, onIssueClick, onJumpAll }: IssuePanelProps) {
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-background-300 bg-background-100">
      <div className="border-b border-background-300 bg-background-50 px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
            <i className="ri-list-check-3 text-accent-500"></i>
            发现问题清单
          </div>
          <span className="font-label text-[11px] text-foreground-500">{issues.length} 项</span>
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
            return (
              <button
                key={issue.id}
                type="button"
                onClick={() => onIssueClick(issue.id)}
                className={`w-full cursor-pointer rounded-lg border p-3 text-left transition-all duration-200 ${
                  active
                    ? "border-primary-300 bg-primary-50/70 ring-1 ring-primary-300"
                    : "border-background-300 bg-background-50 hover:border-background-400 hover:bg-background-50"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className={`inline-flex items-center whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${severityStyle[issue.severity]}`}>
                    {issue.severity}
                  </span>
                  <span className="font-label flex items-center gap-1 text-[10px] text-foreground-500">
                    <span className={`h-1.5 w-1.5 rounded-full ${dot[issue.severity]}`}></span>
                    {issue.location}
                  </span>
                </div>
                <p className={`mt-1.5 text-xs leading-relaxed ${active ? "text-primary-800" : "text-foreground-700"}`}>
                  「{issue.excerpt}」
                </p>
                <div className="mt-1.5 flex items-center justify-between">
                  <span className="text-[11px] text-foreground-500">建议：{issue.suggestion}</span>
                  <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md transition-all ${
                    active ? "bg-primary-500 text-background-50" : "bg-background-200 text-foreground-500"
                  }`}>
                    <i className="ri-corner-down-right-line text-xs"></i>
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </div>
      <div className="border-t border-background-300 bg-background-50 px-4 py-2.5">
        <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-foreground-500">
          <i className="ri-lightbulb-flash-line mt-0.5 shrink-0 text-primary-500"></i>
          点击问题可锚定到投标书正文对应章节并高亮命中句；「一键锚定」顺序定位全部问题位置。
        </p>
      </div>
    </div>
  );
}