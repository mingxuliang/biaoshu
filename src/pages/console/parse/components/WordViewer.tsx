import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { renderAsync } from "docx-preview";
import {
  downloadTenderDocument,
  getTenderParagraphs,
  triggerFileDownload,
  type TenderParagraph,
} from "@/lib/api";

interface WordViewerProps {
  projectName: string;
  projectCode: string;
  tenderDocumentId: string;
  fileName?: string;
  paragraphs?: TenderParagraph[];
  anchorIndex?: number | null;
}

export interface WordViewerHandle {
  scrollToIndex: (index: number) => void;
}

const zoomOptions = [75, 90, 100, 125, 150];

const WordViewer = forwardRef<WordViewerHandle, WordViewerProps>(function WordViewer(
  { projectName, projectCode, tenderDocumentId, fileName, paragraphs: paragraphsProp, anchorIndex = null },
  ref,
) {
  const [zoom, setZoom] = useState(100);
  const [searchQuery, setSearchQuery] = useState("");
  const [paragraphs, setParagraphs] = useState<TenderParagraph[]>(paragraphsProp ?? []);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [fileBlob, setFileBlob] = useState<Blob | null>(null);
  const [rendering, setRendering] = useState(false);
  const [pdfUrl, setPdfUrl] = useState("");
  const hostRef = useRef<HTMLDivElement>(null);

  const displayName = fileName || projectName || projectCode || "招标文件.docx";
  const isPdf = /\.pdf$/i.test(displayName) || fileBlob?.type === "application/pdf";

  useEffect(() => {
    if (paragraphsProp) setParagraphs(paragraphsProp);
  }, [paragraphsProp]);

  useEffect(() => {
    if (!tenderDocumentId) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    setFileBlob(null);

    Promise.all([
      downloadTenderDocument(tenderDocumentId),
      getTenderParagraphs(tenderDocumentId).catch(() => [] as TenderParagraph[]),
    ])
      .then(([blob, paras]) => {
        if (cancelled) return;
        setFileBlob(blob);
        if (!paragraphsProp) setParagraphs(paras);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "招标文件原文加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [tenderDocumentId]);

  // PDF：走浏览器原生 PDF 渲染，仅需生成 objectURL；docx：走 docx-preview 渲染到 host。
  useEffect(() => {
    if (loading || error || !fileBlob) return;
    if (!isPdf) {
      setPdfUrl("");
      return;
    }
    const url = URL.createObjectURL(fileBlob);
    setPdfUrl(url);
    return () => {
      URL.revokeObjectURL(url);
    };
  }, [fileBlob, loading, error, isPdf]);

  useEffect(() => {
    if (loading || error || !fileBlob || isPdf) return;
    const host = hostRef.current;
    if (!host) return;
    let cancelled = false;
    setRendering(true);
    host.innerHTML = "";
    renderAsync(fileBlob, host, undefined, {
      className: "tender-docx",
      inWrapper: true,
      ignoreWidth: false,
      breakPages: true,
      renderHeaders: true,
      renderFooters: true,
    })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "招标文件原文渲染失败");
      })
      .finally(() => {
        if (!cancelled) setRendering(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fileBlob, loading, error, isPdf]);

  const clearHits = () => {
    hostRef.current?.querySelectorAll("[data-tender-hit]").forEach((el) => {
      el.removeAttribute("data-tender-hit");
    });
  };

  const markHits = (query: string) => {
    if (isPdf) return 0;
    const root = hostRef.current;
    if (!root) return 0;
    clearHits();
    const q = query.trim().toLowerCase();
    if (!q) return 0;
    let n = 0;
    root.querySelectorAll("p, h1, h2, h3, h4, h5, li, td, span").forEach((el) => {
      if ((el.textContent || "").toLowerCase().includes(q)) {
        el.setAttribute("data-tender-hit", "1");
        n += 1;
      }
    });
    const first = root.querySelector("[data-tender-hit='1']");
    first?.scrollIntoView({ behavior: "smooth", block: "center" });
    return n;
  };

  const scrollToIndex = useCallback((index: number) => {
    if (isPdf) return;
    const para = paragraphs.find((p) => p.index === index);
    const root = hostRef.current;
    if (!root || !para?.text) return;
    const needle = para.text.replace(/\s+/g, "").slice(0, 24);
    if (!needle) return;
    const nodes = root.querySelectorAll("p, h1, h2, h3, h4, h5, li, td");
    for (const el of nodes) {
      const compact = (el.textContent || "").replace(/\s+/g, "");
      if (compact.includes(needle)) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.setAttribute("data-tender-flash", "1");
        window.setTimeout(() => el.removeAttribute("data-tender-flash"), 2800);
        return;
      }
    }
  }, [paragraphs, isPdf]);

  useImperativeHandle(ref, () => ({ scrollToIndex }), [scrollToIndex]);

  useEffect(() => {
    if (anchorIndex == null || loading) return;
    const timer = window.setTimeout(() => scrollToIndex(anchorIndex), 120);
    return () => window.clearTimeout(timer);
  }, [anchorIndex, loading, scrollToIndex]);

  useEffect(() => {
    if (loading || isPdf) return;
    markHits(searchQuery);
  }, [searchQuery, loading, isPdf]);

  const downloadName = /\.(docx|pdf)$/i.test(displayName) ? displayName : `${displayName}${isPdf ? ".pdf" : ".docx"}`;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-background-300 bg-background-100">
      <div className="flex flex-wrap items-center gap-1 border-b border-background-300 bg-background-50 px-2.5 py-1.5">
        {!isPdf && (
          <>
            <select
              value={zoom}
              onChange={(e) => setZoom(Number(e.target.value))}
              className="h-8 cursor-pointer rounded border border-background-300 bg-background-50 px-1.5 text-xs text-foreground-700 outline-none"
            >
              {zoomOptions.map((z) => (
                <option key={z} value={z}>
                  {z}%
                </option>
              ))}
            </select>
            <span className="mx-1 h-4 w-px bg-background-300" />
          </>
        )}
        {fileBlob && (
          <button
            type="button"
            onClick={() => triggerFileDownload(fileBlob, downloadName)}
            className="flex h-8 cursor-pointer items-center gap-1 rounded border border-background-300 bg-background-50 px-2 text-xs text-foreground-700 hover:bg-background-100"
          >
            <i className="ri-download-2-line"></i>
            下载原文件
          </button>
        )}
        {isPdf ? (
          <span className="ml-auto flex items-center gap-1 text-[11px] text-primary-600">
            <i className="ri-lock-2-line"></i>只读预览 · PDF 由浏览器原生渲染，缩放/搜索请使用其自带工具栏
          </span>
        ) : (
          <div className="relative ml-auto flex items-center gap-2">
            <i className="ri-search-line absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-foreground-400"></i>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索文档内容…"
              className="h-8 w-44 rounded-md border border-background-300 bg-background-50 pl-8 pr-3 text-xs text-foreground-700 outline-none transition-all focus:w-56 focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-400"
            />
            <span className="flex items-center gap-1 text-[11px] text-primary-600">
              <i className="ri-lock-2-line"></i>只读预览
            </span>
          </div>
        )}
      </div>

      <div className={`relative flex-1 overflow-auto bg-background-200/50 ${isPdf ? "" : "px-4 py-5 md:px-6"}`}>
        {(loading || rendering) && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-background-200/80 text-sm text-foreground-500">
            <i className="ri-loader-4-line mr-1.5 animate-spin"></i>
            正在加载招标文件原文…
          </div>
        )}
        {error && !loading ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-sm text-foreground-500">
            <i className="ri-file-warning-line text-2xl text-accent-500"></i>
            {error}
          </div>
        ) : isPdf ? (
          pdfUrl && (
            <iframe
              src={pdfUrl}
              title="招标文件 PDF 预览"
              className="h-full w-full border-0"
              style={{ visibility: loading ? "hidden" : "visible" }}
            />
          )
        ) : (
          <div
            className="mx-auto w-fit origin-top"
            style={{ transform: `scale(${zoom / 100})`, visibility: rendering || loading ? "hidden" : "visible" }}
          >
            <div ref={hostRef} className="tender-docx-host" />
          </div>
        )}
      </div>

      <div className="flex items-center justify-between border-t border-background-300 bg-background-100 px-4 py-1.5 text-[11px] text-foreground-500">
        <span className="flex min-w-0 items-center gap-1 truncate">
          <i className={`${isPdf ? "ri-file-pdf-2-line" : "ri-file-word-2-line"} text-primary-500`}></i>
          {displayName}
        </span>
        <span>上传的原{isPdf ? " PDF" : " Word"}文档</span>
      </div>
    </div>
  );
});

export default WordViewer;

WordViewer.displayName = "WordViewer";
