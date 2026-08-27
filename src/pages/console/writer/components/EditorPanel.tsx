import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import type { OutlineNode } from "@/lib/api";
import { isOriginalFormTitle } from "@/lib/outlineNum";
import StatusBadge from "../../components/StatusBadge";
import ChapterEditor, { type ChapterEditorHandle } from "./ChapterEditor";

export interface EditorPanelHandle {
  insertImage: (src: string, alt: string) => boolean;
}

interface EditorPanelProps {
  chapter: OutlineNode | undefined;
  content: string;
  generating: boolean;
  onGenerate: () => void;
  onSave: () => void;
  onExport: () => void;
  onContentChange: (text: string) => void;
  exporting?: boolean;
}

const EditorPanel = forwardRef<EditorPanelHandle, EditorPanelProps>(function EditorPanel(
  { chapter, content, generating, onGenerate, onSave, onExport, onContentChange, exporting = false },
  ref,
) {
  const [fontSize, setFontSize] = useState("小四");
  const [fontFamily, setFontFamily] = useState("宋体");
  const chapterRef = useRef<ChapterEditorHandle | null>(null);
  const wordCount = content.trim() ? Math.round(content.replace(/\s/g, "").length) : 0;
  const useOriginal = !!chapter && (chapter.status === "用原文" || isOriginalFormTitle(chapter.title, chapter.num));

  useImperativeHandle(
    ref,
    () => ({
      insertImage: (src, alt) => chapterRef.current?.insertImage(src, alt) ?? false,
    }),
    [],
  );

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
        <div className="ml-auto flex items-center gap-2">
          <span className="hidden text-xs text-foreground-500 sm:block">
            约 <span className="font-label text-gradient font-medium">{wordCount}</span> 字
          </span>
          <button
            type="button"
            onClick={onSave}
            className="flex h-7 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border border-background-300 px-2.5 text-xs font-medium text-foreground-600 transition-colors hover:bg-background-200"
          >
            <i className="ri-save-3-line text-xs"></i>
            保存
          </button>
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
          <span>本章为招标书已给出的固定格式文件，请直接使用招标书原文填写后打印签字，无需 AI 撰写。</span>
        </div>
      )}

      {chapter ? (
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
