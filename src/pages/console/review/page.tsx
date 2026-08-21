import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Modal from "../components/Modal";
import Toast from "../components/Toast";
import StatusBadge from "../components/StatusBadge";
import TypeBadge from "../components/TypeBadge";
import WordEditor, { type SerializedRevisionContent, type WordEditorHandle } from "./components/WordEditor";
import DocTree from "./components/DocTree";
import IssuePanel from "./components/IssuePanel";
import { useProjects } from "@/context/ProjectContext";
import { useAuth } from "@/context/AuthContext";
import {
  ApiError,
  autosaveBidRevisionContent,
  createBidRevisionVersion,
  exportBidRevisionDocx,
  getOrCreateBidRevision,
  listBidRevisionVersions,
  restoreBidRevisionVersion,
  type BidRevision,
  type BidRevisionVersion,
} from "@/lib/api";
import type { PreReviewIssue } from "@/mocks/preReview";

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

export default function ReviewPage() {
  const { projects } = useProjects();
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get("project") || "";
  const currentProject = projects.find((p) => p.id === selectedId);

  const [editMode, setEditMode] = useState(true);
  const [activeIssueId, setActiveIssueId] = useState<string | null>(null);
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [note, setNote] = useState("");
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });

  const [revision, setRevision] = useState<BidRevision | null>(null);
  const [revisionLoading, setRevisionLoading] = useState(true);
  const [revisionError, setRevisionError] = useState<string | null>(null);
  const [versions, setVersions] = useState<BidRevisionVersion[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);

  const editorRef = useRef<WordEditorHandle>(null);

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const selectProject = (id: string) => setSearchParams({ project: id });

  const goBackToList = () => setSearchParams({}, { replace: true });

  /* 项目选定后加载真实的修改闭环草稿（基于最新一轮已完成预审构建） */
  useEffect(() => {
    if (!currentProject) return;
    let cancelled = false;
    setRevisionLoading(true);
    setRevisionError(null);
    setRevision(null);
    setVersions([]);
    setActiveIssueId(null);
    setActiveSectionId(null);

    getOrCreateBidRevision(currentProject.id)
      .then((data) => {
        if (cancelled) return;
        setRevision(data);
        return listBidRevisionVersions(data.id).then((vs) => {
          if (!cancelled) setVersions(vs);
        });
      })
      .catch((err) => {
        if (cancelled) return;
        setRevisionError(err instanceof ApiError ? err.message : "加载修改闭环草稿失败，请稍后重试");
      })
      .finally(() => {
        if (!cancelled) setRevisionLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [currentProject?.id]);

  /* 章节 → 问题映射，用于目录/清单高亮联动 */
  const sectionIssueMap = useMemo(() => {
    const map: Record<string, PreReviewIssue[]> = {};
    (revision?.sections || []).forEach((s) => {
      s.paragraphs.forEach((p) => {
        if (!p.problem) return;
        const issue = revision?.issues.find((i) => i.id === p.problem!.issueId);
        if (issue) {
          map[s.id] = map[s.id] || [];
          map[s.id].push(issue);
        }
      });
    });
    return map;
  }, [revision]);

  const issueSectionMap = useMemo(() => {
    const map: Record<string, string> = {};
    (revision?.sections || []).forEach((s) => {
      s.paragraphs.forEach((p) => {
        if (p.problem) map[p.problem.issueId] = s.id;
      });
    });
    return map;
  }, [revision]);

  const jumpToSection = (sectionId: string) => {
    setActiveSectionId(sectionId);
    editorRef.current?.scrollToSection(sectionId);
  };

  const jumpToIssue = (issueId: string) => {
    const sectionId = issueSectionMap[issueId];
    if (sectionId) setActiveSectionId(sectionId);
    setActiveIssueId(issueId);
    editorRef.current?.scrollToIssue(issueId);
  };

  const jumpAll = () => {
    const first = revision?.issues[0];
    if (first) {
      jumpToIssue(first.id);
      showToast("已按问题顺序锚定首个问题，可用右侧清单逐一跳转", "info");
    }
  };

  const saveVersion = async () => {
    if (!revision) return;
    const content = editorRef.current?.getSerializedContent();
    if (!content) {
      showToast("编辑器尚未就绪，请稍后重试", "error");
      return;
    }
    setSaving(true);
    try {
      const version = await createBidRevisionVersion(revision.id, {
        blocks: content.blocks,
        contentState: content.contentState as unknown as Record<string, unknown>,
        note: note.trim() || "保存当前编辑版本",
        wordCount: content.wordCount,
        author: user?.name || "未署名",
      });
      setVersions((prev) => [version, ...prev]);
      setNote("");
      setSaveOpen(false);
      showToast(`已保存新版本 ${version.label}：${version.note}`);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "保存版本失败，请稍后重试", "error");
    } finally {
      setSaving(false);
    }
  };

  const restoreVersion = async (v: BidRevisionVersion) => {
    if (!revision) return;
    try {
      const { contentState } = await restoreBidRevisionVersion(revision.id, v.id);
      setRevision((prev) => (prev ? { ...prev, contentState } : prev));
      setReloadKey((k) => k + 1);
      setHistoryOpen(false);
      showToast(`已恢复版本 ${v.label}（${v.note}）`, "info");
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "恢复版本失败，请稍后重试", "error");
    }
  };

  const handleAutosave = (content: SerializedRevisionContent) => {
    if (!revision) return;
    autosaveBidRevisionContent(revision.id, content.contentState as unknown as Record<string, unknown>).catch(() => {
      // 静默失败：自动保存不打断编辑体验，用户仍可通过「保存版本」显式保存
    });
  };

  const exportDoc = async () => {
    if (!revision || !currentProject) return;
    setExporting(true);
    try {
      const blob = await exportBidRevisionDocx(revision.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${currentProject.name}-投标书修改版.docx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showToast("导出成功，已开始下载 Word 文档");
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "导出失败，请先保存至少一个版本", "error");
    } finally {
      setExporting(false);
    }
  };

  const targetBidDocumentId = versions[0]?.bidDocumentId || revision?.bidDocumentId || "";

  const inputCls =
    "h-9 w-full rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500";

  /* 未选择项目：先选择项目 */
  if (!currentProject) {
    return (
      <div>
        <PageHeader
          title="审核后修改闭环"
          description="把预审报告变成可执行的修改闭环：在 Word 式标书正文中高亮问题句、逐项改写、保存版本，并支持对修改后的标书发起二次评审。第一步，请先选择要修改的投标项目。"
        />
        <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
          <div className="flex flex-wrap items-center gap-2.5 border-b border-background-300 bg-background-50 px-5 py-4 sm:justify-between">
            <div className="flex items-center gap-2.5">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
                <i className="ri-loop-left-line text-lg"></i>
              </span>
              <div>
                <div className="font-label text-sm font-semibold text-foreground-900">第一步 · 选择投标项目</div>
                <div className="text-xs text-foreground-500">修改闭环需要绑定一个具体项目，请先选择后再进入 Word 编辑工作台</div>
              </div>
            </div>
            <select
              value=""
              onChange={(e) => e.target.value && selectProject(e.target.value)}
              className="h-9 w-full cursor-pointer rounded-md border border-background-300 bg-background-100 px-2.5 text-xs text-foreground-600 outline-none focus:border-primary-400 sm:w-auto sm:max-w-[280px]"
            >
              <option value="">快速选择项目…</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
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
                  <span className="text-xs text-foreground-400 transition-colors group-hover:text-primary-500">进入修改 →</span>
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
        </div>
        <Toast message={toast.message} type={toast.type} visible={toast.visible} />
      </div>
    );
  }

  /* 已选择项目，但正在加载修改闭环草稿 */
  if (revisionLoading) {
    return (
      <div>
        <PageHeader title="审核后修改闭环" description={`正在为「${currentProject.name}」加载修改闭环草稿…`} />
        <div className="flex h-64 items-center justify-center rounded-lg border border-background-300 bg-background-100 text-sm text-foreground-500">
          <i className="ri-loader-4-line mr-2 animate-spin text-lg text-primary-500"></i>
          正在读取最新预审结果并定位段落问题…
        </div>
      </div>
    );
  }

  /* 已选择项目，但该项目暂无已完成的预审记录 */
  if (revisionError || !revision) {
    return (
      <div>
        <PageHeader
          title="审核后修改闭环"
          description="修改闭环基于「AI 预审中心」的真实预审结果构建，需要先完成一轮预审才能进入 Word 编辑工作台。"
          actions={
            <button
              type="button"
              onClick={goBackToList}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
            >
              <i className="ri-arrow-left-s-line text-sm"></i>
              返回项目列表
            </button>
          }
        />
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-background-300 bg-background-100 p-10 text-center">
          <i className="ri-file-warning-line text-3xl text-accent-500"></i>
          <p className="text-sm text-foreground-700">{revisionError || `「${currentProject.name}」暂无已完成的预审记录`}</p>
          <p className="text-xs text-foreground-500">请先在「AI 预审中心」对该项目完成一次预审，再回到本页开始修改闭环</p>
          <Link
            to={`/console/audit?project=${currentProject.id}`}
            className="mt-1 flex h-9 items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
          >
            <i className="ri-shield-check-line text-sm"></i>
            前往 AI 预审中心
          </Link>
        </div>
        <Toast message={toast.message} type={toast.type} visible={toast.visible} />
      </div>
    );
  }

  /* 已选择项目：三栏 Word 工作台 */
  return (
    <div>
      <PageHeader
        title="审核后修改闭环"
        description="左侧文档目录定位章节，中间为真实 Word 编辑器（支持格式工具栏、格式刷、分栏、表格、链接），预审问题句原地高亮，右侧问题清单可一键锚定对应章节。"
        actions={
          <button
            type="button"
            onClick={exportDoc}
            disabled={exporting}
            className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {exporting ? <i className="ri-loader-4-line animate-spin text-sm"></i> : <i className="ri-file-word-2-line text-sm"></i>}
            导出 Word
          </button>
        }
      />

      {/* 当前项目选择 + 状态 */}
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
            <i className="ri-file-word-2-line text-base"></i>
          </span>
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-foreground-900">{currentProject.name}</div>
            <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-foreground-500">
              <span>编号 {currentProject.code}</span>
              <span>·</span>
              <span>预审问题 {revision.issues.length} 项</span>
              <StatusBadge status="改写中" />
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-md border border-background-300 bg-background-100 p-0.5">
            <button
              type="button"
              onClick={() => setEditMode(true)}
              className={`font-label flex cursor-pointer items-center gap-1 whitespace-nowrap rounded-md px-3 py-1.5 text-xs font-medium transition-all ${
                editMode ? "bg-gradient-to-r from-primary-500 to-primary-600 text-background-50" : "text-foreground-600 hover:text-foreground-900"
              }`}
            >
              <i className="ri-pencil-line text-xs"></i>
              编辑
            </button>
            <button
              type="button"
              onClick={() => setEditMode(false)}
              className={`font-label flex cursor-pointer items-center gap-1 whitespace-nowrap rounded-md px-3 py-1.5 text-xs font-medium transition-all ${
                !editMode ? "bg-gradient-to-r from-primary-500 to-primary-600 text-background-50" : "text-foreground-600 hover:text-foreground-900"
              }`}
            >
              <i className="ri-eye-line text-xs"></i>
              预览
            </button>
          </div>
          <button
            type="button"
            onClick={() => setHistoryOpen(true)}
            className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 px-2.5 text-xs text-foreground-600 transition-colors hover:bg-background-200"
          >
            <i className="ri-history-line text-sm"></i>
            版本 {versions.length}
          </button>
          <button
            type="button"
            onClick={() => setSaveOpen(true)}
            className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-3 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
          >
            <i className="ri-save-3-line text-sm"></i>
            保存版本
          </button>
          <select
            value={currentProject.id}
            onChange={(e) => selectProject(e.target.value)}
            className="h-8 w-full cursor-pointer rounded-md border border-background-300 bg-background-50 px-2.5 text-xs text-foreground-600 outline-none focus:border-primary-400 sm:w-auto sm:max-w-[200px]"
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
      </div>

      {/* 三栏：左目录 | 中 Word 编辑器 | 右问题清单 */}
      <div className="grid h-[760px] grid-cols-1 gap-4 lg:grid-cols-[248px_minmax(0,1fr)_316px]">
        <DocTree
          sections={revision.sections}
          activeSectionId={activeSectionId}
          activeIssueId={activeIssueId}
          onSelectSection={jumpToSection}
        />
        <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
          <WordEditor
            key={`${currentProject.id}-${reloadKey}`}
            ref={editorRef}
            sections={revision.sections}
            issues={revision.issues}
            editMode={editMode}
            onIssueClick={jumpAll}
            initialContentState={revision.contentState}
            onAutosave={handleAutosave}
          />
        </div>
        <IssuePanel
          issues={revision.issues}
          activeIssueId={activeIssueId}
          onIssueClick={jumpToIssue}
          onJumpAll={jumpAll}
        />
      </div>

      <div className="mt-4 flex items-center justify-between">
        <p className="flex items-start gap-1.5 text-xs text-foreground-500">
          <i className="ri-loop-left-line mt-0.5 text-primary-500"></i>
          修改完成后，点击右侧问题清单逐项确认消除，再进入「AI 预审中心」对修改后的标书发起二次评审评分。
        </p>
        <Link
          to={`/console/audit?project=${currentProject.id}${targetBidDocumentId ? `&bidDocumentId=${targetBidDocumentId}` : ""}`}
          className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-accent-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-accent-600"
        >
          <i className="ri-shield-check-line text-sm"></i>
          进入二次评审
        </Link>
      </div>

      {/* 保存版本弹窗 */}
      <Modal open={saveOpen} onClose={() => setSaveOpen(false)} title="保存版本" subtitle={`${currentProject.name} · 投标书正文`} width="max-w-md">
        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-foreground-600">版本说明</label>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={200}
              rows={3}
              placeholder="记录本次修改要点，例如：修正投标有效期承诺、补充业绩四件套…"
              className={`${inputCls} h-auto resize-none py-2 leading-relaxed`}
            />
          </div>
          <div className="flex items-start gap-1.5 rounded-md bg-background-50 px-3 py-2 text-[11px] text-foreground-500">
            <i className="ri-information-line mt-0.5 text-primary-500"></i>
            保存后将生成新版本并加入版本列表，可随时预览或恢复历史版本。
          </div>
          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={() => setSaveOpen(false)}
              className="h-9 cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
            >
              取消
            </button>
            <button
              type="button"
              onClick={saveVersion}
              disabled={saving}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saving ? <i className="ri-loader-4-line animate-spin text-sm"></i> : <i className="ri-save-3-line text-sm"></i>}
              保存版本
            </button>
          </div>
        </div>
      </Modal>

      {/* 版本列表弹窗 */}
      <Modal open={historyOpen} onClose={() => setHistoryOpen(false)} title="版本历史" subtitle={`${currentProject.name} · 共 ${versions.length} 个版本`} width="max-w-xl">
        <div className="space-y-2.5">
          {versions.length === 0 && (
            <p className="py-6 text-center text-xs text-foreground-500">暂无已保存的版本，点击「保存版本」创建第一个版本</p>
          )}
          {versions.map((v, idx) => (
            <div key={v.id} className={`rounded-lg border p-3 ${idx === 0 ? "border-primary-300 bg-primary-50/50" : "border-background-300 bg-background-50"}`}>
              <div className="flex items-center gap-2">
                <span className={`font-label rounded-md px-2 py-0.5 text-xs font-semibold ${idx === 0 ? "bg-primary-500 text-background-50" : "bg-background-200 text-foreground-600"}`}>
                  {v.label}
                </span>
                <span className="text-xs font-medium text-foreground-800">{v.note}</span>
                {idx === 0 && (
                  <span className="font-label ml-auto rounded bg-primary-100 px-1.5 py-0.5 text-[10px] text-primary-600">当前</span>
                )}
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-foreground-500">
                <span className="flex items-center gap-0.5"><i className="ri-time-line"></i>{v.createdAt.slice(0, 16).replace("T", " ")}</span>
                <span className="flex items-center gap-0.5"><i className="ri-user-line"></i>{v.author}</span>
                <span className="flex items-center gap-0.5"><i className="ri-file-text-line"></i>{v.wordCount} 字</span>
              </div>
              {idx !== 0 && (
                <div className="mt-2 flex items-center justify-end gap-1.5">
                  <button
                    type="button"
                    onClick={() => restoreVersion(v)}
                    className="flex h-7 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md bg-primary-500 px-2.5 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
                  >
                    <i className="ri-history-line"></i>恢复
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </Modal>

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}
