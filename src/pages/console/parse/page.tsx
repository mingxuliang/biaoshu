import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Toast from "../components/Toast";
import TypeBadge from "../components/TypeBadge";
import { useProjects } from "@/context/ProjectContext";
import {
  createTenderParseJob,
  downloadChecklistReport,
  getLatestChecklist,
  lockChecklist,
  pollTenderParseJobUntilDone,
  triggerFileDownload,
  type Checklist,
} from "@/lib/api";
import WordViewer from "./components/WordViewer";
import ParseResults from "./components/ParseResults";
import TenderDocumentGate, { type TenderDocSource } from "./components/TenderDocumentGate";

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

export default function ParsePage() {
  const { projects } = useProjects();
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get("project") || "";
  const currentProject = projects.find((p) => p.id === selectedId);

  const [parsing, setParsing] = useState(false);
  const [locking, setLocking] = useState(false);
  const [docSource, setDocSource] = useState<TenderDocSource | null>(null);
  const [checklist, setChecklist] = useState<Checklist | null>(null);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });

  useEffect(() => {
    if (!selectedId) {
      setChecklist(null);
      return;
    }
    let cancelled = false;
    getLatestChecklist(selectedId)
      .then((latest) => {
        if (!cancelled) setChecklist(latest);
      })
      .catch(() => {
        if (!cancelled) setChecklist(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const selectProject = (id: string) => setSearchParams({ project: id });

  const goBackToList = () => setSearchParams({}, { replace: true });

  const startParse = async () => {
    if (!currentProject || !docSource?.tenderDocumentId || parsing) return;
    setParsing(true);
    showToast(`AI 正在解析招标文件「${docSource.name}」：按固定一级/二级指标逐项抽取…`, "info");
    try {
      const job = await createTenderParseJob(currentProject.id, docSource.tenderDocumentId);
      const finalStatus = await pollTenderParseJobUntilDone(job.job_id, { timeoutMs: 12 * 60 * 1000 });
      const latest = await getLatestChecklist(currentProject.id);
      setChecklist(latest);
      if (finalStatus.status === "done" && !latest.error) {
        const dims = latest.dimensions ?? [];
        const filled = dims.reduce(
          (n, d) => n + d.items.reduce((m, i) => m + i.sections.reduce((s, sec) => s + sec.rows.filter((r) => r.content.trim()).length, 0), 0),
          0,
        );
        showToast(`解析完成：已填 ${filled} 项分析字段，未抽到的指标保持空白`);
      } else {
        showToast(latest.error || "解析未能抽取到有效内容，指标项仍可核对空白字段", "error");
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : "解析失败，请重试", "error");
    } finally {
      setParsing(false);
    }
  };

  const handleLock = async () => {
    if (!currentProject || !checklist || checklist.locked || locking) return;
    setLocking(true);
    try {
      const locked = await lockChecklist(currentProject.id, checklist.id);
      setChecklist(locked);
      showToast(`已锁定本项目评标尺子 v${locked.version}，预审引擎将按此尺子判定`);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "锁定失败，请重试", "error");
    } finally {
      setLocking(false);
    }
  };

  const handleDocContinue = (doc: TenderDocSource) => {
    setDocSource(doc);
  };

  /* 未选择项目：先选择项目再分析 */
  if (!currentProject) {
    return (
      <div>
        <PageHeader
          title="招标文件解析与对标清单"
          description="把招标文件解析为可执行的评分点与否决项清单。第一步，请先选择要解析的投标项目。"
        />
        <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
          <div className="flex items-center gap-2.5 border-b border-background-300 bg-background-50 px-5 py-4">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
              <i className="ri-projector-2-line text-lg"></i>
            </span>
            <div>
              <div className="font-label text-sm font-semibold text-foreground-900">第一步 · 选择投标项目</div>
              <div className="text-xs text-foreground-500">招标文件解析需要绑定一个具体项目，请先选择后再进行解析</div>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-3 p-5 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => selectProject(p.id)}
                className="group flex cursor-pointer flex-col gap-2.5 rounded-lg border border-background-300 bg-background-50 p-4 text-left transition-all duration-300 hover:border-primary-300/70 hover:bg-primary-50/40"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary-100 text-secondary-600">
                    <i className="ri-folder-open-line text-lg"></i>
                  </span>
                  <span className="text-xs text-foreground-400 transition-colors group-hover:text-primary-500">选择 →</span>
                </div>
                <div>
                  <div className="truncate text-sm font-medium text-foreground-900 group-hover:text-primary-600">{p.name}</div>
                  <div className="mt-0.5 text-xs text-foreground-500">编号 {p.code}</div>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <TypeBadge type={p.type} />
                  <span className="text-[11px] text-foreground-500">截止 {p.deadline}</span>
                </div>
              </button>
            ))}
          </div>
          <div className="flex items-center justify-between border-t border-background-300 bg-background-50 px-5 py-3">
            <span className="text-xs text-foreground-500">共 {projects.length} 个项目可解析</span>
            <select
              value=""
              onChange={(e) => e.target.value && selectProject(e.target.value)}
              className="h-8 w-auto cursor-pointer rounded-md border border-background-300 bg-background-50 px-2.5 text-xs text-foreground-600 outline-none focus:border-primary-400 sm:max-w-[280px]"
            >
              <option value="">快速选择项目…</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <Toast message={toast.message} type={toast.type} visible={toast.visible} />
      </div>
    );
  }

  /* 已选择项目：左右分栏解析工作台 */
  return (
    <div className="flex h-[calc(100vh-6rem)] flex-col">
      <PageHeader
        title="招标文件解析与对标清单"
        description="左侧浏览招标文件原文，右侧按固定一级维度与二级分析项目查看抽取结果。未抽到的字段保持空白。"
        actions={
          docSource ? (
            <>
              <button
                type="button"
                onClick={startParse}
                disabled={parsing || !docSource.tenderDocumentId}
                className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <i className={`${parsing ? "ri-loader-4-line animate-spin" : "ri-file-settings-line"} text-sm`}></i>
                {parsing ? "解析中…" : checklist ? "重新解析" : "开始解析"}
              </button>
            </>
          ) : undefined
        }
      />

      {/* 未选择文件：先上传招标文件 */}
      {!docSource ? (
        <TenderDocumentGate
          projectId={currentProject.id}
          projectName={currentProject.name}
          projectCode={currentProject.code}
          onContinue={handleDocContinue}
        />
      ) : (
        <>
          {/* 当前解析对象信息条 */}
          <div className="mb-4 flex flex-col gap-2 rounded-lg border border-background-300 bg-background-100 px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-center gap-2">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary-50 text-primary-600">
                <i className="ri-file-list-3-line text-base"></i>
              </span>
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="text-[11px] text-foreground-500">当前解析对象</span>
                  <span className="font-label rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">{docSource.source}</span>
                </div>
                <div className="truncate text-sm font-medium text-foreground-900">{docSource.name}</div>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <span className="text-[11px] text-foreground-500">
                {docSource.format} · {docSource.size}
              </span>
              <button
                type="button"
                onClick={() => {
                  setDocSource(null);
                }}
                className="flex h-8 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-2.5 text-xs font-medium text-foreground-600 transition-colors hover:bg-background-200 hover:text-primary-600"
              >
                <i className="ri-swap-line text-sm"></i>
                更换文件
              </button>
            </div>
          </div>

      {/* 当前项目信息栏 */}
      <div className="mb-4 flex flex-col gap-3 rounded-lg border border-background-300 bg-background-100 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-2.5">
          <button
            type="button"
            onClick={goBackToList}
            className="flex h-8 shrink-0 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-2.5 text-xs font-medium text-foreground-600 transition-colors hover:bg-background-200 hover:text-primary-600"
          >
            <i className="ri-arrow-left-s-line text-sm"></i>
            返回项目列表
          </button>
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
            <i className="ri-file-settings-line text-base"></i>
          </span>
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-foreground-900">{currentProject.name}</div>
            <div className="text-[11px] text-foreground-500">
              编号 {currentProject.code} · {currentProject.type} ·{" "}
              {checklist
                ? checklist.locked
                  ? `评标尺子已锁定 v${checklist.version}`
                  : `评标尺子草稿 v${checklist.version}`
                : "尚未解析评标尺子"}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={currentProject.id}
            onChange={(e) => selectProject(e.target.value)}
            className="h-8 w-full cursor-pointer rounded-md border border-background-300 bg-background-50 px-2.5 text-xs text-foreground-600 outline-none focus:border-primary-400 sm:w-auto sm:max-w-[280px]"
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <span className="hidden shrink-0 items-center gap-1 whitespace-nowrap rounded-md bg-secondary-100 px-2 py-1 text-[11px] font-medium text-secondary-700 md:flex">
            <i className="ri-check-double-line"></i>
            已绑定 {currentProject.code}
          </span>
        </div>
      </div>

      {/* 左右分栏：左侧Word原文 + 右侧AI解析 */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="min-h-0">
          <WordViewer
            projectName={currentProject.name}
            projectCode={currentProject.code}
            tenderDocumentId={docSource.tenderDocumentId}
            fileName={docSource.name}
          />
        </div>
        <div className="min-h-0">
          <ParseResults
            checklist={checklist}
            parsing={parsing}
            locking={locking}
            onLock={handleLock}
            onShare={async () => {
              try {
                await navigator.clipboard.writeText(window.location.href);
                showToast("当前解析页链接已复制到剪贴板");
              } catch {
                showToast("无法写入剪贴板，请手动复制浏览器地址栏", "error");
              }
            }}
            onDownload={async () => {
              if (!checklist || !currentProject) {
                showToast("请先完成解析再下载报告", "error");
                return;
              }
              try {
                const blob = await downloadChecklistReport(currentProject.id, checklist.id);
                triggerFileDownload(blob, `${currentProject.code}-解析报告-v${checklist.version}.docx`);
                showToast("解析报告已开始下载");
              } catch (err) {
                showToast(err instanceof Error ? err.message : "导出解析报告失败", "error");
              }
            }}
          />
        </div>
      </div>

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
        </>
      )}
    </div>
  );
}