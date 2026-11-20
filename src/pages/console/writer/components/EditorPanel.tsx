import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import type { OutlineNode } from "@/lib/api";
import { isSkipAiWrite } from "@/lib/outlineNum";
import { defaultLayout, type LayoutConfig } from "@/mocks/writerSteps";
import StatusBadge from "../../components/StatusBadge";
import ChapterEditor, { type ChapterEditorHandle } from "./ChapterEditor";
import LayoutPreview from "./LayoutPreview";

export interface EditorPanelHandle {
  insertImage: (src: string, alt: string) => boolean;
}

interface EditorPanelProps {
  draftId: string;
  chapter: OutlineNode | undefined;
  content: string;
  generating: boolean;
  onGenerate: () => void;
  onSave: () => void | Promise<void>;
  onExport: () => void;
  onSelfCheck?: () => void;
  selfChecking?: boolean;
  onContentChange: (text: string) => void;
  exporting?: boolean;
  layout?: LayoutConfig | null;
}

function writingLayout(layout?: LayoutConfig | null): LayoutConfig {
  if (!layout || layout.fromTender) return defaultLayout;
  return {
    ...defaultLayout,
    ...layout,
    headings: { ...defaultLayout.headings, ...layout.headings },
  };
}

const EditorPanel = forwardRef<EditorPanelHandle, EditorPanelProps>(function EditorPanel(
  {
    draftId,
    chapter,
    content,
    generating,
    onGenerate,
    onSave,
    onExport,
    onSelfCheck,
    selfChecking = false,
    onContentChange,
    exporting = false,
    layout,
  },
  ref,
) {
  const applied = writingLayout(layout);
  const layoutFont = applied.bodyFont || "仿宋";
  const layoutSize = applied.fontSize || "小四";
  const [fontSize, setFontSize] = useState(layoutSize);
  const [fontFamily, setFontFamily] = useState(layoutFont);
  const [mode, setMode] = useState<"edit" | "preview">("edit");
  const [refreshToken, setRefreshToken] = useState(0);
  const chapterRef = useRef<ChapterEditorHandle | null>(null);
  const wordCount = content.trim() ? Math.round(content.replace(/\s/g, "").length) : 0;
  const useOriginal = !!chapter && isSkipAiWrite(chapter);

  useEffect(() => {
    setFontFamily(layoutFont);
    setFontSize(layoutSize);
  }, [layoutFont, layoutSize]);

  useEffect(() => {
    setMode("edit");
  }, [chapter?.id]);

  useImperativeHandle(
    ref,
    () => ({
      insertImage: (src, alt) => chapterRef.current?.insertImage(src, alt) ?? false,
    }),
    [],
  );

  const handleSaveClick = async () => {
    await onSave();
    if (mode === "preview") setRefreshToken((n) => n + 1);
  };

  const switchToPreview = async () => {
    await onSave();
    setMode("preview");
    setRefreshToken((n) => n + 1);
  };

  return (
    <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden rounded-lg border border-background-300 bg-background-100">
      <div className="flex flex-wrap items-center gap-2 border-b border-background-300 bg-background-50 px-4 py-2.5">
        <h3 className="font-heading text-sm font-semibold tracking-wide text-foreground-950">
          {chapter ? `${chapter.num} · ${chapter.title}` : "选择章节"}
        </h3>
        {chapter && <StatusBadge status={chapter.status} />}
        {chapter && chapter.aiRounds > 0 && (
          <span className="flex items-center gap-1 rounded bg-primary-50 px-2 py-0.5 text-[11px] font-medium text-primary-600">
            <i className="ri-sparkling-2-line text-xs"></i>
            AI 已优化 {chapter.aiRounds} 轮
          </span>
        )}
        {chapter && (
          <div className="flex h-7 items-center rounded-md border border-background-300 bg-background-50 p-0.5 text-xs">
            <button
              type="button"
              onClick={() => setMode("edit")}
              className={`flex h-full cursor-pointer items-center gap-1 rounded px-2 transition-colors ${
                mode === "edit" ? "bg-primary-500 text-background-50" : "text-foreground-600 hover:bg-background-200"
              }`}
            >
              <i className="ri-edit-line text-xs"></i>
              编辑
            </button>
            <button
              type="button"
              onClick={switchToPreview}
              className={`flex h-full cursor-pointer items-center gap-1 rounded px-2 transition-colors ${
                mode === "preview" ? "bg-primary-500 text-background-50" : "text-foreground-600 hover:bg-background-200"
              }`}
              title="按 Word 版式渲染本章，所见与导出一致"
            >
              <i className="ri-file-word-2-line text-xs"></i>
              版式预览
            </button>
          </div>
        )}
        <div className="ml-auto flex items-center gap-2">
          {mode === "edit" && (
            <span className="hidden text-xs text-foreground-500 sm:block">
              约 <span className="font-label text-gradient font-medium">{wordCount}</span> 字
            </span>
          )}
          {mode === "preview" && (
            <button
              type="button"
              onClick={switchToPreview}
              className="flex h-7 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border border-background-300 px-2.5 text-xs font-medium text-foreground-600 transition-colors hover:bg-background-200"
            >
              <i className="ri-refresh-line text-xs"></i>
              刷新预览
            </button>
          )}
          <button
            type="button"
            onClick={handleSaveClick}
            className="flex h-7 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border border-background-300 px-2.5 text-xs font-medium text-foreground-600 transition-colors hover:bg-background-200"
          >
            <i className="ri-save-3-line text-xs"></i>
            保存
          </button>
          {onSelfCheck && (
            <button
              type="button"
              onClick={onSelfCheck}
              disabled={selfChecking}
              className="flex h-7 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border border-background-300 px-2.5 text-xs font-medium text-foreground-600 transition-colors hover:bg-background-200 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <i className={`${selfChecking ? "ri-loader-4-line animate-spin" : "ri-shield-check-line"} text-xs`}></i>
              {selfChecking ? "自查中…" : "提交前自查"}
            </button>
          )}
          <button
            type="button"
            onClick={onExport}
            disabled={exporting}
            className="flex h-7 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border border-background-300 px-2.5 text-xs font-medium text-foreground-600 transition-colors hover:bg-background-200 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <i className={`${exporting ? "ri-loader-4-line animate-spin" : "ri-download-2-line"} text-xs`}></i>
            {exporting ? "导出中…" : "导出"}
          </button>
          {!useOriginal && (
          <button
            type="button"
            onClick={onGenerate}
            disabled={generating || !chapter}
            className="flex h-7 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md bg-gradient-to-r from-primary-500 to-primary-600 px-3 text-xs font-semibold text-background-50 transition-all hover:from-primary-600 hover:to-primary-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <i className={`${generating ? "ri-loader-4-line animate-spin" : "ri-sparkling-2-line"} text-xs`}></i>
            {generating ? "AI 生成中…" : "AI 生成"}
          </button>
          )}
        </div>
      </div>

      {useOriginal && (
        <div className="flex items-start gap-2 border-b border-background-300 bg-secondary-50 px-4 py-2 text-xs leading-relaxed text-foreground-600">
          <i className="ri-file-text-line mt-0.5 shrink-0 text-sm text-secondary-600"></i>
          <span>以下为招标书原文格式，请按空填写后打印签字，无需 AI 改写。</span>
        </div>
      )}

      {chapter && mode === "preview" ? (
        <LayoutPreview draftId={draftId} chapterId={chapter.id} refreshToken={refreshToken} />
      ) : chapter ? (
        <ChapterEditor
          key={chapter.id}
          chapterId={chapter.id}
          markdown={content}
          editable={!generating}
          fontFamily={fontFamily}
          fontSize={fontSize}
          onFontFamily={setFontFamily}
          onFontSize={setFontSize}
          onMarkdownChange={onContentChange}
          layout={applied}
          applyTenderIndent={!useOriginal}
          onReady={(handle) => {
            chapterRef.current = handle;
          }}
        />
      ) : (
        <div className="flex flex-1 items-center justify-center text-sm text-foreground-500">请选择左侧章节</div>
      )}

      {generating && (
        <div className="pointer-events-none absolute inset-x-0 bottom-10 top-14 flex items-start justify-center pt-24">
          <span className="rounded-md bg-background-100/90 px-3 py-1.5 text-xs text-primary-600 shadow-sm">
            AI 正在生成本章正文…
          </span>
        </div>
      )}

      <div className="flex items-center gap-4 border-t border-background-300 bg-background-50 px-5 py-2 text-[11px] text-foreground-500">
        <span className="flex items-center gap-1">
          <i className="ri-file-word-2-line text-primary-500 text-xs"></i>
          可编辑正文 · 插图插入当前光标
        </span>
        <span className="ml-auto">当前章节 {wordCount} 字</span>
      </div>
    </div>
  );
});

export default EditorPanel;
