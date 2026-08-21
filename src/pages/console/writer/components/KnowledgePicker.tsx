import { useEffect, useMemo, useState } from "react";
import {
  KNOWLEDGE_SCOPES,
  getKnowledgeChapterDetail,
  getKnowledgeChapters,
  listKnowledgeDocuments,
  suggestKnowledgeForChapter,
  type KnowledgeChapter,
  type KnowledgeChapterDetail,
  type KnowledgeDoc,
  type KnowledgeRef,
} from "@/lib/api";

interface KnowledgePickerProps {
  projectId: string;
  nodeNum: string;
  nodeTitle: string;
  nodeIdea?: string;
  initialRefs: KnowledgeRef[];
  onClose: () => void;
  onSave: (refs: KnowledgeRef[]) => void;
}

const emptyRef = (docId: string, docTitle: string, mode: KnowledgeRef["mode"]): KnowledgeRef => ({
  docId,
  docTitle,
  chapters: [],
  mode,
});

export default function KnowledgePicker({
  projectId,
  nodeNum,
  nodeTitle,
  nodeIdea,
  initialRefs,
  onClose,
  onSave,
}: KnowledgePickerProps) {
  const [scope, setScope] = useState("全部");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [refs, setRefs] = useState<KnowledgeRef[]>(initialRefs);
  const [aiThinking, setAiThinking] = useState(false);
  const [preview, setPreview] = useState<KnowledgeChapterDetail | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const [allDocs, setAllDocs] = useState<KnowledgeDoc[]>([]);
  const [docChapters, setDocChapters] = useState<Record<string, KnowledgeChapter[]>>({});

  useEffect(() => {
    let cancelled = false;
    listKnowledgeDocuments({ projectId })
      .then((docs) => {
        if (!cancelled) setAllDocs(docs);
      })
      .catch(() => {
        /* 拉取失败时保持空列表，用户仍可关闭弹窗 */
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const docs = useMemo(
    () => (scope === "全部" ? allDocs : allDocs.filter((d) => d.scope === scope)),
    [allDocs, scope]
  );

  const ensureChapters = (docId: string) => {
    if (docChapters[docId]) return;
    getKnowledgeChapters(docId)
      .then((chapters) => setDocChapters((prev) => ({ ...prev, [docId]: chapters })))
      .catch(() => setDocChapters((prev) => ({ ...prev, [docId]: [] })));
  };

  const toggleDoc = (docId: string, docTitle: string) => {
    setRefs((prev) => {
      const exists = prev.some((r) => r.docId === docId);
      if (exists) return prev.filter((r) => r.docId !== docId);
      ensureChapters(docId);
      return [...prev, emptyRef(docId, docTitle, "manual")];
    });
    setExpanded((p) => ({ ...p, [docId]: true }));
  };

  const toggleChapter = (docId: string, chapter: string) => {
    setRefs((prev) =>
      prev.map((r) =>
        r.docId === docId
          ? {
              ...r,
              chapters: r.chapters.includes(chapter)
                ? r.chapters.filter((c) => c !== chapter)
                : [...r.chapters, chapter],
            }
          : r
      )
    );
  };

  const setMode = (docId: string, mode: KnowledgeRef["mode"]) => {
    setRefs((prev) => prev.map((r) => (r.docId === docId ? { ...r, mode } : r)));
  };

  const runAi = () => {
    setAiThinking(true);
    const query = `${nodeTitle} ${nodeIdea ?? ""}`.trim();
    suggestKnowledgeForChapter(projectId, query)
      .then((suggestions) => {
        const next: KnowledgeRef[] = suggestions.map((s) => ({
          docId: s.docId,
          docTitle: s.docTitle,
          chapters: s.chapters,
          mode: "ai" as const,
        }));
        setRefs(next);
        setExpanded(Object.fromEntries(next.map((r) => [r.docId, true])));
        next.forEach((r) => ensureChapters(r.docId));
      })
      .catch(() => {
        /* AI 推荐失败时静默降级，用户可继续手动选择 */
      })
      .finally(() => setAiThinking(false));
  };

  const save = () => {
    onSave(refs);
    onClose();
  };

  const openPreview = (docId: string, docTitle: string, chapter: string) => {
    setPreviewLoading(true);
    getKnowledgeChapterDetail(docId, chapter)
      .then((detail) => setPreview(detail))
      .catch(() => setPreview({ docTitle, heading: chapter, paragraphs: ["加载章节内容失败，请稍后重试"] }))
      .finally(() => setPreviewLoading(false));
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground-950/40 p-4" onClick={onClose}>
      <div
        className="flex max-h-[86vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-background-300 bg-background-100"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center gap-2.5 border-b border-background-300 px-4 py-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
            <i className="ri-bookmark-line text-base"></i>
          </span>
          <div className="min-w-0 flex-1">
            <div className="font-heading text-sm font-semibold tracking-wide text-foreground-900">设置参考知识库</div>
            <div className="truncate text-[11px] text-foreground-500">
              章节 {nodeNum} · {nodeTitle}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-6 w-6 cursor-pointer items-center justify-center rounded text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800"
          >
            <i className="ri-close-line text-xs"></i>
          </button>
        </div>

        {/* AI 自动选择 */}
        <div className="border-b border-background-300 bg-background-50 px-4 py-3">
          <div className="flex items-center gap-2.5">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-accent-100 text-accent-600">
              <i className="ri-sparkling-2-line text-sm"></i>
            </span>
            <div className="flex-1">
              <div className="text-xs font-semibold text-foreground-800">AI 自动选择参考知识库</div>
              <div className="text-[11px] text-foreground-500">依据章节标题与编写思路，检索最相关的知识库文档与章节</div>
            </div>
            <button
              type="button"
              onClick={runAi}
              disabled={aiThinking}
              className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-accent-500 px-3 text-xs font-medium text-background-50 transition-colors hover:bg-accent-600 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <i className={`${aiThinking ? "ri-loader-4-line animate-spin" : "ri-magic-line"} text-xs`}></i>
              {aiThinking ? "AI 分析中…" : "AI 自动选择"}
            </button>
          </div>
          {refs.some((r) => r.mode === "ai") && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-accent-700">
              <i className="ri-check-double-line"></i>
              已按 AI 推荐选择 {refs.filter((r) => r.mode === "ai").length} 篇文档，可继续手动调整
            </div>
          )}
        </div>

        {/* 文档列表 */}
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex items-center gap-1.5 border-b border-background-200 bg-background-50 px-4 py-2">
            <i className="ri-database-2-line text-xs text-foreground-400"></i>
            <div className="flex flex-wrap gap-1">
              {KNOWLEDGE_SCOPES.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setScope(s)}
                  className={`cursor-pointer whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] transition-colors ${
                    scope === s ? "bg-primary-500 text-background-50" : "bg-background-100 text-foreground-500 hover:bg-background-200"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-4 py-3">
            {docs.map((doc) => {
              const ref = refs.find((r) => r.docId === doc.id);
              const checked = !!ref;
              const isOpen = expanded[doc.id] ?? checked;
              const chapters = docChapters[doc.id] ?? [];
              return (
                <div key={doc.id} className="overflow-hidden rounded-lg border border-background-200 bg-background-50">
                  <div className="flex items-center gap-2 px-3 py-2.5">
                    <label className="flex shrink-0 cursor-pointer items-center gap-2">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleDoc(doc.id, doc.title)}
                        className="h-3.5 w-3.5 cursor-pointer accent-primary-500"
                      />
                    </label>
                    <button
                      type="button"
                      onClick={() => {
                        setExpanded((p) => ({ ...p, [doc.id]: !p[doc.id] }));
                        ensureChapters(doc.id);
                      }}
                      className="flex min-w-0 flex-1 cursor-pointer items-center gap-1.5 text-left"
                    >
                      <i className={`ri-file-text-line text-sm text-primary-500`}></i>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-xs font-medium text-foreground-800">{doc.title}</div>
                        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-foreground-500">
                          <span className="rounded bg-secondary-100 px-1 py-0.5 text-secondary-700">{doc.scope}</span>
                          <span className="rounded bg-secondary-100 px-1 py-0.5 text-secondary-700">{doc.type}</span>
                          <span className="rounded bg-secondary-100 px-1 py-0.5 text-secondary-700">{doc.sliceCount} 切片</span>
                        </div>
                      </div>
                      <i className={`ri-arrow-down-s-line text-xs text-foreground-400 transition-transform ${isOpen ? "rotate-180" : ""}`}></i>
                    </button>
                  </div>

                  {isOpen && checked && (
                    <div className="border-t border-background-200 px-3 py-2">
                      <div className="mb-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-foreground-500">
                        <span>选择引用章节：</span>
                        {ref.mode === "ai" ? (
                          <span className="flex items-center gap-1 text-accent-600">
                            <i className="ri-sparkling-2-line text-xs"></i>
                            AI 已自动选择 {ref.chapters.length} 章
                          </span>
                        ) : (
                          <span>手动选择 {ref.chapters.length} 章</span>
                        )}
                        <button
                          type="button"
                          onClick={() => setMode(doc.id, ref.mode === "manual" ? "ai" : "manual")}
                          className="ml-auto cursor-pointer text-primary-600 hover:text-primary-700"
                        >
                          {ref.mode === "manual" ? "改用 AI 选" : "改用手动选"}
                        </button>
                      </div>
                      {chapters.length === 0 ? (
                        <div className="py-2 text-center text-[11px] text-foreground-400">该文档暂无可识别的章节</div>
                      ) : (
                        <div className="flex flex-wrap gap-1.5">
                          {chapters.map((ch) => {
                            const sel = ref.chapters.includes(ch.heading);
                            return (
                              <div key={ch.heading} className="flex items-center gap-1">
                                <button
                                  type="button"
                                  onClick={() => toggleChapter(doc.id, ch.heading)}
                                  className={`cursor-pointer whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] transition-colors ${
                                    sel
                                      ? "bg-primary-100 text-primary-700 ring-1 ring-primary-200"
                                      : "bg-background-100 text-foreground-500 hover:bg-background-200"
                                  }`}
                                >
                                  <i className={`${sel ? "ri-checkbox-circle-fill" : "ri-checkbox-blank-circle-line"} mr-1 text-xs`}></i>
                                  {ch.heading}
                                </button>
                                <button
                                  type="button"
                                  title="查看章节文字详情"
                                  onClick={() => openPreview(doc.id, doc.title, ch.heading)}
                                  className="flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center rounded text-foreground-400 transition-colors hover:bg-primary-50 hover:text-primary-600"
                                >
                                  <i className="ri-eye-line text-[11px]"></i>
                                </button>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
            {docs.length === 0 && <div className="py-10 text-center text-xs text-foreground-500">该范围内暂无知识库文档</div>}
          </div>
        </div>

        {/* 已选摘要 + 操作 */}
        <div className="border-t border-background-300 bg-background-50 px-4 py-3">
          <div className="mb-2 flex flex-wrap gap-1.5">
            {refs.length === 0 ? (
              <span className="text-[11px] text-foreground-400">尚未选择参考知识库</span>
            ) : (
              refs.map((r) => (
                <span key={r.docId} className="flex items-center gap-1 rounded bg-secondary-100 px-2 py-0.5 text-[11px] text-secondary-700">
                  <i className={`${r.mode === "ai" ? "ri-sparkling-2-line" : "ri-bookmark-3-line"} text-xs`}></i>
                  {r.docTitle}
                  {r.chapters.length > 0 && <span className="text-secondary-500">（{r.chapters.length}章）</span>}
                </span>
              ))
            )}
          </div>
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="flex h-9 cursor-pointer items-center whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
            >
              取消
            </button>
            <button
              type="button"
              onClick={save}
              disabled={refs.length === 0}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <i className="ri-check-line text-sm"></i>
              保存知识库设置
            </button>
          </div>
        </div>
      </div>

      {/* 章节文字详情弹窗 */}
      {preview && (
        <div
          className="absolute inset-0 z-50 flex items-center justify-center bg-foreground-950/40 p-4"
          onClick={() => setPreview(null)}
        >
          <div
            className="flex max-h-[82vh] w-full max-w-lg flex-col overflow-hidden rounded-xl border border-background-300 bg-background-100"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2.5 border-b border-background-300 px-4 py-3">
              <span className="flex h-8 w-8 items-center justify-center rounded-md bg-secondary-100 text-secondary-700">
                <i className="ri-eye-line text-base"></i>
              </span>
              <div className="min-w-0 flex-1">
                <div className="font-heading text-sm font-semibold tracking-wide text-foreground-900">章节详情预览</div>
                <div className="truncate text-[11px] text-foreground-500">
                  {preview.docTitle} · {preview.heading}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setPreview(null)}
                className="flex h-6 w-6 cursor-pointer items-center justify-center rounded text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800"
              >
                <i className="ri-close-line text-xs"></i>
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
              {previewLoading ? (
                <div className="py-10 text-center text-xs text-foreground-500">
                  <i className="ri-loader-4-line mr-1 animate-spin"></i>
                  加载中…
                </div>
              ) : (
                <div className="space-y-2.5">
                  {preview.paragraphs.map((p, i) => (
                    <p key={i} className="text-[13px] leading-[1.9] text-foreground-600">
                      {p}
                    </p>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
