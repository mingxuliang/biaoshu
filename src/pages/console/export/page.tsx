import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Modal from "../components/Modal";
import Toast from "../components/Toast";
import StatusBadge from "../components/StatusBadge";
import { useAuth } from "@/context/AuthContext";
import { useProjects } from "@/context/ProjectContext";
import {
  ApiError,
  createExport,
  downloadExportRecord,
  getExportChecks,
  listExportRecords,
  type ExportChecks,
  type ExportRecord,
  type ExportScope,
} from "@/lib/api";

const SCOPE_LABEL: Record<ExportScope, string> = { business: "商务标", tech: "技术标" };

function scopeLabel(scope?: string): string {
  return scope === "business" || scope === "tech" ? SCOPE_LABEL[scope] : "—";
}

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

function formatFileSize(bytes: number): string {
  if (!bytes) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatHash(hash: string): string {
  if (!hash) return "—";
  return hash.length > 12 ? `${hash.slice(0, 6)}…${hash.slice(-4)}` : hash;
}

function formatDateTime(iso: string): string {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 16);
}

export default function ExportPage() {
  const { token } = useAuth();
  const { projects, loading: projectsLoading } = useProjects();

  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const projectId = searchParams.get("project") || "";
  const scope: ExportScope = searchParams.get("scope") === "tech" ? "tech" : "business";
  // null 表示跟随招标文件；用户点了明标/暗标才算手动覆盖
  const [modeOverride, setModeOverride] = useState<"明标" | "暗标" | null>(null);
  const [checks, setChecks] = useState<ExportChecks | null>(null);
  const [checksError, setChecksError] = useState("");
  const [checksLoading, setChecksLoading] = useState(false);
  const [records, setRecords] = useState<ExportRecord[]>([]);
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });

  const updateParams = useCallback(
    (patch: { project?: string; scope?: ExportScope }) => {
      const next = new URLSearchParams(searchParams);
      if (patch.project !== undefined) next.set("project", patch.project);
      if (patch.scope !== undefined) next.set("scope", patch.scope);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  useEffect(() => {
    if (!projectId && projects.length > 0) updateParams({ project: projects[0].id });
  }, [projects, projectId, updateParams]);

  // 换项目或换分册后，回到「跟随招标文件」
  useEffect(() => {
    setModeOverride(null);
  }, [projectId, scope]);

  const currentProject = useMemo(() => projects.find((p) => p.id === projectId), [projects, projectId]);

  // 实际生效的模式：以后端复检结果为准；商务标永远是明标
  const mode: "明标" | "暗标" = checks?.mode ?? modeOverride ?? "明标";
  const blindAllowed = checks?.blindAllowed ?? scope === "tech";
  const categoryText =
    checks?.categoryLabel ||
    (currentProject?.category === "工程类" ? "工程标" : currentProject ? "软件服务标" : "");

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const loadChecks = useCallback(async () => {
    if (!token || !projectId) {
      setChecks(null);
      return;
    }
    setChecksLoading(true);
    setChecksError("");
    try {
      const result = await getExportChecks(token, projectId, scope, modeOverride ?? undefined);
      setChecks(result);
    } catch (err) {
      setChecks(null);
      setChecksError(err instanceof ApiError ? err.message : "导出前校验加载失败");
    } finally {
      setChecksLoading(false);
    }
  }, [token, projectId, scope, modeOverride]);

  const loadRecords = useCallback(async () => {
    if (!token || !projectId) {
      setRecords([]);
      return;
    }
    try {
      const list = await listExportRecords(token, projectId);
      setRecords(list);
    } catch {
      setRecords([]);
    }
  }, [token, projectId]);

  useEffect(() => {
    loadChecks();
  }, [loadChecks]);

  useEffect(() => {
    loadRecords();
  }, [loadRecords]);

  const openExport = () => {
    if (!checks) {
      showToast(checksError || "暂无可导出内容", "error");
      return;
    }
    if (checks.blocked) {
      showToast(`导出前校验未通过：${checks.blockReason || "存在阻断项"}，请回到修改闭环处理`, "error");
      window.setTimeout(() => navigate(`/console/review?project=${projectId}&scope=${scope}`), 1200);
      return;
    }
    setExportOpen(true);
  };

  const triggerDownload = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const handleExport = async (e: FormEvent) => {
    e.preventDefault();
    if (!token || !projectId) return;
    setExportOpen(false);
    setExporting(true);
    try {
      const record = await createExport(token, projectId, scope, mode);
      showToast("导出完成，已生成文件并开始下载");
      try {
        const blob = await downloadExportRecord(token, record.id);
        triggerDownload(blob, record.filename || `${currentProject?.name || "投标文件"}-${SCOPE_LABEL[scope]}-${mode}.docx`);
      } catch {
        showToast("导出记录已生成，但自动下载失败，请在下方记录表中手动下载", "info");
      }
      await Promise.all([loadRecords(), loadChecks()]);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "导出失败，已阻断并返回修改闭环", "error");
      await loadRecords();
    } finally {
      setExporting(false);
    }
  };

  const handleDownload = async (record: ExportRecord) => {
    if (!token) return;
    setDownloadingId(record.id);
    try {
      const blob = await downloadExportRecord(token, record.id);
      triggerDownload(
        blob,
        record.filename || `${currentProject?.name || "投标文件"}-${scopeLabel(record.scope)}-${record.mode}.docx`,
      );
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "下载失败", "error");
    } finally {
      setDownloadingId(null);
    }
  };

  const inputCls =
    "h-9 w-full cursor-pointer rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20";

  const canExport = !!checks && !checks.blocked && !checksLoading;

  return (
    <div>
      <PageHeader
        title="Word 导出与交付"
        description="复用修改闭环产出的投标文件，按商务标 / 技术标分别复检（规则按工程标、软件服务标取用），技术标按招标要求决定是否暗标，校验通过才可导出。"
        actions={
          <button
            type="button"
            onClick={openExport}
            disabled={exporting || !canExport}
            className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <i className={`${exporting ? "ri-loader-4-line animate-spin" : "ri-download-2-line"} text-sm`}></i>
            {exporting ? "导出中…" : "导出 Word"}
          </button>
        }
      />

      {/* 导出配置 */}
      <div className="mb-4 grid grid-cols-1 gap-3 lg:grid-cols-3">
        {/* 项目 + 当前版本 */}
        <div className="rounded-lg border border-background-300 bg-background-100 p-4 lg:col-span-2">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium text-foreground-800">
            <i className="ri-settings-4-line text-primary-500"></i>
            导出配置
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-foreground-600">投标项目</label>
              <select
                value={projectId}
                onChange={(e) => updateParams({ project: e.target.value })}
                disabled={projectsLoading || projects.length === 0}
                className={inputCls}
              >
                {projects.length === 0 && <option value="">暂无项目</option>}
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-foreground-600">修改闭环最新版本</label>
              {checks ? (
                <div className="flex h-9 items-center gap-2 rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-700">
                  <span className="font-medium text-foreground-900">{checks.versionLabel}</span>
                  <span className="text-xs text-foreground-500">· {checks.wordCount} 字</span>
                  <span className="text-xs text-foreground-500">· {formatDateTime(checks.updatedAt)}</span>
                </div>
              ) : (
                <div className="flex h-9 items-center rounded-md border border-dashed border-background-300 bg-background-50 px-3 text-xs text-foreground-500">
                  {checksLoading ? "加载中…" : checksError || "请先在「修改闭环」完成一次保存"}
                </div>
              )}
            </div>
          </div>
          {checks?.checklistLocked === false && (
            <div className="mt-3 flex items-start gap-2 rounded-md border border-secondary-200 bg-secondary-50 px-3 py-2 text-xs text-foreground-700">
              <i className="ri-lock-unlock-line mt-0.5 text-secondary-600"></i>
              评标尺子还没有锁定，复检用的是最新一份解析结果。建议先到「招标解析」核对并锁定后再导出。
            </div>
          )}
          <div className="mt-3">
            <label className="mb-1.5 flex items-center gap-2 text-xs font-medium text-foreground-600">
              导出分册
              {categoryText && (
                <span className="rounded border border-secondary-200 bg-secondary-50 px-1.5 py-0.5 text-[10px] font-medium text-secondary-600">
                  {categoryText}
                </span>
              )}
            </label>
            <div className="flex gap-1.5">
              {(["business", "tech"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => updateParams({ scope: s })}
                  className={`flex cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border px-3 py-1.5 text-xs font-medium transition-all ${
                    scope === s
                      ? "border-primary-200 bg-primary-50 text-primary-600"
                      : "border-background-300 bg-transparent text-foreground-600 hover:border-background-400"
                  }`}
                >
                  <i className={`${s === "tech" ? "ri-tools-line" : "ri-briefcase-line"} text-sm`}></i>
                  {SCOPE_LABEL[s]}
                </button>
              ))}
              <span className="ml-2 self-center text-[11px] text-foreground-500">
                商务标与技术标分别复检、分别导出，各用自己在修改闭环里最新保存的版本
              </span>
            </div>
          </div>
          <div className="mt-3">
            <label className="mb-1.5 block text-xs font-medium text-foreground-600">导出版本</label>
            <div className="flex flex-wrap gap-1.5">
              {(["明标", "暗标"] as const).map((m) => {
                const disabled = m === "暗标" && !blindAllowed;
                return (
                  <button
                    key={m}
                    type="button"
                    disabled={disabled}
                    title={disabled ? "暗标只适用于技术标" : undefined}
                    onClick={() => setModeOverride(m)}
                    className={`flex cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border px-3 py-1.5 text-xs font-medium transition-all disabled:cursor-not-allowed disabled:opacity-50 ${
                      mode === m
                        ? "border-primary-200 bg-primary-50 text-primary-600"
                        : "border-background-300 bg-transparent text-foreground-600 hover:border-background-400"
                    }`}
                  >
                    <i className={`${m === "暗标" ? "ri-eye-off-line" : "ri-eye-line"} text-sm`}></i>
                    {m}
                  </button>
                );
              })}
              <span className="ml-2 self-center text-[11px] text-foreground-500">
                {!blindAllowed
                  ? "商务标按明标导出，不做暗标处理"
                  : checks?.anonymityRequired
                    ? modeOverride === null
                      ? "招标文件要求暗标，已默认选暗标"
                      : "招标文件要求暗标；你手动改了导出版本"
                    : modeOverride === null
                      ? "招标文件没有暗标要求，默认明标"
                      : "招标文件没有暗标要求；你手动选了暗标"}
              </span>
            </div>
            {blindAllowed && (
              <div className="mt-1.5 text-[11px] text-foreground-500">
                暗标会清空作者 / 修改者 / 标题等文档属性、公司名、自定义属性、批注与修订痕迹，并删掉页眉页脚里的单位名称；正文里出现单位名称会被拦截。
              </div>
            )}
          </div>
        </div>

        {/* 导出前校验 */}
        <div className="rounded-lg border border-background-300 bg-background-100 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium text-foreground-800">
            <i className="ri-checkbox-circle-line text-primary-500"></i>
            导出前校验
          </div>
          {checks ? (
            <ul className="space-y-2">
              {checks.items.map((c) => (
                <li key={c.key} className="flex items-start gap-2 text-xs">
                  <span
                    className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${
                      c.ok ? "bg-primary-50 text-primary-500" : "bg-accent-50 text-accent-600"
                    }`}
                  >
                    <i className={`${c.ok ? "ri-check-line" : "ri-close-line"} text-[10px]`}></i>
                  </span>
                  <div>
                    <div className={c.ok ? "text-foreground-700" : "text-accent-700 font-medium"}>{c.label}</div>
                    {!c.ok && c.note && <div className="mt-0.5 text-[11px] text-foreground-500">{c.note}</div>}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="py-2 text-xs text-foreground-500">{checksLoading ? "校验中…" : checksError || "暂无可校验内容"}</div>
          )}
          <button
            type="button"
            onClick={() => loadChecks()}
            disabled={checksLoading || !projectId}
            className="mt-3 flex h-8 w-full cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-md border border-primary-200 bg-primary-50 text-xs font-medium text-primary-600 transition-colors hover:bg-primary-100 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <i className={`ri-refresh-line ${checksLoading ? "animate-spin" : ""}`}></i>
            重新校验
          </button>
        </div>
      </div>

      {/* 导出记录 */}
      <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
        <div className="flex items-center justify-between border-b border-background-300 bg-background-50 px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
            <i className="ri-history-line text-primary-500"></i>
            导出记录
          </div>
          <span className="font-label text-xs text-foreground-500">共 {records.length} 条 · 含操作人 / 校验结果 / 哈希</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[880px] text-left">
            <thead>
              <tr className="font-label border-b border-background-300 bg-background-50 text-xs text-foreground-500">
                <th className="px-4 py-2.5 font-medium">文件名</th>
                <th className="px-3 py-2.5 font-medium">分册</th>
                <th className="px-3 py-2.5 font-medium">模式</th>
                <th className="px-3 py-2.5 font-medium">操作人</th>
                <th className="px-3 py-2.5 font-medium">校验</th>
                <th className="px-3 py-2.5 font-medium">大小</th>
                <th className="px-3 py-2.5 font-medium">导出时间</th>
                <th className="px-3 py-2.5 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {records.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-xs text-foreground-500">
                    暂无导出记录
                  </td>
                </tr>
              )}
              {records.map((rec) => (
                <tr key={rec.id} className="group border-b border-background-200 transition-colors last:border-0 hover:bg-primary-50/30">
                  <td className="max-w-[320px] px-4 py-3">
                    <div className="truncate text-sm font-medium text-foreground-900">{rec.filename || "—"}</div>
                    <div className="mt-0.5 font-label text-[10px] text-foreground-500">哈希 {formatHash(rec.fileHash)}</div>
                  </td>
                  <td className="px-3 py-3">
                    <span className="whitespace-nowrap text-sm text-foreground-700">{scopeLabel(rec.scope)}</span>
                  </td>
                  <td className="px-3 py-3">
                    <span
                      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium ${
                        rec.mode === "暗标"
                          ? "bg-secondary-100 text-secondary-600 border-secondary-200"
                          : "bg-primary-50 text-primary-600 border-primary-200"
                      }`}
                    >
                      <i className={`${rec.mode === "暗标" ? "ri-eye-off-line" : "ri-eye-line"} text-xs`}></i>
                      {rec.mode}
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    <span className="whitespace-nowrap text-sm text-foreground-700">{rec.operator}</span>
                  </td>
                  <td className="px-3 py-3">
                    <StatusBadge status={rec.checkStatus} pulse={rec.checkStatus === "阻断"} />
                  </td>
                  <td className="px-3 py-3">
                    <span className="whitespace-nowrap text-xs text-foreground-500">{formatFileSize(rec.fileSize)}</span>
                  </td>
                  <td className="px-3 py-3">
                    <span className="whitespace-nowrap text-xs text-foreground-500">{formatDateTime(rec.createdAt)}</span>
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex items-center justify-end gap-0.5">
                      {rec.checkStatus === "阻断" ? (
                        <span className="whitespace-nowrap text-xs text-accent-600">{rec.checkNote || "已阻断"}</span>
                      ) : (
                        <button
                          type="button"
                          title="下载"
                          onClick={() => handleDownload(rec)}
                          disabled={downloadingId === rec.id}
                          className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-primary-50 hover:text-primary-600 disabled:opacity-50"
                        >
                          <i className={`${downloadingId === rec.id ? "ri-loader-4-line animate-spin" : "ri-download-2-line"} text-sm`}></i>
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 导出确认弹窗 */}
      <Modal open={exportOpen} onClose={() => setExportOpen(false)} title="确认导出" subtitle={`${currentProject?.name || ""} · ${SCOPE_LABEL[scope]} · ${mode}`}>
        <form onSubmit={handleExport} className="space-y-4">
          <div className="rounded-lg bg-background-50 px-3 py-2.5 text-xs text-foreground-500">
            将基于{SCOPE_LABEL[scope]}在修改闭环里最新保存的版本（<span className="font-medium text-foreground-800">{checks?.versionLabel}</span>）生成 <span className="font-medium text-foreground-800">.docx</span>；
            {mode === "暗标"
              ? "暗标模式将另存一份脱敏文件：清空作者 / 公司 / 标题等文档属性、自定义属性、批注和修订痕迹，并删掉页眉页脚里的单位名称。"
              : "明标模式另存一份导出副本，不做任何脱敏处理。"}
          </div>
          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => setExportOpen(false)}
              className="h-9 cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
            >
              取消
            </button>
            <button
              type="submit"
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
            >
              <i className="ri-download-2-line text-sm"></i>
              确认导出
            </button>
          </div>
        </form>
      </Modal>

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}
