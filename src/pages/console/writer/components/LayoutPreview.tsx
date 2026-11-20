import { useEffect, useRef, useState } from "react";
import { fetchWriterPreviewPage, renderWriterPreview } from "@/lib/api";

interface Props {
  draftId: string;
  chapterId: string;
  /** 每次变化都触发一次重渲（保存成功后、手动点刷新时递增）。 */
  refreshToken: number;
}

interface PreviewState {
  loading: boolean;
  error: string | null;
  pageUrls: string[];
  cached: boolean;
  ms: number;
}

const EMPTY: PreviewState = { loading: false, error: null, pageUrls: [], cached: false, ms: 0 };

/** 章节版式预览：用和导出同一条路径生成的 docx，交给 LibreOffice 渲染成 PDF 再按页出图。 */
export default function LayoutPreview({ draftId, chapterId, refreshToken }: Props) {
  const [state, setState] = useState<PreviewState>(EMPTY);
  const urlsRef = useRef<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    urlsRef.current.forEach((u) => URL.revokeObjectURL(u));
    urlsRef.current = [];
    setState({ ...EMPTY, loading: true });

    (async () => {
      try {
        const info = await renderWriterPreview(draftId, chapterId);
        if (cancelled) return;
        const urls: string[] = [];
        for (let page = 1; page <= info.pages; page++) {
          const blob = await fetchWriterPreviewPage(draftId, info.hash, page);
          if (cancelled) {
            urls.forEach((u) => URL.revokeObjectURL(u));
            return;
          }
          urls.push(URL.createObjectURL(blob));
        }
        if (cancelled) {
          urls.forEach((u) => URL.revokeObjectURL(u));
          return;
        }
        urlsRef.current = urls;
        setState({ loading: false, error: null, pageUrls: urls, cached: info.cached, ms: info.ms });
      } catch (err) {
        if (cancelled) return;
        const message =
          err instanceof Error && /503|渲染|LibreOffice/.test(err.message)
            ? err.message
            : "版式预览暂时不可用，可以继续编辑和导出";
        setState({ ...EMPTY, loading: false, error: message });
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftId, chapterId, refreshToken]);

  useEffect(
    () => () => {
      urlsRef.current.forEach((u) => URL.revokeObjectURL(u));
    },
    [],
  );

  if (state.loading) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-foreground-500">
        <i className="ri-loader-4-line mr-2 animate-spin"></i>
        正在按 Word 版式渲染本章…
      </div>
    );
  }
  if (state.error) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center text-sm text-foreground-500">
        <i className="ri-error-warning-line text-xl text-accent-500"></i>
        <span>{state.error}</span>
      </div>
    );
  }
  if (!state.pageUrls.length) {
    return <div className="flex flex-1 items-center justify-center text-sm text-foreground-500">本章暂无内容可预览</div>;
  }
  return (
    <div className="flex-1 overflow-y-auto bg-background-200/60 p-4">
      <div className="mb-2 text-center text-[11px] text-foreground-500">
        版式预览 · {state.pageUrls.length} 页{state.cached ? "（缓存）" : `（渲染 ${state.ms}ms）`} ·
        仅本章节，页码不代表全文；中文字形为开源替代字体，与 Word 略有差异
      </div>
      <div className="mx-auto flex max-w-3xl flex-col items-center gap-4">
        {state.pageUrls.map((url, i) => (
          <img
            key={url}
            src={url}
            alt={`第 ${i + 1} 页`}
            className="w-full rounded-sm border border-background-300 bg-white shadow-sm"
          />
        ))}
      </div>
    </div>
  );
}
