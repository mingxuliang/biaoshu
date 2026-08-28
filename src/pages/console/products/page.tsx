import { useEffect, useMemo, useState, type FormEvent, type MouseEvent } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Modal from "../components/Modal";
import Toast from "../components/Toast";
import PaginationBar from "../components/PaginationBar";
import { useAuth } from "@/context/AuthContext";
import { useProductCatalog } from "@/context/ProductCatalogContext";
import { hasPerm } from "@/lib/permissions";
import {
  PRODUCT_LIBRARY_CATEGORIES,
  type ProductLibrary,
  type ProductLibraryCategory,
} from "@/mocks/products";

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

const categoryStyle: Record<ProductLibraryCategory, string> = {
  软件系统: "bg-primary-50 text-primary-600 border-primary-200",
  货物设备: "bg-accent-50 text-accent-600 border-accent-200",
  综合方案: "bg-secondary-100 text-secondary-700 border-secondary-200",
};

const categoryIcon: Record<ProductLibraryCategory, string> = {
  软件系统: "ri-apps-line",
  货物设备: "ri-server-line",
  综合方案: "ri-stack-line",
};

const inputCls =
  "h-9 w-full rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500";
const labelCls = "mb-1.5 block text-xs font-medium text-foreground-600";

const PAGE_SIZE = 9;
const emptyForm = {
  name: "",
  category: "软件系统" as ProductLibraryCategory,
  description: "",
  owner: "",
};

export default function ProductsPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const canEdit = hasPerm(user?.role, "writer");
  const { libraries, addLibrary, updateLibrary, deleteLibrary } = useProductCatalog();

  const [keyword, setKeyword] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<"全部" | ProductLibraryCategory>("全部");
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ProductLibrary | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [page, setPage] = useState(1);

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const filtered = useMemo(() => {
    let list = libraries;
    if (categoryFilter !== "全部") list = list.filter((l) => l.category === categoryFilter);
    if (keyword.trim()) {
      const kw = keyword.trim().toLowerCase();
      list = list.filter(
        (l) =>
          l.name.toLowerCase().includes(kw) ||
          l.description.toLowerCase().includes(kw) ||
          l.owner.toLowerCase().includes(kw),
      );
    }
    return list;
  }, [libraries, categoryFilter, keyword]);

  useEffect(() => {
    setPage(1);
  }, [keyword, categoryFilter]);

  useEffect(() => {
    const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    setPage((p) => Math.min(p, totalPages));
  }, [filtered.length]);

  const paged = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return filtered.slice(start, start + PAGE_SIZE);
  }, [filtered, page]);

  const stats = useMemo(() => {
    return {
      libraries: libraries.length,
      products: libraries.reduce((s, l) => s + (l.featureCount || 0), 0),
      pending: libraries.reduce((s, l) => s + (l.pendingCount || 0), 0),
      docs: libraries.reduce((s, l) => s + (l.sourceCount || 0), 0),
    };
  }, [libraries]);

  const countsOf = (lib: ProductLibrary) => ({
    total: lib.featureCount || 0,
    pending: lib.pendingCount || 0,
    images: lib.imageCount || 0,
  });

  const openCreate = () => {
    setEditing(null);
    setForm({ ...emptyForm, owner: user?.name || "" });
    setModalOpen(true);
  };

  const openEdit = (lib: ProductLibrary, e: MouseEvent) => {
    e.stopPropagation();
    setEditing(lib);
    setForm({
      name: lib.name,
      category: lib.category,
      description: lib.description,
      owner: lib.owner,
    });
    setModalOpen(true);
  };

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) {
      showToast("请填写产品库名称", "error");
      return;
    }
    try {
      if (editing) {
        await updateLibrary(editing.id, {
          name: form.name.trim(),
          category: form.category,
          description: form.description.trim(),
          owner: form.owner.trim() || "本企业",
        });
        showToast("产品库已更新");
      } else {
        const created = await addLibrary({
          name: form.name.trim(),
          category: form.category,
          description: form.description.trim(),
          owner: form.owner.trim() || user?.name || "本企业",
        });
        showToast("产品库已创建，可进入后上传技术标抽取功能点");
        setModalOpen(false);
        navigate(`/console/products/${created.id}`);
        return;
      }
      setModalOpen(false);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "保存失败", "error");
    }
  };

  const handleDelete = async (lib: ProductLibrary, e: MouseEvent) => {
    e.stopPropagation();
    const n = lib.featureCount || 0;
    if (!window.confirm(`确定删除产品库「${lib.name}」？其中 ${n} 条功能点将一并删除。`)) return;
    try {
      await deleteLibrary(lib.id);
      showToast("已删除产品库");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "删除失败", "error");
    }
  };

  const statCards = [
    { key: "libraries", label: "产品库", value: stats.libraries, icon: "ri-stack-line", gradient: "from-primary-400 to-primary-600", bar: "from-primary-500 to-primary-400" },
    { key: "products", label: "功能点 / 产品", value: stats.products, icon: "ri-box-3-line", gradient: "from-secondary-400 to-secondary-500", bar: "from-secondary-400 to-secondary-300" },
    { key: "pending", label: "待审核", value: stats.pending, icon: "ri-error-warning-line", gradient: "from-accent-400 to-accent-500", bar: "from-accent-500 to-accent-400" },
    { key: "docs", label: "来源技术标", value: stats.docs, icon: "ri-file-text-line", gradient: "from-primary-400 to-primary-600", bar: "from-primary-500 to-primary-400" },
  ];

  return (
    <div>
      <PageHeader
        title="产品功能库"
        description="企业可建立多个产品库。每个库独立抽取功能点与附图；文档中的资质证照会同步到资质证照库并查重，不进入产品库。"
        actions={
          canEdit ? (
            <button
              type="button"
              onClick={openCreate}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
            >
              <i className="ri-add-line text-sm"></i>
              新建产品库
            </button>
          ) : undefined
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

      <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-primary-200 bg-primary-50/50 px-4 py-2.5 text-sm text-primary-800">
        <i className="ri-lightbulb-line text-base"></i>
        <span className="font-medium">结构说明：</span>
        <span>一个产品库对应一个可投标产品；库内是该产品的功能点 / 模块 / 货物条目，互不混用。</span>
      </div>

      <div className="mb-4 flex flex-col gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5 lg:flex-row lg:items-center">
        <div className="relative flex-1">
          <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-xs text-foreground-500"></i>
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索产品库名称、说明或负责人…"
            className={`${inputCls} pl-9`}
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {(["全部", ...PRODUCT_LIBRARY_CATEGORIES] as const).map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => setCategoryFilter(c)}
              className={`cursor-pointer whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-medium transition-all ${
                categoryFilter === c
                  ? "border-primary-200 bg-primary-50 text-primary-600"
                  : "border-background-300 bg-transparent text-foreground-600 hover:border-background-400 hover:text-foreground-700"
              }`}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {paged.map((lib) => {
          const counts = countsOf(lib);
          return (
            <div
              key={lib.id}
              role="button"
              tabIndex={0}
              onClick={() => navigate(`/console/products/${lib.id}`)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  navigate(`/console/products/${lib.id}`);
                }
              }}
              className="group flex cursor-pointer flex-col rounded-lg border border-background-300 bg-background-100 p-4 text-left transition-all hover:border-primary-300/60"
            >
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
                  <i className={`${categoryIcon[lib.category]} text-lg`}></i>
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-foreground-900">{lib.name}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <span className={`inline-flex items-center whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] font-medium ${categoryStyle[lib.category]}`}>
                      {lib.category}
                    </span>
                    {lib.owner && (
                      <span className="inline-flex items-center gap-0.5 rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">
                        <i className="ri-user-line"></i>
                        {lib.owner}
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <p className="mt-3 line-clamp-2 text-xs leading-relaxed text-foreground-600">{lib.description || "暂无说明"}</p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <span className="rounded bg-background-200 px-1.5 py-0.5 text-[10px] text-foreground-600">{counts.total} 个功能点</span>
                <span className="rounded bg-background-200 px-1.5 py-0.5 text-[10px] text-foreground-600">{counts.images} 张附图</span>
                {counts.pending > 0 && (
                  <span className="rounded bg-accent-50 px-1.5 py-0.5 text-[10px] text-accent-700">{counts.pending} 待审核</span>
                )}
              </div>
              <div className="mt-auto flex items-center justify-between border-t border-background-200 pt-3" style={{ marginTop: "auto" }}>
                <span className="font-label text-xs text-foreground-500">更新 {lib.updatedAt}</span>
                {canEdit && (
                  <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                    <button
                      type="button"
                      title="编辑产品库"
                      onClick={(e) => openEdit(lib, e)}
                      className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-primary-50 hover:text-primary-600"
                    >
                      <i className="ri-pencil-line text-sm"></i>
                    </button>
                    <button
                      type="button"
                      title="删除"
                      onClick={(e) => handleDelete(lib, e)}
                      className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-red-50 hover:text-red-600"
                    >
                      <i className="ri-delete-bin-line text-sm"></i>
                    </button>
                  </div>
                )}
              </div>
            </div>
          );
        })}
        {filtered.length === 0 && (
          <div className="col-span-full rounded-lg border border-background-300 bg-background-100 py-16 text-center">
            <i className="ri-inbox-line text-3xl text-foreground-400"></i>
            <p className="mt-3 text-sm text-foreground-500">
              {libraries.length === 0 ? "暂无产品库，请先新建一个可投标产品" : "没有找到匹配的产品库"}
            </p>
          </div>
        )}
      </div>
      {filtered.length > 0 && (
        <div className="mt-3 overflow-hidden rounded-lg border border-background-300 bg-background-100">
          <PaginationBar total={filtered.length} page={page} pageSize={PAGE_SIZE} onPageChange={setPage} />
        </div>
      )}

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editing ? "编辑产品库" : "新建产品库"}
        subtitle="一个产品库对应企业的一个可投标产品，功能点不要跨库混放。"
      >
        <form onSubmit={handleSave} className="space-y-4">
          <div>
            <label className={labelCls} htmlFor="lib-name">
              产品名称 <span className="text-accent-500">*</span>
            </label>
            <input
              id="lib-name"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="例如：培训管理平台"
              className={inputCls}
            />
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className={labelCls} htmlFor="lib-cat">
                产品类别
              </label>
              <select
                id="lib-cat"
                value={form.category}
                onChange={(e) => setForm((f) => ({ ...f, category: e.target.value as ProductLibraryCategory }))}
                className={`${inputCls} cursor-pointer`}
              >
                {PRODUCT_LIBRARY_CATEGORIES.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls} htmlFor="lib-owner">
                负责人 / 部门
              </label>
              <input
                id="lib-owner"
                value={form.owner}
                onChange={(e) => setForm((f) => ({ ...f, owner: e.target.value }))}
                placeholder="例如：产品部"
                className={inputCls}
              />
            </div>
          </div>
          <div>
            <label className={labelCls} htmlFor="lib-desc">
              说明
            </label>
            <textarea
              id="lib-desc"
              rows={3}
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              placeholder="该产品覆盖的业务与适用投标类型"
              className="w-full resize-none rounded-md border border-background-300 bg-background-50 px-3 py-2 text-sm leading-relaxed text-foreground-800 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20"
            />
          </div>
          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={() => setModalOpen(false)}
              className="h-9 cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
            >
              取消
            </button>
            <button
              type="submit"
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
            >
              <i className="ri-save-3-line text-sm"></i>
              {editing ? "保存" : "创建并进入"}
            </button>
          </div>
        </form>
      </Modal>

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}
