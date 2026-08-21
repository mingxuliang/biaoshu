import { useState } from "react";
import type { OutlineNode } from "@/lib/api";
import StatusBadge from "../../components/StatusBadge";

interface EditorPanelProps {
  chapter: OutlineNode | undefined;
  content: string;
  generating: boolean;
  onGenerate: () => void;
  onSave: () => void;
  onExport: () => void;
  insertedImages?: { url: string; type: string }[];
}

const badgeMap: Record<string, { label: string; cls: string; icon: string }> = {
  flow: { label: "AI流程图", cls: "bg-accent-500/80", icon: "ri-flow-chart" },
  arch: { label: "AI架构图", cls: "bg-secondary-500/80", icon: "ri-git-branch-line" },
  normal: { label: "AI生图", cls: "bg-primary-500/80", icon: "ri-magic-line" },
};

function renderContent(text: string, images: { url: string; type: string }[]) {
  if (!text.trim()) {
    return (
      <div className="flex h-full flex-col items-center justify-center py-16 text-center">
        <span className="flex h-12 w-12 items-center justify-center rounded-xl border border-primary-200 bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
          <i className="ri-sparkling-2-line text-xl"></i>
        </span>
        <p className="mt-3 text-sm text-foreground-500">本章节尚未撰写</p>
        <p className="mt-1 text-xs text-foreground-500">点击右上角「AI 生成」按钮，AI 将结合招标文件评分点自动撰写内容</p>
      </div>
    );
  }

  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];

  lines.forEach((line, i) => {
    const trimmed = line.trim();
    if (!trimmed) {
      elements.push(<div key={`empty-${i}`} className="h-2" />);
      return;
    }
    if (trimmed.startsWith("### ")) {
      elements.push(
        <h4 key={i} className="mb-2 mt-4 text-[15px] font-bold text-foreground-950 first:mt-0">
          {trimmed.slice(4)}
        </h4>
      );
      return;
    }
    if (trimmed.startsWith("## ")) {
      elements.push(
        <h3 key={i} className="mb-2 mt-5 text-lg font-bold text-foreground-950 first:mt-0">
          {trimmed.slice(3)}
        </h3>
      );
      return;
    }
    if (/^\d+[）.)\]].*/.test(trimmed) || trimmed.startsWith("（") && /^（[一二三四五六七八九十]+）/.test(trimmed)) {
      // Numbered item like 1) or （一）
      elements.push(
        <p key={i} className="py-0.5 text-[13px] leading-[1.9] text-foreground-800">
          {trimmed}
        </p>
      );
      return;
    }
    if (trimmed.startsWith("-") || trimmed.startsWith("*")) {
      elements.push(
        <p key={i} className="flex gap-2 py-0.5 text-[13px] leading-[1.9] text-foreground-700">
          <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-primary-400"></span>
          <span>{trimmed.slice(1).trim()}</span>
        </p>
      );
      return;
    }
    elements.push(
      <p key={i} className="py-0.5 text-[13px] leading-[1.9] text-foreground-700">
        {trimmed}
      </p>
    );
  });

  // Insert demo images inline after certain paragraphs
  if (images.length > 0) {
    const imageElements: React.ReactNode[] = [];
    images.forEach((img) => {
      const badge = badgeMap[img.type] ?? badgeMap.normal;
      const isFlow = img.type === "flow";
      imageElements.push(
        <div key={`img-${img.url}`} className="my-4 flex justify-center">
          <div className={`relative inline-block overflow-hidden rounded-lg border border-background-300 ${isFlow ? "w-full max-w-2xl" : "max-w-full"}`}>
            <img
              src={img.url}
              alt={badge.label}
              className={isFlow ? "w-full object-contain" : "max-h-48 w-auto object-contain"}
            />
            <span className={`absolute right-1 top-1 flex items-center gap-0.5 rounded px-1 py-0.5 text-[9px] font-medium text-background-50 ${badge.cls}`}>
              <i className={badge.icon}></i>
              {badge.label}
            </span>
          </div>
        </div>
      );
    });
    // Distribute images through the content
    const totalElements = elements.length;
    const step = Math.max(1, Math.floor(totalElements / (images.length + 1)));
    const combined: React.ReactNode[] = [];
    let imgIdx = 0;
    elements.forEach((el, i) => {
      combined.push(el);
      if ((i + 1) % step === 0 && imgIdx < imageElements.length) {
        combined.push(imageElements[imgIdx++]);
      }
    });
    return combined;
  }

  return elements;
}

export default function EditorPanel({
  chapter,
  content,
  generating,
  onGenerate,
  onSave,
  onExport,
  insertedImages = [],
}: EditorPanelProps) {
  const [fontSize, setFontSize] = useState("小四");
  const [fontFamily, setFontFamily] = useState("宋体");
  const wordCount = content.trim() ? Math.round(content.replace(/\s/g, "").length) : 0;

  const fontSizeOptions = ["小三", "小四", "四号", "三号"];
  const fontFamilyOptions = ["宋体", "黑体", "仿宋", "楷体"];

  return (
    <div className="flex min-w-0 flex-1 flex-col rounded-lg border border-background-300 bg-background-100">
      {/* 工具栏 */}
      <div className="flex flex-wrap items-center gap-1 border-b border-background-300 bg-background-50 px-3 py-1.5">
        {/* 撤销/重做 */}
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            className="flex h-6 w-6 cursor-pointer items-center justify-center rounded text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800"
            title="撤销"
          >
            <i className="ri-arrow-go-back-line text-xs"></i>
          </button>
          <button
            type="button"
            className="flex h-6 w-6 cursor-pointer items-center justify-center rounded text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800"
            title="重做"
          >
            <i className="ri-arrow-go-forward-line text-xs"></i>
          </button>
        </div>

        <div className="mx-1 hidden h-4 w-px bg-background-300 sm:block" />

        {/* 字体选择 */}
        <select
          value={fontFamily}
          onChange={(e) => setFontFamily(e.target.value)}
          className="h-6 cursor-pointer rounded border border-background-300 bg-background-50 px-1.5 text-[11px] text-foreground-700 outline-none focus:border-primary-400"
          title="字体"
        >
          {fontFamilyOptions.map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>

        {/* 字号选择 */}
        <select
          value={fontSize}
          onChange={(e) => setFontSize(e.target.value)}
          className="h-6 cursor-pointer rounded border border-background-300 bg-background-50 px-1.5 text-[11px] text-foreground-700 outline-none focus:border-primary-400"
          title="字号"
        >
          {fontSizeOptions.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <div className="mx-1 hidden h-4 w-px bg-background-300 sm:block" />

        {/* 格式按钮 */}
        <div className="flex items-center gap-0.5">
          {[
            { icon: "ri-bold", title: "加粗" },
            { icon: "ri-italic", title: "斜体" },
            { icon: "ri-underline", title: "下划线" },
          ].map((item) => (
            <button
              key={item.icon}
              type="button"
              className="flex h-6 w-6 cursor-pointer items-center justify-center rounded text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800"
              title={item.title}
            >
              <i className={`${item.icon} text-xs`}></i>
            </button>
          ))}
        </div>

        <div className="mx-1 hidden h-4 w-px bg-background-300 sm:block" />

        {/* 对齐按钮 */}
        <div className="flex items-center gap-0.5">
          {[
            { icon: "ri-align-left", title: "左对齐" },
            { icon: "ri-align-center", title: "居中" },
            { icon: "ri-align-right", title: "右对齐" },
            { icon: "ri-align-justify", title: "两端对齐" },
          ].map((item) => (
            <button
              key={item.icon}
              type="button"
              className="flex h-6 w-6 cursor-pointer items-center justify-center rounded text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800"
              title={item.title}
            >
              <i className={`${item.icon} text-xs`}></i>
            </button>
          ))}
        </div>

        <div className="mx-1 hidden h-4 w-px bg-background-300 sm:block" />

        {/* 列表 */}
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            className="flex h-6 w-6 cursor-pointer items-center justify-center rounded text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800"
            title="无序列表"
          >
            <i className="ri-list-unordered text-xs"></i>
          </button>
          <button
            type="button"
            className="flex h-6 w-6 cursor-pointer items-center justify-center rounded text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800"
            title="有序列表"
          >
            <i className="ri-list-ordered-2 text-xs"></i>
          </button>
        </div>

        <div className="mx-1 hidden h-4 w-px bg-background-300 sm:block" />

        {/* 查找替换 */}
        <button
          type="button"
          className="flex h-6 cursor-pointer items-center gap-1 rounded px-1.5 text-[11px] text-foreground-500 transition-colors hover:bg-background-200"
          title="查找替换"
        >
          <i className="ri-find-replace-line text-xs"></i>
          查找替换
        </button>

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
            className="flex h-7 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border border-background-300 px-2.5 text-xs font-medium text-foreground-600 transition-colors hover:bg-background-200"
          >
            <i className="ri-download-2-line text-xs"></i>
            导出
          </button>
          <button
            type="button"
            onClick={onGenerate}
            disabled={generating}
            className="flex h-7 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md bg-gradient-to-r from-primary-500 to-primary-600 px-3 text-xs font-semibold text-background-50 transition-all hover:from-primary-600 hover:to-primary-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <i className={`${generating ? "ri-loader-4-line animate-spin" : "ri-sparkling-2-line"} text-xs`}></i>
            {generating ? "AI 生成中…" : "AI 生成"}
          </button>
        </div>
      </div>

      {/* 文档标题栏 */}
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
      </div>

      {/* 内容区 — Word 纸张样式 */}
      <div className="relative flex-1 overflow-y-auto bg-background-200/50 px-4 py-4">
        <div className="word-sheet mx-auto min-h-[620px] max-w-3xl rounded-sm px-10 py-10">
          {renderContent(content, insertedImages)}
          {generating && (
            <span className="ml-1 inline-block h-4 w-0.5 bg-primary-500 animate-blink-bar" />
          )}
        </div>
      </div>

      {/* 状态栏 */}
      <div className="flex items-center gap-4 border-t border-background-300 bg-background-50 px-5 py-2 text-[11px] text-foreground-500">
        <span className="flex items-center gap-1">
          <i className="ri-file-text-line text-primary-500 text-xs"></i>
          当前章节 {wordCount} 字
        </span>
        {chapter && chapter.aiRounds > 0 && (
          <span className="flex items-center gap-1">
            <i className="ri-sparkling-2-line text-accent-500 text-xs"></i>
            AI 已优化 {chapter.aiRounds} 轮
          </span>
        )}
        <span className="ml-auto">自动保存于 刚刚</span>
      </div>
    </div>
  );
}