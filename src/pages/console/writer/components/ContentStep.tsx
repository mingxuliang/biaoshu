import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Toast from "../../components/Toast";
import ChapterTree from "./ChapterTree";
import EditorPanel, { type EditorPanelHandle } from "./EditorPanel";
import ImagePanel from "./ImagePanel";
import FloatingChat from "./FloatingChat";
import {
  ApiError,
  createChapterGenerateJob,
  createGenerateAllJob,
  exportWriterDraftDocx,
  getWriterSelfCheck,
  downloadWriterTraceMatrix,
  type WriterSelfCheck,
  type GenerateAllProgress,
  type WaterCheck,
  getOrCreateWriterDraft,
  pollWriterJobUntilDone,
  saveChapterContent,
  type KnowledgeRef,
  type OutlineNode,
  type WriterImageItem,
} from "@/lib/api";
import { compactOutlineTitles, isOriginalFormTitle, isSkipAiWrite } from "@/lib/outlineNum";
import type { ImageConfig, LayoutConfig, PageConfig } from "@/mocks/writerSteps";
import { chapterCharTargets } from "@/lib/pageBudget";

/** 缺资质材料的红字提示数量，与后端 red_marker.count_gaps 同一标记。 */
function countMaterialGaps(md: string): number {
  return (md.match(/【缺少资质材料，请补充后再投标】/g) || []).length + (md.match(/【缺人员】|【缺】/g) || []).length;
}

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
  knowledgeRefs: Record<string, KnowledgeRef[]>;
  onKnowledgeRefsChange: (next: Record<string, KnowledgeRef[]>) => void;
  layout?: LayoutConfig | null;
  page?: PageConfig | null;
  imageSettings?: ImageConfig | null;
  onBack: () => void;
  docKind?: "tech" | "business";
}

export default function ContentStep({
  projectId,
  draftId,
  outline,
  onOutlineChange,
  chapterContents,
  onChapterContentsChange,
  projectName,
  knowledgeRefs,
  onKnowledgeRefsChange,
  layout,
  page,
  imageSettings,
  onBack,
  docKind = "tech",
}: ContentStepProps) {
  const docKindLabel = docKind === "business" ? "商务标" : "技术标";
  const [activeId, setActiveId] = useState<string>(outline[0]?.id ?? "");
  const [generatingId, setGeneratingId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportedDocId, setExportedDocId] = useState<string | null>(null);
  const [selfChecking, setSelfChecking] = useState(false);
  const [selfCheck, setSelfCheck] = useState<WriterSelfCheck | null>(null);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });
  const [batch, setBatch] = useState<GenerateAllProgress | null>(null);
  const [batchRunning, setBatchRunning] = useState(false);
  const [overwriteAll, setOverwriteAll] = useState(false);
  const [showFailed, setShowFailed] = useState(false);
  const [waterCheck, setWaterCheck] = useState<WaterCheck | null>(null);
  const generatingRef = useRef(false);
  const chapterContentsRef = useRef(chapterContents);
  chapterContentsRef.current = chapterContents;
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
  const chapterTarget = activeNode ? chapterCharTargets(outline, page, layout)[activeNode.id] : undefined;
  const chapterWritten = (chapterContents[activeId] || "").replace(/\s/g, "").length;

  const startGenerateAll = async () => {
    if (generatingRef.current) return;
    if (!window.confirm(overwriteAll ? "将按目录重写全部章节，已有正文会被覆盖，确定继续？" : "将按目录补全还没有正文的章节，已有正文不动，确定开始？")) {
      return;
    }
    generatingRef.current = true;
    setBatchRunning(true);
    setBatch({ total: 0, done: 0, items: [] });
    let lastDone = -1;
    const syncDraft = async (doneIds: string[]) => {
      try {
        const refreshed = await getOrCreateWriterDraft(projectId, docKind);
        onOutlineChange(refreshed.outline);
        const merged = { ...chapterContentsRef.current };
        for (const id of doneIds) merged[id] = refreshed.chapterContents[id] ?? merged[id];
        onChapterContentsChange(merged);
      } catch {
        /* 下一次进度更新会再刷新 */
      }
    };
    try {
      const job = await createGenerateAllJob(draftId, overwriteAll);
      const finished = await pollWriterJobUntilDone(job.jobId, {
        intervalMs: 2000,
        timeoutMs: 6 * 60 * 60 * 1000,
        onUpdate: (current) => {
          const result = current.result;
          if (!result) return;
          setBatch(result);
          if (result.waterCheck) setWaterCheck(result.waterCheck);
          const done = result.done ?? 0;
          if (done !== lastDone) {
            lastDone = done;
            void syncDraft((result.items ?? []).filter((item) => item.status === "done").map((item) => item.id));
          }
        },
      });
      const result = finished.result;
      if (result) {
        setBatch(result);
        if (result.waterCheck) setWaterCheck(result.waterCheck);
      }
      const doneIds = (result?.items ?? []).filter((item) => item.status === "done").map((item) => item.id);
      await syncDraft(doneIds);
      const failed = result?.failed?.length ?? 0;
      if (finished.status === "failed") {
        showToast(finished.error || "全文生成失败，请稍后重试", "error");
      } else if (failed > 0) {
        setShowFailed(true);
        showToast(`全文生成完成，${failed} 章失败，可单独重试`, "info");
      } else {
        showToast("全文生成完成");
      }
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "全文生成任务失败，请检查网络后重试", "error");
    } finally {
      generatingRef.current = false;
      setBatchRunning(false);
    }
  };

  const startGenerate = async (chapterId: string) => {
    if (generatingRef.current) {
      if (batchRunning) showToast("全文生成进行中，请等它结束后再单独生成", "info");
      return;
    }
    const node = outline.find((c) => c.id === chapterId);
    if (!node) return;
    if (isSkipAiWrite(node)) {
      showToast(
        isOriginalFormTitle(node.title, node.num)
          ? "本章内容直接取自招标书格式原文，无需 AI 撰写；有金额、人员等空白请人工填写"
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
      const result = await pollWriterJobUntilDone(job.jobId, { intervalMs: 1500, timeoutMs: 8 * 60 * 1000 });
      if (result.status === "failed") {
        showToast(result.error || "本章生成失败，请重试", "error");
        onOutlineChange(outline.map((c) => (c.id === chapterId ? { ...c, status: "待生成" } : c)));
        return;
      }
      const refreshed = await getOrCreateWriterDraft(projectId, docKind);
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

  const handleSelfCheck = async () => {
    setSelfChecking(true);
    try {
      setSelfCheck(await getWriterSelfCheck(draftId));
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "自查失败，请检查网络后重试", "error");
    } finally {
      setSelfChecking(false);
    }
  };

  const handleTraceMatrix = async () => {
    try {
      const blob = await downloadWriterTraceMatrix(draftId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${projectName}-追溯矩阵.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "追溯矩阵下载失败", "error");
    }
  };

  const gapChapters = outline
    .map((node) => ({ id: node.id, title: `${node.num || ""}${node.title}`, n: countMaterialGaps(chapterContents[node.id] || "") }))
    .filter((item) => item.n > 0);
  const gapTotal = gapChapters.reduce((sum, item) => sum + item.n, 0);

  const downloadExport = async (force: boolean) => {
    const { blob, bidDocumentId } = await exportWriterDraftDocx(draftId, force);
    setExportedDocId(bidDocumentId || null);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${projectName}-${docKindLabel}（撰写工作台导出）.docx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast("导出成功，已开始下载 Word 文档");
  };

  const handleExport = async () => {
    if (gapTotal > 0) {
      showToast(`仍有 ${gapTotal} 处缺资质材料，导出文件里已用红字标出，补齐前无法应标`, "info");
    }
    setExporting(true);
    try {
      await downloadExport(false);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "导出失败，请检查网络后重试";
      if (err instanceof ApiError && err.status === 400 && message.includes("水利施组校核未通过")) {
        if (window.confirm(`${message}\n\n仍要导出吗？`)) {
          try {
            await downloadExport(true);
          } catch (again) {
            showToast(again instanceof ApiError ? again.message : "导出失败，请检查网络后重试", "error");
          }
          return;
        }
      }
      showToast(message, "error");
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
          <div className="font-heading text-sm font-semibold tracking-wide text-foreground-900">第四步 · {docKindLabel}正文生成</div>
          <div className="text-xs text-foreground-500">按目录逐章 AI 撰写；承诺、授权、投标函、开标一览带入招标书原文，报价分项和偏离表逐条应答</div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {exportedDocId && (
            <Link
              to={`/console/audit?project=${projectId}&bidDocumentId=${exportedDocId}&scope=${docKind}`}
              className="flex h-8 items-center gap-1.5 whitespace-nowrap rounded-md border border-primary-300 px-3 text-xs font-medium text-primary-600 transition-colors hover:bg-primary-50"
            >
              <i className="ri-shield-flash-line text-sm"></i>
              用刚导出的{docKindLabel}去预审
            </Link>
          )}
          <button
            type="button"
            onClick={onBack}
            className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-3 text-xs font-medium text-foreground-600 transition-colors hover:bg-background-200"
          >
            <i className="ri-arrow-left-s-line text-sm"></i>
            上一步
          </button>
          <label className="flex cursor-pointer items-center gap-1 text-xs text-foreground-600" title="勾选后已有正文的章节也会被覆盖重写">
            <input
              type="checkbox"
              checked={overwriteAll}
              disabled={batchRunning}
              onChange={(e) => setOverwriteAll(e.target.checked)}
            />
            全部重写
          </label>
          <button
            type="button"
            onClick={startGenerateAll}
            disabled={batchRunning || outline.length === 0}
            className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-3 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <i className={`${batchRunning ? "ri-loader-4-line animate-spin" : "ri-magic-line"} text-sm`}></i>
            {batchRunning ? "全文生成中" : "生成全部章节"}
          </button>
          <div className="hidden items-center gap-4 text-xs text-foreground-500 md:flex">
            <span>
              章节完成 <span className="font-label text-gradient font-medium">{doneCount}/{outline.length}</span>
            </span>
            <span>
              全文约 <span className="font-label text-gradient font-medium">{totalWords}</span> 字
            </span>
            {chapterTarget ? (
              <span>
                本章目标约 <span className="font-label text-gradient font-medium">{chapterTarget}</span> 字 / 已写{" "}
                <span className="font-label text-gradient font-medium">{chapterWritten}</span> 字
              </span>
            ) : null}
          </div>
        </div>
      </div>

      {batch ? (
        <div className="shrink-0 border-b border-background-300 bg-background-50 px-4 py-2 text-xs text-foreground-600">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-medium text-foreground-800">
              全文生成 {batch.done ?? 0}/{batch.total ?? 0} 章
            </span>
            {batch.skipped ? <span className="text-foreground-500">跳过已有正文 {batch.skipped} 章</span> : null}
            {(batch.items ?? []).find((item) => item.status === "running") ? (
              <span className="truncate text-primary-600">
                正在写：
                {(batch.items ?? [])
                  .filter((item) => item.status === "running")
                  .map((item) => item.title)
                  .join("、")}
              </span>
            ) : null}
            {(batch.failed?.length ?? 0) > 0 ? (
              <button
                type="button"
                onClick={() => setShowFailed((value) => !value)}
                className="cursor-pointer text-red-600 hover:underline"
              >
                {batch.failed?.length} 章失败{showFailed ? "（收起）" : "（查看）"}
              </button>
            ) : null}
            {!batchRunning ? (
              <button
                type="button"
                onClick={() => {
                  setBatch(null);
                  setShowFailed(false);
                }}
                className="ml-auto cursor-pointer text-foreground-400 hover:text-foreground-700"
              >
                关闭
              </button>
            ) : null}
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-background-200">
            <div
              className="h-full rounded-full bg-primary-500 transition-all"
              style={{ width: `${batch.total ? Math.min(100, Math.round(((batch.done ?? 0) / batch.total) * 100)) : 0}%` }}
            />
          </div>
          {showFailed && (batch.failed?.length ?? 0) > 0 ? (
            <ul className="mt-1.5 space-y-0.5 text-[11px] text-red-600">
              {batch.failed?.map((item) => (
                <li key={item.id} className="flex items-center gap-2">
                  <span className="truncate">
                    「{item.title}」{item.error ? `：${item.error}` : ""}
                  </span>
                  <button
                    type="button"
                    disabled={batchRunning}
                    onClick={() => void startGenerate(item.id)}
                    className="shrink-0 cursor-pointer text-primary-600 hover:underline disabled:opacity-50"
                  >
                    重试
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {gapChapters.length > 0 ? (
        <div className="shrink-0 border-b border-red-200 bg-red-50 px-4 py-2 text-xs leading-relaxed text-red-700">
          <span className="text-sm font-bold">
            有 {gapChapters.length} 章缺资质材料（共 {gapTotal} 处），缺这些材料无法应标。
          </span>
          请到「企业资质证照库」录入并审核入库后，重新生成对应章节：
          {gapChapters.slice(0, 8).map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setActiveId(item.id)}
              className="ml-2 cursor-pointer font-semibold underline"
            >
              {item.title}
            </button>
          ))}
          {gapChapters.length > 8 ? " 等" : ""}
        </div>
      ) : null}

      {waterCheck && (waterCheck.blocking.length > 0 || waterCheck.advisory.length > 0 || (waterCheck.siteGaps?.length ?? 0) > 0) ? (
        <div className="shrink-0 border-b border-accent-200 bg-accent-50 px-4 py-2 text-xs leading-relaxed text-accent-800">
          <div className="font-medium">
            水利校核：{waterCheck.blocking.length} 条需处理
            {waterCheck.advisory.length ? `，${waterCheck.advisory.length} 条建议` : ""}
            {waterCheck.siteGaps?.length ? `，勘察待补 ${waterCheck.siteGaps.length} 项` : ""}
          </div>
          {waterCheck.siteGaps?.length ? (
            <div className="mt-0.5">勘察资料还缺：{waterCheck.siteGaps.join("、")}。正文里这些项会标成待补，请在工程事实里补上后再生成。</div>
          ) : null}
          {[...waterCheck.blocking, ...waterCheck.advisory].slice(0, 8).map((item, index) => (
            <button
              key={`${item.chapterId}-${index}`}
              type="button"
              onClick={() => item.chapterId && setActiveId(item.chapterId)}
              className="mt-0.5 block cursor-pointer text-left hover:underline"
            >
              {item.axis} · {item.message}
            </button>
          ))}
        </div>
      ) : null}

      {/* 三栏撰写工作区 */}
      <div className="flex min-h-0 flex-1 gap-3 p-3">
        <ChapterTree
          nodes={outline}
          activeId={activeId}
          onSelect={setActiveId}
          onGenerate={startGenerate}
          onNodesChange={onOutlineChange}
        />
        <EditorPanel
          ref={editorRef}
          draftId={draftId}
          chapter={activeNode}
          content={chapterContents[activeId] || ""}
          generating={generatingId === activeId}
          onGenerate={() => startGenerate(activeId)}
          onSave={handleSave}
          onExport={handleExport}
          onSelfCheck={handleSelfCheck}
          selfChecking={selfChecking}
          onContentChange={handleContentChange}
          exporting={exporting}
          layout={layout}
        />
        <div className="hidden lg:flex">
          <ImagePanel
            projectId={projectId}
            draftId={draftId}
            chapterId={activeId}
            chapterNum={activeNode?.num}
            chapterTitle={activeNode?.title}
            chapterIdea={activeNode?.idea}
            chapterContent={chapterContents[activeId] || ""}
            imageSettings={imageSettings}
            knowledgeRefs={knowledgeRefs}
            onKnowledgeRefsChange={onKnowledgeRefsChange}
            onInsertImage={handleInsertImage}
          />
        </div>
      </div>

      {selfCheck && (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/30 p-6">
          <div className="flex max-h-full w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-background-300 bg-background-50 shadow-xl">
            <div className="flex items-center gap-2 border-b border-background-300 px-4 py-3">
              <h3 className="text-sm font-semibold text-foreground-950">
                提交前自查{selfCheck.ok ? "：各项均通过" : ""}
              </h3>
              <button
                type="button"
                onClick={handleTraceMatrix}
                className="ml-auto h-7 cursor-pointer rounded-md border border-background-300 px-2.5 text-xs text-foreground-600 hover:bg-background-200"
              >
                下载追溯矩阵
              </button>
              <button
                type="button"
                onClick={() => setSelfCheck(null)}
                className="h-7 cursor-pointer rounded-md border border-background-300 px-2.5 text-xs text-foreground-600 hover:bg-background-200"
              >
                关闭
              </button>
            </div>
            <div className="min-h-0 flex-1 space-y-3 overflow-auto px-4 py-3 text-xs leading-relaxed text-foreground-700">
              {selfCheck.checks.map((check) => (
                <div key={check.name}>
                  <div className="font-semibold text-foreground-950">
                    {check.ok ? "通过" : `${check.problems.length} 项提示`} · {check.name}
                  </div>
                  {check.problems.slice(0, 12).map((problem, index) => (
                    <div key={index} className="pl-3 text-foreground-600">
                      - {problem}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 悬浮 AI 聊天 */}
      <FloatingChat
        projectName={projectName}
        draftId={draftId}
        chapterId={activeId}
        onApplied={async () => {
          try {
            const refreshed = await getOrCreateWriterDraft(projectId, docKind);
            onOutlineChange(refreshed.outline);
            onChapterContentsChange(refreshed.chapterContents);
          } catch {
            /* 对话已经写回，刷新失败时下次进入正文仍会读到新内容 */
          }
        }}
      />
    </div>
  );
}
