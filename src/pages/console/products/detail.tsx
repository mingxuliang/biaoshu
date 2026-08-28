import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Modal from "../components/Modal";
import Toast from "../components/Toast";
import PaginationBar from "../components/PaginationBar";
import StatusBadge from "../components/StatusBadge";
import AuthImage from "../components/AuthImage";
import { useAuth } from "@/context/AuthContext";
import { useProductCatalog } from "@/context/ProductCatalogContext";
import { hasPerm } from "@/lib/permissions";
import { pollProductExtractJobUntilDone, uploadProductSourceDocs } from "@/lib/api";
import { PRODUCT_KINDS, type ProductImage, type ProductItem, type ProductKind, type ProductStatus } from "@/mocks/products";

type MainTab = "products" | "parse";

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

const emptyForm = {
  name: "",
  kind: "软件功能" as ProductKind,
  module: "",
  params: "",
  intro: "",
  bidCopy: "",
  brand: "",
  model: "",
  unit: "",
};

const kindIcon: Record<ProductKind, string> = {
  软件功能: "ri-apps-line",
  货物产品: "ri-server-line",
  模块方案: "ri-organization-chart",
};

const IMAGE_KINDS: ProductImage["kind"][] = ["界面", "架构", "流程", "实物"];
const MAX_FEATURE_IMAGES = 80;
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
const PAGE_SIZE = 15;

function guessImageKind(filename: string): ProductImage["kind"] {
  const n = filename.toLowerCase();
  if (/架构|architecture|arch|topo/.test(n)) return "架构";
  if (/流程|flow|bpmn/.test(n)) return "流程";
  if (/实物|photo|jpg|jpeg/.test(n) && /设备|服务器|机柜|hardware/.test(n)) return "实物";
  return "界面";
}
const imageKindIcon: Record<ProductImage["kind"], string> = {
  界面: "ri-window-line",
  架构: "ri-node-tree",
  流程: "ri-flow-chart",
  实物: "ri-image-line",
};

const inputCls =
  "h-9 w-full rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500";
const labelCls = "mb-1.5 block text-xs font-medium text-foreground-600";

function imageCountOf(item: ProductItem): number {
  return item.images.length + (item.children || []).reduce((sum, child) => sum + child.images.length, 0);
}

function formatBidCopy(item: ProductItem): string {
  const childDir =
    item.children && item.children.length > 0
      ? `二级目录：${item.children.map((c) => c.name).join("、")}`
      : "";
  return [`【${item.name}】`, item.module ? `所属：${item.module}` : "", childDir, item.params ? `参数：${item.params}` : "", item.bidCopy]
    .filter(Boolean)
    .join("\n");
}

function FeatureDetailBody({ item }: { item: ProductItem }) {
  return (
    <div className="space-y-4">
      {item.params ? (
        <div>
          <div className={labelCls}>技术参数</div>
          <p className="text-sm leading-relaxed text-foreground-700">{item.params}</p>
        </div>
      ) : null}
      <div>
        <div className={labelCls}>写标可用说明</div>
        <div className="rounded-lg border border-background-300 bg-background-50 px-3 py-2.5 text-sm leading-relaxed text-foreground-800">
          {item.bidCopy || item.intro || "尚未生成写标说明"}
        </div>
      </div>
      <div>
        <div className={labelCls}>附图</div>
        {item.images.length === 0 ? (
          <p className="text-xs text-foreground-500">该功能点尚未绑定附图。</p>
        ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {item.images.map((img) => (
              <div key={img.id} className="overflow-hidden rounded-lg border border-background-300 bg-background-50">
                {img.url ? (
                  <AuthImage src={img.url} alt={img.caption} eager className="h-24 w-full object-cover" />
                ) : (
                  <div className="flex h-24 items-center justify-center bg-gradient-to-br from-secondary-100 to-secondary-200 text-secondary-500">
                    <i className={`${imageKindIcon[img.kind]} text-2xl`}></i>
                  </div>
                )}
                <div className="px-2 py-1.5">
                  <div className="truncate text-[11px] font-medium text-foreground-800">{img.caption}</div>
                  <div className="text-[10px] text-foreground-500">{img.kind}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ProductLibraryDetailPage() {
  const { libraryId = "" } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canEdit = hasPerm(user?.role, "writer");
  const catalog = useProductCatalog();
  const library = catalog.getLibrary(libraryId);
  const items = catalog.itemsOf(libraryId);
  const jobs = catalog.jobsOf(libraryId);

  const [tab, setTab] = useState<MainTab>("products");
  const [kindFilter, setKindFilter] = useState<"全部" | ProductKind>("全部");
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string[]>([]);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });
  const [editOpen, setEditOpen] = useState(false);
  const [editing, setEditing] = useState<ProductItem | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [draftImages, setDraftImages] = useState<ProductImage[]>([]);
  const [addingImages, setAddingImages] = useState(false);
  const [detailItem, setDetailItem] = useState<ProductItem | null>(null);
  const [detailChildId, setDetailChildId] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [parsing, setParsing] = useState(false);
  const [ready, setReady] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!libraryId) return;
    let cancelled = false;
    setReady(false);
    catalog
      .refreshLibraries()
      .then(() => catalog.loadLibraryContents(libraryId))
      .catch(() => {
        if (!cancelled) setToast({ message: "加载产品库失败，请稍后重试", type: "error", visible: true });
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [libraryId]);

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const openDetail = (item: ProductItem) => {
    setDetailItem(item);
    setDetailChildId(item.children?.[0]?.id || "");
  };

  const filtered = useMemo(() => {
    let list = items;
    if (kindFilter !== "全部") list = list.filter((p) => p.kind === kindFilter);
    if (keyword.trim()) {
      const kw = keyword.trim().toLowerCase();
      list = list.filter((p) => {
        const hitSelf =
          p.name.toLowerCase().includes(kw) ||
          p.module.toLowerCase().includes(kw) ||
          p.params.toLowerCase().includes(kw) ||
          p.intro.toLowerCase().includes(kw) ||
          p.sourceDoc.toLowerCase().includes(kw);
        const hitChild = (p.children || []).some(
          (c) =>
            c.name.toLowerCase().includes(kw) ||
            (c.intro || "").toLowerCase().includes(kw) ||
            (c.params || "").toLowerCase().includes(kw),
        );
        return hitSelf || hitChild;
      });
    }
    return list;
  }, [items, kindFilter, keyword]);

  useEffect(() => {
    setPage(1);
  }, [keyword, kindFilter]);

  useEffect(() => {
    const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    setPage((p) => Math.min(p, totalPages));
  }, [filtered.length]);

  const paged = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return filtered.slice(start, start + PAGE_SIZE);
  }, [filtered, page]);

  const stats = useMemo(
    () => ({
      total: items.length,
      pending: items.filter((p) => p.status === "待审核").length,
      withImage: items.filter((p) => imageCountOf(p) > 0).length,
      docs: new Set(items.map((p) => p.sourceDoc).filter(Boolean)).size,
    }),
    [items],
  );

  const selectedItems = items.filter((p) => selected.includes(p.id));

  const toggleSelect = (id: string) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const toggleSelectAll = () => {
    if (paged.length > 0 && paged.every((p) => selected.includes(p.id))) {
      setSelected((prev) => prev.filter((id) => !paged.some((p) => p.id === id)));
      return;
    }
    setSelected((prev) => [...new Set([...prev, ...paged.map((p) => p.id)])]);
  };

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm);
    setDraftImages([]);
    setEditOpen(true);
  };

  const openEdit = (item: ProductItem) => {
    setEditing(item);
    setForm({
      name: item.name,
      kind: item.kind,
      module: item.module,
      params: item.params,
      intro: item.intro,
      bidCopy: item.bidCopy,
      brand: item.brand,
      model: item.model,
      unit: item.unit,
    });
    setDraftImages(item.images.map((img) => ({ ...img })));
    setEditOpen(true);
  };

  const handleAddImages = async (fileList: FileList | null) => {
    if (!fileList?.length) return;
    const room = MAX_FEATURE_IMAGES - draftImages.length;
    if (room <= 0) {
      showToast(`最多上传 ${MAX_FEATURE_IMAGES} 张附图`, "info");
      return;
    }
    const picked = Array.from(fileList).slice(0, room);
    const rejected = picked.filter((f) => !f.type.startsWith("image/") || f.size > MAX_IMAGE_BYTES);
    const accepted = picked.filter((f) => f.type.startsWith("image/") && f.size <= MAX_IMAGE_BYTES);
    if (rejected.length) {
      showToast("仅支持 8MB 以内的 JPG / PNG / WebP 图片", "error");
    }
    if (!accepted.length) return;
    setAddingImages(true);
    try {
      const next: ProductImage[] = accepted.map((file) => ({
        id: `img-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        caption: file.name.replace(/\.[^.]+$/, "").slice(0, 40) || "附图",
        kind: guessImageKind(file.name),
        url: URL.createObjectURL(file),
        file,
      }));
      setDraftImages((prev) => [...prev, ...next].slice(0, MAX_FEATURE_IMAGES));
    } catch {
      showToast("读取图片失败，请重试", "error");
    } finally {
      setAddingImages(false);
      if (imageInputRef.current) imageInputRef.current.value = "";
    }
  };

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) {
      showToast("请填写功能 / 产品名称", "error");
      return;
    }
    const newImages = draftImages.filter((img) => img.file).map((img) => ({
      file: img.file as File,
      caption: img.caption.trim() || "附图",
      kind: img.kind,
    }));
    const payload = {
      name: form.name.trim(),
      kind: form.kind,
      module: form.module,
      params: form.params,
      intro: form.intro,
      bidCopy: form.bidCopy.trim() || form.intro.trim(),
      brand: form.brand,
      model: form.model,
      unit: form.unit,
    };
    try {
      if (editing) {
        await catalog.updateItem(editing.id, payload, newImages);
        showToast("已保存功能点");
      } else {
        await catalog.createItem(libraryId, { ...payload, status: "待审核" }, newImages);
        showToast(newImages.length ? `已新增功能点，含 ${newImages.length} 张附图` : "已新增功能点，请审核后入库");
      }
      setEditOpen(false);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "保存失败", "error");
    }
  };

  const handleStatus = async (item: ProductItem, status: ProductStatus) => {
    try {
      await catalog.updateItem(item.id, { status });
      showToast(status === "已入库" ? `「${item.name}」已入库，撰写时可匹配` : `「${item.name}」已停用`);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "更新状态失败", "error");
    }
  };

  const handleDelete = async (item: ProductItem) => {
    if (!window.confirm(`确定删除「${item.name}」？其下二级功能点也会一并删除，撰写将无法再匹配。`)) return;
    try {
      await catalog.deleteItem(item.id);
      setSelected((prev) => prev.filter((id) => id !== item.id));
      showToast("已删除");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "删除失败", "error");
    }
  };

  const copyText = async (text: string, ok: string) => {
    try {
      await navigator.clipboard.writeText(text);
      showToast(ok);
    } catch {
      showToast("复制失败，请手动摘录", "error");
    }
  };

  const handleParseUpload = async (e: FormEvent) => {
    e.preventDefault();
    if (!uploadFiles.length) {
      showToast("请先选择技术标文件", "error");
      return;
    }
    setParsing(true);
    setUploadOpen(false);
    setTab("parse");
    try {
      const created = await uploadProductSourceDocs(libraryId, uploadFiles);
      await catalog.loadLibraryContents(libraryId);
      showToast(`已上传 ${created.length} 份，正在抽取…`, "info");
      await Promise.all(
        created.map((job) =>
          pollProductExtractJobUntilDone(job.id).catch((err) => {
            showToast(err instanceof Error ? err.message : `${job.filename} 抽取失败`, "error");
            return null;
          }),
        ),
      );
      await catalog.loadLibraryContents(libraryId);
      await catalog.refreshLibraries();
      showToast("抽取完成，结果已写入本产品库");
      setTab("products");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "上传失败", "error");
    } finally {
      setParsing(false);
      setUploadFiles([]);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  if (!ready) {
    return (
      <div className="rounded-lg border border-background-300 bg-background-100 py-16 text-center">
        <i className="ri-loader-4-line animate-spin text-3xl text-primary-500"></i>
        <p className="mt-3 text-sm text-foreground-500">正在加载产品库…</p>
      </div>
    );
  }

  if (!library) {
    return (
      <div className="rounded-lg border border-background-300 bg-background-100 py-16 text-center">
        <i className="ri-error-warning-line text-3xl text-foreground-400"></i>
        <p className="mt-3 text-sm text-foreground-500">产品库不存在或已删除</p>
        <button
          type="button"
          onClick={() => navigate("/console/products")}
          className="mt-4 h-9 cursor-pointer rounded-md border border-background-300 px-4 text-sm text-foreground-600 hover:bg-background-200"
        >
          返回产品库列表
        </button>
      </div>
    );
  }

  const statCards = [
    { key: "total", label: "一级功能菜单", value: stats.total, icon: "ri-box-3-line", gradient: "from-primary-400 to-primary-600", bar: "from-primary-500 to-primary-400" },
    { key: "pending", label: "待审核", value: stats.pending, icon: "ri-error-warning-line", gradient: "from-accent-400 to-accent-500", bar: "from-accent-500 to-accent-400" },
    { key: "withImage", label: "已配图", value: stats.withImage, icon: "ri-image-line", gradient: "from-secondary-400 to-secondary-500", bar: "from-secondary-400 to-secondary-300" },
    { key: "docs", label: "来源技术标", value: stats.docs, icon: "ri-file-text-line", gradient: "from-primary-400 to-primary-600", bar: "from-primary-500 to-primary-400" },
  ];

  return (
    <div>
      <PageHeader
        title={library.name}
        description={`${library.category} · ${library.description || "本库功能点仅用于该产品投标匹配，不与其他产品库混用。"}`}
        actions={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => navigate("/console/products")}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 bg-background-100 px-4 text-sm font-medium text-foreground-700 transition-colors hover:bg-background-200"
            >
              <i className="ri-arrow-left-s-line text-sm"></i>
              全部产品库
            </button>
            {canEdit && (
              <>
                <button
                  type="button"
                  onClick={() => setUploadOpen(true)}
                  className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 bg-background-100 px-4 text-sm font-medium text-foreground-700 transition-colors hover:bg-background-200"
                >
                  <i className="ri-upload-cloud-2-line text-sm"></i>
                  上传技术标
                </button>
                <button
                  type="button"
                  onClick={openCreate}
                  className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
                >
                  <i className="ri-add-line text-sm"></i>
                  新建功能点
                </button>
              </>
            )}
          </div>
        }
      />

      <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {statCards.map((card) => (
          <div
            key={card.key}
            className="group relative flex items-center gap-3 overflow-hidden rounded-lg border border-background-300 bg-background-100 p-3.5 transition-all duration-300 hover:border-primary-300/60"
          >
            <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${card.gradient} text-background-50`}>
              <i className={`${card.icon} text-lg`}></i>
            </span>
            <div className="min-w-0 flex-1">
              <div className="font-label text-[11px] text-foreground-500">{card.label}</div>
              <div className="font-heading text-gradient mt-0.5 text-xl font-bold tracking-wide">{card.value}</div>
            </div>
            <div className={`absolute bottom-0 left-0 right-0 h-[2px] bg-gradient-to-r ${card.bar} opacity-0 transition-opacity duration-300 group-hover:opacity-100`} />
          </div>
        ))}
      </div>

      <div className="mb-4 flex flex-col gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5 lg:flex-row lg:items-center">
        <div className="flex flex-wrap items-center gap-1.5">
          {(
            [
              { key: "products" as const, label: "企业产品", icon: "ri-box-3-line" },
              { key: "parse" as const, label: "文件解析", icon: "ri-file-search-line" },
            ]
          ).map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={`flex cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border px-3 py-1.5 text-xs font-medium transition-all ${
                tab === t.key
                  ? "border-primary-200 bg-primary-50 text-primary-600"
                  : "border-background-300 bg-transparent text-foreground-600 hover:border-background-400 hover:text-foreground-700"
              }`}
            >
              <i className={`${t.icon} text-sm`}></i>
              {t.label}
            </button>
          ))}
        </div>
        {tab === "products" && (
          <>
            <div className="flex flex-wrap items-center gap-1.5">
              {(["全部", ...PRODUCT_KINDS] as const).map((k) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => setKindFilter(k)}
                  className={`cursor-pointer whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-medium transition-all ${
                    kindFilter === k
                      ? "border-primary-200 bg-primary-50 text-primary-600"
                      : "border-background-300 bg-transparent text-foreground-600 hover:border-background-400 hover:text-foreground-700"
                  }`}
                >
                  {k}
                </button>
              ))}
            </div>
            <div className="relative flex-1 lg:max-w-xs lg:ml-auto">
              <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-xs text-foreground-500"></i>
              <input
                type="text"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="搜索一级菜单或二级功能点…"
                className={`${inputCls} pl-9`}
              />
            </div>
          </>
        )}
      </div>

      {tab === "products" ? (
        <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1080px] text-left">
              <thead>
                <tr className="font-label border-b border-background-300 bg-background-50 text-xs text-foreground-500">
                  <th className="w-10 px-4 py-3 font-medium">
                    <input
                      type="checkbox"
                      checked={paged.length > 0 && paged.every((p) => selected.includes(p.id))}
                      onChange={toggleSelectAll}
                      className="h-3.5 w-3.5 cursor-pointer accent-primary-500"
                      aria-label="全选本页"
                    />
                  </th>
                  <th className="px-3 py-3 font-medium">一级功能菜单</th>
                  <th className="px-3 py-3 font-medium">类型</th>
                  <th className="px-3 py-3 font-medium">技术参数</th>
                  <th className="px-3 py-3 font-medium">详细介绍</th>
                  <th className="px-3 py-3 font-medium">附图</th>
                  <th className="px-3 py-3 font-medium">状态</th>
                  <th className="px-3 py-3 text-right font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {paged.map((item) => (
                  <tr key={item.id} className="group border-b border-background-200 transition-colors last:border-0 hover:bg-primary-50/30">
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selected.includes(item.id)}
                        onChange={() => toggleSelect(item.id)}
                        className="h-3.5 w-3.5 cursor-pointer accent-primary-500"
                        aria-label={`选择 ${item.name}`}
                      />
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex items-start gap-2.5">
                        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
                          <i className={`${kindIcon[item.kind]} text-sm`}></i>
                        </span>
                        <div className="min-w-0">
                          <button
                            type="button"
                            onClick={() => openDetail(item)}
                            className="cursor-pointer truncate text-left text-sm font-medium text-foreground-900 hover:text-primary-600"
                          >
                            {item.name}
                          </button>
                          <div className="mt-0.5 text-xs text-foreground-500">
                            {item.module && item.module !== item.name ? item.module : "一级功能菜单"}
                            {item.brand ? ` · ${item.brand}${item.model ? ` ${item.model}` : ""}` : ""}
                            {item.aliases && item.aliases.length > 0 ? ` · 别名 ${item.aliases.slice(0, 2).join("、")}` : ""}
                          </div>
                          {(item.children || []).length > 0 && (
                            <div className="mt-1 text-[11px] leading-relaxed text-foreground-600">
                              <span className="text-foreground-500">二级目录 {item.children!.length} 项：</span>
                              {item.children!.slice(0, 8).map((c) => c.name).join("、")}
                              {item.children!.length > 8 ? "…" : ""}
                            </div>
                          )}
                          {item.mergeStatus && item.mergeStatus !== "新增" && (
                            <div className="mt-1">
                              <StatusBadge status={item.mergeStatus} />
                            </div>
                          )}
                          {item.paramsConflict && item.paramsConflict.length > 0 && (
                            <div className="mt-1 text-[10px] text-accent-700">参数冲突：{item.paramsConflict[0]}</div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <span className="inline-flex items-center whitespace-nowrap rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">
                        {item.kind}
                      </span>
                    </td>
                    <td className="max-w-[220px] px-3 py-3">
                      <div className="line-clamp-2 text-xs leading-relaxed text-foreground-700">{item.params || "—"}</div>
                    </td>
                    <td className="max-w-[280px] px-3 py-3">
                      <div className="line-clamp-2 text-xs leading-relaxed text-foreground-600">{item.intro || "—"}</div>
                    </td>
                    <td className="px-3 py-3">
                      {imageCountOf(item) === 0 ? (
                        <span className="text-xs text-foreground-400">无图</span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded bg-primary-50 px-1.5 py-0.5 text-[10px] font-medium text-primary-600">
                          <i className="ri-image-line"></i>
                          {imageCountOf(item)} 张
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <StatusBadge status={item.status} />
                    </td>
                    <td className="px-3 py-3 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          type="button"
                          title="查看图文说明"
                          onClick={() => openDetail(item)}
                          className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800"
                        >
                          <i className="ri-eye-line text-sm"></i>
                        </button>
                        {canEdit && (
                          <>
                            <button
                              type="button"
                              title="编辑"
                              onClick={() => openEdit(item)}
                              className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-colors hover:bg-primary-50 hover:text-primary-600"
                            >
                              <i className="ri-pencil-line text-sm"></i>
                            </button>
                            {item.status === "待审核" && (
                              <button
                                type="button"
                                title="审核入库"
                                onClick={() => handleStatus(item, "已入库")}
                                className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-colors hover:bg-primary-50 hover:text-primary-600"
                              >
                                <i className="ri-check-line text-sm"></i>
                              </button>
                            )}
                            {item.mergeStatus === "疑似重复" && item.suspectedIds?.[0] && (
                              <>
                                <button
                                  type="button"
                                  title="合并为一条"
                                  onClick={() => catalog.resolveItems(libraryId, item.id, item.suspectedIds![0], "merge").then(() => showToast("已合并")).catch((err) => showToast(err instanceof Error ? err.message : "合并失败", "error"))}
                                  className="flex h-7 cursor-pointer items-center rounded-md px-1.5 text-[10px] font-medium text-primary-600 hover:bg-primary-50"
                                >
                                  合并
                                </button>
                                <button
                                  type="button"
                                  title="保留两条"
                                  onClick={() => catalog.resolveItems(libraryId, item.id, item.suspectedIds![0], "keep_both").then(() => showToast("已拆开为两条")).catch((err) => showToast(err instanceof Error ? err.message : "操作失败", "error"))}
                                  className="flex h-7 cursor-pointer items-center rounded-md px-1.5 text-[10px] font-medium text-foreground-600 hover:bg-background-200"
                                >
                                  就是两条
                                </button>
                              </>
                            )}
                            <button
                              type="button"
                              title="删除"
                              onClick={() => handleDelete(item)}
                              className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-colors hover:bg-red-50 hover:text-red-600"
                            >
                              <i className="ri-delete-bin-line text-sm"></i>
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-16 text-center">
                      <i className="ri-inbox-line text-3xl text-foreground-400"></i>
                      <p className="mt-3 text-sm text-foreground-500">
        {items.length === 0 ? "本产品库暂无一级功能菜单，请上传该产品的技术标" : "没有找到匹配的功能菜单"}
                      </p>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {selected.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-background-300 bg-background-50 px-4 py-2.5">
              <span className="text-xs text-foreground-600">
                已选 <span className="font-label font-medium text-primary-600">{selected.length}</span> 项（仅本产品库）
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setSelected([])}
                  className="h-8 cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-3 text-xs font-medium text-foreground-600 transition-colors hover:bg-background-200"
                >
                  取消选择
                </button>
                <button
                  type="button"
                  onClick={() => setPreviewOpen(true)}
                  className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-3 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
                >
                  <i className="ri-file-copy-2-line"></i>
                  预览写标素材
                </button>
              </div>
            </div>
          )}
          <div className="border-t border-background-300 bg-background-50">
            <PaginationBar total={filtered.length} page={page} pageSize={PAGE_SIZE} onPageChange={setPage} />
          </div>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
          <div className="flex items-center justify-between border-b border-background-300 bg-background-50 px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
              <i className="ri-file-search-line text-primary-500"></i>
              本产品技术标解析
            </div>
            <span className="font-label text-xs text-foreground-500">共 {jobs.length} 份 · 功能点只进入「{library.name}」，证照同步到资质库</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[880px] text-left">
              <thead>
                <tr className="font-label border-b border-background-300 bg-background-50 text-xs text-foreground-500">
                  <th className="px-4 py-2.5 font-medium">文件名</th>
                  <th className="px-3 py-2.5 font-medium">状态</th>
                  <th className="px-3 py-2.5 font-medium">抽取条数</th>
                  <th className="px-3 py-2.5 font-medium">大小</th>
                  <th className="px-3 py-2.5 font-medium">上传时间</th>
                  <th className="px-3 py-2.5 text-right font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id} className="border-b border-background-200 transition-colors last:border-0 hover:bg-primary-50/30">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <i className="ri-file-word-2-line text-primary-500"></i>
                        <div>
                          <div className="text-sm font-medium text-foreground-900">{job.filename}</div>
                          <div className="mt-0.5 text-[11px] text-foreground-500">{job.note}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <StatusBadge status={job.status} pulse={job.status === "解析中"} />
                    </td>
                    <td className="px-3 py-3">
                      <span className="font-heading text-gradient text-sm font-bold">{job.extracted}</span>
                      {(job.merged || job.suspected || job.conflicts) ? (
                        <div className="mt-0.5 text-[10px] text-foreground-500">
                          并入 {job.merged || 0} · 疑似 {job.suspected || 0} · 冲突 {job.conflicts || 0}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-3 py-3 text-xs text-foreground-600">{job.sizeLabel}</td>
                    <td className="px-3 py-3 text-xs text-foreground-500">{job.uploadedAt}</td>
                    <td className="px-3 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => {
                          setKindFilter("全部");
                          setKeyword(job.filename);
                          setTab("products");
                        }}
                        className="cursor-pointer whitespace-nowrap rounded-md border border-primary-200 bg-primary-50 px-2.5 py-1 text-xs font-medium text-primary-600 transition-colors hover:bg-primary-100"
                      >
                        查看抽取结果
                      </button>
                    </td>
                  </tr>
                ))}
                {jobs.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-16 text-center">
                      <i className="ri-upload-cloud-2-line text-3xl text-foreground-400"></i>
                      <p className="mt-3 text-sm text-foreground-500">本产品库尚未上传技术标</p>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Modal
        open={editOpen}
        onClose={() => setEditOpen(false)}
        title={editing ? "编辑功能点" : "新建功能点"}
        subtitle={`将写入产品库「${library.name}」，短名称用于与招标条款匹配。`}
        width="max-w-2xl"
      >
        <form onSubmit={handleSave} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className={labelCls} htmlFor="p-name">
                功能 / 产品名称 <span className="text-accent-500">*</span>
              </label>
              <input id="p-name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="例如：证书颁发" className={inputCls} />
            </div>
            <div>
              <label className={labelCls} htmlFor="p-kind">
                类型
              </label>
              <select id="p-kind" value={form.kind} onChange={(e) => setForm((f) => ({ ...f, kind: e.target.value as ProductKind }))} className={`${inputCls} cursor-pointer`}>
                {PRODUCT_KINDS.map((k) => (
                  <option key={k}>{k}</option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls} htmlFor="p-module">
                所属模块
              </label>
              <input id="p-module" value={form.module} onChange={(e) => setForm((f) => ({ ...f, module: e.target.value }))} placeholder="例如：组织与账号" className={inputCls} />
            </div>
            <div>
              <label className={labelCls} htmlFor="p-params">
                技术参数
              </label>
              <input id="p-params" value={form.params} onChange={(e) => setForm((f) => ({ ...f, params: e.target.value }))} className={inputCls} />
            </div>
            {form.kind === "货物产品" && (
              <>
                <div>
                  <label className={labelCls} htmlFor="p-brand">
                    品牌
                  </label>
                  <input id="p-brand" value={form.brand} onChange={(e) => setForm((f) => ({ ...f, brand: e.target.value }))} className={inputCls} />
                </div>
                <div>
                  <label className={labelCls} htmlFor="p-model">
                    型号规格
                  </label>
                  <input id="p-model" value={form.model} onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))} className={inputCls} />
                </div>
                <div>
                  <label className={labelCls} htmlFor="p-unit">
                    单位
                  </label>
                  <input id="p-unit" value={form.unit} onChange={(e) => setForm((f) => ({ ...f, unit: e.target.value }))} className={inputCls} />
                </div>
              </>
            )}
          </div>
          <div>
            <label className={labelCls} htmlFor="p-intro">
              详细介绍
            </label>
            <textarea
              id="p-intro"
              rows={3}
              value={form.intro}
              onChange={(e) => setForm((f) => ({ ...f, intro: e.target.value }))}
              className="w-full resize-none rounded-md border border-background-300 bg-background-50 px-3 py-2 text-sm leading-relaxed text-foreground-800 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20"
            />
          </div>
          <div>
            <label className={labelCls} htmlFor="p-copy">
              写标可用说明
            </label>
            <textarea
              id="p-copy"
              rows={4}
              value={form.bidCopy}
              onChange={(e) => setForm((f) => ({ ...f, bidCopy: e.target.value }))}
              className="w-full resize-none rounded-md border border-background-300 bg-background-50 px-3 py-2 text-sm leading-relaxed text-foreground-800 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20"
            />
          </div>
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-xs font-medium text-foreground-600">附图</span>
              <span className="text-[11px] text-foreground-400">
                {draftImages.length}/{MAX_FEATURE_IMAGES} · JPG / PNG / WebP，单张不超过 8MB
              </span>
            </div>
            {draftImages.length > 0 && (
              <div className="mb-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
                {draftImages.map((img) => (
                  <div key={img.id} className="overflow-hidden rounded-lg border border-background-300 bg-background-50">
                    {img.url ? (
                      <AuthImage src={img.url} alt={img.caption} eager className="h-24 w-full object-cover" />
                    ) : (
                      <div className="flex h-24 items-center justify-center bg-gradient-to-br from-secondary-100 to-secondary-200 text-secondary-500">
                        <i className={`${imageKindIcon[img.kind]} text-2xl`}></i>
                      </div>
                    )}
                    <div className="space-y-1.5 p-2">
                      <input
                        value={img.caption}
                        onChange={(e) =>
                          setDraftImages((prev) => prev.map((x) => (x.id === img.id ? { ...x, caption: e.target.value } : x)))
                        }
                        placeholder="图注"
                        className="h-7 w-full rounded border border-background-300 bg-background-100 px-2 text-[11px] text-foreground-800 outline-none focus:border-primary-400"
                      />
                      <div className="flex items-center gap-1">
                        <select
                          value={img.kind}
                          onChange={(e) =>
                            setDraftImages((prev) =>
                              prev.map((x) => (x.id === img.id ? { ...x, kind: e.target.value as ProductImage["kind"] } : x)),
                            )
                          }
                          className="h-7 flex-1 cursor-pointer rounded border border-background-300 bg-background-100 px-1.5 text-[11px] text-foreground-700 outline-none"
                        >
                          {IMAGE_KINDS.map((k) => (
                            <option key={k}>{k}</option>
                          ))}
                        </select>
                        <button
                          type="button"
                          title="移除"
                          onClick={() => setDraftImages((prev) => prev.filter((x) => x.id !== img.id))}
                          className="flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded text-foreground-500 hover:bg-red-50 hover:text-red-600"
                        >
                          <i className="ri-delete-bin-line text-sm"></i>
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div
              className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-background-300 bg-background-50 px-4 py-5 text-center"
              onDragOver={(e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = "copy";
              }}
              onDrop={(e) => {
                e.preventDefault();
                void handleAddImages(e.dataTransfer.files);
              }}
            >
              <i className="ri-image-add-line text-2xl text-primary-500"></i>
              <p className="text-xs text-foreground-500">上传界面截图、架构图或流程图，写标时随本功能点插入</p>
              <input
                ref={imageInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp,image/gif,.jpg,.jpeg,.png,.webp,.gif"
                multiple
                className="hidden"
                id="p-feature-images"
                onChange={(e) => void handleAddImages(e.target.files)}
              />
              <label
                htmlFor="p-feature-images"
                className={`mt-0.5 flex h-8 items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-3 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600 ${
                  addingImages || draftImages.length >= MAX_FEATURE_IMAGES ? "pointer-events-none opacity-60" : "cursor-pointer"
                }`}
              >
                <i className={`${addingImages ? "ri-loader-4-line animate-spin" : "ri-folder-add-line"}`}></i>
                {addingImages ? "读取中…" : "选择图片"}
              </label>
            </div>
          </div>
          <div className="flex items-center justify-end gap-2 pt-1">
            <button type="button" onClick={() => setEditOpen(false)} className="h-9 cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200">
              取消
            </button>
            <button type="submit" className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600">
              <i className="ri-save-3-line text-sm"></i>
              保存
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={!!detailItem}
        onClose={() => {
          setDetailItem(null);
          setDetailChildId("");
        }}
        title={detailItem ? detailItem.name : "图文说明"}
        subtitle={detailItem ? `${library.name} · 一级功能菜单 · 来源 ${detailItem.sourceDoc}` : undefined}
        width="max-w-3xl"
      >
        {detailItem && (() => {
          const children = detailItem.children || [];
          const viewing =
            children.find((child) => child.id === detailChildId) || children[0] || detailItem;
          return (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="inline-flex items-center rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">{viewing.kind}</span>
                <StatusBadge status={viewing.status} />
                {children.length > 0 && viewing.id !== detailItem.id ? (
                  <span className="text-[10px] text-foreground-500">二级功能 · {viewing.name}</span>
                ) : null}
              </div>
              {children.length > 0 && (
                <div>
                  <div className={labelCls}>二级功能目录</div>
                  <div className="flex flex-wrap gap-1.5">
                    {children.map((child) => (
                      <button
                        key={child.id}
                        type="button"
                        onClick={() => setDetailChildId(child.id)}
                        className={`cursor-pointer whitespace-nowrap rounded-md border px-2.5 py-1 text-xs font-medium transition-all ${
                          viewing.id === child.id
                            ? "border-primary-200 bg-primary-50 text-primary-600"
                            : "border-background-300 bg-transparent text-foreground-600 hover:border-background-400 hover:text-foreground-700"
                        }`}
                      >
                        {child.name}
                        {child.images.length > 0 ? (
                          <span className="ml-1 text-[10px] opacity-70">{child.images.length}</span>
                        ) : null}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <FeatureDetailBody item={viewing} />
              <div className="flex items-center justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => void copyText(formatBidCopy(viewing), "已复制写标说明")}
                  className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
                >
                  <i className="ri-file-copy-line text-sm"></i>
                  复制说明
                </button>
                {canEdit && (
                  <button
                    type="button"
                    onClick={() => {
                      openEdit(viewing);
                      setDetailItem(null);
                      setDetailChildId("");
                    }}
                    className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
                  >
                    <i className="ri-pencil-line text-sm"></i>
                    编辑
                  </button>
                )}
              </div>
            </div>
          );
        })()}
      </Modal>

      <Modal open={previewOpen} onClose={() => setPreviewOpen(false)} title="写标素材预览" subtitle={`来自产品库「${library.name}」，不会串入其他产品`} width="max-w-2xl">
        <div className="space-y-3">
          {selectedItems.map((item) => (
            <div key={item.id} className="rounded-lg border border-background-300 bg-background-50 p-3">
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <div className="text-sm font-medium text-foreground-900">{item.name}</div>
                <span className="text-[10px] text-foreground-500">{item.images.length} 张附图</span>
              </div>
              <p className="text-xs leading-relaxed text-foreground-700">{item.bidCopy || item.intro}</p>
              {item.images.some((img) => img.url) && (
                <div className="mt-2 flex gap-1.5 overflow-x-auto">
                  {item.images.filter((img) => img.url).map((img) => (
                    <AuthImage key={img.id} src={img.url} alt={img.caption} className="h-14 w-20 shrink-0 rounded border border-background-300 object-cover" />
                  ))}
                </div>
              )}
            </div>
          ))}
          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={() => void copyText(selectedItems.map(formatBidCopy).join("\n\n"), "已复制全部写标说明")}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
            >
              <i className="ri-file-copy-2-line text-sm"></i>
              复制全部
            </button>
            <button
              type="button"
              onClick={() => {
                setPreviewOpen(false);
                navigate("/console/writer");
              }}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
            >
              <i className="ri-edit-2-line text-sm"></i>
              去撰写工作台
            </button>
          </div>
        </div>
      </Modal>

      <Modal
        open={uploadOpen}
        onClose={() => {
          if (parsing) return;
          setUploadOpen(false);
        }}
        title="上传本产品技术标"
        subtitle={`功能点只进入「${library.name}」。文档里的营业执照、荣誉证书、合同复印件等会同步到资质证照库并查重合并，不写入本产品库。`}
      >
        <form onSubmit={handleParseUpload} className="space-y-4">
          <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-background-300 bg-background-50 px-4 py-6 text-center">
            <i className="ri-upload-cloud-2-line text-2xl text-primary-500"></i>
            <p className="text-xs text-foreground-500">
              {uploadFiles.length ? uploadFiles.map((f) => f.name).join("、") : "可同时选择多份过往技术标 / 响应文件；其中的资质证照会自动进入资质证照库"}
            </p>
            <input
              ref={fileRef}
              type="file"
              accept=".doc,.docx,.pdf"
              multiple
              onChange={(e) => setUploadFiles(Array.from(e.target.files || []))}
              className="hidden"
              id="p-file"
            />
            <label htmlFor="p-file" className="mt-1 flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-3 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600">
              <i className="ri-folder-add-line"></i>
              选择文件
            </label>
          </div>
          <div className="flex items-center justify-end gap-2">
            <button type="button" onClick={() => setUploadOpen(false)} className="h-9 cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200">
              取消
            </button>
            <button type="submit" disabled={parsing} className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-60">
              <i className={`${parsing ? "ri-loader-4-line animate-spin" : "ri-sparkling-2-line"} text-sm`}></i>
              {parsing ? "正在抽取…" : "开始抽取"}
            </button>
          </div>
        </form>
      </Modal>

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}
