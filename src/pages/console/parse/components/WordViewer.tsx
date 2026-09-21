import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { renderAsync } from "docx-preview";
import {
  downloadTenderDocument,
  getTenderParagraphs,
  getTenderPreviewMeta,
  getTenderSheetPreview,
  locateTenderText,
  triggerFileDownload,
  type TenderLocateHit,
  type TenderParagraph,
  type TenderSheet,
} from "@/lib/api";
import AuthImage from "../../components/AuthImage";
import { isDocxFile, isImageFile, isPdfFile, isSpreadsheetFile, ensureBlobMime } from "@/lib/tenderPackage";
import { findContentAnchor, findSheetRow, locateNeedles, type LocateTarget } from "@/lib/tenderAnchor";

interface WordViewerProps {
  projectName: string;
  projectCode: string;
  tenderDocumentId: string;
  fileName?: string;
  paragraphs?: TenderParagraph[];
  anchorIndex?: number | null;
  locateQuery?: LocateTarget | null;
}

export interface WordViewerHandle {
  scrollToIndex: (index: number) => void;
  locateText: (text: string, label?: string) => Promise<boolean>;
}

const zoomOptions = [75, 90, 100, 125, 150];

function colLetter(n: number): string {
  let s = "";
  let x = n;
  while (x > 0) {
    const m = (x - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    x = Math.floor((x - 1) / 26);
  }
  return s;
}

function compactCell(s: string): string {
  return (s || "").replace(/\s+/g, "").replace(/[：:、，,。；;．.|｜]/g, "");
}

const WordViewer = forwardRef<WordViewerHandle, WordViewerProps>(function WordViewer(
  { projectName, projectCode, tenderDocumentId, fileName, paragraphs: paragraphsProp, anchorIndex = null, locateQuery = null },
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
  const [pdfHit, setPdfHit] = useState<TenderLocateHit | null>(null);
  const [sheets, setSheets] = useState<TenderSheet[]>([]);
  const [sheetIndex, setSheetIndex] = useState(0);
  const [sheetHit, setSheetHit] = useState<{ sheet: number; row: number } | null>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);

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
    setPdfHit(null);
    setSheets([]);
    setSheetIndex(0);
    setSheetHit(null);

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
      getTenderParagraphs(tenderDocumentId)
        .then((paras) => {
          if (!cancelled) setParagraphs(paras);
        })
        .catch(() => {
          if (!cancelled && !paragraphsProp) setParagraphs([]);
        });
      return () => {
        cancelled = true;
      };
    }

    if (isSpreadsheetFile(fileName || displayName)) {
      getTenderSheetPreview(tenderDocumentId)
        .then((preview) => {
          if (cancelled) return;
          setSheets(preview.sheets || []);
          if (!(preview.sheets || []).length) setError("未能从该 Excel 中还原表格，请另存为 .xlsx 后重新上传");
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(err instanceof Error ? err.message : "Excel 预览失败");
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

  const flashNode = (el: Element) => {
    el.setAttribute("data-tender-flash", "1");
    window.setTimeout(() => el.removeAttribute("data-tender-flash"), 2800);
  };

  const locateInDom = useCallback((query: string, label?: string): boolean => {
    const root = hostRef.current || sheetRef.current;
    if (!root) return false;
    const keys = locateNeedles(query, label);
    if (!keys.length) return false;
    hostRef.current?.querySelectorAll("[data-tender-flash]").forEach((el) => el.removeAttribute("data-tender-flash"));
    const nodes = root.querySelectorAll("p, h1, h2, h3, h4, h5, li, td, span");
    const compact = (s: string) => s.replace(/\s+/g, "").replace(/[：:、，,。；;．.]/g, "");
    const labelC = compact(label || "");
    let best: { el: Element; score: number } | null = null;
    for (const el of nodes) {
      const raw = (el.textContent || "").trim();
      const t = compact(raw);
      if (!t) continue;
      let score = 0;
      for (const key of keys) {
        const k = compact(key);
        if (k.length < 2) continue;
        if (t.includes(k) || (k.includes(t) && t.length >= 6)) {
          score = Math.max(score, k.length + (raw.length < 120 ? 10 : 0));
        }
      }
      if (labelC && t.includes(labelC)) {
        score += 18;
        if (/[：:]/.test(raw)) score += 8;
      }
      if (/^\d+\.\d+/.test(raw) || /^第[0-9一二三四五六七八九十百]+[章节篇]/.test(raw)) score += 12;
      if (score > (best?.score ?? 0)) best = { el, score };
    }
    if (!best || best.score < 8) return false;
    best.el.scrollIntoView({ behavior: "smooth", block: "center" });
    flashNode(best.el);
    return true;
  }, []);

  const scrollPdfHit = useCallback((page: number) => {
    const run = () => {
      const hitEl = scrollRef.current?.querySelector(`[data-pdf-page="${page}"] .tender-pdf-hit`);
      const pageEl = scrollRef.current?.querySelector(`[data-pdf-page="${page}"]`);
      (hitEl || pageEl)?.scrollIntoView({ behavior: "smooth", block: "center" });
    };
    window.setTimeout(run, 80);
    window.setTimeout(run, 400);
  }, []);

  const locateText = useCallback(
    async (text: string, label?: string): Promise<boolean> => {
      const q = (text || "").trim();
      if (!q) return false;
      if (isPdf) {
        try {
          const hit = await locateTenderText(tenderDocumentId, q, label);
          if (!hit.found || hit.page < 1 || !(hit.rects || []).length) return false;
          setVisiblePages((n) => Math.max(n, hit.page + 2));
          setPdfHit(hit);
          scrollPdfHit(hit.page);
          return true;
        } catch {
          return false;
        }
      }
      if (isSheet) {
        const best = findSheetRow(sheets, q);
        if (!best) return false;
        const hitRow = best.row;
        setSheetIndex(best.sheet);
        setSheetHit({ sheet: best.sheet, row: hitRow });
        window.setTimeout(() => {
          sheetRef.current?.querySelector(`[data-sheet-row="${hitRow}"]`)?.scrollIntoView({
            behavior: "smooth",
            block: "center",
          });
        }, 60);
        return true;
      }
      if (locateInDom(q, label)) return true;
      const para = findContentAnchor(q, paragraphs, label);
      if (para) return locateInDom(para.text, label);
      return false;
    },
    [isPdf, isSheet, tenderDocumentId, paragraphs, locateInDom, scrollPdfHit, sheets],
  );

  const scrollToIndex = useCallback((index: number) => {
    const para = paragraphs.find((p) => p.index === index);
    if (!para?.text) return;
    if (isPdf) {
      if (para.page) {
        setVisiblePages((n) => Math.max(n, para.page! + 2));
        setPdfHit({ found: true, page: para.page, pageCount: pdfPages, snippet: para.text, heading: para.text, rects: [] });
        scrollPdfHit(para.page);
      }
      return;
    }
    locateInDom(para.text);
  }, [paragraphs, isPdf, pdfPages, locateInDom, scrollPdfHit]);

  useImperativeHandle(ref, () => ({ scrollToIndex, locateText }), [scrollToIndex, locateText]);

  useEffect(() => {
    if (anchorIndex == null || loading) return;
    const timer = window.setTimeout(() => scrollToIndex(anchorIndex), 120);
    return () => window.clearTimeout(timer);
  }, [anchorIndex, loading, scrollToIndex]);

  useEffect(() => {
    if (!locateQuery?.content || loading) return;
    const timer = window.setTimeout(() => {
      void locateText(locateQuery.content, locateQuery.label);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [locateQuery, loading, locateText, tenderDocumentId]);

  useEffect(() => {
    if (loading || isPdf || isSheet) return;
    markHits(searchQuery);
  }, [searchQuery, loading, isPdf, isSheet]);

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
        {(fileBlob || isPdf || isSheet) && (
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
              placeholder={isSheet ? "搜索表格内容…" : "搜索文档内容…"}
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

      <div ref={scrollRef} className={`relative flex-1 bg-background-200/50 ${isSheet ? "overflow-hidden" : "overflow-auto"} ${isPdf || isSheet ? "" : "px-4 py-5 md:px-6"}`}>
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
            {Array.from({ length: Math.min(visiblePages, pdfPages) }, (_, i) => {
              const pageNo = i + 1;
              const active = pdfHit?.page === pageNo && (pdfHit.rects || []).length > 0;
              const badge = [pdfHit?.heading, pdfHit?.snippet].filter(Boolean).join(" · ");
              return (
                <div
                  key={`${tenderDocumentId}-${pageNo}`}
                  data-pdf-page={pageNo}
                  className="relative inline-block max-w-full"
                >
                  <AuthImage
                    eager={i < 2 || active}
                    src={`/api/tender-documents/${tenderDocumentId}/preview-page?page=${pageNo}`}
                    alt={`${displayName} 第 ${pageNo} 页`}
                    className="max-w-full rounded shadow"
                    fallbackText={`第 ${pageNo} 页加载失败`}
                  />
                  {active &&
                    (pdfHit?.rects || []).map((r, ri) => (
                      <span
                        key={`${pageNo}-${ri}`}
                        className="tender-pdf-hit"
                        style={{
                          left: `${r.x * 100}%`,
                          top: `${r.y * 100}%`,
                          width: `${r.w * 100}%`,
                          height: `${Math.max(r.h * 100, 1.2)}%`,
                        }}
                      />
                    ))}
                  {active && badge && (
                    <div
                      className="pointer-events-none absolute max-w-[90%] truncate rounded bg-primary-600/90 px-2 py-0.5 text-[10px] font-medium text-background-50"
                      style={{
                        left: `${Math.min(86, (pdfHit?.rects?.[0]?.x || 0) * 100)}%`,
                        top: `calc(${(pdfHit?.rects?.[0]?.y || 0) * 100}% - 22px)`,
                      }}
                    >
                      {badge}
                    </div>
                  )}
                </div>
              );
            })}
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
          <div ref={sheetRef} className="tender-excel">
            {(() => {
              const sheet = sheets[sheetIndex];
              const searchKey = compactCell(searchQuery);
              if (!sheet?.rows?.length) {
                return (
                  <div className="flex h-full min-h-[240px] flex-col items-center justify-center gap-2 px-4 text-center text-sm text-foreground-500">
                    <i className="ri-table-line text-2xl text-foreground-300"></i>
                    未能从该 Excel 中还原表格。旧版 .xls 请另存为 .xlsx 后重新上传。
                  </div>
                );
              }
              const colCount = Math.max(1, ...sheet.rows.map((r) => r.length));
              return (
                <>
                  <div className="tender-excel-scroll">
                    <table className="tender-excel-grid">
                      <thead>
                        <tr>
                          <th className="tender-excel-corner" />
                          {Array.from({ length: colCount }, (_, i) => (
                            <th key={i}>{colLetter(i + 1)}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {sheet.rows.map((row, ri) => {
                          const hit = sheetHit?.sheet === sheetIndex && sheetHit.row === ri;
                          const searched = !hit && searchKey.length >= 2 && compactCell(row.join("")).includes(searchKey);
                          return (
                            <tr
                              key={ri}
                              data-sheet-row={ri}
                              className={hit ? "is-hit" : searched ? "is-search" : undefined}
                            >
                              <th>{ri + 1}</th>
                              {Array.from({ length: colCount }, (_, ci) => (
                                <td key={ci} title={row[ci] || ""}>
                                  {row[ci] || ""}
                                </td>
                              ))}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <div className="tender-excel-tabs">
                    {sheets.map((item, i) => (
                      <button
                        key={`${item.name}-${i}`}
                        type="button"
                        className={i === sheetIndex ? "is-active" : undefined}
                        onClick={() => {
                          setSheetIndex(i);
                          setSheetHit((prev) => (prev?.sheet === i ? prev : null));
                        }}
                      >
                        {item.name || `工作表${i + 1}`}
                      </button>
                    ))}
                  </div>
                </>
              );
            })()}
          </div>
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
        <span>上传的原{isPdf ? " PDF" : isSheet ? " Excel 表格" : isImage ? " 图片" : " Word"}文档{isSheet && sheets[sheetIndex]?.rows?.length ? ` · ${sheets[sheetIndex].rows.length} 行` : ""}</span>
      </div>
    </div>
  );
});

export default WordViewer;

WordViewer.displayName = "WordViewer";
