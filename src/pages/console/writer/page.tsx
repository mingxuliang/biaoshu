import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Toast from "../components/Toast";
import StatusBadge from "../components/StatusBadge";
import TypeBadge from "../components/TypeBadge";
import { useProjects } from "@/context/ProjectContext";
import StepNav from "./components/StepNav";
import BidSettings, { type WriterSettingsPayload } from "./components/BidSettings";
import BidInterpret from "./components/BidInterpret";
import OutlineStep from "./components/OutlineStep";
import ContentStep from "./components/ContentStep";
import { getOrCreateWriterDraft, updateWriterDraft, type OutlineNode, type WriterDraft } from "@/lib/api";
import { compactOutlineTitles } from "@/lib/outlineNum";
import type { InterpretSource } from "@/mocks/writerSteps";

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

export default function WriterPage() {
  const { projects } = useProjects();
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get("project") || "";
  const currentProject = projects.find((p) => p.id === selectedId);

  const [draft, setDraft] = useState<WriterDraft | null>(null);
  const [draftLoading, setDraftLoading] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);

  const [step, setStep] = useState<number>(1);
  const [completed, setCompleted] = useState<Record<number, boolean>>({});
  const [modelId, setModelId] = useState<string>("deepseek-v4-pro");
  const [selectedKnowledge, setSelectedKnowledge] = useState<string[]>([]);
  const [selectedProductLibraryId, setSelectedProductLibraryId] = useState<string>("");
  const [interpretSource, setInterpretSource] = useState<InterpretSource>("reuse");
  const [outline, setOutline] = useState<OutlineNode[]>([]);
  const [chapterContents, setChapterContents] = useState<Record<string, string>>({});
  const [settingsPayload, setSettingsPayload] = useState<Partial<WriterSettingsPayload>>({});
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  // 选定项目后加载/新建撰写草稿，作为四步共用的唯一数据源（modelId/selectedKnowledge/outline/正文/step 均可断点续写）
  useEffect(() => {
    if (!currentProject) {
      setDraft(null);
      return;
    }
    let cancelled = false;
    setDraftLoading(true);
    setDraftError(null);
    getOrCreateWriterDraft(currentProject.id)
      .then((d) => {
        if (cancelled) return;
        setDraft(d);
        setModelId(!d.modelId || d.modelId === "deepseek" ? "deepseek-v4-pro" : d.modelId);
        setSelectedKnowledge(d.selectedKnowledge || []);
        setSelectedProductLibraryId(d.selectedProductLibraryId || "");
        setInterpretSource(d.interpretSource || "reuse");
        const compacted = compactOutlineTitles(d.outline || []);
        setOutline(compacted);
        const raw = d.outline || [];
        const outlineChanged =
          compacted.length !== raw.length ||
          compacted.some((n, i) => n.title !== raw[i]?.title || n.status !== raw[i]?.status);
        if (outlineChanged && compacted.length > 0) {
          updateWriterDraft(d.id, { outline: compacted }).catch(() => {
            /* 标题收短或固定格式件收叶失败不阻塞进入工作台 */
          });
        }
        const nextContents = { ...(d.chapterContents || {}) };
        for (const n of compacted) {
          if (n.status === "用原文" && !nextContents[n.id]) {
            nextContents[n.id] =
              `## ${n.title}\n\n本章为招标书已给出的固定格式文件，请直接使用招标书原文填写后打印签字，系统不展开目录、不撰写正文。`;
          }
        }
        setChapterContents(nextContents);
        setSettingsPayload((d.settings as Partial<WriterSettingsPayload>) || {});
        const resumeStep = d.step && d.step >= 1 && d.step <= 4 ? d.step : 1;
        setStep(resumeStep);
        const resumedCompleted: Record<number, boolean> = {};
        for (let s = 1; s < resumeStep; s += 1) resumedCompleted[s] = true;
        setCompleted(resumedCompleted);
      })
      .catch((err) => {
        if (cancelled) return;
        setDraftError(err instanceof Error ? err.message : "撰写草稿加载失败，请刷新重试");
      })
      .finally(() => {
        if (!cancelled) setDraftLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentProject?.id]);

  const selectProject = (id: string) => setSearchParams({ project: id });

  const goBackToList = () => setSearchParams({}, { replace: true });

  const persistStep = (s: number, draftId: string) => {
    updateWriterDraft(draftId, { step: s }).catch(() => {
      /* 步骤持久化失败不阻塞前端流转，用户仍可继续操作 */
    });
  };

  const completeStep = (s: number) => {
    setCompleted((prev) => ({ ...prev, [s]: true }));
    setStep(s + 1);
    if (draft) persistStep(s + 1, draft.id);
    showToast(`已完成第 ${s} 步，进入下一步`);
  };

  const goToStep = (target: number) => {
    // 仅允许进入已完成步骤或当前步骤
    if (completed[target] || target === step) {
      setStep(target);
      if (draft) persistStep(target, draft.id);
    }
  };

  const goBack = () => {
    setStep((s) => {
      const next = Math.max(1, s - 1);
      if (draft) persistStep(next, draft.id);
      return next;
    });
  };

  const handleSettingsNext = (settings: WriterSettingsPayload) => {
    setSettingsPayload(settings);
    if (draft) {
      updateWriterDraft(draft.id, {
        modelId,
        selectedKnowledge,
        selectedProductLibraryId: selectedProductLibraryId || null,
        settings: settings as unknown as Record<string, unknown>,
      }).catch(() => {
        showToast("标书设置保存失败，请检查网络后重试", "error");
      });
    }
    completeStep(1);
  };

  const handleInterpretConfirm = () => {
    if (draft) {
      updateWriterDraft(draft.id, { interpretSource }).catch(() => {
        /* 解读来源保存失败不阻塞流转 */
      });
    }
    completeStep(2);
  };

  const handleOutlineNext = () => {
    if (draft) {
      updateWriterDraft(draft.id, { outline }).catch(() => {
        showToast("目录保存失败，请检查网络后重试", "error");
      });
    }
    completeStep(3);
  };

  /* 未选择项目：先选择项目 */
  if (!currentProject) {
    return (
      <div>
        <PageHeader
          title="AI 撰写工作台"
          description="把招标解析与预审结论变成可落地的撰写闭环：四步式推进（标书设置 → 标书解读 → 目录生成 → 正文生成）。第一步，请先选择要撰写的投标项目。"
        />
        <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
          <div className="flex flex-wrap items-center gap-2.5 border-b border-background-300 bg-background-50 px-5 py-4 sm:justify-between">
            <div className="flex items-center gap-2.5">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
                <i className="ri-edit-2-line text-lg"></i>
              </span>
              <div>
                <div className="font-label text-sm font-semibold text-foreground-900">第一步 · 选择投标项目</div>
                <div className="text-xs text-foreground-500">撰写工作台需要绑定一个具体项目，请先选择后再进入四步撰写流程</div>
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
                  <span className="text-xs text-foreground-400 transition-colors group-hover:text-primary-500">进入撰写 →</span>
                </div>
                <div>
                  <div className="truncate text-sm font-medium text-foreground-900 group-hover:text-primary-600">{p.name}</div>
                  <div className="mt-0.5 text-xs text-foreground-500">编号 {p.code}</div>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <TypeBadge type={p.type} />
                  <StatusBadge status={p.status} />
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

  /* 撰写草稿加载中 */
  if (draftLoading && !draft) {
    return (
      <div className="flex h-[calc(100vh-6.5rem)] min-h-[560px] flex-col items-center justify-center gap-2 rounded-lg border border-background-300 bg-background-100 text-foreground-500">
        <i className="ri-loader-4-line animate-spin text-2xl"></i>
        <span className="text-sm">正在加载撰写草稿…</span>
      </div>
    );
  }

  /* 撰写草稿加载失败 */
  if (draftError || !draft) {
    return (
      <div className="flex h-[calc(100vh-6.5rem)] min-h-[560px] flex-col items-center justify-center gap-2 rounded-lg border border-background-300 bg-background-100 text-center text-foreground-500">
        <i className="ri-error-warning-line text-2xl text-red-400"></i>
        <span className="text-sm">{draftError || "撰写草稿加载失败，请刷新重试"}</span>
      </div>
    );
  }

  /* 已选择项目：四步式撰写工作台 */
  return (
    <div className="flex h-[calc(100vh-6.5rem)] min-h-[560px] flex-col gap-3">
      {/* 项目信息 + 步骤导航 */}
      <div className="flex flex-col gap-2.5">
        <div className="flex flex-col gap-2 rounded-lg border border-background-300 bg-background-100 px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between">
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
              <i className="ri-edit-2-line text-base"></i>
            </span>
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-foreground-900">{currentProject.name}</div>
              <div className="text-[11px] text-foreground-500">
                编号 {currentProject.code} · {currentProject.type} · 四步式撰写
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={currentProject.id}
              onChange={(e) => selectProject(e.target.value)}
              className="h-7 w-full cursor-pointer rounded-md border border-background-300 bg-background-50 px-2 text-xs text-foreground-600 outline-none focus:border-primary-400 sm:w-auto sm:max-w-[280px]"
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <StatusBadge status={currentProject.status} />
          </div>
        </div>
        <StepNav current={step} completed={completed} onStepClick={goToStep} />
      </div>

      {/* 当前步骤内容 */}
      <div className="flex min-h-0 flex-1 flex-col">
        {step === 1 && (
          <BidSettings
            projectId={currentProject.id}
            modelId={modelId}
            onModelChange={(id) => {
              setModelId(id);
              if (draft) {
                updateWriterDraft(draft.id, { modelId: id }).catch(() => {
                  /* 模型选择失败不阻塞界面，进入下一步时会再次保存 */
                });
              }
            }}
            selectedKnowledge={selectedKnowledge}
            onKnowledgeChange={setSelectedKnowledge}
            selectedProductLibraryId={selectedProductLibraryId}
            onProductLibraryChange={(id) => {
              setSelectedProductLibraryId(id);
              if (draft) {
                updateWriterDraft(draft.id, { selectedProductLibraryId: id || null }).catch(() => {
                  /* 产品库选择失败不阻塞界面 */
                });
              }
            }}
            initialSettings={settingsPayload}
            onNext={handleSettingsNext}
          />
        )}
        {step === 2 && (
          <BidInterpret
            projectId={currentProject.id}
            source={interpretSource}
            onSourceChange={setInterpretSource}
            onConfirm={handleInterpretConfirm}
            onBack={goBack}
          />
        )}
        {step === 3 && (
          <OutlineStep
            projectId={currentProject.id}
            projectName={currentProject.name}
            project={currentProject}
            draftId={draft.id}
            outline={outline}
            onOutlineChange={setOutline}
            initialKnowledgeRefs={draft.knowledgeRefs}
            onOutlineRegenerated={(payload) => {
              setChapterContents(payload?.chapterContents || {});
              setDraft((d) =>
                d ? { ...d, knowledgeRefs: {}, chapterContents: payload?.chapterContents || {} } : d,
              );
            }}
            onNext={handleOutlineNext}
            onBack={goBack}
          />
        )}
        {step === 4 && (
          <ContentStep
            projectId={currentProject.id}
            draftId={draft.id}
            outline={outline}
            onOutlineChange={setOutline}
            chapterContents={chapterContents}
            onChapterContentsChange={setChapterContents}
            projectName={currentProject.name}
            onBack={goBack}
          />
        )}
      </div>

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}
