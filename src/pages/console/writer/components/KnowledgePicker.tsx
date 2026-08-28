import { useEffect, useMemo, useState } from "react";
import AuthImage from "../../components/AuthImage";
import { useAuth } from "@/context/AuthContext";
import {
  getKnowledgeChapterDetail,
  getKnowledgeChapters,
  listKnowledgeDocuments,
  listProductFeatures,
  listProductLibraries,
  listQualifications,
  suggestKnowledgeForChapter,
  type KnowledgeChapter,
  type KnowledgeDoc,
  type KnowledgeRef,
  type KnowledgeRefSource,
  type KnowledgeSliceImage,
  type ProductItem,
  type ProductLibrary,
  type QualificationAsset,
  type QualificationKind,
} from "@/lib/api";
import { collectHeadings, nestHeadings, type HeadingNode } from "../headingTree";

type SourceTab = KnowledgeRefSource;

interface KnowledgePickerProps {
  projectId: string;
  nodeNum: string;
  nodeTitle: string;
  nodeIdea?: string;
  initialRefs: KnowledgeRef[];
  onClose: () => void;
  onSave: (refs: KnowledgeRef[]) => void;
}

const QUAL_KIND_LABEL: Record<QualificationKind, string> = {
  cert: "企业证照",
  people: "人员证书",
  achievement: "业绩",
  equipment: "设备机具",
  credit: "信用材料",
  contract: "合同",
  financial: "财务",
};

const QUAL_KIND_ORDER: QualificationKind[] = [
  "cert",
  "people",
  "achievement",
  "contract",
  "financial",
  "equipment",
  "credit",
];

const TABS: { key: SourceTab; label: string; icon: string }[] = [
  { key: "product", label: "产品功能库", icon: "ri-apps-line" },
  { key: "qualification", label: "资质证照库", icon: "ri-vip-crown-line" },
  { key: "knowledge", label: "文档知识库", icon: "ri-book-2-line" },
];

const QUAL_DOC_ID = "qual-library";

type Preview =
  | { kind: "knowledge"; title: string; heading: string; paragraphs: string[]; images: KnowledgeSliceImage[]; loading: boolean }
  | { kind: "product"; item: ProductItem; libraryName: string }
  | { kind: "qualification"; item: QualificationAsset };

function sourceOf(ref: KnowledgeRef): SourceTab {
  return ref.source || "knowledge";
}

export default function KnowledgePicker({
  projectId,
  nodeNum,
  nodeTitle,
  nodeIdea,
  initialRefs,
  onClose,
  onSave,
}: KnowledgePickerProps) {
  const { token } = useAuth();
  const [tab, setTab] = useState<SourceTab>("product");
  const [refs, setRefs] = useState<KnowledgeRef[]>(
    initialRefs.map((r) => ({ ...r, source: r.source || "knowledge" })),
  );
  const [aiThinking, setAiThinking] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [keyword, setKeyword] = useState("");

  const [libraries, setLibraries] = useState<ProductLibrary[]>([]);
  const [libFeatures, setLibFeatures] = useState<Record<string, ProductItem[]>>({});
  const [expandedLibs, setExpandedLibs] = useState<Record<string, boolean>>({});
  const [expandedFeats, setExpandedFeats] = useState<Record<string, boolean>>({});

  const [quals, setQuals] = useState<QualificationAsset[]>([]);
  const [expandedKinds, setExpandedKinds] = useState<Record<string, boolean>>({});

  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [docChapters, setDocChapters] = useState<Record<string, KnowledgeChapter[]>>({});
  const [expandedDocs, setExpandedDocs] = useState<Record<string, boolean>>({});
  const [expandedHeadings, setExpandedHeadings] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let cancelled = false;
    listProductLibraries()
      .then((list) => {
        if (!cancelled) setLibraries(list);
      })
      .catch(() => {
        if (!cancelled) setLibraries([]);
      });
    listKnowledgeDocuments({ projectId })
      .then((list) => {
        if (!cancelled) setDocs(list);
      })
      .catch(() => {
        if (!cancelled) setDocs([]);
      });
    if (token) {
      listQualifications(token)
        .then((list) => {
          if (!cancelled) setQuals(list);
        })
        .catch(() => {
          if (!cancelled) setQuals([]);
        });
    }
    return () => {
      cancelled = true;
    };
  }, [projectId, token]);

  const ensureFeatures = (libraryId: string) => {
    if (libFeatures[libraryId]) return;
    listProductFeatures(libraryId)
      .then((items) => setLibFeatures((prev) => ({ ...prev, [libraryId]: items })))
      .catch(() => setLibFeatures((prev) => ({ ...prev, [libraryId]: [] })));
  };

  const ensureChapters = (docId: string) => {
    if (docChapters[docId]) return;
    getKnowledgeChapters(docId)
      .then((chapters) => setDocChapters((prev) => ({ ...prev, [docId]: chapters })))
      .catch(() => setDocChapters((prev) => ({ ...prev, [docId]: [] })));
  };

  const toggleIds = (source: SourceTab, docId: string, docTitle: string, ids: string[], on: boolean) => {
    setRefs((prev) => {
      const existing = prev.find((r) => sourceOf(r) === source && r.docId === docId);
      const current = new Set(existing?.chapters || []);
      ids.forEach((id) => {
        if (on) current.add(id);
        else current.delete(id);
      });
      const rest = prev.filter((r) => !(sourceOf(r) === source && r.docId === docId));
      if (current.size === 0) return rest;
      return [
        ...rest,
        {
          source,
          docId,
          docTitle,
          chapters: [...current],
          mode: existing?.mode === "ai" ? "ai" : "manual",
        },
      ];
    });
  };

  const selectedSet = (source: SourceTab, docId: string) =>
    new Set(refs.find((r) => sourceOf(r) === source && r.docId === docId)?.chapters || []);

  const openKnowledgePreview = (docId: string, docTitle: string, heading: string) => {
    setPreview({ kind: "knowledge", title: docTitle, heading, paragraphs: [], images: [], loading: true });
    getKnowledgeChapterDetail(docId, heading)
      .then((detail) =>
        setPreview({
          kind: "knowledge",
          title: detail.docTitle || docTitle,
          heading: detail.heading,
          paragraphs: detail.paragraphs,
          images: detail.images || [],
          loading: false,
        }),
      )
      .catch(() =>
        setPreview({
          kind: "knowledge",
          title: docTitle,
          heading,
          paragraphs: ["加载失败，请稍后重试"],
          images: [],
          loading: false,
        }),
      );
  };

  const runAi = () => {
    setAiThinking(true);
    const query = `${nodeTitle} ${nodeIdea ?? ""}`.trim().toLowerCase();
    const tokens = query.split(/\s+/).filter((t) => t.length >= 2);

    const hit = (...parts: string[]) => {
      const blob = parts.join(" ").toLowerCase();
      return tokens.some((t) => blob.includes(t)) || (query && blob.includes(query));
    };

    const existingProduct = refs.filter((r) => sourceOf(r) === "product");

    const qualIds = quals.filter((q) => hit(q.name, q.kind, q.owner, q.number, q.detail)).map((q) => q.id);
    const qualRef: KnowledgeRef | null = qualIds.length
      ? { source: "qualification", docId: QUAL_DOC_ID, docTitle: "资质证照库", chapters: qualIds, mode: "ai" }
      : null;

    suggestKnowledgeForChapter(projectId, `${nodeTitle} ${nodeIdea ?? ""}`.trim())
      .catch(() => [])
      .then((suggestions) => {
        const knowledgeRefs: KnowledgeRef[] = (suggestions || []).map((s) => ({
          source: "knowledge" as const,
          docId: s.docId,
          docTitle: s.docTitle,
          chapters: s.chapters,
          mode: "ai" as const,
        }));
        knowledgeRefs.forEach((r) => {
          setExpandedDocs((p) => ({ ...p, [r.docId]: true }));
          ensureChapters(r.docId);
        });
        const next = [...existingProduct, ...(qualRef ? [qualRef] : []), ...knowledgeRefs];
        setRefs(next);
        if (qualRef) setTab("qualification");
        else if (knowledgeRefs.length) setTab("knowledge");
      })
      .finally(() => setAiThinking(false));
  };

  const kw = keyword.trim().toLowerCase();
  const visibleLibs = useMemo(
    () => (kw ? libraries.filter((l) => l.name.toLowerCase().includes(kw) || (l.description || "").toLowerCase().includes(kw)) : libraries),
    [libraries, kw],
  );
  const visibleQuals = useMemo(
    () =>
      kw
        ? quals.filter(
            (q) =>
              q.name.toLowerCase().includes(kw) ||
              q.number.toLowerCase().includes(kw) ||
              (q.owner || "").toLowerCase().includes(kw),
          )
        : quals,
    [quals, kw],
  );
  const visibleDocs = useMemo(
    () => (kw ? docs.filter((d) => d.title.toLowerCase().includes(kw)) : docs),
    [docs, kw],
  );

  const save = () => {
    onSave(refs);
    onClose();
  };

  const refCount = refs.reduce((n, r) => n + Math.max(r.chapters.length, 1), 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground-950/40 p-4" onClick={onClose}>
      <div
        className="flex h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-background-300 bg-background-100"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2.5 border-b border-background-300 px-4 py-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
            <i className="ri-bookmark-line text-base"></i>
          </span>
          <div className="min-w-0 flex-1">
            <div className="font-heading text-sm font-semibold tracking-wide text-foreground-900">设置参考资料</div>
            <div className="truncate text-[11px] text-foreground-500">
              章节 {nodeNum} · {nodeTitle} · 产品库/资质库勾选到二级，文档知识库勾选到三级
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

        <div className="border-b border-background-300 bg-background-50 px-4 py-3">
          <div className="flex items-center gap-2.5">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-accent-100 text-accent-600">
              <i className="ri-sparkling-2-line text-sm"></i>
            </span>
            <div className="flex-1">
              <div className="text-xs font-semibold text-foreground-800">AI 自动选择</div>
              <div className="text-[11px] text-foreground-500">
                按本章检索证照与知识文档；产品功能请用目录页「自动匹配产品功能库」或在本页手动勾选
              </div>
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
        </div>

        <div className="flex min-h-0 flex-1">
          <div className="flex w-[46%] min-w-0 flex-col border-r border-background-300">
            <div className="flex items-center gap-1 border-b border-background-200 bg-background-50 px-3 py-2">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => setTab(t.key)}
                  className={`flex cursor-pointer items-center gap-1 whitespace-nowrap rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
                    tab === t.key ? "bg-primary-500 text-background-50" : "text-foreground-600 hover:bg-background-200"
                  }`}
                >
                  <i className={`${t.icon} text-xs`}></i>
                  {t.label}
                </button>
              ))}
            </div>
            <div className="border-b border-background-200 px-3 py-2">
              <div className="relative">
                <i className="ri-search-line absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-foreground-400"></i>
                <input
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  placeholder={tab === "product" ? "搜索产品或功能…" : tab === "qualification" ? "搜索证照 / 证号…" : "搜索文档…"}
                  className="h-8 w-full rounded-md border border-background-300 bg-background-50 pl-8 pr-3 text-xs outline-none focus:border-primary-400"
                />
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
              {tab === "product" && (
                <ProductTree
                  libraries={visibleLibs}
                  libFeatures={libFeatures}
                  expandedLibs={expandedLibs}
                  expandedFeats={expandedFeats}
                  selectedOf={(id) => selectedSet("product", id)}
                  onToggleLib={(lib, open) => {
                    setExpandedLibs((p) => ({ ...p, [lib.id]: open }));
                    if (open) ensureFeatures(lib.id);
                  }}
                  onToggleFeat={(id, open) => setExpandedFeats((p) => ({ ...p, [id]: open }))}
                  onToggleIds={(lib, ids, on) => toggleIds("product", lib.id, lib.name, ids, on)}
                  onPreview={(item, lib) => setPreview({ kind: "product", item, libraryName: lib.name })}
                />
              )}
              {tab === "qualification" && (
                <QualTree
                  items={visibleQuals}
                  expandedKinds={expandedKinds}
                  selected={selectedSet("qualification", QUAL_DOC_ID)}
                  onToggleKind={(kind, open) => setExpandedKinds((p) => ({ ...p, [kind]: open }))}
                  onToggleIds={(ids, on) => toggleIds("qualification", QUAL_DOC_ID, "资质证照库", ids, on)}
                  onPreview={(item) => setPreview({ kind: "qualification", item })}
                />
              )}
              {tab === "knowledge" && (
                <DocTree
                  docs={visibleDocs}
                  docChapters={docChapters}
                  expandedDocs={expandedDocs}
                  expandedHeadings={expandedHeadings}
                  selectedOf={(id) => selectedSet("knowledge", id)}
                  onToggleDoc={(doc, open) => {
                    setExpandedDocs((p) => ({ ...p, [doc.id]: open }));
                    if (open) ensureChapters(doc.id);
                  }}
                  onToggleHeading={(key, open) => setExpandedHeadings((p) => ({ ...p, [key]: open }))}
                  onToggleIds={(doc, ids, on) => toggleIds("knowledge", doc.id, doc.title, ids, on)}
                  onPreview={(doc, heading) => openKnowledgePreview(doc.id, doc.title, heading)}
                />
              )}
            </div>
          </div>

          <div className="flex min-w-0 flex-1 flex-col bg-background-50">
            <div className="border-b border-background-200 px-4 py-2 text-xs font-medium text-foreground-700">
              <i className="ri-eye-line mr-1 text-primary-500"></i>
              在线预览
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
              {!preview && (
                <div className="flex h-full flex-col items-center justify-center gap-1 text-center text-xs text-foreground-500">
                  <i className="ri-file-search-line text-2xl text-foreground-400"></i>
                  在左侧目录中点选条目，即可在此查看功能说明、证照扫描件或文档章节
                </div>
              )}
              {preview?.kind === "knowledge" && (
                <div>
                  <div className="text-sm font-medium text-foreground-900">{preview.heading}</div>
                  <div className="mt-0.5 text-[11px] text-foreground-500">{preview.title}</div>
                  {preview.loading ? (
                    <div className="py-10 text-center text-xs text-foreground-500">
                      <i className="ri-loader-4-line mr-1 animate-spin"></i>
                      加载中…
                    </div>
                  ) : (
                    <div className="mt-3 space-y-2.5">
                      {(preview.images || []).length > 0 && (
                        <div className="grid grid-cols-2 gap-2">
                          {preview.images.map((img) => (
                            <div key={img.id} className="overflow-hidden rounded-lg border border-background-300 bg-background-50">
                              <AuthImage src={img.url} alt={img.caption} eager className="h-24 w-full object-cover" />
                              {img.caption ? (
                                <div className="truncate px-2 py-1 text-[10px] text-foreground-500">{img.caption}</div>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      )}
                      {preview.paragraphs.map((p, i) => (
                        <p key={i} className="text-[13px] leading-[1.9] text-foreground-600">
                          {p}
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {preview?.kind === "product" && <ProductPreview item={preview.item} libraryName={preview.libraryName} />}
              {preview?.kind === "qualification" && <QualPreview item={preview.item} />}
            </div>
          </div>
        </div>

        <div className="border-t border-background-300 bg-background-50 px-4 py-3">
          <div className="mb-2 flex flex-wrap gap-1.5">
            {refs.length === 0 ? (
              <span className="text-[11px] text-foreground-400">尚未选择参考资料</span>
            ) : (
              refs.map((r) => (
                <span key={`${sourceOf(r)}:${r.docId}`} className="flex items-center gap-1 rounded bg-secondary-100 px-2 py-0.5 text-[11px] text-secondary-700">
                  <i className={`${r.mode === "ai" ? "ri-sparkling-2-line" : "ri-bookmark-3-line"} text-xs`}></i>
                  {r.docTitle}
                  {r.chapters.length > 0 && <span className="text-secondary-500">（{r.chapters.length}）</span>}
                </span>
              ))
            )}
          </div>
          <div className="flex items-center justify-end gap-2">
            <span className="mr-auto text-[11px] text-foreground-500">已选 {refCount} 项</span>
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
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
            >
              <i className="ri-check-line text-sm"></i>
              保存设置
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ProductTree({
  libraries,
  libFeatures,
  expandedLibs,
  expandedFeats,
  selectedOf,
  onToggleLib,
  onToggleFeat,
  onToggleIds,
  onPreview,
}: {
  libraries: ProductLibrary[];
  libFeatures: Record<string, ProductItem[]>;
  expandedLibs: Record<string, boolean>;
  expandedFeats: Record<string, boolean>;
  selectedOf: (libraryId: string) => Set<string>;
  onToggleLib: (lib: ProductLibrary, open: boolean) => void;
  onToggleFeat: (id: string, open: boolean) => void;
  onToggleIds: (lib: ProductLibrary, ids: string[], on: boolean) => void;
  onPreview: (item: ProductItem, lib: ProductLibrary) => void;
}) {
  if (libraries.length === 0) {
    return <EmptyHint text="暂无产品库。请先在资源模块录入可投标产品。" />;
  }
  return (
    <div className="space-y-0.5">
      {libraries.map((lib) => {
        const open = !!expandedLibs[lib.id];
        const features = libFeatures[lib.id] || [];
        const selected = selectedOf(lib.id);
        return (
          <div key={lib.id}>
            <TreeRow
              depth={0}
              icon="ri-apps-line"
              label={lib.name}
              meta={`${lib.featureCount || features.length} 个一级功能`}
              expanded={open}
              hasChildren
              onToggleExpand={() => onToggleLib(lib, !open)}
            />
            {open &&
              features.map((feat) => {
                const kids = feat.children || [];
                const featOpen = expandedFeats[feat.id] ?? kids.length > 0;
                const ids = [feat.id, ...kids.map((c) => c.id)];
                const allOn = ids.every((id) => selected.has(id));
                return (
                  <div key={feat.id}>
                    <TreeRow
                      depth={1}
                      icon="ri-folder-line"
                      label={feat.name}
                      meta={kids.length ? `${kids.length} 个二级` : "一级功能"}
                      checked={selected.has(feat.id)}
                      indeterminate={!allOn && ids.some((id) => selected.has(id))}
                      expanded={featOpen}
                      hasChildren={kids.length > 0}
                      onToggleExpand={() => onToggleFeat(feat.id, !featOpen)}
                      onCheck={(on) => onToggleIds(lib, on ? ids : ids, on)}
                      onPreview={() => onPreview(feat, lib)}
                    />
                    {featOpen &&
                      kids.map((child) => (
                        <TreeRow
                          key={child.id}
                          depth={2}
                          icon="ri-file-list-2-line"
                          label={child.name}
                          meta="二级功能"
                          checked={selected.has(child.id)}
                          onCheck={(on) => onToggleIds(lib, [child.id], on)}
                          onPreview={() => onPreview(child, lib)}
                        />
                      ))}
                  </div>
                );
              })}
            {open && features.length === 0 && <div className="px-3 py-2 text-[11px] text-foreground-400">正在加载功能目录…</div>}
          </div>
        );
      })}
    </div>
  );
}

function QualTree({
  items,
  expandedKinds,
  selected,
  onToggleKind,
  onToggleIds,
  onPreview,
}: {
  items: QualificationAsset[];
  expandedKinds: Record<string, boolean>;
  selected: Set<string>;
  onToggleKind: (kind: string, open: boolean) => void;
  onToggleIds: (ids: string[], on: boolean) => void;
  onPreview: (item: QualificationAsset) => void;
}) {
  if (items.length === 0) {
    return <EmptyHint text="暂无证照。请先在资质证照库录入或抽取。" />;
  }
  return (
    <div className="space-y-0.5">
      {QUAL_KIND_ORDER.map((kind) => {
        const group = items.filter((q) => q.kind === kind);
        if (!group.length) return null;
        const open = expandedKinds[kind] ?? true;
        const ids = group.map((q) => q.id);
        const allOn = ids.every((id) => selected.has(id));
        return (
          <div key={kind}>
            <TreeRow
              depth={0}
              icon="ri-folder-line"
              label={QUAL_KIND_LABEL[kind]}
              meta={`${group.length} 条`}
              expanded={open}
              hasChildren
              checked={allOn}
              indeterminate={!allOn && ids.some((id) => selected.has(id))}
              onToggleExpand={() => onToggleKind(kind, !open)}
              onCheck={(on) => onToggleIds(ids, on)}
            />
            {open &&
              group.map((item) => (
                <TreeRow
                  key={item.id}
                  depth={1}
                  icon="ri-file-shield-2-line"
                  label={item.name}
                  meta={[item.number, item.owner].filter(Boolean).join(" · ") || QUAL_KIND_LABEL[item.kind]}
                  checked={selected.has(item.id)}
                  onCheck={(on) => onToggleIds([item.id], on)}
                  onPreview={() => onPreview(item)}
                />
              ))}
          </div>
        );
      })}
    </div>
  );
}

function DocTree({
  docs,
  docChapters,
  expandedDocs,
  expandedHeadings,
  selectedOf,
  onToggleDoc,
  onToggleHeading,
  onToggleIds,
  onPreview,
}: {
  docs: KnowledgeDoc[];
  docChapters: Record<string, KnowledgeChapter[]>;
  expandedDocs: Record<string, boolean>;
  expandedHeadings: Record<string, boolean>;
  selectedOf: (docId: string) => Set<string>;
  onToggleDoc: (doc: KnowledgeDoc, open: boolean) => void;
  onToggleHeading: (key: string, open: boolean) => void;
  onToggleIds: (doc: KnowledgeDoc, ids: string[], on: boolean) => void;
  onPreview: (doc: KnowledgeDoc, heading: string) => void;
}) {
  if (docs.length === 0) {
    return <EmptyHint text="该项目可见范围内暂无知识文档。" />;
  }
  return (
    <div className="space-y-0.5">
      {docs.map((doc) => {
        const open = !!expandedDocs[doc.id];
        const chapters = docChapters[doc.id] || [];
        const tree = nestHeadings(chapters);
        const selected = selectedOf(doc.id);
        return (
          <div key={doc.id}>
            <TreeRow
              depth={0}
              icon="ri-file-text-line"
              label={doc.title}
              meta={`${doc.scope} · ${doc.sliceCount} 切片`}
              expanded={open}
              hasChildren
              onToggleExpand={() => onToggleDoc(doc, !open)}
            />
            {open && tree.length === 0 && <div className="px-3 py-2 text-[11px] text-foreground-400">该文档暂无可识别章节</div>}
            {open &&
              tree.map((node) => (
                <HeadingBranch
                  key={node.heading}
                  doc={doc}
                  node={node}
                  selected={selected}
                  expandedHeadings={expandedHeadings}
                  onToggleHeading={onToggleHeading}
                  onToggleIds={onToggleIds}
                  onPreview={onPreview}
                />
              ))}
          </div>
        );
      })}
    </div>
  );
}

function HeadingBranch({
  doc,
  node,
  selected,
  expandedHeadings,
  onToggleHeading,
  onToggleIds,
  onPreview,
}: {
  doc: KnowledgeDoc;
  node: HeadingNode;
  selected: Set<string>;
  expandedHeadings: Record<string, boolean>;
  onToggleHeading: (key: string, open: boolean) => void;
  onToggleIds: (doc: KnowledgeDoc, ids: string[], on: boolean) => void;
  onPreview: (doc: KnowledgeDoc, heading: string) => void;
}) {
  const key = `${doc.id}:${node.heading}`;
  const open = expandedHeadings[key] ?? node.depth < 3;
  const ids = collectHeadings(node);
  const allOn = ids.every((id) => selected.has(id));
  const someOn = ids.some((id) => selected.has(id));
  return (
    <div>
      <TreeRow
        depth={Math.min(node.depth, 4)}
        icon={node.children.length ? "ri-folder-line" : "ri-article-line"}
        label={node.heading}
        meta={
          node.children.length
            ? `${node.children.length} 节${node.imageCount ? ` · ${node.imageCount} 图` : ""}`
            : `${node.sliceCount} 段${node.imageCount ? ` · ${node.imageCount} 图` : ""}`
        }
        checked={selected.has(node.heading)}
        indeterminate={!allOn && someOn}
        expanded={open}
        hasChildren={node.children.length > 0}
        onToggleExpand={() => onToggleHeading(key, !open)}
        onCheck={(on) => onToggleIds(doc, ids, on)}
        onPreview={() => onPreview(doc, node.heading)}
      />
      {open &&
        node.children.map((child) => (
          <HeadingBranch
            key={child.heading}
            doc={doc}
            node={child}
            selected={selected}
            expandedHeadings={expandedHeadings}
            onToggleHeading={onToggleHeading}
            onToggleIds={onToggleIds}
            onPreview={onPreview}
          />
        ))}
    </div>
  );
}

function TreeRow({
  depth,
  icon,
  label,
  meta,
  checked,
  indeterminate,
  expanded,
  hasChildren,
  onToggleExpand,
  onCheck,
  onPreview,
}: {
  depth: number;
  icon: string;
  label: string;
  meta?: string;
  checked?: boolean;
  indeterminate?: boolean;
  expanded?: boolean;
  hasChildren?: boolean;
  onToggleExpand?: () => void;
  onCheck?: (on: boolean) => void;
  onPreview?: () => void;
}) {
  return (
    <div
      className="group flex items-center gap-1 rounded-md py-1 pr-1 hover:bg-primary-50/60"
      style={{ paddingLeft: 8 + depth * 14 }}
    >
      {hasChildren ? (
        <button
          type="button"
          onClick={onToggleExpand}
          className="flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center text-foreground-400"
        >
          <i className={`ri-arrow-right-s-line text-sm transition-transform ${expanded ? "rotate-90" : ""}`}></i>
        </button>
      ) : (
        <span className="inline-block h-5 w-5 shrink-0" />
      )}
      {onCheck && (
        <input
          type="checkbox"
          checked={!!checked}
          ref={(el) => {
            if (el) el.indeterminate = !!indeterminate && !checked;
          }}
          onChange={(e) => onCheck(e.target.checked)}
          className="h-3.5 w-3.5 shrink-0 cursor-pointer accent-primary-500"
        />
      )}
      <button
        type="button"
        onClick={onPreview || onToggleExpand}
        className="flex min-w-0 flex-1 cursor-pointer items-center gap-1.5 text-left"
      >
        <i className={`${icon} shrink-0 text-xs text-primary-500`}></i>
        <span className="min-w-0 flex-1 truncate text-xs text-foreground-800">{label}</span>
        {meta && <span className="shrink-0 text-[10px] text-foreground-400">{meta}</span>}
      </button>
    </div>
  );
}

function ProductPreview({ item, libraryName }: { item: ProductItem; libraryName: string }) {
  const kids = item.children || [];
  const imgs = [...(item.images || []), ...kids.flatMap((c) => c.images || [])];
  return (
    <div>
      <div className="text-sm font-medium text-foreground-900">{item.name}</div>
      <div className="mt-0.5 text-[11px] text-foreground-500">
        {libraryName} · {item.kind}
        {item.module ? ` · ${item.module}` : ""}
      </div>
      {item.params && <p className="mt-3 text-xs leading-relaxed text-foreground-700">{item.params}</p>}
      {item.intro && <p className="mt-2 text-[13px] leading-[1.9] text-foreground-600">{item.intro}</p>}
      {item.bidCopy && <p className="mt-2 rounded bg-background-100 px-2 py-1.5 text-xs leading-relaxed text-foreground-700">{item.bidCopy}</p>}
      {imgs.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {imgs.map((img) => (
            <AuthImage key={img.id} src={img.url} alt={img.caption} className="h-20 w-28 rounded border border-background-300 object-cover" eager />
          ))}
        </div>
      )}
      {kids.length > 0 && (
        <div className="mt-4">
          <div className="text-[11px] font-medium text-foreground-500">二级功能 {kids.length} 项</div>
          <ul className="mt-1 space-y-1">
            {kids.map((c) => (
              <li key={c.id} className="text-xs text-foreground-700">
                {c.name}
                {c.intro ? <span className="text-foreground-500"> · {c.intro.slice(0, 40)}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function QualPreview({ item }: { item: QualificationAsset }) {
  return (
    <div>
      <div className="text-sm font-medium text-foreground-900">{item.name}</div>
      <div className="mt-0.5 text-[11px] text-foreground-500">
        {QUAL_KIND_LABEL[item.kind]} · {item.number || "未填编号"}
        {item.owner ? ` · ${item.owner}` : ""}
      </div>
      <div className="mt-2 text-[11px] text-foreground-500">
        {item.validUntil === "长期" ? "长期有效" : `有效期至 ${item.validUntil}`}
      </div>
      {item.detail && <p className="mt-3 text-[13px] leading-[1.9] text-foreground-600">{item.detail}</p>}
      {item.ocrText && (
        <p className="mt-2 rounded bg-background-100 px-2 py-1.5 text-[11px] leading-5 text-foreground-500">OCR：{item.ocrText}</p>
      )}
      {item.images && item.images.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {item.images.map((img) => (
            <AuthImage key={img.id} src={img.url} alt={img.caption} className="h-28 w-40 rounded border border-background-300 object-cover" eager />
          ))}
        </div>
      )}
    </div>
  );
}

function EmptyHint({ text }: { text: string }) {
  return (
    <div className="px-3 py-10 text-center text-xs text-foreground-500">
      <i className="ri-inbox-line mb-1 block text-lg text-foreground-400"></i>
      {text}
    </div>
  );
}
