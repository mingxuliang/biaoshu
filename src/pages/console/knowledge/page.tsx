import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import PageHeader from "../components/PageHeader";
import Modal from "../components/Modal";
import Toast from "../components/Toast";
import { useAuth } from "@/context/AuthContext";
import { hasPerm } from "@/lib/permissions";
import {
  ApiError,
  KNOWLEDGE_SCOPES,
  KNOWLEDGE_TYPES,
  deleteKnowledgeDocument,
  listKnowledgeDocuments,
  uploadKnowledgeDocument,
  type KnowledgeDoc,
} from "@/lib/api";

const scopeStyle: Record<string, string> = {
  企业库: "bg-primary-50 text-primary-600 border-primary-200",
  项目库: "bg-accent-50 text-accent-600 border-accent-200",
  个人库: "bg-secondary-100 text-secondary-600 border-secondary-200",
};

const typeIcon: Record<string, string> = {
  历史中标标书: "ri-file-chart-line",
  专项方案: "ri-file-settings-line",
  施工工艺: "ri-tools-line",
  规范条文: "ri-book-2-line",
  制度表单: "ri-file-list-3-line",
  图表模板: "ri-pie-chart-2-line",
};

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

export default function KnowledgePage() {
  const { token, user } = useAuth();
  const canUpload = hasPerm(user?.role, "writer");
  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [scope, setScope] = useState("全部");
  const [typeFilter, setTypeFilter] = useState("全部类型");
  const [keyword, setKeyword] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });

  const [uploadScope, setUploadScope] = useState<KnowledgeDoc["scope"]>("企业库");
  const [uploadType, setUploadType] = useState<string>(KNOWLEDGE_TYPES[0]);
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadTags, setUploadTags] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const loadDocs = useCallback(async () => {
    setLoading(true);
    try {
      const list = await listKnowledgeDocuments();
      setDocs(list);
    } catch {
      showToast("加载知识库列表失败，请稍后重试", "error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDocs();
  }, [loadDocs]);

  const filtered = useMemo(() => {
    let list = docs;
    if (scope !== "全部") list = list.filter((d) => d.scope === scope);
    if (typeFilter !== "全部类型") list = list.filter((d) => d.type === typeFilter);
    if (keyword.trim()) {
      const kw = keyword.trim().toLowerCase();
      list = list.filter(
        (d) => d.title.toLowerCase().includes(kw) || d.tags.some((t) => t.toLowerCase().includes(kw)),
      );
    }
    return list;
  }, [docs, scope, typeFilter, keyword]);

  const resetUploadForm = () => {
    setUploadScope("企业库");
    setUploadType(KNOWLEDGE_TYPES[0]);
    setUploadTitle("");
    setUploadTags("");
    setUploadFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleUpload = async (e: FormEvent) => {
    e.preventDefault();
    if (!token) {
      showToast("请先登录后再上传文档", "error");
      return;
    }
    if (!uploadFile) {
      showToast("请先选择要上传的文件", "error");
      return;
    }

    setUploading(true);
    try {
      await uploadKnowledgeDocument(token, {
        scope: uploadScope,
        type: uploadType,
        title: uploadTitle.trim() || undefined,
        tags: uploadTags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
        file: uploadFile,
      });
      setUploadOpen(false);
      resetUploadForm();
      showToast("文档已入库，正在按标题切片…", "success");
      loadDocs();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "上传失败，请稍后重试", "error");
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (doc: KnowledgeDoc) => {
    try {
      await deleteKnowledgeDocument(doc.id);
      setDocs((prev) => prev.filter((d) => d.id !== doc.id));
      showToast("已删除该知识文档");
    } catch {
      showToast("删除失败，请稍后重试", "error");
    }
  };

  const inputCls =
    "h-9 w-full rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500";
  const labelCls = "mb-1.5 block text-xs font-medium text-foreground-600";

  return (
    <div>
      <PageHeader
        title="文档知识库"
        description="沉淀企业可复用的技术方案、历史标书片段、规范条文与图表，供撰写时检索引用；内置虚词表与高危句式规则知识。"
        actions={
          canUpload ? (
          <button
            type="button"
            onClick={() => setUploadOpen(true)}
            className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
          >
            <i className="ri-add-line text-sm"></i>
            上传文档
          </button>
          ) : undefined
        }
      />

      {/* 检索工具栏 */}
      <div className="mb-4 flex flex-col gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5 lg:flex-row lg:items-center">
        <div className="relative flex-1">
          <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-xs text-foreground-500"></i>
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="按标题或标签检索：深基坑 / 盾构 / 桥梁验收…"
            className={`${inputCls} pl-9`}
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {KNOWLEDGE_SCOPES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setScope(s)}
              className={`cursor-pointer whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-medium transition-all ${
                scope === s
                  ? "border-primary-200 bg-primary-50 text-primary-600"
                  : "border-background-300 bg-transparent text-foreground-600 hover:border-background-400 hover:text-foreground-700"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className={`${inputCls} w-36 cursor-pointer`}
        >
          <option>全部类型</option>
          {KNOWLEDGE_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>

      {/* 内置规则知识条 */}
      <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-primary-200 bg-primary-50/50 px-4 py-2.5 text-sm text-primary-800">
        <i className="ri-settings-3-line text-base"></i>
        <span className="font-medium">内置规则知识（只读）：</span>
        <span>《青天评审规则》五维权重 · 查重阈值 30/42 · 《虚词表》六类虚词与高危句式</span>
      </div>

      {/* 文档列表 */}
      {loading ? (
        <div className="rounded-lg border border-background-300 bg-background-100 py-16 text-center">
          <i className="ri-loader-4-line animate-spin text-2xl text-foreground-400"></i>
          <p className="mt-3 text-sm text-foreground-500">正在加载知识库…</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((doc) => (
            <div key={doc.id} className="group flex flex-col rounded-lg border border-background-300 bg-background-100 p-4 transition-all hover:border-primary-300/60">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-secondary-400 to-secondary-500 text-background-50">
                  <i className={`${typeIcon[doc.type] ?? "ri-file-text-line"} text-lg`}></i>
                </span>
                <div className="min-w-0 flex-1">
                  <div className="line-clamp-2 text-sm font-medium text-foreground-900">{doc.title}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <span className={`inline-flex items-center whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] font-medium ${scopeStyle[doc.scope]}`}>
                      {doc.scope}
                    </span>
                    <span className="inline-flex items-center whitespace-nowrap rounded bg-background-200 px-1.5 py-0.5 text-[10px] text-foreground-500">
                      {doc.type}
                    </span>
                  </div>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {doc.tags.map((tag) => (
                  <span key={tag} className="inline-flex items-center gap-0.5 rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">
                    <i className="ri-price-tag-3-line"></i>
                    {tag}
                  </span>
                ))}
              </div>
              {doc.reviewFlag && (
                <div className="mt-2.5 flex items-center gap-1.5 rounded-md bg-accent-50 px-2.5 py-1.5 text-xs text-accent-700">
                  <i className="ri-alert-line"></i>
                  {doc.reviewFlag}
                </div>
              )}
              <div className="mt-auto flex items-center justify-between border-t border-background-200 pt-3" style={{ marginTop: "auto" }}>
                <span className="font-label text-xs text-foreground-500">
                  {doc.sliceCount} 个切片 · {doc.source}
                </span>
                <div className="flex items-center gap-1">
                  {canUpload && (
                  <button
                    type="button"
                    title="删除"
                    onClick={() => handleDelete(doc)}
                    className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-red-50 hover:text-red-600"
                  >
                    <i className="ri-delete-bin-line text-sm"></i>
                  </button>
                  )}
                </div>
              </div>
            </div>
          ))}
          {filtered.length === 0 && (
            <div className="col-span-full rounded-lg border border-background-300 bg-background-100 py-16 text-center">
              <i className="ri-inbox-line text-3xl text-foreground-400"></i>
              <p className="mt-3 text-sm text-foreground-500">没有找到匹配的知识文档</p>
            </div>
          )}
        </div>
      )}

      {/* 上传弹窗 */}
      <Modal
        open={uploadOpen}
        onClose={() => {
          setUploadOpen(false);
          resetUploadForm();
        }}
        title="上传知识文档"
        subtitle="Word/PDF 入库后按标题自动切片，保留来源便于溯源"
      >
        <form onSubmit={handleUpload} className="space-y-4">
          <div>
            <label className={labelCls} htmlFor="k-title">
              文档标题（留空则使用文件名）
            </label>
            <input
              id="k-title"
              value={uploadTitle}
              onChange={(e) => setUploadTitle(e.target.value)}
              placeholder="例如：城东快速路改造工程-技术标（中标）"
              className={inputCls}
            />
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className={labelCls} htmlFor="k-scope">
                归属范围
              </label>
              <select
                id="k-scope"
                value={uploadScope}
                onChange={(e) => setUploadScope(e.target.value as KnowledgeDoc["scope"])}
                className={`${inputCls} cursor-pointer`}
              >
                <option>企业库</option>
                <option>项目库</option>
                <option>个人库</option>
              </select>
            </div>
            <div>
              <label className={labelCls} htmlFor="k-type">
                文档类型
              </label>
              <select
                id="k-type"
                value={uploadType}
                onChange={(e) => setUploadType(e.target.value)}
                className={`${inputCls} cursor-pointer`}
              >
                {KNOWLEDGE_TYPES.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <label className={labelCls} htmlFor="k-tags">
              标签（逗号分隔，可选）
            </label>
            <input
              id="k-tags"
              value={uploadTags}
              onChange={(e) => setUploadTags(e.target.value)}
              placeholder="例如：市政, 道路, 桥梁"
              className={inputCls}
            />
          </div>
          <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-background-300 bg-background-50 px-4 py-6 text-center">
            <i className="ri-upload-cloud-2-line text-2xl text-primary-500"></i>
            <p className="text-xs text-foreground-500">
              {uploadFile ? uploadFile.name : "点击选择 .doc / .docx / .pdf 文件"}
            </p>
            <input
              ref={fileInputRef}
              type="file"
              accept=".doc,.docx,.pdf"
              onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
              className="hidden"
              id="k-file"
            />
            <label
              htmlFor="k-file"
              className="mt-1 flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-3 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
            >
              <i className="ri-folder-add-line"></i>
              选择文件
            </label>
          </div>
          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => {
                setUploadOpen(false);
                resetUploadForm();
              }}
              className="h-9 cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={uploading}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <i className={`${uploading ? "ri-loader-4-line animate-spin" : "ri-upload-2-line"} text-sm`}></i>
              {uploading ? "正在上传并切片…" : "上传并切片"}
            </button>
          </div>
        </form>
      </Modal>

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}
