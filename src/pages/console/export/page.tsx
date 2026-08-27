import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
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
} from "@/lib/api";

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

  const [projectId, setProjectId] = useState("");
  const [mode, setMode] = useState<"明标" | "暗标">("明标");
  const [checks, setChecks] = useState<ExportChecks | null>(null);
  const [checksError, setChecksError] = useState("");
  const [checksLoading, setChecksLoading] = useState(false);
  const [records, setRecords] = useState<ExportRecord[]>([]);
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });

  useEffect(() => {
    if (!projectId && projects.length > 0) setProjectId(projects[0].id);
  }, [projects, projectId]);

  const currentProject = useMemo(() => projects.find((p) => p.id === projectId), [projects, projectId]);

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
      const result = await getExportChecks(token, projectId, mode);
      setChecks(result);
    } catch (err) {
      setChecks(null);
      setChecksError(err instanceof ApiError ? err.message : "导出前校验加载失败");
    } finally {
      setChecksLoading(false);
    }
  }, [token, projectId, mode]);

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
      showToast(`导出前校验未通过：${checks.blockReason || "存在阻断项"}，已阻断并返回修改闭环`, "error");
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
      const record = await createExport(token, projectId, mode);
      showToast("导出完成，已生成文件并开始下载");
      try {
        const blob = await downloadExportRecord(token, record.id);
        triggerDownload(blob, record.filename || `${currentProject?.name || "投标文件"}-${mode}.docx`);
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
      triggerDownload(blob, record.filename || `${currentProject?.name || "投标文件"}-${record.mode}.docx`);
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
        description="复用修改闭环产出的投标文件，导出前用真实引擎复检废标 / 虚词 / 查重 / 版式 / 暗标残留，校验通过才可导出。"
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
                onChange={(e) => setProjectId(e.target.value)}
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
          <div className="mt-3">
            <label className="mb-1.5 block text-xs font-medium text-foreground-600">导出版本</label>
            <div className="flex gap-1.5">
              {(["明标", "暗标"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={`flex cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border px-3 py-1.5 text-xs font-medium transition-all ${
                    mode === m
                      ? "border-primary-200 bg-primary-50 text-primary-600"
                      : "border-background-300 bg-transparent text-foreground-600 hover:border-background-400"
                  }`}
                >
                  <i className={`${m === "暗标" ? "ri-eye-off-line" : "ri-eye-line"} text-sm`}></i>
                  {m}
                </button>
              ))}
              <span className="ml-2 self-center text-[11px] text-foreground-500">
                暗标自动清空文档属性中的作者 / 修改者 / 标题等身份信息
              </span>
            </div>
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
                  <td colSpan={7} className="px-4 py-8 text-center text-xs text-foreground-500">
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
      <Modal open={exportOpen} onClose={() => setExportOpen(false)} title="确认导出" subtitle={`${currentProject?.name || ""} · ${mode}`}>
        <form onSubmit={handleExport} className="space-y-4">
          <div className="rounded-lg bg-background-50 px-3 py-2.5 text-xs text-foreground-500">
            将基于修改闭环最新保存版本（<span className="font-medium text-foreground-800">{checks?.versionLabel}</span>）生成 <span className="font-medium text-foreground-800">.docx</span>；
            {mode === "暗标"
              ? "暗标模式将另存一份新文件，并清空作者 / 修改者 / 标题等文档属性。"
              : "明标模式直接使用当前文档，不做任何脱敏处理。"}
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
