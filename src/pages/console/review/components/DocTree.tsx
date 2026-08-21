import type { BidSection } from "@/lib/api";

interface DocTreeProps {
  sections: BidSection[];
  activeSectionId: string | null;
  activeIssueId: string | null;
  onSelectSection: (sectionId: string) => void;
}

interface SectionNode {
  section: BidSection;
  issueCount: number;
}

const levelPad: Record<number, string> = {
  1: "pl-2",
  2: "pl-6",
  3: "pl-9",
};

const levelBullet: Record<number, string> = {
  1: "bg-primary-500",
  2: "bg-primary-400",
  3: "bg-primary-300",
};

const levelText: Record<number, string> = {
  1: "text-sm font-semibold text-foreground-900",
  2: "text-[13px] font-medium text-foreground-800",
  3: "text-xs font-medium text-foreground-700",
};

export default function DocTree({ sections, activeSectionId, activeIssueId, onSelectSection }: DocTreeProps) {
  const tree: SectionNode[] = sections.map((section) => {
    let issueCount = 0;
    section.paragraphs.forEach((p) => {
      if (p.problem) issueCount += 1;
    });
    return { section, issueCount };
  });

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-background-300 bg-background-100">
      <div className="flex items-center justify-between border-b border-background-300 bg-background-50 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
          <i className="ri-bookmark-3-line text-primary-500"></i>
          文档目录
        </div>
        <span className="font-label text-[11px] text-foreground-500">{tree.length} 章</span>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        <div className="space-y-0.5">
          {tree.map(({ section, issueCount }) => {
            const active = activeSectionId === section.id;
            return (
              <button
                key={section.id}
                type="button"
                onClick={() => onSelectSection(section.id)}
                className={`flex w-full cursor-pointer items-center gap-2 rounded-md py-1.5 pr-2 text-left transition-all duration-200 ${levelPad[section.level]} ${
                  active ? "bg-primary-50/80 ring-1 ring-primary-200" : "hover:bg-background-200/70"
                }`}
              >
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${levelBullet[section.level]} ${active ? "ring-2 ring-primary-300/50" : ""}`} />
                <span className={`min-w-0 flex-1 truncate ${levelText[section.level]} ${active ? "text-primary-700" : ""}`}>
                  {section.heading}
                </span>
                {issueCount > 0 && (
                  <span
                    className={`font-label flex h-4 shrink-0 items-center whitespace-nowrap rounded-full px-1.5 text-[10px] font-semibold ${
                      active ? "bg-accent-500 text-background-50" : "bg-accent-100 text-accent-700"
                    }`}
                  >
                    {issueCount}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>
      <div className="border-t border-background-300 bg-background-50 px-4 py-2.5">
        <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-foreground-500">
          <i className="ri-map-pin-2-line mt-0.5 shrink-0 text-primary-500"></i>
          点击章节锚定到编辑区对应位置；数字为该章节待整改问题数。
        </p>
      </div>
    </div>
  );
}