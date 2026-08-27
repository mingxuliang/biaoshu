import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import {
  ApiError,
  downloadKnowledgeDocument,
  downloadTenderDocument,
  generateWriterImage,
  listKnowledgeDocuments,
  listProjectTenderDocuments,
  listWriterImages,
  optimizeWriterImagePrompt,
  triggerFileDownload,
  uploadWriterImage,
  type KnowledgeDoc,
  type TenderDocumentSummary,
  type WriterImageItem,
  type WriterImageMode,
} from "@/lib/api";

interface ImagePanelProps {
  projectId: string;
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

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

export default function ImagePanel({ projectId, onInsertImage }: ImagePanelProps) {
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
  const [refs, setRefs] = useState<{ kind: "tender" | "knowledge"; id: string; name: string; extra: string }[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  useEffect(() => {
    if (!token || rightTab !== "reference") return;
    let cancelled = false;
    Promise.all([
      listProjectTenderDocuments(token, projectId).catch(() => [] as TenderDocumentSummary[]),
      listKnowledgeDocuments({ projectId }).catch(() => [] as KnowledgeDoc[]),
    ]).then(([tenders, knowledge]) => {
      if (cancelled) return;
      const items = [
        ...tenders.map((d) => ({
          kind: "tender" as const,
          id: d.id,
          name: d.filename,
          extra: formatSize(d.sizeBytes),
        })),
        ...knowledge.map((d) => ({
          kind: "knowledge" as const,
          id: d.id,
          name: d.title,
          extra: d.scope,
        })),
      ];
      setRefs(items);
    });
    return () => {
      cancelled = true;
    };
  }, [token, projectId, rightTab]);

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

  const handleDownloadRef = async (item: { kind: "tender" | "knowledge"; id: string; name: string }) => {
    try {
      const blob =
        item.kind === "tender" ? await downloadTenderDocument(item.id) : await downloadKnowledgeDocument(item.id);
      triggerFileDownload(blob, item.name);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "下载失败");
    }
  };

  const currentImages = imageTab === "ai" ? generated : gallery;

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
                    <img src={img.url} alt={img.prompt || img.filename} className="h-full w-full object-cover" />
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
        <div className="flex-1 overflow-y-auto px-3 py-3">
          {refs.length === 0 ? (
            <p className="py-8 text-center text-xs text-foreground-500">暂无本项目招标文件或知识库文档</p>
          ) : (
            <div className="space-y-2">
              {refs.map((ref) => (
                <div
                  key={`${ref.kind}-${ref.id}`}
                  className="flex items-center gap-2 rounded-md border border-background-300 bg-background-50 p-2 transition-colors hover:border-primary-200"
                >
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-secondary-100 text-secondary-600">
                    <i className="ri-file-text-line text-xs"></i>
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs text-foreground-700">{ref.name}</div>
                    <div className="text-[10px] text-foreground-400">{ref.extra}</div>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleDownloadRef(ref)}
                    className="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center rounded text-foreground-400 hover:bg-background-200 hover:text-primary-600"
                    title="下载"
                  >
                    <i className="ri-download-line text-xs"></i>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
