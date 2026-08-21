import { useRef, type RefObject } from "react";
import type { BidSection } from "@/mocks/bidDocument";
import type { PreReviewIssue } from "@/mocks/preReview";

interface BidWordDocProps {
  sections: BidSection[];
  issues: PreReviewIssue[];
  activeIssueId: string | null;
  editMode: boolean;
  zoom: number;
  onIssueClick: (issueId: string) => void;
  sectionRefs: RefObject<Record<string, HTMLDivElement | null>>;
}

const severityMark: Record<string, string> = {
  废标: "bg-accent-500/25 text-accent-800 ring-1 ring-accent-500/40",
  降档: "bg-accent-500/20 text-accent-700 ring-1 ring-accent-400/30",
  扣分: "bg-secondary-200/70 text-secondary-900 ring-1 ring-secondary-300/50",
  建议: "bg-primary-200/70 text-primary-800 ring-1 ring-primary-300/50",
};

const levelNum: Record<number, string> = {
  1: "font-heading text-lg font-semibold text-foreground-950",
  2: "text-[15px] font-semibold text-foreground-900",
  3: "text-sm font-semibold text-foreground-800",
};

const levelSize: Record<number, string> = {
  1: "text-lg",
  2: "text-[15px]",
  3: "text-sm",
};

function splitHighlight(text: string, highlight: string): string[] {
  if (!highlight) return [text];
  const parts = text.split(highlight);
  return parts;
}

export default function BidWordDoc({
  sections,
  issues,
  activeIssueId,
  editMode,
  zoom,
  onIssueClick,
  sectionRefs,
}: BidWordDocProps) {
  const focusRef = useRef<HTMLDivElement | null>(null);

  const issueMap = new Map(issues.map((i) => [i.id, i]));

  return (
    <div className="flex h-full items-start justify-center overflow-auto bg-background-200/50 px-6 py-8">
      <div
        ref={focusRef}
        className="h-full w-[760px] shrink-0 space-y-6 rounded-md border border-background-300 bg-background-50 p-12 shadow-none transition-transform duration-200"
        style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top center" }}
      >
        {sections.map((section) => (
          <div key={section.id} ref={(el) => { sectionRefs.current[section.id] = el; }}>
            <div className={`${levelNum[section.level]} mb-2`}>
              <span className={`${levelSize[section.level]} mr-1.5 inline-block align-middle font-heading text-foreground-700`}>
                {section.heading.includes("第") ? "" : ""}
              </span>
              {section.heading}
            </div>
            <div className="space-y-2.5">
              {section.paragraphs.map((para) => {
                const issue = para.problem ? issueMap.get(para.problem.issueId) : undefined;
                const isActive = para.problem && activeIssueId === para.problem.issueId;
                return (
                  <div
                    key={para.id}
                    contentEditable={editMode}
                    suppressContentEditableWarning
                    className={`text-sm leading-7 text-foreground-800 outline-none ${
                      editMode ? "cursor-text hover:bg-background-100/60" : "cursor-default"
                    }`}
                  >
                    {para.problem && issue ? (
                      (() => {
                        const parts = splitHighlight(para.text, para.problem.highlight);
                        return parts.map((part, idx) => (
                          <span key={idx}>
                            {part}
                            {idx < parts.length - 1 && (
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.preventDefault();
                                  onIssueClick(para.problem!.issueId);
                                }}
                                className={`mx-0.5 inline cursor-pointer whitespace-nowrap rounded px-0.5 font-medium transition-all ${severityMark[issue.severity]} ${
                                  isActive ? "ring-2 ring-primary-500 animate-pulse" : ""
                                }`}
                              >
                                {para.problem.highlight}
                              </button>
                            )}
                          </span>
                        ));
                      })()
                    ) : (
                      <span>{para.text}</span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}