import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { renderAsync } from "docx-preview";
import { downloadBidDocumentFile, type BidSection } from "@/lib/api";
import { sourceVisibleText, visibleNeedles } from "@/lib/excerpt";
import type { PreReviewIssue } from "@/mocks/preReview";

/* 修改闭环只读预览：直接打开本册已上传的商务标/技术标源文件。
 * docx 用 docx-preview（含图/表）；PDF 用浏览器内嵌。不再语义重建。
 */

export interface BidDocxViewerHandle {
  scrollToSection: (sectionId: string) => boolean;
  scrollToIssue: (issueId: string) => boolean;
}

interface BidDocxViewerProps {
  bidDocumentId: string;
  sections: BidSection[];
  issues: PreReviewIssue[];
  fileName?: string;
  active?: boolean;
  onAnchored?: (issueIds: string[]) => void;
  onIssueChapters?: (issueSections: Record<string, string>) => void;
}

function isPdfBlob(blob: Blob | null, fileName?: string): boolean {
  if ((fileName || "").toLowerCase().endsWith(".pdf")) return true;
  return (blob?.type || "").toLowerCase().includes("pdf");
}

const zoomOptions = [75, 90, 100, 125, 150];

const severityBg: Record<string, string> = {
  废标: "rgba(255,77,79,0.30)",
  降档: "rgba(255,140,0,0.28)",
  扣分: "rgba(245,178,0,0.30)",
  建议: "rgba(40,120,255,0.22)",
};

function normalize(s: string): string {
  return (s || "").replace(/\s+/g, "");
}

const TOC_DOTS = /[.．…·]{3,}\s*\d{1,4}\s*$/;
const TOC_PAGE_TAIL = /\s+\d{1,4}\s*$/;

function isTocNode(el: HTMLElement): boolean {
  const t = (el.textContent || "").replace(/\s+/g, " ").trim();
  if (!t) return false;
  const compact = t.replace(/\s+/g, "");
  if (compact === "目录" || (compact.startsWith("目录") && compact.length <= 8)) return true;
  if (TOC_DOTS.test(t)) return true;
  if (TOC_PAGE_TAIL.test(t) && !t.includes("。") && t.length <= 64) {
    const head = t.replace(TOC_PAGE_TAIL, "").trim();
    if (/^第[0-9一二三四五六七八九十百零]+[章节篇]/.test(head) || /^\d+\.\d+/.test(head) || /^[一二三四五六七八九十]+、/.test(head)) {
      return true;
    }
  }
  return false;
}

function tagRank(el: HTMLElement): number {
  const tag = el.tagName;
  if (/^H[1-6]$/.test(tag) || tag === "P") return 2;
  if (tag === "LI") return 1;
  return 0;
}

function isScoreIndexTable(table: HTMLElement): boolean {
  const blob = (table.textContent || "").replace(/\s+/g, "");
  if (/详细评审索引|评审索引表/.test(blob)) return true;
  return /评分标准/.test(blob) && /应答文件|分值|评分项/.test(blob);
}

function inScoreIndex(el: HTMLElement): boolean {
  const table = el.closest("table");
  return !!table && isScoreIndexTable(table);
}

function isIndexBlob(text: string): boolean {
  const t = text || "";
  if (/评分标准|应答文件|详细评审索引|评审索引表|评分项/.test(t)) return true;
  return (t.match(/认证证书/g) || []).length >= 2;
}

function matchScore(el: HTMLElement, needleNorm: string): number {
  const raw = (el.textContent || "").replace(/\s+/g, " ").trim();
  const n = normalize(raw);
  if (!n || (!n.includes(needleNorm) && n !== needleNorm)) return -1;
  if (isTocNode(el) || inScoreIndex(el) || isIndexBlob(raw)) return -1;
  let score = 0;
  if (n === needleNorm) score += 80;
  else {
    const extra = n.length - needleNorm.length;
    if (extra > 24) score -= 20;
    score += Math.max(0, 40 - extra);
  }
  if (/^\d+(?:\.\d+)+/.test(raw)) score += 25;
  score += tagRank(el);
  return score;
}

function issueChaptersFromDom(
  issues: PreReviewIssue[],
  sections: BidSection[],
  anchorMap: Record<string, HTMLElement>,
): Record<string, string> {
  const heads = sections
    .map((s) => ({ id: s.id, el: anchorMap[s.id] }))
    .filter((x): x is { id: string; el: HTMLElement } => !!x.el)
    .sort((a, b) => {
      const pos = a.el.compareDocumentPosition(b.el);
      if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
      if (pos & Node.DOCUMENT_POSITION_PRECEDING) return 1;
      return 0;
    });
  const out: Record<string, string> = {};
  for (const issue of issues) {
    const el = anchorMap[issue.id];
    if (!el) continue;
    let last = "";
    for (const h of heads) {
      if (h.el === el) {
        last = h.id;
        break;
      }
      const pos = h.el.compareDocumentPosition(el);
      if (pos & Node.DOCUMENT_POSITION_FOLLOWING || pos & Node.DOCUMENT_POSITION_CONTAINED_BY) {
        last = h.id;
      }
    }
    if (last) out[issue.id] = last;
  }
  return out;
}

function pickTitle(blocks: HTMLElement[], needle: string, used: Set<HTMLElement>, allowIndex = false): HTMLElement | undefined {
  const needleNorm = normalize(needle);
  if (needleNorm.length < 4) return undefined;
  let hit: HTMLElement | undefined;
  let best = -1;
  for (const el of blocks) {
    if (used.has(el)) continue;
    if (!allowIndex && (isTocNode(el) || inScoreIndex(el))) continue;
    const score = matchScore(el, needleNorm);
    if (score < 0) continue;
    if (score > best || score === best) {
      hit = el;
      best = score;
    }
  }
  return hit;
}

const BidDocxViewer = forwardRef<BidDocxViewerHandle, BidDocxViewerProps>(function BidDocxViewer(
  { bidDocumentId, sections, issues, fileName, active = true, onAnchored, onIssueChapters },
  ref,
) {
  const [zoom, setZoom] = useState(100);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [fileBlob, setFileBlob] = useState<Blob | null>(null);
  const [pdfUrl, setPdfUrl] = useState("");
  const [rendering, setRendering] = useState(false);
  const hostRef = useRef<HTMLDivElement>(null);
  const anchorMapRef = useRef<Record<string, HTMLElement>>({});

  useEffect(() => {
    if (!bidDocumentId) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    setFileBlob(null);
    downloadBidDocumentFile(bidDocumentId)
      .then((blob) => {
        if (!cancelled) setFileBlob(blob);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "投标文件原文加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [bidDocumentId]);

  const pdfMode = isPdfBlob(fileBlob, fileName);

  useEffect(() => {
    if (!fileBlob || !pdfMode) {
      setPdfUrl("");
      return;
    }
    const url = URL.createObjectURL(fileBlob);
    setPdfUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [fileBlob, pdfMode]);

  useEffect(() => {
    if (!active || loading || error || !fileBlob || pdfMode) return;
    const host = hostRef.current;
    if (!host) return;
    let cancelled = false;
    setRendering(true);
    host.innerHTML = "";
    renderAsync(fileBlob, host, undefined, {
      className: "bidrev-docx",
      inWrapper: true,
      ignoreWidth: false,
      ignoreImages: false,
      useBase64URL: true,
      breakPages: true,
      renderHeaders: true,
      renderFooters: true,
    })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "投标文件原文渲染失败");
      })
      .finally(() => {
        if (!cancelled) setRendering(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fileBlob, loading, error, active, pdfMode]);

  /* 渲染完成后：把预审问题句 / 章节标题定位到真实 DOM 节点上——原文原样渲染，
   * 不重建结构，靠文本包含关系反查节点。问题优先于目录标题；章节标题不占用问题节点。 */
  useEffect(() => {
    if (loading || rendering || error) return;
    const host = hostRef.current;
    if (!host) return;
    host.querySelectorAll<HTMLElement>("[data-issue-id]").forEach((el) => {
      el.removeAttribute("data-issue-id");
      el.removeAttribute("data-issue-severity");
      el.style.removeProperty("--issue-bg");
    });

    const anchorMap: Record<string, HTMLElement> = {};
    const blocks = Array.from(
      host.querySelectorAll<HTMLElement>("p, h1, h2, h3, h4, h5, h6, li, td"),
    );
    const usedIssues = new Set<HTMLElement>();
    const highlightByIssue = new Map<string, string>();
    sections.forEach((section) => {
      section.paragraphs.forEach((para) => {
        if (para.problem?.issueId && para.problem.highlight) {
          highlightByIssue.set(para.problem.issueId, para.problem.highlight);
        }
      });
    });

    const locate = (needles: string[]): HTMLElement | undefined => {
      for (const needle of needles) {
        const exact = pickTitle(blocks, needle, usedIssues, false);
        if (exact && normalize(exact.textContent || "") === normalize(needle)) return exact;
      }
      for (const needle of needles) {
        const hit = pickTitle(blocks, needle, usedIssues, false);
        if (hit) return hit;
      }
      for (const needle of needles) {
        const hit = pickTitle(blocks, needle, usedIssues, true);
        if (hit) return hit;
      }
      return undefined;
    };

    issues.forEach((issue) => {
      const needles = visibleNeedles(issue.excerpt, issue.location);
      const visible = sourceVisibleText(issue.excerpt, issue.location);
      const hl = highlightByIssue.get(issue.id) || "";
      if (visible && !needles.includes(visible)) needles.unshift(visible);
      if (hl && !hl.includes("【附图") && !isIndexBlob(hl)) {
        const visLen = (visible || needles[0] || "").replace(/\s+/g, "").length;
        if (!visLen || hl.replace(/\s+/g, "").length <= visLen + 12) needles.unshift(hl);
      }
      const target = locate(needles);
      if (!target) return;
      usedIssues.add(target);
      anchorMap[issue.id] = target;
      const severity = issue.severity || "建议";
      target.setAttribute("data-issue-id", issue.id);
      target.setAttribute("data-issue-severity", severity);
      target.style.setProperty("--issue-bg", severityBg[severity] || severityBg.建议);
    });

    sections.forEach((section) => {
      const headingNeedle = normalize(section.heading);
      if (!headingNeedle || section.heading === "文档开头") return;
      const headingTarget = [...blocks]
        .reverse()
        .find((el) => !isTocNode(el) && normalize(el.textContent || "") === headingNeedle);
      if (headingTarget) anchorMap[section.id] = headingTarget;
    });

    anchorMapRef.current = anchorMap;
    onAnchored?.(issues.filter((issue) => anchorMap[issue.id]).map((issue) => issue.id));
    onIssueChapters?.(issueChaptersFromDom(issues, sections, anchorMap));
  }, [loading, rendering, error, sections, issues, onAnchored, onIssueChapters]);

  const scrollToKey = useCallback((key: string): boolean => {
    const el = anchorMapRef.current[key];
    if (!el) return false;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("issue-flash");
    window.setTimeout(() => el.classList.remove("issue-flash"), 3400);
    return true;
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      scrollToSection: (sectionId: string) => scrollToKey(sectionId),
      scrollToIssue: (issueId: string) => scrollToKey(issueId),
    }),
    [scrollToKey],
  );

  const displayName = fileName || "投标书原文.docx";

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex flex-wrap items-center gap-1 border-b border-background-300 bg-background-100 px-2.5 py-1.5">
        <select
          value={zoom}
          onChange={(e) => setZoom(Number(e.target.value))}
          className="h-7 cursor-pointer rounded border border-background-300 bg-background-50 px-1.5 text-xs text-foreground-700 outline-none"
        >
          {zoomOptions.map((z) => (
            <option key={z} value={z}>
              {z}%
            </option>
          ))}
        </select>
        <span className="ml-auto flex items-center gap-1 text-[11px] text-primary-600">
          <i className={pdfMode ? "ri-file-pdf-2-line" : "ri-file-word-2-line"}></i>
          {pdfMode ? "按上传的 PDF 源文件预览" : "按上传的 Word 源文件预览（含图、表）"}
        </span>
      </div>
      <div className="relative flex-1 overflow-auto bg-background-200/50 px-4 py-5">
        {(loading || rendering) && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-background-200/80 text-sm text-foreground-500">
            <i className="ri-loader-4-line mr-1.5 animate-spin"></i>
            正在按原文样式渲染投标书…
          </div>
        )}
        {error && !loading ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-sm text-foreground-500">
            <i className="ri-file-warning-line text-2xl text-accent-500"></i>
            {error}
          </div>
        ) : pdfMode && pdfUrl ? (
          <iframe
            title={displayName}
            src={pdfUrl}
            className="h-full min-h-[640px] w-full border-0 bg-background-50"
          />
        ) : (
          <div
            className="mx-auto w-fit origin-top"
            style={{ transform: `scale(${zoom / 100})`, visibility: rendering || loading ? "hidden" : "visible" }}
          >
            <div ref={hostRef} className="bidrev-docx-host" />
          </div>
        )}
      </div>
      <div className="flex items-center justify-between border-t border-background-300 bg-background-100 px-4 py-1.5 text-[11px] text-foreground-500">
        <span className="flex min-w-0 items-center gap-1 truncate">
          <i className="ri-file-word-2-line text-primary-500"></i>
          {displayName}
        </span>
        <span>本册源文件</span>
      </div>
    </div>
  );
});

export default BidDocxViewer;

BidDocxViewer.displayName = "BidDocxViewer";
