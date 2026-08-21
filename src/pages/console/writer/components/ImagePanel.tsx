import { useState, useRef } from "react";

interface ImagePanelProps {
  onInsertImage: (item: { url: string; type: string }) => void;
}

type ImageTab = "ai" | "gallery" | "web";
type RightTab = "image" | "reference";
type AiMode = "normal" | "flow" | "arch";

const mockAiImages = [
  { id: 1, url: "https://readdy.ai/api/search-image?query=Industrial%20construction%20site%20with%20workers%20in%20safety%20helmets%20and%20vests%2C%20professional%20photography%2C%20realistic%2C%20daylight&width=480&height=360&seq=ai-img-1&orientation=landscape", label: "人员施工图" },
  { id: 2, url: "https://readdy.ai/api/search-image?query=Modern%20data%20center%20server%20room%20with%20rows%20of%20racks%20and%20led%20lights%2C%20clean%20infrastructure%2C%20professional%20photography&width=480&height=360&seq=ai-img-2&orientation=landscape", label: "数据中心" },
  { id: 3, url: "https://readdy.ai/api/search-image?query=Office%20team%20meeting%20in%20modern%20conference%20room%2C%20business%20professionals%20discussing%20project%2C%20natural%20lighting&width=480&height=360&seq=ai-img-3&orientation=landscape", label: "团队会议" },
  { id: 4, url: "https://readdy.ai/api/search-image?query=Construction%20worker%20operating%20heavy%20machinery%20at%20building%20site%2C%20yellow%20excavator%2C%20safety%20equipment&width=480&height=360&seq=ai-img-4&orientation=landscape", label: "施工现场" },
  { id: 5, url: "https://readdy.ai/api/search-image?query=Quality%20inspection%20engineer%20checking%20equipment%20with%20tablet%2C%20industrial%20setting%2C%20professional%20attire&width=480&height=360&seq=ai-img-5&orientation=landscape", label: "质检" },
  { id: 6, url: "https://readdy.ai/api/search-image?query=Aerial%20view%20of%20large%20urban%20infrastructure%20project%20under%20construction%2C%20cranes%20and%20machinery%2C%20professional%20photography&width=480&height=360&seq=ai-img-6&orientation=landscape", label: "航拍全景" },
];

const mockFlowImages = [
  { id: 11, url: "https://readdy.ai/api/search-image?query=Construction%20site%20work%20organization%20flowchart%20diagram%20with%20connected%20labeled%20boxes%20and%20directional%20arrows%2C%20clean%20white%20background%2C%20professional%20engineering%20flow%20diagram%2C%20flat%20vector%20style%2C%20teal%20and%20slate%20colors&width=480&height=360&seq=flow-org-01&orientation=landscape", label: "施工组织流程图" },
  { id: 12, url: "https://readdy.ai/api/search-image?query=Project%20schedule%20network%20diagram%20with%20interconnected%20milestone%20nodes%20and%20critical%20path%20arrows%2C%20clean%20white%20background%2C%20professional%20project%20management%20flow%20chart&width=480&height=360&seq=flow-sched-02&orientation=landscape", label: "进度计划流程图" },
  { id: 13, url: "https://readdy.ai/api/search-image?query=Quality%20management%20process%20flowchart%20with%20decision%20diamonds%20and%20action%20boxes%2C%20standard%20flowchart%20notation%2C%20clean%20white%20background%2C%20flat%20vector%20diagram&width=480&height=360&seq=flow-qual-03&orientation=landscape", label: "质量管理流程图" },
  { id: 14, url: "https://readdy.ai/api/search-image?query=Safety%20emergency%20response%20flowchart%20with%20red%20and%20amber%20accent%20boxes%20and%20arrows%2C%20standard%20flowchart%20symbols%2C%20clean%20white%20background%2C%20flat%20vector&width=480&height=360&seq=flow-safe-04&orientation=landscape", label: "安全应急流程图" },
  { id: 15, url: "https://readdy.ai/api/search-image?query=Inspection%20approval%20workflow%20diagram%20with%20horizontal%20swim%20lanes%20and%20step%20boxes%2C%20clean%20white%20background%2C%20professional%20flat%20vector%20flowchart&width=480&height=360&seq=flow-app-05&orientation=landscape", label: "报验审批流程" },
  { id: 16, url: "https://readdy.ai/api/search-image?query=Company%20organizational%20chart%20with%20hierarchy%20boxes%20and%20connecting%20lines%2C%20clean%20white%20background%2C%20flat%20minimal%20design%2C%20corporate%20structure%20diagram&width=480&height=360&seq=flow-chart-06&orientation=landscape", label: "组织架构图" },
];

const mockArchImages = [
  { id: 21, url: "https://readdy.ai/api/search-image?query=Layered%20software%20system%20architecture%20diagram%20with%20stacked%20horizontal%20layers%2C%20clean%20white%20background%2C%20flat%20vector%20illustration&width=480&height=360&seq=arch-layer-01&orientation=landscape", label: "系统分层图" },
  { id: 22, url: "https://readdy.ai/api/search-image?query=Network%20topology%20diagram%20with%20servers%20routers%20and%20connected%20nodes%2C%20clean%20white%20background%2C%20flat%20vector%20illustration&width=480&height=360&seq=arch-net-02&orientation=landscape", label: "网络拓扑图" },
  { id: 23, url: "https://readdy.ai/api/search-image?query=Cloud%20deployment%20architecture%20diagram%20with%20services%20and%20data%20flows%2C%20clean%20white%20background%2C%20flat%20vector%20illustration&width=480&height=360&seq=arch-dep-03&orientation=landscape", label: "部署架构图" },
  { id: 24, url: "https://readdy.ai/api/search-image?query=Microservices%20architecture%20diagram%20with%20multiple%20service%20blocks%20and%20message%20queue%20connections%2C%20clean%20white%20background%2C%20flat%20vector&width=480&height=360&seq=arch-micro-04&orientation=landscape", label: "微服务架构" },
];

const mockGalleryImages = [
  { id: 101, url: "https://readdy.ai/api/search-image?query=Company%20office%20building%20exterior%2C%20modern%20architecture%2C%20glass%20facade%2C%20professional%20real%20estate%20photography&width=480&height=360&seq=gal-1&orientation=landscape", label: "公司大楼" },
  { id: 102, url: "https://readdy.ai/api/search-image?query=Certification%20badge%20and%20quality%20award%20plaque%2C%20iso%20certificate%20document%2C%20professional%20product%20photography&width=480&height=360&seq=gal-2&orientation=landscape", label: "资质证书" },
  { id: 103, url: "https://readdy.ai/api/search-image?query=Software%20dashboard%20interface%20showing%20analytics%20charts%20and%20data%20visualization%2C%20modern%20ui%20design%2C%20clean%20minimal&width=480&height=360&seq=gal-3&orientation=landscape", label: "系统界面" },
  { id: 104, url: "https://readdy.ai/api/search-image?query=Training%20session%20with%20instructor%20and%20students%20in%20classroom%2C%20projector%20screen%2C%20professional%20education%20photography&width=480&height=360&seq=gal-4&orientation=landscape", label: "培训现场" },
];

const mockWebImages = [
  { id: 201, url: "https://readdy.ai/api/search-image?query=Smart%20city%20transportation%20system%20with%20metro%20and%20digital%20signage%2C%20modern%20urban%20infrastructure&width=480&height=360&seq=web-1&orientation=landscape", label: "智慧城市" },
  { id: 202, url: "https://readdy.ai/api/search-image?query=Cloud%20computing%20technology%20concept%20with%20connected%20devices%20and%20data%20streams%2C%20abstract%20digital%20illustration&width=480&height=360&seq=web-2&orientation=landscape", label: "云计算" },
  { id: 203, url: "https://readdy.ai/api/search-image?query=Cybersecurity%20shield%20protecting%20digital%20network%2C%20holographic%20security%20lock%20icon&width=480&height=360&seq=web-3&orientation=landscape", label: "网络安全" },
  { id: 204, url: "https://readdy.ai/api/search-image?query=Ai%20artificial%20intelligence%20brain%20neural%20network%2C%20glowing%20nodes%20and%20connections&width=480&height=360&seq=web-4&orientation=landscape", label: "AI大脑" },
];

const flowTypes = ["施工组织", "进度计划", "质量管理", "安全应急", "报验审批", "组织架构"];
const archTypes = ["系统分层图", "网络拓扑图", "部署架构图", "微服务架构"];

export default function ImagePanel({ onInsertImage }: ImagePanelProps) {
  const [rightTab, setRightTab] = useState<RightTab>("image");
  const [imageTab, setImageTab] = useState<ImageTab>("ai");
  const [aiPrompt, setAiPrompt] = useState("施工组织流程图");
  const [aiMode, setAiMode] = useState<AiMode>("flow");
  const [flowType, setFlowType] = useState(flowTypes[0]);
  const [archType, setArchType] = useState(archTypes[0]);
  const [generating, setGenerating] = useState(false);
  const [preview, setPreview] = useState(false);
  const [selectedImage, setSelectedImage] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const modePool = aiMode === "flow" ? mockFlowImages : aiMode === "arch" ? mockArchImages : mockAiImages;

  const handleModeChange = (mode: AiMode) => {
    setAiMode(mode);
    setPreview(false);
    setAiPrompt(mode === "flow" ? "施工组织流程图" : mode === "arch" ? "系统分层架构" : "");
    setSelectedImage(null);
  };

  const handleGenerate = () => {
    if (generating) return;
    setGenerating(true);
    window.setTimeout(() => {
      setPreview(true);
      setGenerating(false);
    }, 2000);
  };

  const currentImages =
    imageTab === "ai" ? (preview ? modePool : modePool.slice(0, 2)) :
    imageTab === "gallery" ? mockGalleryImages :
    mockWebImages;

  const watermarkColor =
    aiMode === "flow" ? "bg-accent-500/80" : aiMode === "arch" ? "bg-secondary-500/80" : "bg-primary-500/80";
  const watermarkLabel = aiMode === "flow" ? "AI流程图" : aiMode === "arch" ? "AI架构图" : "AI生图";

  return (
    <div className="flex w-72 shrink-0 flex-col rounded-lg border border-background-300 bg-background-100 lg:w-80">
      {/* 顶部标签：图片 / 引用资料 */}
      <div className="flex items-center border-b border-background-300 px-3 py-2">
        <button
          type="button"
          onClick={() => setRightTab("image")}
          className={`flex items-center gap-1 rounded-md px-3 py-1 text-xs font-medium transition-colors ${
            rightTab === "image"
              ? "bg-primary-50 text-primary-600"
              : "text-foreground-500 hover:text-foreground-700"
          }`}
        >
          <i className="ri-image-line"></i>
          图片
        </button>
        <button
          type="button"
          onClick={() => setRightTab("reference")}
          className={`flex items-center gap-1 rounded-md px-3 py-1 text-xs font-medium transition-colors ${
            rightTab === "reference"
              ? "bg-primary-50 text-primary-600"
              : "text-foreground-500 hover:text-foreground-700"
          }`}
        >
          <i className="ri-file-list-line"></i>
          引用资料
        </button>
      </div>

      {rightTab === "image" ? (
        <>
          {/* 图片子标签 */}
          <div className="flex items-center gap-1 border-b border-background-300 px-3 py-2">
            {([
              { key: "ai", label: "AI生图", icon: "ri-magic-line" },
              { key: "gallery", label: "私人图库", icon: "ri-gallery-line" },
              { key: "web", label: "网络图片", icon: "ri-global-line" },
            ] as { key: ImageTab; label: string; icon: string }[]).map((t) => (
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
            {/* AI 生图区域 */}
            {imageTab === "ai" && (
              <div className="mb-3 space-y-2">
                {/* 生图模式：普通配图 / 流程图 / 架构图 */}
                <div className="flex items-center gap-1 rounded-md bg-background-200 p-1">
                  <button
                    type="button"
                    onClick={() => handleModeChange("normal")}
                    className={`flex flex-1 cursor-pointer items-center justify-center gap-1 rounded px-1.5 py-1.5 text-xs font-medium transition-colors ${
                      aiMode === "normal"
                        ? "bg-primary-500 text-background-50"
                        : "text-foreground-600 hover:text-foreground-800"
                    }`}
                  >
                    <i className="ri-image-edit-line"></i>
                    配图
                  </button>
                  <button
                    type="button"
                    onClick={() => handleModeChange("flow")}
                    className={`flex flex-1 cursor-pointer items-center justify-center gap-1 rounded px-1.5 py-1.5 text-xs font-medium transition-colors ${
                      aiMode === "flow"
                        ? "bg-accent-500 text-background-50"
                        : "text-foreground-600 hover:text-foreground-800"
                    }`}
                  >
                    <i className="ri-flow-chart"></i>
                    流程图
                  </button>
                  <button
                    type="button"
                    onClick={() => handleModeChange("arch")}
                    className={`flex flex-1 cursor-pointer items-center justify-center gap-1 rounded px-1.5 py-1.5 text-xs font-medium transition-colors ${
                      aiMode === "arch"
                        ? "bg-secondary-500 text-background-50"
                        : "text-foreground-600 hover:text-foreground-800"
                    }`}
                  >
                    <i className="ri-git-branch-line"></i>
                    架构图
                  </button>
                </div>

                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={aiPrompt}
                    onChange={(e) => setAiPrompt(e.target.value)}
                    placeholder={
                      aiMode === "flow" ? "输入流程描述，如：施工组织流程…"
                      : aiMode === "arch" ? "输入架构描述，如：系统分层架构…"
                      : "输入生图描述…"
                    }
                    className="h-8 flex-1 rounded-md border border-background-300 bg-background-50 px-2.5 text-xs text-foreground-900 outline-none transition-all focus:border-primary-400"
                  />
                </div>

                {/* 流程图专属：可选流程类型 */}
                {aiMode === "flow" && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    {flowTypes.map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => setFlowType(t)}
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

                {/* 架构图专属：可选架构类型 */}
                {aiMode === "arch" && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    {archTypes.map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => setArchType(t)}
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

                <div className="flex items-center gap-2 text-[11px] text-foreground-500">
                  <button type="button" className="flex cursor-pointer items-center gap-0.5 text-primary-600 hover:text-primary-700">
                    <i className="ri-lightbulb-line"></i>
                    提示词优化
                  </button>
                  <span className="ml-auto">概念1.0</span>
                  <span>比例1:1</span>
                </div>
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
                <div className="text-[10px] text-foreground-400">
                  预计消耗点数 {aiMode === "flow" ? 2 : 1}
                </div>
              </div>
            )}

            {/* 图库/网络图片搜索 */}
            {imageTab !== "ai" && (
              <div className="mb-3">
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    placeholder="搜索图片…"
                    className="h-8 flex-1 rounded-md border border-background-300 bg-background-50 px-2.5 text-xs text-foreground-900 outline-none transition-all focus:border-primary-400"
                  />
                  <button
                    type="button"
                    className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-md border border-background-300 text-foreground-500 hover:bg-background-50"
                  >
                    <i className="ri-search-line text-xs"></i>
                  </button>
                </div>
              </div>
            )}

            {/* 图片网格 */}
            <div className="grid grid-cols-2 gap-2">
              {currentImages.map((img) => (
                <div
                  key={img.id}
                  className={`group relative cursor-pointer overflow-hidden rounded-md border transition-all ${
                    selectedImage === img.id
                      ? "border-accent-500 ring-1 ring-accent-400"
                      : "border-background-300 hover:border-accent-300"
                  }`}
                  onClick={() => {
                    setSelectedImage(img.id);
                    onInsertImage({ url: img.url, type: imageTab === "ai" ? aiMode : "image" });
                  }}
                >
                  <div className="relative aspect-[4/3] w-full overflow-hidden bg-background-200">
                    <img
                      src={img.url}
                      alt={img.label}
                      className="h-full w-full object-cover"
                    />
                    {/* 水印 */}
                    {imageTab === "ai" && (
                      <span className={`absolute left-1 top-1 flex items-center gap-0.5 rounded px-1 py-0.5 text-[9px] font-medium text-background-50 ${watermarkColor}`}>
                        <i className="ri-magic-line"></i>
                        {watermarkLabel}
                      </span>
                    )}
                    {/* 插入按钮 */}
                    <div className="absolute inset-0 flex items-center justify-center bg-black/30 opacity-0 transition-opacity group-hover:opacity-100">
                      <span className="rounded bg-background-50 px-2 py-1 text-[11px] font-medium text-foreground-900">
                        点击插入
                      </span>
                    </div>
                  </div>
                  <div className="truncate px-1.5 py-1 text-[11px] text-foreground-600">
                    {img.label}
                  </div>
                </div>
              ))}
            </div>

            {/* 手动上传 */}
            <div className="mt-3">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="flex h-8 w-full cursor-pointer items-center justify-center gap-1 rounded-md border border-dashed border-background-400 text-xs text-foreground-500 transition-colors hover:border-primary-300 hover:text-primary-600"
              >
                <i className="ri-upload-cloud-line"></i>
                手动插入图片
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) {
                    const url = URL.createObjectURL(file);
                    onInsertImage({ url, type: "image" });
                  }
                  if (e.target) e.target.value = "";
                }}
              />
            </div>
          </div>
        </>
      ) : (
        /* 引用资料 */
        <div className="flex-1 overflow-y-auto px-3 py-3">
          <div className="space-y-2">
            {[
              { name: "招标文件_技术参数.pdf", size: "2.4 MB" },
              { name: "评分标准_商务部分.docx", size: "156 KB" },
              { name: "合同模板_标准版.docx", size: "89 KB" },
              { name: "资质要求清单.xlsx", size: "45 KB" },
            ].map((ref, i) => (
              <div
                key={i}
                className="flex items-center gap-2 rounded-md border border-background-300 bg-background-50 p-2 transition-colors hover:border-primary-200"
              >
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-secondary-100 text-secondary-600">
                  <i className="ri-file-text-line text-xs"></i>
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-xs text-foreground-700">{ref.name}</div>
                  <div className="text-[10px] text-foreground-400">{ref.size}</div>
                </div>
                <button
                  type="button"
                  className="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center rounded text-foreground-400 hover:bg-background-200 hover:text-primary-600"
                  title="引用"
                >
                  <i className="ri-link text-xs"></i>
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}