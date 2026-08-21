import { useState, type FormEvent } from "react";
import PageHeader from "../components/PageHeader";
import Modal from "../components/Modal";
import Toast from "../components/Toast";
import StatusBadge from "../components/StatusBadge";
import { projects } from "@/mocks/projects";
import { exportRecords, sections } from "@/mocks/exports";

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

const preChecks = [
  { key: "cover", label: "对标覆盖率 ≥ 95%", ok: true },
  { key: "waste", label: "无未关闭废标项", ok: false },
  { key: "word", label: "虚词密度 ≤ 30%", ok: true },
  { key: "toc", label: "目录页码一致", ok: true },
  { key: "anonym", label: "暗标标识无残留", ok: true },
  { key: "size", label: "文件大小 / 页数合规", ok: true },
];

export default function ExportPage() {
  const [projectId, setProjectId] = useState(projects[0].id);
  const [section, setSection] = useState(sections[0]);
  const [mode, setMode] = useState<"明标" | "暗标">("明标");
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });

  const currentProject = projects.find((p) => p.id === projectId) || projects[0];

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const openExport = () => {
    const blocked = preChecks.find((c) => !c.ok);
    if (blocked) {
      showToast(`导出前校验未通过：${blocked.label}，已阻断并返回修改闭环`, "error");
      return;
    }
    setExportOpen(true);
  };

  const handleExport = (e: FormEvent) => {
    e.preventDefault();
    setExportOpen(false);
    setExporting(true);
    showToast("正在按招标格式要求生成 Word 并剥离元数据…", "info");
    window.setTimeout(() => {
      setExporting(false);
      showToast("导出完成：Word 与 PDF 已生成，附线下用印清单");
    }, 2000);
  };

  const inputCls =
    "h-9 w-full cursor-pointer rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20";

  return (
    <div>
      <PageHeader
        title="Word 导出与交付"
        description="按招标文件格式要求导出可提交的分册 Word 标书，并做导出前校验；支持暗标版本与附件包。"
        actions={
          <button
            type="button"
            onClick={openExport}
            disabled={exporting}
            className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <i className={`${exporting ? "ri-loader-4-line animate-spin" : "ri-download-2-line"} text-sm`}></i>
            {exporting ? "导出中…" : "导出 Word"}
          </button>
        }
      />

      {/* 导出配置 */}
      <div className="mb-4 grid grid-cols-1 gap-3 lg:grid-cols-3">
        {/* 项目 + 分册 */}
        <div className="rounded-lg border border-background-300 bg-background-100 p-4 lg:col-span-2">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium text-foreground-800">
            <i className="ri-settings-4-line text-primary-500"></i>
            导出配置
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-foreground-600">投标项目</label>
              <select value={projectId} onChange={(e) => setProjectId(e.target.value)} className={inputCls}>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-foreground-600">分册</label>
              <select value={section} onChange={(e) => setSection(e.target.value)} className={inputCls}>
                {sections.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
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
                暗标自动剥离单位名 / logo / 姓名 / 隐藏域 / EXIF
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
          <ul className="space-y-2">
            {preChecks.map((c) => (
              <li key={c.key} className="flex items-center gap-2 text-xs">
                <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${c.ok ? "bg-primary-50 text-primary-500" : "bg-accent-50 text-accent-600"}`}>
                  <i className={`${c.ok ? "ri-check-line" : "ri-close-line"} text-[10px]`}></i>
                </span>
                <span className={c.ok ? "text-foreground-700" : "text-accent-700 font-medium"}>{c.label}</span>
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => showToast("已重跑导出前校验，未通过项返回修改闭环处理", "info")}
            className="mt-3 flex h-8 w-full cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-md border border-primary-200 bg-primary-50 text-xs font-medium text-primary-600 transition-colors hover:bg-primary-100"
          >
            <i className="ri-refresh-line"></i>
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
          <span className="font-label text-xs text-foreground-500">共 {exportRecords.length} 条 · 含操作人 / 模板版本 / 校验结果 / 哈希</span>
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
              {exportRecords.map((rec) => (
                <tr key={rec.id} className="group border-b border-background-200 transition-colors last:border-0 hover:bg-primary-50/30">
                  <td className="max-w-[320px] px-4 py-3">
                    <div className="truncate text-sm font-medium text-foreground-900">{rec.filename}</div>
                    <div className="mt-0.5 font-label text-[10px] text-foreground-500">哈希 {rec.hash}</div>
                  </td>
                  <td className="px-3 py-3">
                    <span className="whitespace-nowrap text-sm text-foreground-700">{rec.section}</span>
                  </td>
                  <td className="px-3 py-3">
                    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium ${
                      rec.mode === "暗标" ? "bg-secondary-100 text-secondary-600 border-secondary-200" : "bg-primary-50 text-primary-600 border-primary-200"
                    }`}>
                      <i className={`${rec.mode === "暗标" ? "ri-eye-off-line" : "ri-eye-line"} text-xs`}></i>
                      {rec.mode}
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    <span className="whitespace-nowrap text-sm text-foreground-700">{rec.operator}</span>
                  </td>
                  <td className="px-3 py-3">
                    <StatusBadge status={rec.checkStatus} pulse={rec.checkStatus === "已阻断"} />
                  </td>
                  <td className="px-3 py-3">
                    <span className="whitespace-nowrap text-xs text-foreground-500">{rec.fileSize}</span>
                  </td>
                  <td className="px-3 py-3">
                    <span className="whitespace-nowrap text-xs text-foreground-500">{rec.exportedAt}</span>
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex items-center justify-end gap-0.5">
                      {rec.checkStatus === "已阻断" ? (
                        <span className="whitespace-nowrap text-xs text-accent-600">{rec.checkNote}</span>
                      ) : (
                        <button
                          type="button"
                          title="下载"
                          onClick={() => showToast("已开始下载文件（演示）", "info")}
                          className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-primary-50 hover:text-primary-600"
                        >
                          <i className="ri-download-2-line text-sm"></i>
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
      <Modal open={exportOpen} onClose={() => setExportOpen(false)} title="确认导出" subtitle={`${currentProject.name} · ${section} · ${mode}`}>
        <form onSubmit={handleExport} className="space-y-4">
          <div className="rounded-lg bg-background-50 px-3 py-2.5 text-xs text-foreground-500">
            将生成 <span className="font-medium text-foreground-800">.docx</span> 与 <span className="font-medium text-foreground-800">PDF 预览</span>，按招标格式套用字体 / 页边距 / 页码 / 封面，自动生成目录与题注；暗标版本将剥离单位名、logo、姓名、隐藏域与图片 EXIF。
          </div>
          <div className="flex items-center gap-2 rounded-lg bg-accent-50 px-3 py-2.5 text-xs text-accent-700">
            <i className="ri-sticky-note-line"></i>
            签章 / 法人签字 / 日期将以占位框输出，并生成「线下用印清单」。
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