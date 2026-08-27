import { useEffect, useMemo, useRef, useState } from "react";
import OutlineTree from "./OutlineTree";
import KnowledgePicker from "./KnowledgePicker";
import FloatingChat from "./FloatingChat";
import Toast from "../../components/Toast";
import WordViewer, { type WordViewerHandle } from "../../parse/components/WordViewer";
import {
  createOutlineJob,
  getLatestChecklist,
  getOrCreateWriterDraft,
  getTenderParagraphs,
  pollWriterJobUntilDone,
  updateWriterDraft,
  type Checklist,
  type KnowledgeRef,
  type OutlineNode,
  type ProjectDto,
  type TenderParagraph,
} from "@/lib/api";
import { compactOutlineTitles, displayOutlineTitle, isOriginalFormTitle, renumberOutline } from "@/lib/outlineNum";
import { findTenderAnchor } from "@/lib/tenderAnchor";

interface OutlineStepProps {
  projectId: string;
  projectName: string;
  project?: ProjectDto;
  draftId: string;
  outline: OutlineNode[];
  onOutlineChange: (nodes: OutlineNode[]) => void;
  initialKnowledgeRefs?: Record<string, KnowledgeRef[]>;
  onOutlineRegenerated?: (payload?: { chapterContents?: Record<string, string> }) => void;
  onNext: () => void;
  onBack: () => void;
}

type RightTab = "outline" | "tenderDoc" | "score" | "overview";

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

function getTopLevelNodes(nodes: OutlineNode[]): OutlineNode[] {
  return nodes.filter((n) => n.parentId === null);
}

export default function OutlineStep({
  projectId,
  projectName,
  project,
  draftId,
  outline,
  onOutlineChange,
  initialKnowledgeRefs,
  onOutlineRegenerated,
  onNext,
  onBack,
}: OutlineStepProps) {
  const [activeId, setActiveId] = useState<string>(outline[0]?.id ?? "");
  const [tab, setTab] = useState<RightTab>("outline");
  const [pickerId, setPickerId] = useState<string | null>(null);
  const [knowledgeMap, setKnowledgeMap] = useState<Record<string, KnowledgeRef[]>>(
    initialKnowledgeRefs ?? {}
  );
  const [generatingOutline, setGeneratingOutline] = useState(false);
  const [scoreFilter, setScoreFilter] = useState("全部");
  const [scoreTab, setScoreTab] = useState<"rules" | "must">("rules");
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });

  const [checklist, setChecklist] = useState<Checklist | null>(null);
  const [checklistLoading, setChecklistLoading] = useState(true);

  const [tenderParagraphs, setTenderParagraphs] = useState<TenderParagraph[]>([]);
  const [tenderLoading, setTenderLoading] = useState(false);
  const [tenderError, setTenderError] = useState<string | null>(null);
  const [tenderAnchor, setTenderAnchor] = useState<number | null>(null);

  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const viewerRef = useRef<WordViewerHandle>(null);

  useEffect(() => {
    if (!outline.some((n) => n.id === activeId)) {
      setActiveId(outline[0]?.id ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outline]);

  useEffect(() => {
    let cancelled = false;
    setChecklistLoading(true);
    getLatestChecklist(projectId)
      .then((data) => {
        if (!cancelled) setChecklist(data);
      })
      .catch(() => {
        if (!cancelled) setChecklist(null);
      })
      .finally(() => {
        if (!cancelled) setChecklistLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    if (!checklist?.tender_document_id) return;
    let cancelled = false;
    setTenderLoading(true);
    setTenderError(null);
    getTenderParagraphs(checklist.tender_document_id)
      .then((data) => {
        if (!cancelled) setTenderParagraphs(data);
      })
      .catch(() => {
        if (!cancelled) setTenderError("招标文件原文加载失败");
      })
      .finally(() => {
        if (!cancelled) setTenderLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [checklist?.tender_document_id]);

  const active = outline.find((n) => n.id === activeId) ?? outline[0];
  const optimizedCount = outline.filter((n) => n.optimized).length;
  const totalWeight = useMemo(() => outline.reduce((s, c) => s + (c.weight ?? 0), 0), [outline]);

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const update = (id: string, patch: Partial<OutlineNode>) => {
    onOutlineChange(outline.map((n) => (n.id === id ? { ...n, ...patch } : n)));
  };

  const generateOutline = async (replaceExisting: boolean) => {
    if (replaceExisting && outline.length > 0) {
      const ok = window.confirm(
        "将按招标文件重新生成全部目录。当前目录、编写思路、章节知识库绑定和已生成正文都会被替换，是否继续？",
      );
      if (!ok) return;
    }
    setGeneratingOutline(true);
    try {
      const job = await createOutlineJob(draftId);
      const result = await pollWriterJobUntilDone(job.jobId, { intervalMs: 1500, timeoutMs: 10 * 60 * 1000 });
      if (result.status === "failed") {
        showToast(result.error || "目录生成失败，请重试", "error");
        return;
      }
      const refreshed = await getOrCreateWriterDraft(projectId);
      const compacted = compactOutlineTitles(refreshed.outline || []);
      onOutlineChange(compacted);
      updateWriterDraft(draftId, { outline: compacted }).catch(() => {
        /* 标题收短失败不阻塞目录展示，进入下一步时会再次保存 */
      });
      setKnowledgeMap({});
      setActiveId(compacted[0]?.id ?? "");
      onOutlineRegenerated?.({ chapterContents: refreshed.chapterContents || {} });
      showToast(
        replaceExisting
          ? `已重新生成全部目录，共 ${compacted.length} 个节点`
          : "已生成应标目录：短名称原样保留，需求说明已提炼为短标题",
      );
    } catch {
      showToast("目录生成失败，请检查网络后重试", "error");
    } finally {
      setGeneratingOutline(false);
    }
  };

  const addTopChapter = () => {
    const newId = `p-${Date.now()}`;
    const n = getTopLevelNodes(outline).length + 1;
    const base: OutlineNode = {
      id: newId,
      num: String(n),
      title: `新增章节 ${n}`,
      idea: "请描述本章编写思路…",
      aiIdea: "围绕评分点补充结构化的编写思路…",
      optimized: false,
      weight: 0,
      dimension: null,
      parentId: null,
      expanded: false,
      status: "待生成",
      words: 0,
      aiRounds: 0,
    };
    onOutlineChange(renumberOutline([...outline, base]));
    setActiveId(newId);
    setTab("outline");
    showToast("已新增章节，可编辑标题与编写思路");
  };

  const optimizeOne = (id: string) => {
    const target = outline.find((n) => n.id === id);
    if (!target) return;
    update(id, { idea: target.aiIdea, optimized: true });
    showToast(`「${target.title}」编写思路已采纳 AI 优化`);
  };

  const optimizeAll = () => {
    onOutlineChange(outline.map((n) => ({ ...n, idea: n.aiIdea, optimized: true })));
    showToast("全部章节编写思路已 AI 优化完成");
  };

  const saveOutline = () => {
    updateWriterDraft(draftId, { outline }).catch(() => {
      /* 静默失败，用户仍可继续编辑；进入下一步时会再次尝试保存 */
    });
  };

  const saveKnowledge = (refs: KnowledgeRef[]) => {
    if (pickerId) {
      const next = { ...knowledgeMap, [pickerId]: refs };
      setKnowledgeMap(next);
      setPickerId(null);
      updateWriterDraft(draftId, { knowledgeRefs: next }).catch(() => {
        /* 静默失败，用户仍可继续编辑；进入下一步时会再次尝试保存 */
      });
      showToast(refs.length > 0 ? `已为章节绑定 ${refs.length} 篇参考知识库文档` : "已清除该章节知识库引用", refs.length > 0 ? "success" : "info");
    }
  };

  const handleSelect = (id: string) => {
    setActiveId(id);
    if (tab === "tenderDoc") {
      const node = outline.find((n) => n.id === id);
      const idx = findTenderAnchor(node, tenderParagraphs);
      setTenderAnchor(idx);
      window.setTimeout(() => {
        if (idx != null) viewerRef.current?.scrollToIndex(idx);
      }, 80);
      if (idx == null && tenderParagraphs.length > 0) {
        showToast("未在招标文件中定位到该章对应条款", "info");
      }
      return;
    }
    if (tab === "outline") {
      window.setTimeout(() => {
        cardRefs.current[id]?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 50);
    }
  };

  useEffect(() => {
    if (tab !== "outline" || !activeId) return;
    window.setTimeout(() => {
      cardRefs.current[activeId]?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 50);
  }, [tab]);

  const tabCls = (t: RightTab) =>
    `flex cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
      tab === t ? "bg-primary-500 text-background-50" : "text-foreground-600 hover:bg-background-200"
    }`;

  const scoreRules = checklist?.scoreRules ?? [];
  const mustRespond = checklist?.mustRespond ?? [];
  const scoreDims = useMemo(() => ["全部", ...Array.from(new Set(scoreRules.map((r) => r.dimension)))], [scoreRules]);
  const filteredScoreRules = scoreFilter === "全部" ? scoreRules : scoreRules.filter((r) => r.dimension === scoreFilter);

  const pickerNode = outline.find((n) => n.id === pickerId);

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-background-300 bg-background-100">
      {/* 头部 */}
      <div className="flex shrink-0 flex-wrap items-center gap-2.5 border-b border-background-300 px-4 py-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-md bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
          <i className="ri-list-check-3 text-base"></i>
        </span>
        <div>
          <div className="font-heading text-sm font-semibold tracking-wide text-foreground-900">第三步 · 目录生成</div>
          <div className="text-xs text-foreground-500">功能需求逐条对应；项目管理等其余需求整理为应标目录并覆盖全文</div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <span className="rounded-md bg-secondary-100 px-2 py-1 text-[11px] font-medium text-secondary-700">
            已优化 {optimizedCount}/{outline.length} 章 · 权重 {totalWeight} 分
          </span>
          {outline.length > 0 && (
            <button
              type="button"
              onClick={() => generateOutline(true)}
              disabled={generatingOutline}
              className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-accent-200 bg-accent-50 px-3 text-xs font-medium text-accent-700 transition-colors hover:bg-accent-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <i className={`${generatingOutline ? "ri-loader-4-line animate-spin" : "ri-refresh-line"} text-xs`}></i>
              {generatingOutline ? "正在重新生成…" : "重新生成目录"}
            </button>
          )}
          {outline.length > 0 && (
            <button
              type="button"
              onClick={optimizeAll}
              disabled={generatingOutline}
              className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-primary-200 bg-primary-50 px-3 text-xs font-medium text-primary-600 transition-colors hover:bg-primary-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <i className="ri-sparkling-2-line text-xs"></i>
              AI 整体优化目录
            </button>
          )}
          <button
            type="button"
            onClick={addTopChapter}
            disabled={generatingOutline}
            className="flex h-8 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-3 text-xs font-medium text-foreground-600 transition-colors hover:bg-background-200 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <i className="ri-add-line text-sm"></i>
            新增章节
          </button>
        </div>
      </div>

      {/* 内容区 */}
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* 左：目录树 */}
        <div className="flex min-h-0 shrink-0 flex-col border-b border-background-300 p-3 lg:border-b-0 lg:border-r">
          <OutlineTree
            nodes={outline}
            activeId={activeId}
            onSelect={handleSelect}
            onNodesChange={onOutlineChange}
            onKnowledge={(id) => setPickerId(id)}
            knowledgeCounts={Object.fromEntries(Object.entries(knowledgeMap).map(([k, v]) => [k, v.length]))}
            locateHint={
              tab === "tenderDoc"
                ? "当前在招标文件页：点击章节锚定到对应需求条款"
                : "当前在编写思路页：点击章节定位到该章编写思路"
            }
          />
        </div>

        {/* 右：标签页 */}
        <div className="flex min-h-0 flex-1 flex-col">
          {/* 标签切换 */}
          <div className="flex shrink-0 items-center gap-1.5 border-b border-background-300 bg-background-50 px-4 py-2">
            <button type="button" className={tabCls("outline")} onClick={() => setTab("outline")}>
              <i className="ri-quill-pen-line text-xs"></i>
              目录编写思路
            </button>
            <button type="button" className={tabCls("tenderDoc")} onClick={() => setTab("tenderDoc")}>
              <i className="ri-file-text-line text-xs"></i>
              招标文件
            </button>
            <button type="button" className={tabCls("score")} onClick={() => setTab("score")}>
              <i className="ri-star-line text-xs"></i>
              评分点
            </button>
            <button type="button" className={tabCls("overview")} onClick={() => setTab("overview")}>
              <i className="ri-building-line text-xs"></i>
              项目概述
            </button>
          </div>

          {/* ========== 目录编写思路 ========== */}
          {tab === "outline" && (
            <div className="flex min-h-0 flex-1 flex-col">
              {outline.length === 0 ? (
                <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-6 py-10 text-center">
                  <span className="flex h-14 w-14 items-center justify-center rounded-xl border border-primary-200 bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
                    <i className="ri-sparkling-2-line text-2xl"></i>
                  </span>
                  <div className="text-sm font-semibold text-foreground-900">尚未生成目录</div>
                  <p className="max-w-md text-xs text-foreground-500">
                    将由大模型阅读招标文件全文，按招标每一条独立要求编制可逐条打勾的应标目录。生成约需 1～3 分钟。
                  </p>
                  <button
                    type="button"
                    onClick={() => generateOutline(false)}
                    disabled={generatingOutline}
                    className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <i className={`${generatingOutline ? "ri-loader-4-line animate-spin" : "ri-magic-line"} text-sm`}></i>
                    {generatingOutline ? "AI 正在生成目录…" : "AI 生成目录"}
                  </button>
                </div>
              ) : (
                <>
                  <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
                    {outline.map((node) => {
                      const isActive = node.id === activeId;
                      const refs = knowledgeMap[node.id] ?? [];
                      const linkedRules = node.dimension
                        ? scoreRules.filter((r) => r.dimension === node.dimension)
                        : [];
                      return (
                        <div
                          key={node.id}
                          ref={(el) => {
                            cardRefs.current[node.id] = el;
                          }}
                          className={`rounded-lg border bg-background-50 p-4 transition-colors ${
                            isActive ? "border-primary-300 ring-1 ring-primary-200/60" : "border-background-200"
                          }`}
                        >
                          {/* 章节标题行 */}
                          <div className="mb-3 flex flex-wrap items-center gap-2">
                            <span className="font-label shrink-0 rounded bg-secondary-100 px-2 py-0.5 text-xs font-medium text-secondary-700">
                              {node.num}
                            </span>
                            <span className="min-w-0 truncate text-sm font-semibold text-foreground-900">{displayOutlineTitle(node.title, node.num)}</span>
                            {node.optimized && (
                              <span className="flex items-center gap-1 rounded bg-primary-50 px-2 py-0.5 text-[11px] font-medium text-primary-600">
                                <i className="ri-sparkling-2-line"></i>已 AI 优化
                              </span>
                            )}
                            <span className="ml-auto rounded bg-accent-100 px-2 py-0.5 text-[11px] font-medium text-accent-700">
                              权重 {node.weight ?? 0} 分
                            </span>
                          </div>

                          {/* 编写思路标签 */}
                          <div className="mb-2 flex items-center gap-1.5">
                            <i className="ri-lightbulb-flash-line text-sm text-accent-500"></i>
                            <span className="text-xs font-medium text-foreground-700">
                              {isOriginalFormTitle(node.title, node.num) || node.status === "用原文"
                                ? "使用招标书原文"
                                : "编写思路"}
                            </span>
                            <span className="text-[11px] text-foreground-500">
                              {isOriginalFormTitle(node.title, node.num) || node.status === "用原文"
                                ? "—— 固定格式件填写后打印签字，不展开目录、不撰写正文"
                                : "—— 功能点写应实现条款；其余需求写应覆盖全文，生成正文时按此应标"}
                            </span>
                          </div>

                          {/* 编写思路输入 */}
                          <div className="mb-3">
                            <textarea
                              value={node.idea}
                              onChange={(e) => update(node.id, { idea: e.target.value })}
                              onBlur={saveOutline}
                              rows={8}
                              maxLength={8000}
                              className="w-full resize-none rounded-md border border-background-300 bg-background-50 px-3 py-2.5 text-sm leading-relaxed text-foreground-800 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20"
                            />
                            <div className="mt-1 flex items-center justify-between text-[11px] text-foreground-400">
                              <span>{node.idea.length}/8000</span>
                              <button
                                type="button"
                                onClick={() => update(node.id, { idea: node.aiIdea, optimized: true })}
                                className="flex cursor-pointer items-center gap-1 text-primary-600 hover:text-primary-700"
                              >
                                <i className="ri-sparkling-2-line text-xs"></i>
                                采纳 AI 建议
                              </button>
                            </div>
                          </div>

                          {/* AI 优化建议（可折叠） */}
                          {!node.optimized && node.aiIdea && (
                            <div className="mb-3 rounded-lg border border-dashed border-background-300 bg-background-100/70 p-3">
                              <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-foreground-700">
                                <i className="ri-sparkling-2-line text-primary-500"></i>
                                AI 优化建议
                              </div>
                              <p className="whitespace-pre-wrap text-[13px] leading-[1.8] text-foreground-600">{node.aiIdea}</p>
                            </div>
                          )}

                          {/* ====== 关联招标书解析规则（按维度实时匹配） ====== */}
                          {linkedRules.length > 0 && (
                            <div className="mb-3 rounded-lg border border-accent-200/60 bg-accent-50/40 p-3">
                              <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-foreground-800">
                                <i className="ri-links-line text-accent-500"></i>
                                关联招标书解析规则 · {node.dimension}
                              </div>
                              <div className="space-y-1.5">
                                {linkedRules.map((rule) => (
                                  <div key={rule.id} className="flex items-start gap-2 rounded-md bg-background-50 px-2.5 py-2">
                                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded bg-primary-100 text-[10px] font-bold text-primary-700">
                                      {rule.weight}
                                    </span>
                                    <div className="min-w-0 flex-1">
                                      <div className="flex items-center gap-1.5">
                                        <span className="rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] font-medium text-secondary-700">
                                          {rule.dimension}
                                        </span>
                                        <span className="text-[11px] text-foreground-500">{rule.sectionPath}</span>
                                      </div>
                                      <div className="mt-0.5 text-xs text-foreground-700">{rule.detail}</div>
                                    </div>
                                  </div>
                                ))}
                              </div>
                              <div className="mt-2 flex items-center gap-1 text-[11px] text-foreground-500">
                                <i className="ri-information-line text-accent-500"></i>
                                本章编写思路已对标 {linkedRules.length} 条解析规则，共 {linkedRules.reduce((s, r) => s + r.weight, 0)} 分
                              </div>
                            </div>
                          )}

                          {/* 已绑定知识库 */}
                          {refs.length > 0 && (
                            <div className="mb-3 rounded-lg border border-background-200 bg-background-50 p-3">
                              <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-foreground-700">
                                <i className="ri-bookmark-line text-primary-500"></i>
                                参考知识库
                              </div>
                              <div className="flex flex-wrap gap-1.5">
                                {refs.map((ref) => (
                                  <span
                                    key={ref.docId}
                                    className="flex items-center gap-1 rounded bg-secondary-100 px-2 py-0.5 text-[11px] text-secondary-700"
                                  >
                                    <i className={`${ref.mode === "ai" ? "ri-sparkling-2-line text-accent-500" : "ri-bookmark-3-line text-primary-500"} text-xs`}></i>
                                    {ref.docTitle}
                                    {ref.chapters.length > 0 && (
                                      <span className="text-secondary-500">（{ref.chapters.length}章）</span>
                                    )}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* 操作 */}
                          <div className="flex items-center justify-end gap-2">
                            <button
                              type="button"
                              onClick={() => setPickerId(node.id)}
                              className={`flex h-7 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 text-xs font-medium transition-colors ${
                                refs.length > 0
                                  ? "border border-primary-200 bg-primary-50 text-primary-600 hover:bg-primary-100"
                                  : "border border-background-300 bg-background-50 text-foreground-600 hover:bg-background-200"
                              }`}
                            >
                              <i className="ri-bookmark-line text-xs"></i>
                              参考知识库 {refs.length > 0 ? `(${refs.length})` : ""}
                            </button>
                            <button
                              type="button"
                              onClick={() => optimizeOne(node.id)}
                              className="flex h-7 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-primary-200 bg-primary-50 px-2.5 text-xs font-medium text-primary-600 transition-colors hover:bg-primary-100"
                            >
                              <i className="ri-sparkling-2-line text-xs"></i>
                              AI 优化本章
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* 底部操作栏 */}
                  <div className="flex shrink-0 items-center justify-between border-t border-background-300 bg-background-50 px-4 py-3">
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={onBack}
                        className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
                      >
                        <i className="ri-arrow-left-s-line text-base"></i>
                        上一步
                      </button>
                      <span className="hidden text-[11px] text-foreground-500 lg:block">
                        <i className="ri-information-line mr-1 text-primary-500"></i>
                        共 {outline.length} 个章节，已优化 {optimizedCount} 章，剩余 {outline.length - optimizedCount} 章待优化
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={onNext}
                      disabled={generatingOutline || outline.length === 0}
                      className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      目录确认，进入正文生成
                      <i className="ri-arrow-right-s-line text-base"></i>
                    </button>
                  </div>
                </>
              )}
            </div>
          )}

          {/* ========== 招标文件 ========== */}
          {tab === "tenderDoc" && (
            <div className="flex min-h-0 flex-1 flex-col p-3">
              {checklistLoading || tenderLoading ? (
                <div className="flex flex-1 items-center justify-center text-xs text-foreground-500">
                  <i className="ri-loader-4-line mr-1.5 animate-spin"></i>
                  正在加载招标文件原文…
                </div>
              ) : !checklist?.tender_document_id ? (
                <div className="flex flex-1 items-center justify-center text-xs text-foreground-500">
                  暂无招标文件记录，请先完成招标解析
                </div>
              ) : tenderError ? (
                <div className="flex flex-1 items-center justify-center text-xs text-red-500">{tenderError}</div>
              ) : (
                <WordViewer
                  ref={viewerRef}
                  projectName={projectName}
                  projectCode={project?.code ?? ""}
                  tenderDocumentId={checklist.tender_document_id}
                  fileName={projectName}
                  paragraphs={tenderParagraphs}
                  anchorIndex={tenderAnchor}
                />
              )}
            </div>
          )}

          {/* ========== 评分点 ========== */}
          {tab === "score" && (
            <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
              {/* 左侧：评分维度切换 */}
              <div className="min-h-0 shrink-0 border-b border-background-300 bg-background-50 p-3 lg:w-56 lg:border-b-0 lg:border-r">
                <div className="mb-2 px-1 text-xs font-semibold text-foreground-700">评分维度</div>
                <div className="flex gap-1.5 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible">
                  {scoreDims.map((dim) => (
                    <button
                      key={dim}
                      type="button"
                      onClick={() => setScoreFilter(dim)}
                      className={`flex shrink-0 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 py-1.5 text-xs transition-colors ${
                        scoreFilter === dim
                          ? "bg-primary-500 text-background-50"
                          : "text-foreground-600 hover:bg-background-200"
                      }`}
                    >
                      {dim}
                      {dim !== "全部" && (
                        <span className={`font-label text-[10px] ${scoreFilter === dim ? "text-background-50/80" : "text-foreground-400"}`}>
                          {scoreRules.filter((r) => r.dimension === dim).length}
                        </span>
                      )}
                    </button>
                  ))}
                  {!checklistLoading && scoreRules.length === 0 && (
                    <div className="px-1 text-[11px] text-foreground-400">暂无评分规则，请先完成招标解析</div>
                  )}
                </div>
              </div>

              {/* 右侧：评分规则 + 废标条款 */}
              <div className="flex min-h-0 flex-1 flex-col">
                {/* 子标签 */}
                <div className="flex shrink-0 items-center gap-1 border-b border-background-300 bg-background-50 px-4 py-2">
                  <button
                    type="button"
                    onClick={() => setScoreTab("rules")}
                    className={`cursor-pointer whitespace-nowrap rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                      scoreTab === "rules" ? "bg-primary-500 text-background-50" : "text-foreground-600 hover:bg-background-200"
                    }`}
                  >
                    评分规则 ({filteredScoreRules.length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setScoreTab("must")}
                    className={`cursor-pointer whitespace-nowrap rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                      scoreTab === "must" ? "bg-primary-500 text-background-50" : "text-foreground-600 hover:bg-background-200"
                    }`}
                  >
                    星号/废标条款 ({mustRespond.length})
                  </button>
                </div>

                <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
                  {scoreTab === "rules" && (
                    <>
                      <div className="mb-1 flex items-center gap-2">
                        <h4 className="font-heading text-sm font-semibold text-foreground-900">
                          {scoreFilter === "全部" ? "全部评分规则" : `${scoreFilter}评分规则`}
                        </h4>
                        <span className="rounded bg-secondary-100 px-2 py-0.5 text-[11px] font-medium text-secondary-700">
                          {filteredScoreRules.length} 条
                        </span>
                      </div>
                      {filteredScoreRules.map((rule) => (
                        <div key={rule.id} className="rounded-lg border border-background-200 bg-background-50 p-3">
                          <div className="mb-2 flex items-center gap-2">
                            <span className="rounded bg-primary-100 px-2 py-0.5 text-[11px] font-medium text-primary-700">{rule.dimension}</span>
                            <span className="rounded bg-accent-100 px-2 py-0.5 text-[11px] font-medium text-accent-700">{rule.weight} 分</span>
                            {rule.isEssential && (
                              <span className="rounded bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-600">关键项</span>
                            )}
                            <span
                              className={`ml-auto rounded px-2 py-0.5 text-[11px] font-medium ${
                                rule.responseStatus === "已覆盖"
                                  ? "bg-green-50 text-green-600"
                                  : rule.responseStatus === "部分"
                                    ? "bg-amber-50 text-amber-600"
                                    : "bg-red-50 text-red-600"
                              }`}
                            >
                              {rule.responseStatus}
                            </span>
                          </div>
                          <div className="text-xs text-foreground-700">{rule.detail}</div>
                          <div className="mt-1.5 text-[11px] text-foreground-500">
                            <i className="ri-map-pin-line mr-1 text-primary-500"></i>
                            关联目录：{rule.sectionPath}
                          </div>
                        </div>
                      ))}
                      {filteredScoreRules.length === 0 && (
                        <div className="py-10 text-center text-xs text-foreground-500">暂无评分规则数据</div>
                      )}
                    </>
                  )}

                  {scoreTab === "must" && (
                    <>
                      <div className="mb-1 flex items-center gap-2">
                        <h4 className="font-heading text-sm font-semibold text-foreground-900">星号条款与废标条款</h4>
                        <span className="rounded bg-secondary-100 px-2 py-0.5 text-[11px] font-medium text-secondary-700">
                          {mustRespond.length} 条
                        </span>
                      </div>
                      {mustRespond.map((item) => (
                        <div key={item.id} className="rounded-lg border border-background-200 bg-background-50 p-3">
                          <div className="mb-2 flex items-center gap-2">
                            <span
                              className={`rounded px-2 py-0.5 text-[11px] font-medium ${
                                item.type === "星号条款"
                                  ? "bg-amber-50 text-amber-700"
                                  : item.type === "废标条款"
                                    ? "bg-red-50 text-red-700"
                                    : "bg-blue-50 text-blue-700"
                              }`}
                            >
                              {item.type}
                            </span>
                            <span
                              className={`ml-auto rounded px-2 py-0.5 text-[11px] font-medium ${
                                item.status === "已响应" ? "bg-green-50 text-green-600" : "bg-red-50 text-red-600"
                              }`}
                            >
                              {item.status}
                            </span>
                          </div>
                          <div className="text-xs font-medium text-foreground-800">{item.clause}</div>
                          <div className="mt-1 text-[11px] text-foreground-500">
                            <i className="ri-file-list-line mr-1 text-primary-500"></i>
                            原文出处：{item.original}
                          </div>
                        </div>
                      ))}
                      {mustRespond.length === 0 && (
                        <div className="py-10 text-center text-xs text-foreground-500">暂无星号/废标条款数据</div>
                      )}
                    </>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ========== 项目概述 ========== */}
          {tab === "overview" && (
            <div className="flex min-h-0 flex-1 flex-col items-center overflow-y-auto bg-background-200/60 px-4 py-5">
              <div className="w-full max-w-3xl space-y-4 rounded-lg bg-background-50 p-6 shadow-sm">
                <div className="mb-2 border-b border-background-200 pb-3 text-center">
                  <div className="font-heading text-base font-semibold text-foreground-900">项目概述</div>
                  <div className="mt-1 text-[11px] text-foreground-500">招标编号：{project?.code ?? "—"}</div>
                </div>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="rounded-lg border border-background-200 bg-background-100 p-3">
                    <div className="mb-1 text-[11px] text-foreground-500">项目名称</div>
                    <div className="text-xs font-medium text-foreground-800">{projectName}</div>
                  </div>
                  <div className="rounded-lg border border-background-200 bg-background-100 p-3">
                    <div className="mb-1 text-[11px] text-foreground-500">项目类型</div>
                    <div className="text-xs font-medium text-foreground-800">{project?.type ?? "—"}</div>
                  </div>
                  <div className="rounded-lg border border-background-200 bg-background-100 p-3">
                    <div className="mb-1 text-[11px] text-foreground-500">预算</div>
                    <div className="text-xs font-medium text-foreground-800">
                      {checklist?.vetoParams.budget_cap_wan != null
                        ? `${checklist.vetoParams.budget_cap_wan} 万元（解析自招标文件）`
                        : project?.budget ?? "待定"}
                    </div>
                  </div>
                  <div className="rounded-lg border border-background-200 bg-background-100 p-3">
                    <div className="mb-1 text-[11px] text-foreground-500">投标截止</div>
                    <div className="text-xs font-medium text-foreground-800">{project?.deadline ?? "—"}</div>
                  </div>
                  <div className="rounded-lg border border-background-200 bg-background-100 p-3">
                    <div className="mb-1 text-[11px] text-foreground-500">投标有效期要求</div>
                    <div className="text-xs font-medium text-foreground-800">
                      {checklist?.vetoParams.validity_days_required != null
                        ? `${checklist.vetoParams.validity_days_required} 个日历天`
                        : "未解析出该项要求"}
                    </div>
                  </div>
                  <div className="rounded-lg border border-background-200 bg-background-100 p-3">
                    <div className="mb-1 text-[11px] text-foreground-500">暗标要求</div>
                    <div className="text-xs font-medium text-foreground-800">
                      {checklist?.vetoParams.anonymity_required ? "是，正文需去标识" : "否 / 未标注"}
                    </div>
                  </div>
                </div>

                {checklist && checklist.vetoParams.qualification_keywords.length > 0 && (
                  <div className="rounded-lg border border-background-200 bg-background-100 p-3">
                    <div className="mb-2 text-xs font-semibold text-foreground-700">资质关键词</div>
                    <div className="flex flex-wrap gap-1.5">
                      {checklist.vetoParams.qualification_keywords.map((kw) => (
                        <span key={kw} className="rounded bg-secondary-100 px-2 py-0.5 text-[11px] text-secondary-700">
                          {kw}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <p className="text-center text-[11px] text-foreground-400">
                  以上信息来自项目基本信息与招标解析的否决参数，招标人/代理机构/建设地点等字段暂无可靠数据来源，未展示
                </p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 悬浮 AI 助手 */}
      <FloatingChat projectName={projectName} draftId={draftId} />

      {/* 知识库弹窗 */}
      {pickerId && pickerNode && (
        <KnowledgePicker
          projectId={projectId}
          nodeNum={pickerNode.num}
          nodeTitle={pickerNode.title}
          nodeIdea={pickerNode.idea}
          initialRefs={knowledgeMap[pickerId] ?? []}
          onClose={() => setPickerId(null)}
          onSave={saveKnowledge}
        />
      )}

      {generatingOutline && outline.length > 0 && (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-background-100/85 backdrop-blur-[1px]">
          <i className="ri-loader-4-line animate-spin text-3xl text-primary-500"></i>
          <div className="text-sm font-medium text-foreground-800">正在重新生成应标目录</div>
          <div className="text-xs text-foreground-500">大模型正在阅读招标文件并编制应标目录，约需 1～3 分钟</div>
        </div>
      )}

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}
