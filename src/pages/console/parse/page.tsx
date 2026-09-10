import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Toast from "../components/Toast";
import TypeBadge from "../components/TypeBadge";
import { useAuth } from "@/context/AuthContext";
import { useProjects } from "@/context/ProjectContext";
import {
  createTenderParseJob,
  downloadChecklistReport,
  getLatestChecklist,
  listProjectTenderDocuments,
  lockChecklist,
  pollTenderParseJobUntilDone,
  triggerFileDownload,
  type Checklist,
  type TenderDocumentSummary,
} from "@/lib/api";
import {
  TENDER_KIND_LABELS,
  TENDER_KIND_SLOTS,
  TENDER_MISSING_HINT,
  effectiveTenderKind,
} from "@/lib/tenderPackage";
import WordViewer from "./components/WordViewer";
import ParseResults from "./components/ParseResults";
import TenderPackagePanel from "./components/TenderPackagePanel";
import Modal from "../components/Modal";

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

export default function ParsePage() {
  const { projects } = useProjects();
  const { token } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get("project") || "";
  const currentProject = projects.find((p) => p.id === selectedId);

  const [parsing, setParsing] = useState(false);
  const [locking, setLocking] = useState(false);
  const [docs, setDocs] = useState<TenderDocumentSummary[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [activeDocId, setActiveDocId] = useState<string>("");
  const [packageOpen, setPackageOpen] = useState(false);
  const [checklist, setChecklist] = useState<Checklist | null>(null);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });

  useEffect(() => {
    if (!selectedId) {
      setChecklist(null);
      setDocs([]);
      setActiveDocId("");
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

  useEffect(() => {
    if (!selectedId || !token) {
      setDocs([]);
      return;
    }
    let cancelled = false;
    setDocsLoading(true);
    listProjectTenderDocuments(token, selectedId)
      .then((list) => {
        if (cancelled) return;
        setDocs(list);
        setActiveDocId((prev) => (prev && list.some((d) => d.id === prev) ? prev : list[0]?.id || ""));
      })
      .catch(() => {
        if (!cancelled) setDocs([]);
      })
      .finally(() => {
        if (!cancelled) setDocsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, token]);

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const selectProject = (id: string) => setSearchParams({ project: id });

  const goBackToList = () => setSearchParams({}, { replace: true });

  const activeDoc = docs.find((d) => d.id === activeDocId) || docs[0] || null;

  const liveSlots = useMemo(() => {
    return TENDER_KIND_SLOTS.map((slot) => {
      const files = docs.filter((d) => effectiveTenderKind(d.kind, d.filename) === slot.key);
      return {
        kind: slot.key,
        label: slot.label,
        uploaded: files.length > 0,
        missingHint: files.length ? "" : TENDER_MISSING_HINT,
        files: files.map((d) => ({
          id: d.id,
          filename: d.filename,
          sizeBytes: d.sizeBytes,
          kind: slot.key,
        })),
      };
    });
  }, [docs]);

  const packageSlots = useMemo(() => {
    const parsed = checklist?.package;
    if (!parsed?.length) return liveSlots;
    return liveSlots.map((slot) => {
      const hit = parsed.find((p) => p.kind === slot.kind);
      return {
        ...slot,
        excerpt: hit?.excerpt || "",
        displayIn: hit?.displayIn || "",
        jumpKey: hit?.jumpKey || "",
      };
    });
  }, [liveSlots, checklist]);

  const startParse = async () => {
    if (!currentProject || !docs.length || parsing) return;
    const ids = docs.map((d) => d.id);
    const primary = docs.find((d) => effectiveTenderKind(d.kind, d.filename) === "main") || docs[0];
    setParsing(true);
    showToast(`AI 正在一并解析招标文件包（${docs.length} 份）：按固定指标抽取，并识读施工图纸…`, "info");
    try {
      const job = await createTenderParseJob(currentProject.id, primary.id, ids);
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

  const handleDocsChange = (next: TenderDocumentSummary[]) => {
    setDocs(next);
    setActiveDocId((prev) => (prev && next.some((d) => d.id === prev) ? prev : next[0]?.id || ""));
  };

  /* 未选择项目：先选择项目再分析 */
  if (!currentProject) {
    return (
      <div>
        <PageHeader
          title="招标文件解析与对标清单"
          description="把招标文件包（正文、图纸、答疑补遗、报价、清单）解析为可执行的评分点与否决项清单。第一步，请先选择要解析的投标项目。"
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

  return (
    <div className="flex h-[calc(100vh-6rem)] flex-col">
      <PageHeader
        title="招标文件解析与对标清单"
        description="分类上传招标文件包后一并解析。左侧预览原文，右侧查看各类型抽取字段；施工图纸会识读图号目录与施工要点。"
        actions={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPackageOpen(true)}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-3 text-sm font-medium text-foreground-700 transition-colors hover:bg-background-200"
            >
              <i className="ri-upload-2-line text-sm"></i>
              管理文件
            </button>
            <button
              type="button"
              onClick={startParse}
              disabled={parsing || docs.length === 0}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <i className={`${parsing ? "ri-loader-4-line animate-spin" : "ri-file-settings-line"} text-sm`}></i>
              {parsing ? "解析中…" : checklist ? "重新解析文件包" : "开始解析文件包"}
            </button>
          </div>
        }
      />

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
              编号 {currentProject.code} · {currentProject.type} · {currentProject.category} ·{" "}
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

      <div className="mb-3 flex flex-col gap-2 rounded-lg border border-background-300 bg-background-50 px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
            <span className="font-medium text-foreground-800">招标文件包</span>
            <span className="font-label rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">
              已上传 {liveSlots.filter((s) => s.uploaded).length}/{liveSlots.length} 类
            </span>
            {liveSlots.filter((s) => s.uploaded).map((s) => (
              <span key={s.kind} className="truncate text-foreground-600">
                {s.label}
                {s.files[0] ? ` · ${s.files[0].filename}` : ""}
              </span>
            ))}
          </div>
          {liveSlots.some((s) => !s.uploaded) && (
            <div className="mt-0.5 text-[11px] text-accent-600">
              {TENDER_MISSING_HINT}：{liveSlots.filter((s) => !s.uploaded).map((s) => s.label).join("、")}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={() => setPackageOpen(true)}
          className="flex h-8 shrink-0 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border border-background-300 bg-background-100 px-2.5 text-xs font-medium text-foreground-700 hover:border-primary-300 hover:text-primary-700"
        >
          <i className="ri-folder-upload-line text-sm"></i>
          上传 / 管理文件
        </button>
      </div>

      <Modal
        open={packageOpen}
        onClose={() => setPackageOpen(false)}
        title="上传招标文件包"
        subtitle="按类型上传正文、答疑补遗、工程量清单、报价文件、施工图纸，关闭后可一并解析"
        width="max-w-5xl"
      >
        <TenderPackagePanel
          projectId={currentProject.id}
          docs={docs}
          loading={docsLoading}
          onDocsChange={handleDocsChange}
        />
        <div className="mt-4 flex justify-end border-t border-background-200 pt-3">
          <button
            type="button"
            onClick={() => setPackageOpen(false)}
            className="flex h-8 cursor-pointer items-center rounded-md bg-primary-500 px-4 text-xs font-medium text-background-50 hover:bg-primary-600"
          >
            完成
          </button>
        </div>
      </Modal>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="flex min-h-0 flex-col">
          {docs.length > 0 && (
            <div className="mb-2 flex gap-1 overflow-x-auto pb-1">
              {docs.map((doc) => {
                const kind = effectiveTenderKind(doc.kind, doc.filename);
                const selected = doc.id === (activeDoc?.id || "");
                return (
                  <button
                    key={doc.id}
                    type="button"
                    onClick={() => setActiveDocId(doc.id)}
                    className={`flex max-w-[220px] shrink-0 cursor-pointer items-center gap-1 rounded-md px-2 py-1 text-[11px] transition-colors ${
                      selected
                        ? "bg-primary-50 text-primary-700 ring-1 ring-primary-200"
                        : "bg-background-100 text-foreground-600 hover:bg-background-200"
                    }`}
                    title={doc.filename}
                  >
                    <span className="truncate font-medium">{doc.filename}</span>
                    <span className="shrink-0 text-[10px] text-foreground-400">{TENDER_KIND_LABELS[kind]}</span>
                  </button>
                );
              })}
            </div>
          )}
          {activeDoc ? (
            <WordViewer
              projectName={currentProject.name}
              projectCode={currentProject.code}
              tenderDocumentId={activeDoc.id}
              fileName={activeDoc.filename}
            />
          ) : (
            <div className="flex h-full min-h-[280px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-background-300 bg-background-50 text-sm text-foreground-500">
              <i className="ri-upload-cloud-2-line text-2xl text-foreground-300"></i>
              请先点击「上传 / 管理文件」补齐招标文件包
            </div>
          )}
        </div>
        <div className="min-h-0">
          <ParseResults
            checklist={checklist}
            parsing={parsing}
            locking={locking}
            category={currentProject.category}
            packageSlots={packageSlots}
            focusKind={activeDoc ? effectiveTenderKind(activeDoc.kind, activeDoc.filename) : undefined}
            focusFileName={activeDoc?.filename}
            focusFileId={activeDoc?.id}
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
    </div>
  );
}
