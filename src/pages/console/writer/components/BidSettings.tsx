import { useEffect, useMemo, useState } from "react";
import {
  modelOptions, defaultStyle, pageSliderTicks, defaultPage, defaultLayout,
  layoutFontSizes, layoutLineSpacings, defaultImage, normalImageOptions,
  archImageOptions, aiImageStyles,
  type StyleConfig, type PageConfig, type LayoutConfig, type ImageConfig,
} from "@/mocks/writerSteps";
import { KNOWLEDGE_SCOPES, KNOWLEDGE_TYPES, listKnowledgeDocuments, listProductLibraries, type KnowledgeDoc, type ProductLibrary } from "@/lib/api";

export interface WriterSettingsPayload {
  style: StyleConfig;
  page: PageConfig;
  layout: LayoutConfig;
  image: ImageConfig;
}

interface BidSettingsProps {
  projectId: string;
  modelId: string;
  onModelChange: (id: string) => void;
  selectedKnowledge: string[];
  onKnowledgeChange: (ids: string[]) => void;
  selectedProductLibraryId: string;
  onProductLibraryChange: (id: string) => void;
  initialSettings?: Partial<WriterSettingsPayload>;
  onNext: (settings: WriterSettingsPayload) => void;
}

export default function BidSettings({
  projectId,
  modelId,
  onModelChange,
  selectedKnowledge,
  onKnowledgeChange,
  selectedProductLibraryId,
  onProductLibraryChange,
  initialSettings,
  onNext,
}: BidSettingsProps) {
  const [style, setStyle] = useState<StyleConfig>(initialSettings?.style ?? defaultStyle);
  const [page, setPage] = useState<PageConfig>(initialSettings?.page ?? defaultPage);
  const [layout, setLayout] = useState<LayoutConfig>(initialSettings?.layout ?? defaultLayout);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [scope, setScope] = useState("全部");
  const [type, setType] = useState("全部");
  const [kw, setKw] = useState("");
  const [image, setImage] = useState<ImageConfig>(initialSettings?.image ?? defaultImage);

  const [knowledgeDocs, setKnowledgeDocs] = useState<KnowledgeDoc[]>([]);
  const [productLibraries, setProductLibraries] = useState<ProductLibrary[]>([]);

  useEffect(() => {
    let cancelled = false;
    listKnowledgeDocuments({ projectId })
      .then((docs) => {
        if (!cancelled) setKnowledgeDocs(docs);
      })
      .catch(() => {
        /* 知识库拉取失败不阻塞标书设置流程，列表保持为空 */
      });
    listProductLibraries()
      .then((libs) => {
        if (!cancelled) setProductLibraries(libs);
      })
      .catch(() => {
        /* 产品库拉取失败不阻塞设置流程 */
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const filtered = useMemo(() => {
    return knowledgeDocs.filter((d) => {
      if (scope !== "全部" && d.scope !== scope) return false;
      if (type !== "全部" && d.type !== type) return false;
      if (kw && !(d.title.includes(kw) || d.tags.some((t) => t.includes(kw)))) return false;
      return true;
    });
  }, [knowledgeDocs, scope, type, kw]);

  const toggle = (id: string) => {
    if (selectedKnowledge.includes(id)) {
      onKnowledgeChange(selectedKnowledge.filter((x) => x !== id));
    } else {
      onKnowledgeChange([...selectedKnowledge, id]);
    }
  };

  const checkCls =
    "flex h-8 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border px-2.5 text-xs transition-colors";
  const inputCls =
    "h-8 w-full rounded-md border border-background-300 bg-background-50 px-2.5 text-xs text-foreground-900 outline-none focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500";

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-background-300 bg-background-100">
      {/* 头部 */}
      <div className="flex shrink-0 items-center gap-2.5 border-b border-background-300 px-4 py-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-md bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
          <i className="ri-settings-3-line text-base"></i>
        </span>
        <div>
          <div className="font-heading text-sm font-semibold tracking-wide text-foreground-900">第一步 · 标书设置</div>
          <div className="text-xs text-foreground-500">选择撰写大模型，目录生成与正文生成均使用该模型</div>
        </div>
        <span className="ml-auto rounded-md bg-secondary-100 px-2 py-1 text-[11px] font-medium text-secondary-700">
          {selectedProductLibraryId ? "已选产品库" : `${selectedKnowledge.length} 份知识库资料已选中`}
        </span>
      </div>

      {/* 内容区 */}
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {/* 1. 大模型选择 */}
        <section className="rounded-lg border border-background-300 bg-background-50 p-3.5">
          <div className="mb-2.5 flex items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded bg-primary-500 text-[10px] font-bold text-background-50">1</span>
            <h4 className="text-sm font-semibold text-foreground-900">选择撰写大模型</h4>
            <span className="text-[11px] text-foreground-500">目录与章节正文均由该模型生成</span>
          </div>
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
            {modelOptions.map((m) => {
              const active = m.id === modelId;
              return (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => onModelChange(m.id)}
                  className={`flex cursor-pointer flex-col gap-1.5 rounded-lg border p-3 text-left transition-all ${
                    active ? "border-primary-400 bg-primary-50/70 ring-1 ring-primary-200" : "border-background-300 bg-background-100 hover:border-primary-200"
                  }`}
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className={`flex h-6 w-6 items-center justify-center rounded-full border text-[10px] ${active ? "border-primary-500 bg-primary-500 text-background-50" : "border-background-300 text-foreground-400"}`}>
                      {active ? <i className="ri-check-line"></i> : <i className="ri-robot-2-line"></i>}
                    </span>
                    {m.tag && <span className="rounded bg-accent-100 px-1.5 py-0.5 text-[10px] font-medium text-accent-700">{m.tag}</span>}
                  </div>
                  <div className="text-sm font-semibold text-foreground-900">{m.name}</div>
                  <div className="text-[11px] text-foreground-500">{m.provider}</div>
                  <p className="text-[11px] leading-relaxed text-foreground-600">{m.desc}</p>
                  <div className="mt-0.5 flex gap-1.5">
                    <span className="rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">上下文 {m.ctx}</span>
                    <span className="rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">速度 {m.speed}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </section>

        <section className="rounded-lg border border-background-300 bg-background-50 p-3.5">
          <div className="mb-2.5 flex flex-wrap items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded bg-primary-500 text-[10px] font-bold text-background-50">2</span>
            <h4 className="text-sm font-semibold text-foreground-900">投标产品</h4>
            <span className="text-[11px] text-foreground-500">一个项目只选一个产品库，正文按已入库功能点组句插图</span>
          </div>
          {productLibraries.length === 0 ? (
            <p className="text-xs text-foreground-500">暂无产品库。请先在「产品功能库」上传技术标并审核入库，或改用下方知识库切片。</p>
          ) : (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {productLibraries.map((lib) => {
                const active = selectedProductLibraryId === lib.id;
                return (
                  <button
                    key={lib.id}
                    type="button"
                    onClick={() => onProductLibraryChange(active ? "" : lib.id)}
                    className={`flex cursor-pointer flex-col gap-1 rounded-lg border p-3 text-left transition-all ${
                      active ? "border-primary-400 bg-primary-50/70 ring-1 ring-primary-200" : "border-background-300 bg-background-100 hover:border-primary-200"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-semibold text-foreground-900">{lib.name}</span>
                      <span className="rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">{lib.category}</span>
                    </div>
                    <p className="line-clamp-2 text-[11px] text-foreground-500">{lib.description || "无说明"}</p>
                    <span className="text-[10px] text-foreground-500">已入库功能点以审核为准 · 共 {lib.featureCount || 0} 条</span>
                  </button>
                );
              })}
            </div>
          )}
        </section>

        {/* 知识库引用配置 */}
        <section className="rounded-lg border border-background-300 bg-background-50 p-3.5">
          <div className="mb-2.5 flex flex-wrap items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded bg-primary-500 text-[10px] font-bold text-background-50">2</span>
            <h4 className="text-sm font-semibold text-foreground-900">知识库引用配置</h4>
            <span className="text-[11px] text-foreground-500">勾选后，AI 撰写正文时会自动检索并引用这些资料切片</span>
            <span className="ml-auto text-[11px] text-primary-600">
              已选 <span className="font-label font-semibold">{selectedKnowledge.length}</span> 份
            </span>
          </div>

          {/* 筛选栏 */}
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <select value={scope} onChange={(e) => setScope(e.target.value)} className={`${checkCls} bg-background-100 text-foreground-600`}>
              {KNOWLEDGE_SCOPES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
            <select value={type} onChange={(e) => setType(e.target.value)} className={`${checkCls} bg-background-100 text-foreground-600`}>
              <option>全部类型</option>
              {KNOWLEDGE_TYPES.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
            <div className="relative flex-1 min-w-[180px]">
              <i className="ri-search-line absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-foreground-400"></i>
              <input value={kw} onChange={(e) => setKw(e.target.value)} placeholder="搜索标题或标签…" className={`${inputCls} pl-7`} />
            </div>
            <button
              type="button"
              onClick={() => onKnowledgeChange(knowledgeDocs.map((d) => d.id))}
              className={`${checkCls} border-primary-200 bg-primary-50 text-primary-600 hover:bg-primary-100`}
            >
              <i className="ri-check-double-line text-xs"></i>
              全选
            </button>
            <button
              type="button"
              onClick={() => onKnowledgeChange([])}
              className={`${checkCls} border-background-300 bg-background-100 text-foreground-500 hover:bg-background-200`}
            >
              清空
            </button>
          </div>

          {/* 列表 */}
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {filtered.map((doc) => {
              const active = selectedKnowledge.includes(doc.id);
              return (
                <button
                  key={doc.id}
                  type="button"
                  onClick={() => toggle(doc.id)}
                  className={`flex cursor-pointer items-start gap-2 rounded-lg border p-2.5 text-left transition-all ${
                    active ? "border-primary-300 bg-primary-50/60" : "border-background-200 bg-background-100 hover:border-primary-200"
                  }`}
                >
                  <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border text-[9px] ${active ? "border-primary-500 bg-primary-500 text-background-50" : "border-background-300 text-transparent"}`}>
                    <i className="ri-check-line"></i>
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-medium text-foreground-800">{doc.title}</span>
                    <span className="mt-0.5 flex flex-wrap gap-1">
                      <span className="rounded bg-secondary-100 px-1 py-0.5 text-[10px] text-secondary-700">{doc.scope}</span>
                      <span className="rounded bg-secondary-100 px-1 py-0.5 text-[10px] text-secondary-700">{doc.type}</span>
                      <span className="rounded bg-secondary-100 px-1 py-0.5 text-[10px] text-secondary-700">{doc.sliceCount}切片</span>
                    </span>
                    {doc.reviewFlag && <span className="mt-1 block text-[10px] text-accent-700">{doc.reviewFlag}</span>}
                  </span>
                </button>
              );
            })}
            {filtered.length === 0 && (
              <div className="col-span-full py-8 text-center text-xs text-foreground-500">无匹配的知识库资料</div>
            )}
          </div>
        </section>

        {/* 3. 页数设置 — 滑块 */}
        <section className="rounded-lg border border-background-300 bg-background-50 p-3.5">
          <div className="mb-1 flex items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded bg-primary-500 text-[10px] font-bold text-background-50">3</span>
            <h4 className="text-sm font-semibold text-foreground-900">预设标书页数</h4>
            <span className="text-[11px] text-foreground-500">
              生成全文约 {page.total} 页，{(page.total * 0.08).toFixed(1)} 万字，系统可能会根据项目内容对页数进行调整。
            </span>
            <button
              type="button"
              onClick={() => setAdvancedOpen(!advancedOpen)}
              className="ml-auto flex cursor-pointer items-center gap-1 text-[11px] font-medium text-primary-500 transition-colors hover:text-primary-600"
            >
              <i className="ri-equalizer-line"></i>
              高级选项
            </button>
          </div>

          {/* 滑块区域 */}
          <div className="relative px-2 pt-6 pb-1">
            {/* 气泡提示 */}
            <div
              className="absolute top-0 flex -translate-x-1/2 flex-col items-center"
              style={{ left: `${(page.total / 2000) * 100}%` }}
            >
              <div className="rounded-md bg-primary-500 px-2 py-0.5 text-xs font-semibold text-background-50 shadow-sm">
                {page.total}
              </div>
              <div className="h-1.5 w-1.5 rotate-45 bg-primary-500 -mt-0.5"></div>
            </div>

            {/* 轨道 + thumb */}
            <input
              type="range"
              min={0}
              max={2000}
              step={10}
              value={page.total}
              onChange={(e) => {
                const total = Number(e.target.value);
                setPage({ ...page, total });
              }}
              className="relative z-10 w-full cursor-pointer appearance-none bg-transparent py-1
                [&::-webkit-slider-runnable-track]:h-2 [&::-webkit-slider-runnable-track]:rounded-full [&::-webkit-slider-runnable-track]:bg-background-200
                [&::-moz-range-track]:h-2 [&::-moz-range-track]:rounded-full [&::-moz-range-track]:bg-background-200
                [&::-webkit-slider-thumb]:-mt-1.5 [&::-webkit-slider-thumb]:h-5 [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-primary-500 [&::-webkit-slider-thumb]:bg-background-50 [&::-webkit-slider-thumb]:shadow-md
                [&::-moz-range-thumb]:-mt-1.5 [&::-moz-range-thumb]:h-5 [&::-moz-range-thumb]:w-5 [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-primary-500 [&::-moz-range-thumb]:bg-background-50 [&::-moz-range-thumb]:shadow-md"
            />

            {/* 刻度线与标签 */}
            <div className="relative mt-1 h-4">
              {pageSliderTicks.map((tick, i) => {
                const pct = (tick / 2000) * 100;
                const isKey = tick % 200 === 0 || tick === 0;
                return (
                  <div
                    key={i}
                    className="absolute top-0 flex flex-col items-center"
                    style={{ left: `${pct}%`, transform: "translateX(-50%)" }}
                  >
                    <span className={`block rounded-full ${isKey ? "h-1.5 w-1.5 bg-primary-400" : "h-1 w-1 bg-background-300"}`}></span>
                    <span className={`mt-0.5 text-[10px] ${isKey ? "text-foreground-700 font-medium" : "text-foreground-400"}`}>
                      {tick}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 高级选项展开 */}
          {advancedOpen && (
            <div className="mt-3 rounded-lg border border-background-200 bg-background-100 p-3">
              <div className="mb-2 text-[11px] font-medium text-foreground-600">板块篇幅分配</div>
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                {(
                  [
                    { key: "cover", label: "封面 / 目录", icon: "ri-file-list-3-line" },
                    { key: "body", label: "正文（技术方案等）", icon: "ri-file-text-line" },
                    { key: "appendix", label: "附件 / 资质证明", icon: "ri-attachment-2" },
                  ] as const
                ).map((item) => (
                  <div key={item.key} className="rounded-lg border border-background-200 bg-background-50 p-2.5">
                    <label className="mb-1 flex items-center gap-1 text-[11px] font-medium text-foreground-600">
                      <i className={`${item.icon} text-primary-500`}></i>
                      {item.label}
                    </label>
                    <div className="flex items-center gap-1.5">
                      <input
                        type="number"
                        min={0}
                        value={page[item.key]}
                        onChange={(e) => setPage({ ...page, [item.key]: Math.max(0, Number(e.target.value) || 0) })}
                        className={`${inputCls} cursor-text`}
                      />
                      <span className="whitespace-nowrap text-[11px] text-foreground-500">页</span>
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-3 flex items-center justify-between rounded-md bg-secondary-50 px-3 py-2 text-[11px] text-secondary-800">
                <span>
                  <i className="ri-calculator-line mr-1"></i>
                  板块合计 <span className="font-label font-semibold">{page.cover + page.body + page.appendix}</span> 页
                  {page.cover + page.body + page.appendix !== page.total && (
                    <span className="ml-1 text-accent-700">（与滑块总页数不一致）</span>
                  )}
                </span>
                <button
                  type="button"
                  onClick={() => setPage({ ...page, cover: 6, body: Math.max(10, page.total - 36), appendix: 30 })}
                  className="text-[11px] text-primary-600 hover:text-primary-700"
                >
                  自动分配
                </button>
              </div>
            </div>
          )}
        </section>

        {/* 4. 排版高级选项 */}
        <section className="rounded-lg border border-background-300 bg-background-50 p-3.5">
          {/* 标题区 */}
          <div className="mb-1 flex items-start gap-2">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-500 text-background-50">
              <i className="ri-stack-line text-base"></i>
            </span>
            <div>
              <h4 className="text-sm font-semibold text-foreground-900">排版高级选项</h4>
              <p className="text-[11px] text-foreground-500">提前设置影响页数的排版项，预估页数更精准</p>
            </div>
          </div>

          {/* 页边距 */}
          <div className="mt-3 rounded-lg border border-background-200 bg-background-100 p-3">
            <div className="mb-3 flex items-center gap-3">
              <span className="flex items-center gap-1 text-xs font-semibold text-foreground-800">
                <span className="inline-block h-3.5 w-1 rounded-sm bg-primary-500"></span>
                页边距
              </span>
              <button
                type="button"
                onClick={() => setLayout({ ...layout, margins: { top: 2, bottom: 2, left: 2, right: 2 } })}
                className="flex cursor-pointer items-center gap-1 rounded-full border border-primary-200 bg-primary-50 px-2.5 py-0.5 text-[11px] font-medium text-primary-600 transition-colors hover:bg-primary-100"
              >
                <i className="ri-file-copy-line text-xs"></i>
                常用规格
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2.5">
              {(
                [
                  { key: "top", label: "上边距" },
                  { key: "bottom", label: "下边距" },
                  { key: "left", label: "左边距" },
                  { key: "right", label: "右边距" },
                ] as const
              ).map((item) => (
                <div key={item.key} className="flex items-center gap-2">
                  <span className="shrink-0 text-xs text-foreground-600">{item.label}</span>
                  <div className="flex flex-1 items-center rounded-md border border-background-300 bg-background-50">
                    <input
                      type="number"
                      min={0.5}
                      max={5}
                      step={0.1}
                      value={layout.margins[item.key]}
                      onChange={(e) => {
                        let v = parseFloat(e.target.value);
                        if (Number.isNaN(v)) v = 0.5;
                        v = Math.max(0.5, Math.min(5, v));
                        setLayout({ ...layout, margins: { ...layout.margins, [item.key]: v } });
                      }}
                      className="h-8 w-full bg-transparent px-2.5 text-xs text-foreground-900 outline-none"
                    />
                    <span className="shrink-0 pr-2.5 text-xs text-foreground-500">cm</span>
                    <div className="flex flex-col border-l border-background-300">
                      <button
                        type="button"
                        onClick={() => {
                          const v = Math.min(5, Math.round((layout.margins[item.key] + 0.1) * 10) / 10);
                          setLayout({ ...layout, margins: { ...layout.margins, [item.key]: v } });
                        }}
                        className="flex h-4 cursor-pointer items-center justify-center px-1.5 hover:bg-background-200"
                      >
                        <i className="ri-arrow-up-s-fill text-[10px] text-foreground-400"></i>
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          const v = Math.max(0.5, Math.round((layout.margins[item.key] - 0.1) * 10) / 10);
                          setLayout({ ...layout, margins: { ...layout.margins, [item.key]: v } });
                        }}
                        className="flex h-4 cursor-pointer items-center justify-center px-1.5 hover:bg-background-200"
                      >
                        <i className="ri-arrow-down-s-fill text-[10px] text-foreground-400"></i>
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-foreground-500">单边可设 0.5~5cm，超出范围会自动收敛</p>
          </div>

          {/* 字号 & 行间距 */}
          <div className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-[11px] font-medium text-foreground-600">正文字号</label>
              <select
                value={layout.fontSize}
                onChange={(e) => setLayout({ ...layout, fontSize: e.target.value })}
                className={`${inputCls} cursor-pointer`}
              >
                {layoutFontSizes.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-foreground-600">正文行间距</label>
              <select
                value={layout.lineSpacing}
                onChange={(e) => setLayout({ ...layout, lineSpacing: e.target.value })}
                className={`${inputCls} cursor-pointer`}
              >
                {layoutLineSpacings.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </div>
          </div>
        </section>

        {/* 5. 配图设置 */}
        <section className="rounded-lg border border-background-300 bg-background-50 p-3.5">
          <div className="mb-1 flex items-start gap-2">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-500 text-background-50">
              <i className="ri-image-2-line text-base"></i>
            </span>
            <div>
              <h4 className="text-sm font-semibold text-foreground-900">配图设置</h4>
              <p className="text-[11px] text-foreground-500">配置标书正文配图与架构图的生成来源，控制配图风格统一性</p>
            </div>
          </div>

          {/* 一、普通配图 */}
          <div className="mt-3 rounded-lg border border-background-200 bg-background-100 p-3">
            <div className="mb-2.5 flex items-center gap-3">
              <span className="flex items-center gap-1 text-xs font-semibold text-foreground-800">
                <span className="inline-block h-3.5 w-1 rounded-sm bg-primary-500"></span>
                一、普通配图
              </span>
              <span className="text-[11px] text-foreground-500">正文内常规配图的获取方式</span>
            </div>
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
              {normalImageOptions.map((opt) => {
                const active = image.normal === opt;
                const meta = {
                  "AI生图": { icon: "ri-sparkling-line", desc: "由豆包 Seedream 按章节描述生成配图" },
                  "本机上传": { icon: "ri-upload-2-line", desc: "在正文配图面板上传本地图片插入章节" },
                }[opt] ?? { icon: "ri-image-line", desc: "在撰写正文的配图面板中完成" };
                return (
                  <button
                    key={opt}
                    type="button"
                    onClick={() => setImage({ ...image, normal: opt })}
                    className={`flex cursor-pointer items-start gap-2 rounded-lg border p-2.5 text-left transition-all ${
                      active ? "border-primary-400 bg-primary-50/70 ring-1 ring-primary-200" : "border-background-200 bg-background-50 hover:border-primary-200"
                    }`}
                  >
                    <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-sm ${active ? "bg-primary-500 text-background-50" : "bg-secondary-100 text-secondary-700"}`}>
                      <i className={meta.icon}></i>
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5 text-xs font-medium text-foreground-800">
                        {opt}
                        {active && <i className="ri-checkbox-circle-fill text-primary-500"></i>}
                      </span>
                      <span className="mt-0.5 block text-[11px] leading-snug text-foreground-500">{meta.desc}</span>
                    </span>
                  </button>
                );
              })}
            </div>
            {image.normal === "AI生图" && (
              <div className="mt-2.5 flex flex-wrap items-center gap-2 rounded-md bg-secondary-50 px-3 py-2">
                <span className="text-[11px] text-secondary-800">生图风格</span>
                <div className="flex flex-wrap gap-1.5">
                  {aiImageStyles.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setImage({ ...image, aiStyle: s })}
                      className={`cursor-pointer whitespace-nowrap rounded-full border px-2.5 py-1 text-[11px] transition-colors ${
                        image.aiStyle === s ? "border-primary-400 bg-primary-50 text-primary-600" : "border-background-300 bg-background-50 text-foreground-600 hover:border-primary-200"
                      }`}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* 二、架构图 */}
          <div className="mt-3 rounded-lg border border-background-200 bg-background-100 p-3">
            <div className="mb-2.5 flex items-center gap-3">
              <span className="flex items-center gap-1 text-xs font-semibold text-foreground-800">
                <span className="inline-block h-3.5 w-1 rounded-sm bg-accent-500"></span>
                二、架构图
              </span>
              <span className="text-[11px] text-foreground-500">系统 / 部署架构图表的生成方式</span>
            </div>
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              {archImageOptions.map((opt) => {
                const active = image.arch === opt;
                const meta = {
                  "AI生成架构图": { icon: "ri-organization-chart", desc: "由豆包 Seedream 按架构描述生成示意图" },
                  "本机上传": { icon: "ri-upload-2-line", desc: "在配图面板上传已有架构图插入章节" },
                }[opt] ?? { icon: "ri-image-line", desc: "在撰写正文的配图面板中完成" };
                return (
                  <button
                    key={opt}
                    type="button"
                    onClick={() => setImage({ ...image, arch: opt })}
                    className={`flex cursor-pointer items-start gap-2 rounded-lg border p-2.5 text-left transition-all ${
                      active ? "border-primary-400 bg-primary-50/70 ring-1 ring-primary-200" : "border-background-200 bg-background-50 hover:border-primary-200"
                    }`}
                  >
                    <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-sm ${active ? "bg-primary-500 text-background-50" : "bg-secondary-100 text-secondary-700"}`}>
                      <i className={meta.icon}></i>
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5 text-xs font-medium text-foreground-800">
                        {opt}
                        {active && <i className="ri-checkbox-circle-fill text-primary-500"></i>}
                      </span>
                      <span className="mt-0.5 block text-[11px] leading-snug text-foreground-500">{meta.desc}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </section>

        {/* 6. 撰写风格 */}
        <section className="rounded-lg border border-background-300 bg-background-50 p-3.5">
          <div className="mb-2.5 flex items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded bg-primary-500 text-[10px] font-bold text-background-50">6</span>
            <h4 className="text-sm font-semibold text-foreground-900">撰写风格与规范</h4>
          </div>
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-[11px] font-medium text-foreground-600">行文基调</label>
              <select value={style.tone} onChange={(e) => setStyle({ ...style, tone: e.target.value })} className={`${inputCls} cursor-pointer`}>
                <option>专业务实 · 突出量化指标</option>
                <option>稳健规范 · 偏重合规表述</option>
                <option>前瞻创新 · 强调技术领先</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-foreground-600">篇幅档位</label>
              <select value={style.length} onChange={(e) => setStyle({ ...style, length: e.target.value })} className={`${inputCls} cursor-pointer`}>
                <option>详细版（对标评分点逐项展开）</option>
                <option>标准版（均衡篇幅）</option>
                <option>精简版（突出要点）</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-foreground-600">企业署名 / 暗标</label>
              <select value={style.firmName} onChange={(e) => setStyle({ ...style, firmName: e.target.value })} className={`${inputCls} cursor-pointer`}>
                <option>我方投标企业（自动去标识）</option>
                <option>保留企业全称（非暗标）</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-foreground-600">格式规范</label>
              <select value={style.strictness} onChange={(e) => setStyle({ ...style, strictness: e.target.value })} className={`${inputCls} cursor-pointer`}>
                <option>严格遵循招标文件格式要求</option>
                <option>采用企业默认标书模板</option>
              </select>
            </div>
          </div>
        </section>
      </div>

      {/* 底部操作 */}
      <div className="flex shrink-0 items-center justify-between border-t border-background-300 bg-background-50 px-4 py-3">
        <span className="text-[11px] text-foreground-500">
          <i className="ri-sparkling-2-line mr-1 text-primary-500"></i>
          设置将保存到本项目，后续生成正文自动生效
        </span>
        <button
          type="button"
          onClick={() => onNext({ style, page, layout, image })}
          disabled={!modelId || (!selectedProductLibraryId && selectedKnowledge.length === 0)}
          className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          保存设置，进入下一步
          <i className="ri-arrow-right-s-line text-base"></i>
        </button>
      </div>
    </div>
  );
}