import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { renderAsync } from "docx-preview";
import {
  downloadTenderDocument,
  getTenderParagraphs,
  getTenderPreviewMeta,
  triggerFileDownload,
  type TenderParagraph,
} from "@/lib/api";
import AuthImage from "../../components/AuthImage";
import { isDocxFile, isImageFile, isPdfFile, isSpreadsheetFile, ensureBlobMime } from "@/lib/tenderPackage";

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
  const [pdfPages, setPdfPages] = useState(0);
  const [visiblePages, setVisiblePages] = useState(6);
  const [downloading, setDownloading] = useState(false);
  const hostRef = useRef<HTMLDivElement>(null);

  const displayName = fileName || projectName || projectCode || "招标文件.docx";
  const isPdf = isPdfFile(displayName);
  const isImage = isImageFile(displayName) || Boolean(fileBlob?.type?.startsWith("image/"));
  const isSheet = isSpreadsheetFile(displayName);
  const isDocx = isDocxFile(displayName) && !isPdf && !isImage && !isSheet;

  useEffect(() => {
    if (paragraphsProp) setParagraphs(paragraphsProp);
  }, [paragraphsProp]);

  useEffect(() => {
    if (!tenderDocumentId) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    setFileBlob(null);
    setPdfUrl("");
    setPdfPages(0);
    setVisiblePages(6);
    setParagraphs(paragraphsProp ?? []);

    if (isPdfFile(fileName || displayName)) {
      getTenderPreviewMeta(tenderDocumentId)
        .then((meta) => {
          if (cancelled) return;
          setPdfPages(meta.pageCount || 0);
          if (!meta.pageCount) setError("该 PDF 没有可预览页面");
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
    }

    downloadTenderDocument(tenderDocumentId, true)
      .then((blob) => ensureBlobMime(blob, fileName || displayName))
      .then((blob) => {
        if (!cancelled) setFileBlob(blob);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "招标文件原文加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    if (!paragraphsProp) {
      getTenderParagraphs(tenderDocumentId)
        .then((paras) => {
          if (!cancelled) setParagraphs(paras);
        })
        .catch(() => {
          if (!cancelled) setParagraphs([]);
        });
    }

    return () => {
      cancelled = true;
    };
  }, [tenderDocumentId, fileName]);

  useEffect(() => {
    if (loading || error || !fileBlob || isPdf) return;
    if (!isImage) {
      setPdfUrl("");
      return;
    }
    const url = URL.createObjectURL(fileBlob);
    setPdfUrl(url);
    return () => {
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    };
  }, [fileBlob, loading, error, isPdf, isImage]);

  useEffect(() => {
    if (loading || error || !fileBlob || !isDocx) return;
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
  }, [fileBlob, loading, error, isDocx]);

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

  const downloadName = /\.[a-z0-9]+$/i.test(displayName) ? displayName : `${displayName}${isPdf ? ".pdf" : isImage ? ".png" : isSheet ? ".xlsx" : ".docx"}`;
  const showSearch = isDocx || isSheet;
  const showZoom = isDocx || isImage;

  const handleDownload = async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      const raw = fileBlob || (await downloadTenderDocument(tenderDocumentId, false));
      const typed = await ensureBlobMime(raw, downloadName);
      triggerFileDownload(typed, downloadName);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "下载失败");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-background-300 bg-background-100">
      <div className="flex flex-wrap items-center gap-1 border-b border-background-300 bg-background-50 px-2.5 py-1.5">
        {showZoom && (
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
        {(fileBlob || isPdf) && (
          <button
            type="button"
            onClick={handleDownload}
            disabled={downloading}
            className="flex h-8 cursor-pointer items-center gap-1 rounded border border-background-300 bg-background-50 px-2 text-xs text-foreground-700 hover:bg-background-100 disabled:opacity-60"
          >
            <i className={`${downloading ? "ri-loader-4-line animate-spin" : "ri-download-2-line"}`}></i>
            {downloading ? "准备下载…" : "下载原文件"}
          </button>
        )}
        {showSearch ? (
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
        ) : (
          <span className="ml-auto flex items-center gap-1 text-[11px] text-primary-600">
            <i className="ri-lock-2-line"></i>
            {isPdf ? "只读预览 · 分页渲染，不会自动下载原文件" : isImage ? "只读预览 · 图片" : "只读预览"}
          </span>
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
          <div className="flex flex-col items-center gap-3 px-3 py-4">
            {Array.from({ length: Math.min(visiblePages, pdfPages) }, (_, i) => (
              <AuthImage
                key={`${tenderDocumentId}-${i + 1}`}
                eager={i < 2}
                src={`/api/tender-documents/${tenderDocumentId}/preview-page?page=${i + 1}`}
                alt={`${displayName} 第 ${i + 1} 页`}
                className="max-w-full rounded shadow"
                fallbackText={`第 ${i + 1} 页加载失败`}
              />
            ))}
            {pdfPages > 0 && (
              <div className="text-[11px] text-foreground-500">
                已显示 {Math.min(visiblePages, pdfPages)} / {pdfPages} 页
              </div>
            )}
            {visiblePages < pdfPages && (
              <button
                type="button"
                onClick={() => setVisiblePages((n) => n + 8)}
                className="flex h-8 cursor-pointer items-center rounded-md border border-background-300 bg-background-50 px-3 text-xs text-foreground-700 hover:bg-background-100"
              >
                加载后续页面
              </button>
            )}
          </div>
        ) : isImage ? (
          pdfUrl && (
            <div className="flex justify-center">
              <img
                src={pdfUrl}
                alt={displayName}
                className="max-w-full origin-top rounded shadow"
                style={{ transform: `scale(${zoom / 100})` }}
              />
            </div>
          )
        ) : isSheet ? (
          <pre className="whitespace-pre-wrap rounded-md border border-background-200 bg-background-50 p-3 text-[12px] leading-5 text-foreground-800">
            {paragraphs.length ? paragraphs.map((p) => p.text).join("\n") : "未能从该 Excel 中抽出单元格文字。旧版 .xls 请另存为 .xlsx。"}
          </pre>
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
          <i className={`${isPdf ? "ri-file-pdf-2-line" : isSheet ? "ri-file-excel-2-line" : isImage ? "ri-image-line" : "ri-file-word-2-line"} text-primary-500`}></i>
          {displayName}
        </span>
        <span>上传的原{isPdf ? " PDF" : isSheet ? " Excel" : isImage ? " 图片" : " Word"}文档</span>
      </div>
    </div>
  );
});

export default WordViewer;

WordViewer.displayName = "WordViewer";
