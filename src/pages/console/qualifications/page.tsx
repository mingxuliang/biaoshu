import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import PageHeader from "../components/PageHeader";
import Modal from "../components/Modal";
import Toast from "../components/Toast";
import PaginationBar from "../components/PaginationBar";
import StatusBadge from "../components/StatusBadge";
import AuthImage from "../components/AuthImage";
import { useAuth } from "@/context/AuthContext";
import { hasPerm } from "@/lib/permissions";
import {
  ApiError,
  createQualification,
  deleteQualification,
  listQualifications,
  listQualificationSourceDocs,
  pollQualificationExtractJobUntilDone,
  resolveQualificationPair,
  updateQualification,
  uploadQualificationSourceDocs,
  type QualificationAsset,
  type QualificationKind,
  type QualificationParseJob,
} from "@/lib/api";

const qualificationTabs = [
  { key: "all", label: "全部", icon: "ri-apps-2-line" },
  { key: "cert", label: "企业证照", icon: "ri-vip-crown-line" },
  { key: "contract", label: "合同", icon: "ri-file-text-line" },
  { key: "financial", label: "财务", icon: "ri-funds-line" },
  { key: "people", label: "人员证书", icon: "ri-id-card-line" },
  { key: "achievement", label: "业绩", icon: "ri-trophy-line" },
  { key: "equipment", label: "设备机具", icon: "ri-truck-line" },
  { key: "credit", label: "信用材料", icon: "ri-shield-star-line" },
] as const;

type TabKey = (typeof qualificationTabs)[number]["key"];
type PageTab = "library" | "parse";

const kindLabel: Record<QualificationKind, string> = {
  cert: "企业证照",
  people: "人员证书",
  achievement: "业绩",
  equipment: "设备机具",
  credit: "信用材料",
  contract: "合同",
  financial: "财务",
};

const kindOptions: { value: QualificationKind; label: string }[] = [
  { value: "cert", label: "企业证照" },
  { value: "contract", label: "合同" },
  { value: "financial", label: "财务" },
  { value: "people", label: "人员证书" },
  { value: "achievement", label: "业绩" },
  { value: "equipment", label: "设备机具" },
  { value: "credit", label: "信用材料" },
];

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

const PAGE_SIZE = 9;
const emptyForm = {
  kind: "cert" as QualificationKind,
  name: "",
  level: "",
  number: "",
  validUntil: "长期",
  owner: "",
  detail: "",
};

export default function QualificationsPage() {
  const { token, user } = useAuth();
  const canEditQual = hasPerm(user?.role, "qual_edit");
  const [items, setItems] = useState<QualificationAsset[]>([]);
  const [jobs, setJobs] = useState<QualificationParseJob[]>([]);
  const [pageTab, setPageTab] = useState<PageTab>("library");
  const [activeTab, setActiveTab] = useState<TabKey>("all");
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<QualificationAsset | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [parsing, setParsing] = useState(false);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });
  const [form, setForm] = useState(emptyForm);
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const parseFileRef = useRef<HTMLInputElement>(null);

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const reload = async () => {
    if (!token) return;
    const [list, sourceDocs] = await Promise.all([listQualifications(token), listQualificationSourceDocs(token)]);
    setItems(list);
    setJobs(sourceDocs);
  };

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    Promise.all([listQualifications(token), listQualificationSourceDocs(token)])
      .then(([list, sourceDocs]) => {
        if (!cancelled) {
          setItems(list);
          setJobs(sourceDocs);
        }
      })
      .catch((err) => {
        if (!cancelled) showToast(err instanceof ApiError ? err.message : "无法加载证照库", "error");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const stats = useMemo(
    () => ({
      total: items.length,
      pending: items.filter((q) => q.reviewStatus === "待审核").length,
      expiring: items.filter((q) => q.status === "将到期").length,
      docs: jobs.length,
    }),
    [items, jobs],
  );

  const filtered = useMemo(() => {
    let list = items;
    if (activeTab !== "all") list = list.filter((q) => q.kind === activeTab);
    if (keyword.trim()) {
      const kw = keyword.toLowerCase();
      list = list.filter(
        (q) =>
          q.name.toLowerCase().includes(kw) ||
          q.number.toLowerCase().includes(kw) ||
          (q.owner || "").toLowerCase().includes(kw) ||
          (q.sources || []).some((s) => (s.filename || "").toLowerCase().includes(kw)),
      );
    }
    return list;
  }, [items, activeTab, keyword]);

  useEffect(() => {
    setPage(1);
  }, [keyword, activeTab]);

  useEffect(() => {
    const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    setPage((p) => Math.min(p, totalPages));
  }, [filtered.length]);

  const paged = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return filtered.slice(start, start + PAGE_SIZE);
  }, [filtered, page]);

  const expiring = items.filter((q) => q.status === "将到期");

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    if (!token) return;
    if (!form.name.trim()) {
      showToast("请填写名称", "error");
      return;
    }
    setSubmitting(true);
    try {
      if (editing) {
        await updateQualification(token, editing.id, {
          kind: form.kind,
          name: form.name.trim(),
          level: form.level.trim(),
          number: form.number.trim(),
          validUntil: form.validUntil.trim() || "长期",
          owner: form.owner.trim(),
          detail: form.detail.trim(),
          file,
        });
        showToast("已保存");
      } else {
        await createQualification(token, {
          kind: form.kind,
          name: form.name.trim(),
          level: form.level.trim(),
          number: form.number.trim(),
          validUntil: form.validUntil.trim() || "长期",
          owner: form.owner.trim(),
          detail: form.detail.trim(),
          file,
        });
        showToast("证照已录入");
      }
      setCreateOpen(false);
      setEditing(null);
      setForm(emptyForm);
      setFile(null);
      await reload();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : editing ? "保存失败" : "录入失败", "error");
    } finally {
      setSubmitting(false);
    }
  };

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm);
    setFile(null);
    setCreateOpen(true);
  };

  const openEdit = (item: QualificationAsset) => {
    setEditing(item);
    setForm({
      kind: item.kind,
      name: item.name,
      level: item.level,
      number: item.number,
      validUntil: item.validUntil,
      owner: item.owner,
      detail: item.detail,
    });
    setFile(null);
    setCreateOpen(true);
  };

  const handleParseUpload = async (e: FormEvent) => {
    e.preventDefault();
    if (!token) return;
    if (!uploadFiles.length) {
      showToast("请先选择商务标文件", "error");
      return;
    }
    setParsing(true);
    setUploadOpen(false);
    setPageTab("parse");
    try {
      const created = await uploadQualificationSourceDocs(token, uploadFiles);
      await reload();
      showToast(`已上传 ${created.length} 份，正在抽取…`, "info");
      await Promise.all(
        created.map((job) =>
          pollQualificationExtractJobUntilDone(token, job.id).catch((err) => {
            showToast(err instanceof Error ? err.message : `${job.filename} 抽取失败`, "error");
            return null;
          }),
        ),
      );
      await reload();
      showToast("抽取完成，重复项已自动合并，请审核");
      setPageTab("library");
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "上传失败", "error");
    } finally {
      setParsing(false);
      setUploadFiles([]);
      if (parseFileRef.current) parseFileRef.current.value = "";
    }
  };

  const handleViewFile = async (item: QualificationAsset, imageUrl?: string) => {
    if (!token) return;
    const path = imageUrl || item.images?.[0]?.url || (item.hasFile ? `/api/qualifications/${item.id}/file` : "");
    if (!path) {
      showToast("尚未抽出扫描图。请重新解析商务标，或在录入时上传扫描件。", "info");
      return;
    }
    try {
      const res = await fetch(path, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) {
        showToast("无法打开扫描件", "error");
        return;
      }
      const blob = await res.blob();
      window.open(URL.createObjectURL(blob), "_blank");
    } catch {
      showToast("无法打开文件", "error");
    }
  };

  const handleCopy = async (item: QualificationAsset) => {
    const text = [item.name, item.number, item.validUntil === "长期" ? "长期有效" : `有效期至 ${item.validUntil}`]
      .filter(Boolean)
      .join(" · ");
    try {
      await navigator.clipboard.writeText(text);
      showToast("已复制证照信息，可粘贴到标书");
    } catch {
      showToast("复制失败，请手动摘录", "error");
    }
  };

  const handleDelete = async (item: QualificationAsset) => {
    if (!token) return;
    if (!window.confirm(`确定删除「${item.name}」？`)) return;
    try {
      await deleteQualification(token, item.id);
      await reload();
      showToast("已删除");
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "删除失败", "error");
    }
  };

  const handleReview = async (item: QualificationAsset) => {
    if (!token) return;
    try {
      await updateQualification(token, item.id, { reviewStatus: "已入库" });
      await reload();
      showToast(`「${item.name}」已入库`);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "审核失败", "error");
    }
  };

  const handleResolve = async (item: QualificationAsset, otherId: string, action: "merge" | "keep_both") => {
    if (!token || !otherId) return;
    try {
      await resolveQualificationPair(token, item.id, otherId, action);
      await reload();
      showToast(action === "merge" ? "已合并为一条" : "已拆开为两条");
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "操作失败", "error");
    }
  };

  const inputCls =
    "h-9 w-full rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500";
  const labelCls = "mb-1.5 block text-xs font-medium text-foreground-600";

  const statCards = [
    { key: "total", label: "材料总数", icon: "ri-vip-crown-line", gradient: "from-primary-400 to-primary-600", bar: "from-primary-500 to-primary-400" },
    { key: "pending", label: "待审核", icon: "ri-error-warning-line", gradient: "from-accent-400 to-accent-500", bar: "from-accent-500 to-accent-400" },
    { key: "expiring", label: "即将到期", icon: "ri-time-line", gradient: "from-secondary-400 to-secondary-500", bar: "from-secondary-400 to-secondary-300" },
    { key: "docs", label: "来源商务标", icon: "ri-file-text-line", gradient: "from-primary-400 to-primary-600", bar: "from-primary-500 to-primary-400" },
  ];

  return (
    <div>
      <PageHeader
        title="企业资质与证照库"
        description="全公司共用一套，不按项目拆分。上传商务标后抽出营业执照、资质证书等扫描图，并查重合并。营业执照仅保留一条；财务即使过期仍可引用。"
        actions={
          canEditQual ? (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setUploadOpen(true)}
                disabled={parsing}
                className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 bg-background-100 px-4 text-sm font-medium text-foreground-700 transition-colors hover:bg-background-200 disabled:opacity-50"
              >
                <i className="ri-upload-2-line text-sm"></i>
                {parsing ? "抽取中…" : "上传商务标"}
              </button>
              <button
                type="button"
                onClick={openCreate}
                className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
              >
                <i className="ri-add-line text-sm"></i>
                录入证照
              </button>
            </div>
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
              <div className="font-heading text-gradient mt-0.5 text-xl font-bold tracking-wide">
                {card.key === "total" && stats.total}
                {card.key === "pending" && stats.pending}
                {card.key === "expiring" && stats.expiring}
                {card.key === "docs" && stats.docs}
              </div>
            </div>
            <div className={`absolute bottom-0 left-0 right-0 h-[2px] bg-gradient-to-r ${card.bar} opacity-0 transition-opacity duration-300 group-hover:opacity-100`} />
          </div>
        ))}
      </div>

      {expiring.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-accent-200 bg-accent-50/50 px-4 py-2.5 text-sm text-accent-800">
          <i className="ri-error-warning-line text-base"></i>
          <span className="font-medium">有效期预警：</span>
          <span>
            {expiring
              .map((q) => `${q.name}${q.warnDays != null ? `（${q.warnDays} 天后）` : ""}`)
              .join("、")}
          </span>
          <span className="text-xs text-accent-700">过期材料仍可使用，不会从库中移除。</span>
        </div>
      )}

      <div className="mb-4 flex flex-col gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5 lg:flex-row lg:items-center">
        <div className="flex flex-wrap items-center gap-1.5">
          {(
            [
              { key: "library" as const, label: "证照库", icon: "ri-vip-crown-line" },
              { key: "parse" as const, label: "文件解析", icon: "ri-file-search-line" },
            ]
          ).map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setPageTab(t.key)}
              className={`flex cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border px-3 py-1.5 text-xs font-medium transition-all ${
                pageTab === t.key
                  ? "border-primary-200 bg-primary-50 text-primary-600"
                  : "border-background-300 bg-transparent text-foreground-600 hover:border-background-400 hover:text-foreground-700"
              }`}
            >
              <i className={`${t.icon} text-sm`}></i>
              {t.label}
            </button>
          ))}
        </div>
        {pageTab === "library" && (
          <>
            <div className="flex flex-wrap items-center gap-1.5">
              {qualificationTabs.map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setActiveTab(tab.key)}
                  className={`flex cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border px-3 py-1.5 text-xs font-medium transition-all ${
                    activeTab === tab.key
                      ? "border-primary-200 bg-primary-50 text-primary-600"
                      : "border-background-300 bg-transparent text-foreground-600 hover:border-background-400 hover:text-foreground-700"
                  }`}
                >
                  <i className={`${tab.icon} text-sm`}></i>
                  {tab.label}
                </button>
              ))}
            </div>
            <div className="relative flex-1 lg:max-w-xs lg:ml-auto">
              <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-xs text-foreground-500"></i>
              <input
                type="text"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="搜索证照 / 合同号 / 来源文件…"
                className={`${inputCls} pl-9`}
              />
            </div>
          </>
        )}
      </div>

      {pageTab === "library" ? (
        <>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {paged.map((item) => (
            <div key={item.id} className="group rounded-lg border border-background-300 bg-background-100 p-4 transition-all hover:border-primary-300/60">
              <div className="flex items-start gap-3">
                {item.images?.[0]?.url ? (
                  <AuthImage
                    src={item.images[0].url}
                    alt={item.name}
                    className="h-10 w-10 shrink-0 rounded-lg border border-background-300 object-cover"
                  />
                ) : (
                <span
                  className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br text-background-50 ${
                    item.kind === "cert" || item.kind === "credit"
                      ? "from-primary-400 to-primary-600"
                      : item.kind === "people"
                        ? "from-accent-400 to-accent-500"
                        : item.kind === "financial"
                          ? "from-secondary-400 to-secondary-500"
                          : "from-primary-400 to-primary-600"
                  }`}
                >
                  <i className={kindIcon(item.kind)}></i>
                </span>
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-foreground-900">{item.name}</div>
                  <div className="mt-0.5 text-xs text-foreground-500">
                    {kindLabel[item.kind]} · {item.number || item.level || "未填编号"}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <StatusBadge status={item.status} pulse={item.status === "将到期"} />
                  {item.reviewStatus === "待审核" && <StatusBadge status="待审核" />}
                </div>
              </div>
              {item.mergeStatus && item.mergeStatus !== "新增" && (
                <div className="mt-2">
                  <StatusBadge status={item.mergeStatus} />
                </div>
              )}
              {item.fieldConflict && item.fieldConflict.length > 0 && (
                <p className="mt-2 text-[10px] text-accent-700">信息冲突：{item.fieldConflict.join("；")}</p>
              )}
              <p className="mt-3 line-clamp-2 text-xs leading-relaxed text-foreground-600">{item.detail}</p>
              {item.images && item.images.length > 0 && (
                <div className="mt-3 flex gap-1.5 overflow-x-auto">
                  {item.images.slice(0, 4).map((img) => (
                    <button
                      key={img.id}
                      type="button"
                      title={img.caption || "查看扫描件"}
                      onClick={() => void handleViewFile(item, img.url)}
                      className="shrink-0 cursor-pointer"
                    >
                      <AuthImage
                        src={img.url}
                        alt={img.caption}
                        className="h-14 w-20 rounded border border-background-300 object-cover"
                      />
                    </button>
                  ))}
                </div>
              )}
              {item.ocrText && (
                <p className="mt-2 line-clamp-3 rounded bg-background-50 px-2 py-1.5 text-[11px] leading-5 text-foreground-500">
                  OCR：{item.ocrText}
                </p>
              )}
              {item.hasFile && item.ocrStatus === "unavailable" && (
                <p className="mt-2 text-[11px] text-accent-600">扫描件已保存，当前环境未安装 OCR 引擎，未识别文字</p>
              )}
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                {item.owner && (
                  <span className="inline-flex items-center gap-1 rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">
                    <i className="ri-user-line"></i>
                    {item.owner}
                  </span>
                )}
                {item.hasFile && (
                  <span className="inline-flex items-center gap-1 rounded bg-primary-50 px-1.5 py-0.5 text-[10px] text-primary-600">
                    <i className="ri-attachment-line"></i>
                    {item.filename || "扫描件"}
                  </span>
                )}
                {item.sources && item.sources.length > 0 && (
                  <span className="inline-flex items-center gap-1 rounded bg-background-200 px-1.5 py-0.5 text-[10px] text-foreground-600">
                    <i className="ri-file-copy-line"></i>
                    {item.sources.length} 份商务标
                  </span>
                )}
                {item.kind === "financial" && item.status === "已过期" && (
                  <span className="inline-flex items-center gap-1 rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">
                    过期仍可使用
                  </span>
                )}
                {item.warnDays != null && (
                  <span className="inline-flex items-center gap-1 rounded bg-accent-50 px-1.5 py-0.5 text-[10px] text-accent-600">
                    <i className="ri-time-line"></i>
                    {item.warnDays} 天后到期
                  </span>
                )}
              </div>
              <div className="mt-3 flex items-center justify-between border-t border-background-200 pt-3">
                <span className="text-[11px] text-foreground-500">
                  {item.validUntil === "长期" ? "长期有效" : `有效期至 ${item.validUntil}`}
                </span>
                <div className="flex items-center gap-1">
                  {canEditQual &&
                    (item.suspectedIds || []).map((otherId) => {
                      const other = items.find((q) => q.id === otherId);
                      if (!other) return null;
                      return (
                        <span key={otherId} className="mr-1 inline-flex items-center gap-1">
                          <button
                            type="button"
                            title={`与「${other.name}」合并`}
                            className="flex h-7 cursor-pointer items-center rounded-md px-1.5 text-[10px] font-medium text-primary-600 hover:bg-primary-50"
                            onClick={() => void handleResolve(item, otherId, "merge")}
                          >
                            合并{other.name ? `·${other.name.slice(0, 6)}` : ""}
                          </button>
                          <button
                            type="button"
                            title={`与「${other.name}」拆开`}
                            className="flex h-7 cursor-pointer items-center rounded-md px-1.5 text-[10px] font-medium text-foreground-600 hover:bg-background-200"
                            onClick={() => void handleResolve(item, otherId, "keep_both")}
                          >
                            就是两条
                          </button>
                        </span>
                      );
                    })}
                  {canEditQual && item.reviewStatus === "待审核" && (
                    <button
                      type="button"
                      title="审核入库"
                      onClick={() => void handleReview(item)}
                      className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-primary-50 hover:text-primary-600"
                    >
                      <i className="ri-check-line text-sm"></i>
                    </button>
                  )}
                  <button
                    type="button"
                    title="复制证照信息"
                    onClick={() => void handleCopy(item)}
                    className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-primary-50 hover:text-primary-600"
                  >
                    <i className="ri-file-copy-line text-sm"></i>
                  </button>
                  <button
                    type="button"
                    title={item.hasFile || (item.images && item.images.length > 0) ? "查看扫描件" : "未抽出扫描图"}
                    onClick={() => void handleViewFile(item)}
                    className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-background-200 hover:text-foreground-800"
                  >
                    <i className="ri-eye-line text-sm"></i>
                  </button>
                  {canEditQual && (
                    <button
                      type="button"
                      title="编辑"
                      onClick={() => openEdit(item)}
                      className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-primary-50 hover:text-primary-600"
                    >
                      <i className="ri-pencil-line text-sm"></i>
                    </button>
                  )}
                  {canEditQual && (
                    <button
                      type="button"
                      title="删除"
                      onClick={() => void handleDelete(item)}
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
              <p className="mt-3 text-sm text-foreground-500">
                {items.length === 0 ? "暂无材料。可手工录入，或上传商务标自动抽取。" : "没有找到匹配的证照，试试调整筛选条件"}
              </p>
            </div>
          )}
        </div>
        {filtered.length > 0 && (
          <div className="mt-3 overflow-hidden rounded-lg border border-background-300 bg-background-100">
            <PaginationBar total={filtered.length} page={page} pageSize={PAGE_SIZE} onPageChange={setPage} />
          </div>
        )}
        </>
      ) : (
        <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
          <div className="flex items-center justify-between border-b border-background-300 bg-background-50 px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
              <i className="ri-file-search-line text-primary-500"></i>
              商务标解析（全公司共用）
            </div>
            <span className="font-label text-xs text-foreground-500">共 {jobs.length} 份 · 抽取结果写入同一套资质库</span>
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
                          {job.error && <div className="mt-0.5 text-[11px] text-accent-700">{job.error}</div>}
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <StatusBadge status={job.status} pulse={job.status === "解析中"} />
                    </td>
                    <td className="px-3 py-3">
                      <span className="font-heading text-gradient text-sm font-bold">{job.extracted}</span>
                      {job.merged || job.suspected || job.conflicts ? (
                        <div className="mt-0.5 text-[10px] text-foreground-500">
                          并入 {job.merged || 0} · 疑似 {job.suspected || 0} · 冲突 {job.conflicts || 0}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-3 py-3 text-xs text-foreground-600">{job.sizeLabel}</td>
                    <td className="px-3 py-3 text-xs text-foreground-500">{job.uploadedAt}</td>
                  </tr>
                ))}
                {jobs.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-16 text-center">
                      <i className="ri-inbox-line text-3xl text-foreground-400"></i>
                      <p className="mt-3 text-sm text-foreground-500">尚未上传商务标。多份文件中的营业执照会自动合并为一条。</p>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Modal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        title="上传商务标抽取资质"
        subtitle="支持多份 .doc / .docx / .pdf。抽出营业执照、证书等扫描图写入证照库；营业执照只保留一套，重复项会合并。"
      >
        <form onSubmit={(e) => void handleParseUpload(e)} className="space-y-4">
          <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-background-300 bg-background-50 px-4 py-8 text-center">
            <i className="ri-upload-cloud-2-line text-2xl text-primary-500"></i>
            <p className="text-xs text-foreground-500">
              {uploadFiles.length ? `已选 ${uploadFiles.length} 个文件` : "可一次选择多份过往商务标"}
            </p>
            {uploadFiles.length > 0 && (
              <ul className="max-h-24 w-full overflow-auto text-left text-[11px] text-foreground-600">
                {uploadFiles.map((f) => (
                  <li key={f.name}>{f.name}</li>
                ))}
              </ul>
            )}
            <button
              type="button"
              onClick={() => parseFileRef.current?.click()}
              className="mt-1 flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-3 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
            >
              <i className="ri-folder-add-line"></i>
              选择文件
            </button>
            <input
              ref={parseFileRef}
              type="file"
              multiple
              accept=".doc,.docx,.pdf"
              className="hidden"
              onChange={(e) => setUploadFiles(Array.from(e.target.files || []))}
            />
          </div>
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => setUploadOpen(false)}
              className="h-9 cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={parsing}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:opacity-50"
            >
              {parsing ? "抽取中…" : "开始抽取"}
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={createOpen}
        onClose={() => {
          setCreateOpen(false);
          setEditing(null);
        }}
        title={editing ? "编辑证照 / 合同 / 财务" : "录入证照 / 合同 / 财务"}
        subtitle={
          editing
            ? "可修正证号、持有人、有效期与类型。营业执照全公司只保留一条。"
            : "请手工填写证号、等级与有效期。财务请注明报表截止日；过期仍可保留使用。"
        }
      >
        <form onSubmit={handleSave} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className={labelCls} htmlFor="q-kind">
                材料类型
              </label>
              <select
                id="q-kind"
                value={form.kind}
                onChange={(e) => setForm((f) => ({ ...f, kind: e.target.value as QualificationKind }))}
                className={`${inputCls} cursor-pointer`}
              >
                {kindOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls} htmlFor="q-name">
                名称 <span className="text-accent-500">*</span>
              </label>
              <input
                id="q-name"
                type="text"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="例如：营业执照"
                className={inputCls}
              />
            </div>
            <div>
              <label className={labelCls} htmlFor="q-number">
                证号 / 合同号
              </label>
              <input
                id="q-number"
                type="text"
                value={form.number}
                onChange={(e) => setForm((f) => ({ ...f, number: e.target.value }))}
                className={inputCls}
              />
            </div>
            <div>
              <label className={labelCls} htmlFor="q-level">
                等级 / 规模
              </label>
              <input
                id="q-level"
                type="text"
                value={form.level}
                onChange={(e) => setForm((f) => ({ ...f, level: e.target.value }))}
                placeholder="例如：一级"
                className={inputCls}
              />
            </div>
            <div>
              <label className={labelCls} htmlFor="q-until">
                有效期 / 报表截止日
              </label>
              <input
                id="q-until"
                type="text"
                value={form.validUntil}
                onChange={(e) => setForm((f) => ({ ...f, validUntil: e.target.value }))}
                placeholder="长期 或 2024-12-31"
                className={inputCls}
              />
            </div>
            <div>
              <label className={labelCls} htmlFor="q-owner">
                持有人 / 归属
              </label>
              <input
                id="q-owner"
                type="text"
                value={form.owner}
                onChange={(e) => setForm((f) => ({ ...f, owner: e.target.value }))}
                className={inputCls}
              />
            </div>
          </div>
          <div>
            <label className={labelCls} htmlFor="q-detail">
              备注
            </label>
            <textarea
              id="q-detail"
              value={form.detail}
              onChange={(e) => setForm((f) => ({ ...f, detail: e.target.value }))}
              rows={3}
              className={`${inputCls} h-auto resize-none py-2`}
            />
          </div>
          <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-background-300 bg-background-50 px-4 py-6 text-center">
            <i className="ri-upload-cloud-2-line text-2xl text-primary-500"></i>
            <p className="text-xs text-foreground-500">{file ? file.name : "可选上传扫描件，支持 PDF/JPG/PNG"}</p>
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="mt-1 flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-3 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
            >
              <i className="ri-folder-add-line"></i>
              选择文件
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,.webp"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => {
                setCreateOpen(false);
                setEditing(null);
              }}
              className="h-9 cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:opacity-50"
            >
              {submitting ? "保存中…" : "保存"}
            </button>
          </div>
        </form>
      </Modal>

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}

function kindIcon(kind: QualificationKind): string {
  switch (kind) {
    case "cert":
      return "ri-vip-crown-line text-lg";
    case "people":
      return "ri-id-card-line text-lg";
    case "achievement":
      return "ri-trophy-line text-lg";
    case "equipment":
      return "ri-truck-line text-lg";
    case "credit":
      return "ri-shield-star-line text-lg";
    case "contract":
      return "ri-file-text-line text-lg";
    case "financial":
      return "ri-funds-line text-lg";
    default:
      return "ri-file-list-line text-lg";
  }
}
