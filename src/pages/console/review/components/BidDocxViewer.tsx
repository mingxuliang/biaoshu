import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { renderAsync } from "docx-preview";
import { downloadBidDocumentFile, type BidSection } from "@/lib/api";
import type { PreReviewIssue } from "@/mocks/preReview";

/* 修改闭环的「原文预览」：不做语义重建，直接用 docx-preview 把投标书原始 .docx
 * 渲染成 HTML（字体/字号/缩进/对齐/表格/图片/页眉页脚与 Word 打开效果一致），
 * problem 高亮和跳转直接定位到这份真实渲染出来的 DOM 节点上。
 * 与可编辑的 WordEditor 是同一份 sections 数据的两种呈现：这里只读、保真度最高；
 * WordEditor 语义重建、保真度较低但可编辑保存。两者按「编辑/预览」开关切换展示。
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

const BidDocxViewer = forwardRef<BidDocxViewerHandle, BidDocxViewerProps>(function BidDocxViewer(
  { bidDocumentId, sections, issues, fileName, active = true },
  ref,
) {
  const [zoom, setZoom] = useState(100);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [fileBlob, setFileBlob] = useState<Blob | null>(null);
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

  useEffect(() => {
    if (!active || loading || error || !fileBlob) return;
    const host = hostRef.current;
    if (!host) return;
    let cancelled = false;
    setRendering(true);
    host.innerHTML = "";
    renderAsync(fileBlob, host, undefined, {
      className: "bidrev-docx",
      inWrapper: true,
      ignoreWidth: false,
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
  }, [fileBlob, loading, error, active]);

  /* 渲染完成后：把预审问题句 / 章节标题定位到真实 DOM 节点上——原文原样渲染，
   * 不重建结构，靠文本包含关系反查节点（与后端 anchor_findings 思路一致）。 */
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
    const used = new Set<HTMLElement>();
    const issueMap = new Map(issues.map((i) => [i.id, i]));

    sections.forEach((section) => {
      const headingTarget = blocks.find(
        (el) => !used.has(el) && normalize(el.textContent || "") === normalize(section.heading),
      );
      if (headingTarget) {
        anchorMap[section.id] = headingTarget;
        used.add(headingTarget);
      }

      section.paragraphs.forEach((para) => {
        if (!para.problem) return;
        const needle = normalize(para.problem.highlight);
        if (!needle) return;
        const target = blocks.find(
          (el) => !used.has(el) && normalize(el.textContent || "").includes(needle),
        );
        if (!target) return;
        used.add(target);
        anchorMap[para.problem.issueId] = target;
        const issue = issueMap.get(para.problem.issueId);
        const severity = issue?.severity || "建议";
        target.setAttribute("data-issue-id", para.problem.issueId);
        target.setAttribute("data-issue-severity", severity);
        target.style.setProperty("--issue-bg", severityBg[severity] || severityBg.建议);
      });
    });
    anchorMapRef.current = anchorMap;
  }, [loading, rendering, error, sections, issues]);

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
          <i className="ri-file-word-2-line"></i>
          按上传投标书原文排版（含一/二级标题）
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
        <span>上传投标书原文</span>
      </div>
    </div>
  );
});

export default BidDocxViewer;

BidDocxViewer.displayName = "BidDocxViewer";
