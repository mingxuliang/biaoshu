import type { BidSection } from "@/lib/api";
import type { PreReviewIssue } from "@/mocks/preReview";
import { issueChapter, visibleNeedles } from "@/lib/excerpt";

/** 未能落到目录章节的问题，单独成组，可从左侧点选。 */
export const UNASSIGNED_SECTION_ID = "__unassigned__";
export const UNASSIGNED_HEADING = "未分章 / 全篇";

export interface IssueChapterGroup {
  id: string;
  heading: string;
  issues: PreReviewIssue[];
}

function norm(s: string): string {
  return (s || "").replace(/\s+/g, "");
}

export function descendantSectionIds(sections: BidSection[], sectionId: string): Set<string> {
  if (sectionId === UNASSIGNED_SECTION_ID) return new Set([UNASSIGNED_SECTION_ID]);
  const idx = sections.findIndex((s) => s.id === sectionId);
  if (idx < 0) return new Set();
  const ids = new Set([sectionId]);
  const level = sections[idx].level;
  for (let i = idx + 1; i < sections.length; i++) {
    if (sections[i].level <= level) break;
    ids.add(sections[i].id);
  }
  return ids;
}

function usableSections(sections: BidSection[]): BidSection[] {
  const indexHead = /详细评审索引|评审索引表/;
  return sections.filter((s) => {
    const heading = (s.heading || "").trim();
    return heading && heading !== "文档开头" && !indexHead.test(heading);
  });
}

/** 给每条预审问题挂上左侧目录的 sectionId。优先已存章节，其次段落锚定，再按原文/标题匹配。 */
export function assignIssuesToSections(issues: PreReviewIssue[], sections: BidSection[]): Record<string, string> {
  const map: Record<string, string> = {};
  const usable = usableSections(sections);
  const indexHead = /详细评审索引|评审索引表/;

  for (const issue of issues) {
    if (issue.sectionId && sections.some((s) => s.id === issue.sectionId)) {
      map[issue.id] = issue.sectionId;
    }
  }

  for (const s of sections) {
    if (indexHead.test(s.heading || "")) continue;
    for (const p of s.paragraphs || []) {
      const iid = p.problem?.issueId;
      if (iid && !map[iid]) map[iid] = s.id;
    }
  }

  for (const issue of issues) {
    if (map[issue.id]) continue;
    const needles = visibleNeedles(issue.excerpt, issue.location)
      .map(norm)
      .filter((n) => n.length >= 8);
    if (!needles.length) continue;
    let bestId = "";
    let best = 0;
    for (const s of usable) {
      const blob = norm(s.heading + (s.paragraphs || []).map((p) => p.text || "").join(""));
      for (const n of needles) {
        if (blob.includes(n) && n.length > best) {
          best = n.length;
          bestId = s.id;
        }
      }
    }
    if (bestId) map[issue.id] = bestId;
  }

  for (const issue of issues) {
    if (map[issue.id]) continue;
    const chap = norm(issue.chapter || issueChapter(issue.location) || issue.location || "");
    if (chap.length < 2) continue;
    let bestId = "";
    let best = -1;
    for (const s of usable) {
      const heading = norm(s.heading);
      if (!heading) continue;
      let score = -1;
      if (heading === chap) score = 5;
      else if (heading.endsWith(chap) || chap.endsWith(heading)) score = 4;
      else if (heading.includes(chap)) score = 3;
      else if (chap.includes(heading) && heading.length >= 6) score = 2;
      if (score > best) {
        best = score;
        bestId = s.id;
      }
    }
    if (bestId) map[issue.id] = bestId;
  }

  for (const issue of issues) {
    if (!map[issue.id]) map[issue.id] = UNASSIGNED_SECTION_ID;
  }
  return map;
}

export function headingBySectionId(sections: BidSection[]): Record<string, string> {
  const out: Record<string, string> = { [UNASSIGNED_SECTION_ID]: UNASSIGNED_HEADING };
  for (const s of sections) out[s.id] = s.heading || UNASSIGNED_HEADING;
  return out;
}

export function groupIssuesByChapter(
  issues: PreReviewIssue[],
  sections: BidSection[],
  issueSectionMap: Record<string, string>,
): IssueChapterGroup[] {
  const headings = headingBySectionId(sections);
  const buckets = new Map<string, PreReviewIssue[]>();
  for (const issue of issues) {
    const sid = issueSectionMap[issue.id] || UNASSIGNED_SECTION_ID;
    const list = buckets.get(sid) || [];
    list.push(issue);
    buckets.set(sid, list);
  }
  const order = [...sections.map((s) => s.id), UNASSIGNED_SECTION_ID];
  return order
    .filter((id) => (buckets.get(id) || []).length > 0)
    .map((id) => ({
      id,
      heading: headings[id] || UNASSIGNED_HEADING,
      issues: buckets.get(id) || [],
    }));
}

/** 目录角标：本章 + 子节未修复问题数。 */
export function pendingCountBySection(
  issues: PreReviewIssue[],
  sections: BidSection[],
  issueSectionMap: Record<string, string>,
): Record<string, number> {
  const own: Record<string, number> = {};
  for (const issue of issues) {
    if (issue.resolved) continue;
    const sid = issueSectionMap[issue.id] || UNASSIGNED_SECTION_ID;
    own[sid] = (own[sid] || 0) + 1;
  }
  const out: Record<string, number> = {};
  for (const s of sections) {
    const ids = descendantSectionIds(sections, s.id);
    out[s.id] = [...ids].reduce((n, id) => n + (own[id] || 0), 0);
  }
  out[UNASSIGNED_SECTION_ID] = own[UNASSIGNED_SECTION_ID] || 0;
  return out;
}

export function filterIssuesForSection(
  issues: PreReviewIssue[],
  sections: BidSection[],
  issueSectionMap: Record<string, string>,
  sectionId: string | null,
): PreReviewIssue[] {
  if (!sectionId) return issues;
  const ids = descendantSectionIds(sections, sectionId);
  return issues.filter((issue) => ids.has(issueSectionMap[issue.id] || UNASSIGNED_SECTION_ID));
}
