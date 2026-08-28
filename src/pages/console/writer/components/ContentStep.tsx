import { useEffect, useRef, useState } from "react";
import Toast from "../../components/Toast";
import ChapterTree from "./ChapterTree";
import EditorPanel, { type EditorPanelHandle } from "./EditorPanel";
import ImagePanel from "./ImagePanel";
import FloatingChat from "./FloatingChat";
import {
  ApiError,
  createChapterGenerateJob,
  exportWriterDraftDocx,
  getOrCreateWriterDraft,
  pollWriterJobUntilDone,
  saveChapterContent,
  type OutlineNode,
  type WriterImageItem,
} from "@/lib/api";
import { isOriginalFormTitle, isSkipAiWrite } from "@/lib/outlineNum";

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

interface ContentStepProps {
  projectId: string;
  draftId: string;
  outline: OutlineNode[];
  onOutlineChange: (nodes: OutlineNode[]) => void;
  chapterContents: Record<string, string>;
  onChapterContentsChange: (contents: Record<string, string>) => void;
  projectName: string;
  onBack: () => void;
}

export default function ContentStep({
  projectId,
  draftId,
  outline,
  onOutlineChange,
  chapterContents,
  onChapterContentsChange,
  projectName,
  onBack,
}: ContentStepProps) {
  const [activeId, setActiveId] = useState<string>(outline[0]?.id ?? "");
  const [generatingId, setGeneratingId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });
  const generatingRef = useRef(false);
  const editorRef = useRef<EditorPanelHandle>(null);

  useEffect(() => {
    if (!outline.some((n) => n.id === activeId)) {
      setActiveId(outline[0]?.id ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outline]);

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const activeNode = outline.find((c) => c.id === activeId);
  const doneCount = outline.filter((c) => c.status === "已完成" || c.status === "用原文").length;
  const totalWords = outline.reduce((s, c) => s + (c.words || 0), 0);

  const startGenerate = async (chapterId: string) => {
    if (generatingRef.current) return;
    const node = outline.find((c) => c.id === chapterId);
    if (!node) return;
    if (isSkipAiWrite(node)) {
      showToast(
        isOriginalFormTitle(node.title, node.num)
          ? "本章请直接使用招标书原文填写后打印签字，无需 AI 撰写"
          : "商务标本章无需应答，无需 AI 撰写",
        "info",
      );
      return;
    }

    generatingRef.current = true;
    setGeneratingId(chapterId);
    setActiveId(chapterId);
    onOutlineChange(outline.map((c) => (c.id === chapterId ? { ...c, status: "生成中" } : c)));

    try {
      const job = await createChapterGenerateJob(draftId, chapterId);
      const result = await pollWriterJobUntilDone(job.jobId, { intervalMs: 1500, timeoutMs: 3 * 60 * 1000 });
      if (result.status === "failed") {
        showToast(result.error || "本章生成失败，请重试", "error");
        onOutlineChange(outline.map((c) => (c.id === chapterId ? { ...c, status: "待生成" } : c)));
        return;
      }
      const refreshed = await getOrCreateWriterDraft(projectId);
      onOutlineChange(refreshed.outline);
      onChapterContentsChange(refreshed.chapterContents);
      showToast(`「${node.title}」内容已由 AI 生成完成`);
    } catch {
      showToast("生成任务失败，请检查网络后重试", "error");
      onOutlineChange(outline.map((c) => (c.id === chapterId ? { ...c, status: "待生成" } : c)));
    } finally {
      generatingRef.current = false;
      setGeneratingId(null);
    }
  };

  const handleSave = async () => {
    if (!activeId) return;
    try {
      await saveChapterContent(draftId, activeId, chapterContents[activeId] || "");
      showToast("本章内容已保存");
    } catch {
      showToast("保存失败，请检查网络后重试", "error");
    }
  };

  const handleContentChange = (text: string) => {
    if (!activeId) return;
    onChapterContentsChange({ ...chapterContents, [activeId]: text });
  };

  const handleInsertImage = (item: WriterImageItem) => {
    if (!activeId) return;
    const label = (item.prompt || item.filename || "插图").replace(/[[\]]/g, "");
    const inserted = editorRef.current?.insertImage(item.url, label);
    if (!inserted) {
      const line = `\n\n![${label}](${item.url})\n`;
      onChapterContentsChange({ ...chapterContents, [activeId]: (chapterContents[activeId] || "") + line });
    }
    showToast(item.mode === "flow" ? "流程图已插入当前章节" : "图片已插入当前章节");
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const blob = await exportWriterDraftDocx(draftId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${projectName}-投标书（撰写工作台导出）.docx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showToast("导出成功，已开始下载 Word 文档");
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "导出失败，请检查网络后重试", "error");
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-background-300 bg-background-100">
      {/* 头部 */}
      <div className="flex shrink-0 flex-wrap items-center gap-2.5 border-b border-background-300 px-4 py-2.5">
        <span className="flex h-8 w-8 items-center justify-center rounded-md bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
          <i className="ri-edit-2-line text-base"></i>
        </span>
        <div>
          <div className="font-heading text-sm font-semibold tracking-wide text-foreground-900">第四步 · 正文生成</div>
          <div className="text-xs text-foreground-500">按目录逐章 AI 撰写；承诺/授权/报价/偏差表等固定格式件带入招标书原文</div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={onBack}
            className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-3 text-xs font-medium text-foreground-600 transition-colors hover:bg-background-200"
          >
            <i className="ri-arrow-left-s-line text-sm"></i>
            上一步
          </button>
          <div className="hidden items-center gap-4 text-xs text-foreground-500 md:flex">
            <span>
              章节完成 <span className="font-label text-gradient font-medium">{doneCount}/{outline.length}</span>
            </span>
            <span>
              全文约 <span className="font-label text-gradient font-medium">{totalWords}</span> 字
            </span>
          </div>
        </div>
      </div>

      {/* 三栏撰写工作区 */}
      <div className="flex min-h-0 flex-1 gap-3 p-3">
        <ChapterTree
          nodes={outline}
          activeId={activeId}
          generatingId={generatingId}
          onSelect={setActiveId}
          onGenerate={startGenerate}
          onNodesChange={onOutlineChange}
        />
        <EditorPanel
          ref={editorRef}
          chapter={activeNode}
          content={chapterContents[activeId] || ""}
          generating={generatingId === activeId}
          onGenerate={() => startGenerate(activeId)}
          onSave={handleSave}
          onExport={handleExport}
          onContentChange={handleContentChange}
          exporting={exporting}
        />
        <div className="hidden lg:flex">
          <ImagePanel projectId={projectId} onInsertImage={handleInsertImage} />
        </div>
      </div>

      {/* 悬浮 AI 聊天 */}
      <FloatingChat
        projectName={projectName}
        draftId={draftId}
        chapterTitle={activeNode?.title}
        chapterExcerpt={(chapterContents[activeId] || "").slice(0, 1200)}
      />

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}
