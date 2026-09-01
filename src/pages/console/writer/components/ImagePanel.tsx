import { useEffect, useMemo, useRef, useState } from "react";
import AuthImage from "../../components/AuthImage";
import { useAuth } from "@/context/AuthContext";
import KnowledgePicker from "./KnowledgePicker";
import {
  ApiError,
  generateWriterImage,
  listProductFeatures,
  listWriterImages,
  optimizeWriterImagePrompt,
  updateWriterDraft,
  uploadWriterImage,
  type KnowledgeRef,
  type ProductItem,
  type WriterImageItem,
  type WriterImageMode,
} from "@/lib/api";

interface ImagePanelProps {
  projectId: string;
  draftId: string;
  chapterId: string;
  chapterNum?: string;
  chapterTitle?: string;
  chapterIdea?: string;
  knowledgeRefs: Record<string, KnowledgeRef[]>;
  onKnowledgeRefsChange: (next: Record<string, KnowledgeRef[]>) => void;
  onInsertImage: (item: WriterImageItem) => void;
}

type ImageTab = "ai" | "gallery";
type RightTab = "image" | "reference";

const flowTypes = ["施工组织", "进度计划", "质量管理", "安全应急", "报验审批", "组织架构"];
const archTypes = ["系统分层图", "网络拓扑图", "部署架构图", "微服务架构"];

const watermarkColor: Record<WriterImageMode, string> = {
  flow: "bg-accent-500/80",
  arch: "bg-secondary-500/80",
  normal: "bg-primary-500/80",
};

const watermarkLabel: Record<WriterImageMode, string> = {
  flow: "流程图",
  arch: "架构图",
  normal: "AI生图",
};

function flattenFeatures(items: ProductItem[]): ProductItem[] {
  const out: ProductItem[] = [];
  const walk = (n: ProductItem) => {
    out.push(n);
    (n.children || []).forEach(walk);
  };
  items.forEach(walk);
  return out;
}

function sourceOf(ref: KnowledgeRef) {
  return ref.source || "knowledge";
}

export default function ImagePanel({
  projectId,
  draftId,
  chapterId,
  chapterNum,
  chapterTitle,
  chapterIdea,
  knowledgeRefs,
  onKnowledgeRefsChange,
  onInsertImage,
}: ImagePanelProps) {
  const { token } = useAuth();
  const [rightTab, setRightTab] = useState<RightTab>("image");
  const [imageTab, setImageTab] = useState<ImageTab>("ai");
  const [aiPrompt, setAiPrompt] = useState("施工组织流程图");
  const [aiMode, setAiMode] = useState<WriterImageMode>("flow");
  const [flowType, setFlowType] = useState(flowTypes[0]);
  const [archType, setArchType] = useState(archTypes[0]);
  const [generating, setGenerating] = useState(false);
  const [optimizing, setOptimizing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generated, setGenerated] = useState<WriterImageItem[]>([]);
  const [gallery, setGallery] = useState<WriterImageItem[]>([]);
  const [galleryLoading, setGalleryLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [libFeatures, setLibFeatures] = useState<Record<string, ProductItem[]>>({});
  const [expandedFeat, setExpandedFeat] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const chapterRefs = knowledgeRefs[chapterId] || [];
  const productRefs = chapterRefs.filter((r) => sourceOf(r) === "product");
  const otherRefs = chapterRefs.filter((r) => sourceOf(r) !== "product");

  useEffect(() => {
    setExpandedFeat(null);
  }, [chapterId]);

  useEffect(() => {
    if (!token || imageTab !== "gallery") return;
    let cancelled = false;
    setGalleryLoading(true);
    listWriterImages(token, projectId)
      .then((items) => {
        if (!cancelled) setGallery(items);
      })
      .catch(() => {
        if (!cancelled) setGallery([]);
      })
      .finally(() => {
        if (!cancelled) setGalleryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, projectId, imageTab]);

  const productLibKey = productRefs.map((r) => r.docId).join(",");
  useEffect(() => {
    const libIds = [...new Set(productLibKey.split(",").filter(Boolean))];
    let cancelled = false;
    libIds.forEach((libId) => {
      setLibFeatures((prev) => {
        if (prev[libId]) return prev;
        listProductFeatures(libId)
          .then((items) => {
            if (!cancelled) setLibFeatures((p) => ({ ...p, [libId]: items }));
          })
          .catch(() => {
            if (!cancelled) setLibFeatures((p) => ({ ...p, [libId]: [] }));
          });
        return prev;
      });
    });
    return () => {
      cancelled = true;
    };
  }, [productLibKey]);

  const boundFeatures = useMemo(() => {
    const rows: { ref: KnowledgeRef; item: ProductItem | null; featureId: string }[] = [];
    productRefs.forEach((ref) => {
      const loaded = libFeatures[ref.docId];
      const index = new Map(flattenFeatures(loaded || []).map((f) => [f.id, f]));
      (ref.chapters || []).forEach((id) => {
        rows.push({ ref, featureId: id, item: index.get(id) || null });
      });
    });
    return rows;
  }, [productRefs, libFeatures]);

  const persistRefs = (nextChapterRefs: KnowledgeRef[]) => {
    const next = { ...knowledgeRefs, [chapterId]: nextChapterRefs };
    onKnowledgeRefsChange(next);
    const productRef = nextChapterRefs.find((r) => sourceOf(r) === "product");
    updateWriterDraft(draftId, {
      knowledgeRefs: next,
      ...(productRef ? { selectedProductLibraryId: productRef.docId } : {}),
    }).catch(() => {
      /* 引用保存失败不打断编辑，下次调整时会再写 */
    });
  };

  const removeFeature = (docId: string, featureId: string) => {
    persistRefs(
      chapterRefs
        .map((r) => {
          if (!(sourceOf(r) === "product" && r.docId === docId)) return r;
          return { ...r, chapters: (r.chapters || []).filter((id) => id !== featureId), mode: "manual" as const };
        })
        .filter((r) => sourceOf(r) !== "product" || (r.chapters || []).length > 0),
    );
  };

  const handleModeChange = (mode: WriterImageMode) => {
    setAiMode(mode);
    setError(null);
    setAiPrompt(mode === "flow" ? "施工组织流程图" : mode === "arch" ? "系统分层架构" : "");
  };

  const handleGenerate = async () => {
    if (!token || generating) return;
    const prompt = aiPrompt.trim() || (aiMode === "flow" ? flowType : aiMode === "arch" ? archType : "");
    if (!prompt) {
      setError("请填写生图描述");
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      const item = await generateWriterImage(token, projectId, prompt, aiMode);
      setGenerated((prev) => [item, ...prev]);
      setSelectedId(item.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "生图失败，请稍后重试");
    } finally {
      setGenerating(false);
    }
  };

  const handleOptimize = async () => {
    if (!token || optimizing || !aiPrompt.trim()) return;
    setOptimizing(true);
    setError(null);
    try {
      const next = await optimizeWriterImagePrompt(token, aiPrompt.trim(), aiMode);
      if (next) setAiPrompt(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "提示词优化失败");
    } finally {
      setOptimizing(false);
    }
  };

  const handleUpload = async (file: File) => {
    if (!token) return;
    setError(null);
    try {
      const item = await uploadWriterImage(token, projectId, file);
      setGallery((prev) => [item, ...prev]);
      setImageTab("gallery");
      onInsertImage(item);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "图片上传失败");
    }
  };

  const currentImages = imageTab === "ai" ? generated : gallery;
  const featuresLoading = productRefs.some((r) => r.docId && !(r.docId in libFeatures));

  return (
    <div className="flex w-72 shrink-0 flex-col rounded-lg border border-background-300 bg-background-100 lg:w-80">
      <div className="flex items-center border-b border-background-300 px-3 py-2">
        <button
          type="button"
          onClick={() => setRightTab("image")}
          className={`flex items-center gap-1 rounded-md px-3 py-1 text-xs font-medium transition-colors ${
            rightTab === "image" ? "bg-primary-50 text-primary-600" : "text-foreground-500 hover:text-foreground-700"
          }`}
        >
          <i className="ri-image-line"></i>
          图片
        </button>
        <button
          type="button"
          onClick={() => setRightTab("reference")}
          className={`flex items-center gap-1 rounded-md px-3 py-1 text-xs font-medium transition-colors ${
            rightTab === "reference" ? "bg-primary-50 text-primary-600" : "text-foreground-500 hover:text-foreground-700"
          }`}
        >
          <i className="ri-file-list-line"></i>
          引用资料
        </button>
      </div>

      {rightTab === "image" ? (
        <>
          <div className="flex items-center gap-1 border-b border-background-300 px-3 py-2">
            {(
              [
                { key: "ai", label: "AI生图", icon: "ri-magic-line" },
                { key: "gallery", label: "私人图库", icon: "ri-gallery-line" },
              ] as { key: ImageTab; label: string; icon: string }[]
            ).map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => setImageTab(t.key)}
                className={`flex-1 rounded-md py-1.5 text-xs font-medium transition-colors ${
                  imageTab === t.key
                    ? "bg-primary-500 text-background-50"
                    : "border border-background-300 text-foreground-600 hover:bg-background-50"
                }`}
              >
                <i className={`${t.icon} mr-1`}></i>
                {t.label}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto px-3 py-3">
            {imageTab === "ai" && (
              <div className="mb-3 space-y-2">
                <div className="flex items-center gap-1 rounded-md bg-background-200 p-1">
                  {(
                    [
                      { key: "normal", label: "配图", icon: "ri-image-edit-line", active: "bg-primary-500" },
                      { key: "flow", label: "流程图", icon: "ri-flow-chart", active: "bg-accent-500" },
                      { key: "arch", label: "架构图", icon: "ri-git-branch-line", active: "bg-secondary-500" },
                    ] as { key: WriterImageMode; label: string; icon: string; active: string }[]
                  ).map((m) => (
                    <button
                      key={m.key}
                      type="button"
                      onClick={() => handleModeChange(m.key)}
                      className={`flex flex-1 cursor-pointer items-center justify-center gap-1 rounded px-1.5 py-1.5 text-xs font-medium transition-colors ${
                        aiMode === m.key ? `${m.active} text-background-50` : "text-foreground-600 hover:text-foreground-800"
                      }`}
                    >
                      <i className={m.icon}></i>
                      {m.label}
                    </button>
                  ))}
                </div>

                <input
                  type="text"
                  value={aiPrompt}
                  onChange={(e) => setAiPrompt(e.target.value)}
                  placeholder={
                    aiMode === "flow"
                      ? "输入流程描述，如：施工组织流程…"
                      : aiMode === "arch"
                        ? "输入架构描述，如：系统分层架构…"
                        : "输入生图描述…"
                  }
                  className="h-8 w-full rounded-md border border-background-300 bg-background-50 px-2.5 text-xs text-foreground-900 outline-none transition-all focus:border-primary-400"
                />

                {aiMode === "flow" && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    {flowTypes.map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => {
                          setFlowType(t);
                          setAiPrompt(`${t}流程图`);
                        }}
                        className={`cursor-pointer rounded-full border px-2 py-0.5 text-[11px] transition-colors ${
                          flowType === t
                            ? "border-accent-300 bg-accent-50 text-accent-700"
                            : "border-background-300 bg-background-50 text-foreground-600 hover:border-accent-300 hover:text-accent-700"
                        }`}
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                )}

                {aiMode === "arch" && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    {archTypes.map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => {
                          setArchType(t);
                          setAiPrompt(t);
                        }}
                        className={`cursor-pointer rounded-full border px-2 py-0.5 text-[11px] transition-colors ${
                          archType === t
                            ? "border-secondary-300 bg-secondary-50 text-secondary-700"
                            : "border-background-300 bg-background-50 text-foreground-600 hover:border-secondary-300 hover:text-secondary-700"
                        }`}
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                )}

                <button
                  type="button"
                  onClick={handleOptimize}
                  disabled={optimizing || !aiPrompt.trim()}
                  className="flex cursor-pointer items-center gap-0.5 text-[11px] text-primary-600 hover:text-primary-700 disabled:opacity-50"
                >
                  <i className={optimizing ? "ri-loader-4-line animate-spin" : "ri-lightbulb-line"}></i>
                  {optimizing ? "优化中…" : "提示词优化"}
                </button>
                <button
                  type="button"
                  onClick={handleGenerate}
                  disabled={generating}
                  className="flex h-8 w-full cursor-pointer items-center justify-center gap-1 rounded-md bg-gradient-to-r from-primary-500 to-primary-600 text-xs font-medium text-background-50 transition-all hover:from-primary-600 hover:to-primary-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {generating ? (
                    <>
                      <i className="ri-loader-4-line animate-spin"></i>
                      生成中…
                    </>
                  ) : (
                    <>
                      <i className="ri-magic-line"></i>
                      {aiMode === "flow" ? `生成${flowType}流程图` : aiMode === "arch" ? "开始生成架构图" : "开始生图"}
                    </>
                  )}
                </button>
              </div>
            )}

            {error && <p className="mb-2 text-[11px] leading-relaxed text-accent-600">{error}</p>}

            {imageTab === "gallery" && galleryLoading && (
              <p className="mb-2 text-[11px] text-foreground-500">正在加载图库…</p>
            )}

            {currentImages.length === 0 && !generating && imageTab === "ai" && (
              <p className="mb-2 text-center text-[11px] text-foreground-400">生成结果会出现在这里，点击即可插入当前章节</p>
            )}
            {currentImages.length === 0 && imageTab === "gallery" && !galleryLoading && (
              <p className="mb-2 text-center text-[11px] text-foreground-400">图库为空，可上传本机图片或先用 AI 生图</p>
            )}

            <div className="grid grid-cols-2 gap-2">
              {currentImages.map((img) => (
                <div
                  key={img.id}
                  className={`group relative cursor-pointer overflow-hidden rounded-md border transition-all ${
                    selectedId === img.id ? "border-accent-500 ring-1 ring-accent-400" : "border-background-300 hover:border-accent-300"
                  }`}
                  onClick={() => {
                    setSelectedId(img.id);
                    onInsertImage(img);
                  }}
                >
                  <div className="relative aspect-[4/3] w-full overflow-hidden bg-background-200">
                    <AuthImage src={img.url} alt={img.prompt || img.filename} eager className="h-full w-full object-cover" />
                    {img.source === "generated" && (
                      <span
                        className={`absolute left-1 top-1 flex items-center gap-0.5 rounded px-1 py-0.5 text-[9px] font-medium text-background-50 ${watermarkColor[img.mode]}`}
                      >
                        <i className="ri-magic-line"></i>
                        {watermarkLabel[img.mode]}
                      </span>
                    )}
                    {img.source === "knowledge" && (
                      <span className="absolute left-1 top-1 rounded bg-secondary-500/80 px-1 py-0.5 text-[9px] font-medium text-background-50">
                        知识库
                      </span>
                    )}
                    <div className="absolute inset-0 flex items-center justify-center bg-black/30 opacity-0 transition-opacity group-hover:opacity-100">
                      <span className="rounded bg-background-50 px-2 py-1 text-[11px] font-medium text-foreground-900">
                        点击插入
                      </span>
                    </div>
                  </div>
                  <div className="truncate px-1.5 py-1 text-[11px] text-foreground-600">
                    {img.prompt || img.filename}
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-3">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="flex h-8 w-full cursor-pointer items-center justify-center gap-1 rounded-md border border-dashed border-background-400 text-xs text-foreground-500 transition-colors hover:border-primary-300 hover:text-primary-600"
              >
                <i className="ri-upload-cloud-line"></i>
                上传本机图片
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void handleUpload(file);
                  if (e.target) e.target.value = "";
                }}
              />
            </div>
          </div>
        </>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="border-b border-background-200 px-3 py-2">
            <div className="truncate text-xs font-medium text-foreground-800">
              {chapterNum ? `${chapterNum} ` : ""}
              {chapterTitle || "未选择章节"}
            </div>
            <div className="mt-0.5 text-[11px] text-foreground-500">
              {productRefs.length > 0
                ? `已引用 ${boundFeatures.length} 项产品功能`
                : "本章尚未绑定产品功能库"}
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
            {featuresLoading && (
              <p className="mb-2 text-[11px] text-foreground-500">
                <i className="ri-loader-4-line mr-1 animate-spin"></i>
                正在加载产品功能…
              </p>
            )}
            {!chapterId ? (
              <p className="py-8 text-center text-xs text-foreground-500">请先在左侧选择章节</p>
            ) : boundFeatures.length === 0 && !featuresLoading ? (
              <p className="py-6 text-center text-xs text-foreground-400">
                目录页自动匹配或下方「选择引用」后，本章引用的产品功能会显示在这里
              </p>
            ) : (
              <div className="space-y-2">
                {boundFeatures.map(({ ref, item, featureId }) => {
                  const open = expandedFeat === featureId;
                  const imgs = item ? [...(item.images || []), ...(item.children || []).flatMap((c) => c.images || [])] : [];
                  return (
                    <div
                      key={`${ref.docId}-${featureId}`}
                      className="rounded-md border border-background-300 bg-background-50"
                    >
                      <div className="flex items-start gap-1.5 p-2">
                        <button
                          type="button"
                          onClick={() => setExpandedFeat(open ? null : featureId)}
                          className="mt-0.5 flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center text-foreground-400"
                          title={open ? "收起" : "展开"}
                        >
                          <i className={`ri-arrow-right-s-line text-sm transition-transform ${open ? "rotate-90" : ""}`}></i>
                        </button>
                        <button
                          type="button"
                          onClick={() => setExpandedFeat(open ? null : featureId)}
                          className="min-w-0 flex-1 cursor-pointer text-left"
                        >
                          <div className="truncate text-xs text-foreground-800">{item?.name || featureId}</div>
                          <div className="truncate text-[10px] text-foreground-400">
                            产品库 · {ref.docTitle}
                            {ref.mode === "ai" ? " · 自动匹配" : " · 手动"}
                          </div>
                        </button>
                        <button
                          type="button"
                          onClick={() => removeFeature(ref.docId, featureId)}
                          className="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center rounded text-foreground-400 hover:bg-background-200 hover:text-accent-600"
                          title="取消引用"
                        >
                          <i className="ri-close-line text-xs"></i>
                        </button>
                      </div>
                      {open && (
                        <div className="border-t border-background-200 px-2 py-2">
                          {item?.intro ? (
                            <p className="text-[11px] leading-relaxed text-foreground-600">{item.intro}</p>
                          ) : (
                            <p className="text-[11px] text-foreground-400">暂无功能说明</p>
                          )}
                          {imgs.length > 0 && (
                            <div className="mt-2 grid grid-cols-2 gap-1.5">
                              {imgs.slice(0, 4).map((img) => (
                                <AuthImage
                                  key={img.id}
                                  src={img.url}
                                  alt={img.caption || item?.name}
                                  eager
                                  className="h-16 w-full rounded border border-background-300 object-cover"
                                />
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            {otherRefs.length > 0 && (
              <div className="mt-3">
                <div className="mb-1 text-[11px] text-foreground-500">其他引用</div>
                <div className="flex flex-wrap gap-1">
                  {otherRefs.map((r) => (
                    <span
                      key={`${sourceOf(r)}:${r.docId}`}
                      className="rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700"
                    >
                      {sourceOf(r) === "qualification" ? "资质 · " : "文档 · "}
                      {r.docTitle}
                      {r.chapters.length > 0 ? `（${r.chapters.length}）` : ""}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
          <div className="border-t border-background-200 px-3 py-2">
            <button
              type="button"
              disabled={!chapterId}
              onClick={() => setPickerOpen(true)}
              className="flex h-8 w-full cursor-pointer items-center justify-center gap-1 rounded-md bg-primary-500 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <i className="ri-bookmark-line"></i>
              {chapterRefs.length > 0 ? "调整 / 重新选择引用" : "选择产品功能引用"}
            </button>
          </div>
        </div>
      )}
      {pickerOpen && chapterId && (
        <KnowledgePicker
          projectId={projectId}
          nodeNum={chapterNum || ""}
          nodeTitle={chapterTitle || ""}
          nodeIdea={chapterIdea}
          initialRefs={chapterRefs}
          onClose={() => setPickerOpen(false)}
          onSave={(refs) => {
            persistRefs(refs);
            setPickerOpen(false);
          }}
        />
      )}
    </div>
  );
}
