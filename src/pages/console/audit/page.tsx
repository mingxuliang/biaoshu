import { useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Toast from "../components/Toast";
import ProgressRing from "../components/ProgressRing";
import PreReviewReport from "./components/PreReviewReport";
import DocumentSourceGate, { type PreReviewDoc } from "./components/DocumentSourceGate";
import ProjectSelectionGate from "../components/ProjectSelectionGate";
import { useProjects } from "@/context/ProjectContext";
import {
  ApiError,
  createPrereviewJob,
  exportLatestReviewReport,
  getLatestReviewRun,
  getReviewRunTrend,
  pollJobUntilDone,
  triggerFileDownload,
  type ReviewReport,
  type TrendPoint,
} from "@/lib/api";

type TabKey = "result" | "trend" | "report";

const tabs: { key: TabKey; label: string; icon: string }[] = [
  { key: "result", label: "预审结果", icon: "ri-file-shield-2-line" },
  { key: "trend", label: "历史趋势", icon: "ri-line-chart-line" },
  { key: "report", label: "预审报告", icon: "ri-file-chart-line" },
];

const levelStyle: Record<string, string> = {
  L1: "from-primary-400 to-primary-600",
  L2: "from-accent-400 to-accent-500",
  L3: "from-primary-400 to-primary-600",
  L4: "from-accent-400 to-accent-500",
  L5: "from-secondary-400 to-secondary-500",
};

const severityStyle: Record<string, string> = {
  废标: "bg-accent-50 text-accent-600 border-accent-200",
  降档: "bg-accent-50 text-accent-600 border-accent-200",
  扣分: "bg-secondary-100 text-secondary-600 border-secondary-200",
  建议: "bg-primary-50 text-primary-600 border-primary-200",
};

const lightColor: Record<string, string> = {
  绿: "#16a34a",
  橙: "#ea580c",
  红: "#dc2626",
};

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

export default function AuditPage() {
  const { projects } = useProjects();
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get("project") || "";
  const currentProject = projects.find((p) => p.id === selectedId);
  const [activeTab, setActiveTab] = useState<TabKey>("result");
  const [reviewing, setReviewing] = useState(false);
  const [secondReviewing, setSecondReviewing] = useState(false);
  /* 修改闭环页「进入二次评审」带来的 bidDocumentId：跳过手动选择文件，直接对该文档发起预审；
     用惰性初始值只消费一次，避免点击「更换文件」后被 URL 参数重新覆盖 */
  const [docSource, setDocSource] = useState<PreReviewDoc | null>(() => {
    const bidDocumentId = new URLSearchParams(window.location.search).get("bidDocumentId");
    if (!bidDocumentId) return null;
    return {
      kind: "upload",
      name: "投标书修改版（来自修改闭环）",
      source: "修改闭环二次评审",
      size: "-",
      updated: "刚刚",
      bidDocumentId,
    };
  });
  const [report, setReport] = useState<ReviewReport | null>(null);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });
  const [exporting, setExporting] = useState(false);

  const busy = reviewing || secondReviewing;

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const selectProject = (id: string) => setSearchParams({ project: id });

  const goBackToList = () => setSearchParams({}, { replace: true });

  const refreshTrend = async (projectId: string) => {
    try {
      setTrend(await getReviewRunTrend(projectId));
    } catch {
      // 趋势加载失败不阻塞主流程
    }
  };

  const runPrereview = async (kind: "first" | "second") => {
    if (!currentProject || !docSource) return;
    const setBusy = kind === "first" ? setReviewing : setSecondReviewing;
    setBusy(true);
      showToast(`AI 预审已启动，正在对「${docSource.name}」执行 L1-L5 分层扫描。技术标按章节送审，最长约 30 万字，通常数分钟内完成…`, "info");
    try {
      const job = await createPrereviewJob(currentProject.id, docSource.bidDocumentId);
      const finalStatus = await pollJobUntilDone(job.job_id, { intervalMs: 2500, timeoutMs: 15 * 60 * 1000 });
      if (finalStatus.status === "failed") {
        showToast(`第 ${finalStatus.round} 轮预审失败：${finalStatus.error ?? "未知错误"}`, "error");
        return;
      }
      const latest = await getLatestReviewRun(currentProject.id);
      setReport(latest);
      await refreshTrend(currentProject.id);
      showToast(
        `第 ${latest.round} 轮预审完成：风险灯【${latest.light}】，发现 ${latest.waste} 项废标风险、${latest.risk} 项扣分，报告已生成`,
      );
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "预审任务执行异常，请重试", "error");
    } finally {
      setBusy(false);
    }
  };

  const startReview = () => {
    if (busy || !docSource) return;
    void runPrereview("first");
  };

  // 修复点：原逻辑用 !secondDone 同时作为「已完成二次评审」与按钮 disabled 条件，
  // 导致按钮永远不可点。现在只要已有一轮完成的报告（意味着可以对回改后的版本再跑一轮），
  // 且当前没有任务在执行，就允许发起。
  const startSecondReview = () => {
    if (busy || !docSource || !report) return;
    void runPrereview("second");
  };

  const changeDocument = () => {
    setDocSource(null);
    setReport(null);
  };

  const maxTrendScore = trend.length ? Math.max(...trend.map((d) => d.score)) : 100;
  const prevTrendPoint = trend.length >= 2 ? trend[trend.length - 2] : null;
  const exportReady = !!report && report.overall >= 90 && report.waste === 0;

  const exportReport = async () => {
    if (!currentProject || !report) return;
    setExporting(true);
    showToast(`正在导出第 ${report.round} 轮 AI 预审报告 Word 文档…`, "info");
    try {
      const blob = await exportLatestReviewReport(currentProject.id);
      triggerFileDownload(blob, `${currentProject.code || currentProject.name}-第${report.round}轮-AI预审报告.docx`);
      showToast("预审报告已开始下载");
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "导出报告失败，请稍后重试", "error");
    } finally {
      setExporting(false);
    }
  };

  const copyReportSummary = async () => {
    if (!report || !currentProject) return;
    const lines = [
      `AI 智能预审报告 · ${currentProject.name}（${currentProject.code}）`,
      `第 ${report.round} 轮 · 综合得分 ${report.overall} · 风险灯 ${report.light}`,
      `废标 ${report.waste} 项 · 扣分 ${report.risk} 项 · 建议 ${report.suggest} 项`,
      ...(report.levels || []).map((lv) => `${lv.key} ${lv.name}：${lv.score} 分，${lv.issues} 项，${lv.status}`),
      "",
      "问题摘要：",
      ...report.issues.slice(0, 20).map((issue, i) => `${i + 1}. [${issue.severity}] ${issue.rule} @ ${issue.location}：${issue.excerpt}`),
    ];
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      showToast("预审报告摘要已复制到剪贴板");
    } catch {
      showToast("复制失败，请检查浏览器剪贴板权限", "error");
    }
  };

  /* 未选择项目：先选择项目 */
  if (!currentProject) {
    return (
      <ProjectSelectionGate
        title="AI 预审中心"
        description="用青天口径在投标前预审「自己的标」：否决项、五维技术标、商务客观项、虚词与查重，输出带原文定位的预审报告，并支持对修改闭环后的标书发起二次评审。"
        stepLabel="第一步 · 选择投标项目"
        stepHint="预审中心需要绑定一个具体项目，请先选择后再进入预审界面"
        icon="ri-shield-flash-line"
        accentClass="from-accent-400 to-accent-500"
        onSelect={selectProject}
      />
    );
  }

  return (
    <div>
      <PageHeader
        title="AI 预审中心"
        description="用青天口径在投标前预审「自己的标」：否决项、五维技术标、商务客观项、虚词与查重，输出带原文定位的预审报告，并支持对修改闭环后的标书发起二次评审。"
        actions={docSource ? (
          <>
            <button
              type="button"
              onClick={startReview}
              disabled={busy}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <i className={`${reviewing ? "ri-loader-4-line animate-spin" : "ri-shield-flash-line"} text-sm`}></i>
              {reviewing ? "预审中…" : "发起全量预审"}
            </button>
            <button
              type="button"
              onClick={startSecondReview}
              disabled={busy || !report}
              title={!report ? "请先完成一轮全量预审，回改标书后再发起二次评审" : undefined}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <i className={`${secondReviewing ? "ri-loader-4-line animate-spin" : "ri-refresh-line"} text-sm`}></i>
              {secondReviewing ? "二次评审中…" : "对修改后标书发起二次评审"}
            </button>
          </>) : undefined}
      />

      {/* 未选择文件：先选择预审投标文件 */}
      {!docSource ? (
        <DocumentSourceGate
          projectId={currentProject.id}
          projectName={currentProject.name}
          projectCode={currentProject.code}
          onContinue={setDocSource}
        />
      ) : (
        <>
          {/* 已选文件信息条 */}
          <div className="mb-4 flex flex-col gap-2 rounded-lg border border-background-300 bg-background-100 px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-center gap-2">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent-50 text-accent-600">
                <i className="ri-file-word-2-line text-base"></i>
              </span>
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="text-[11px] text-foreground-500">当前预审对象</span>
                  <span className="font-label rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">{docSource.source}</span>
                </div>
                <div className="truncate text-sm font-medium text-foreground-900">{docSource.name}</div>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <span className="text-[11px] text-foreground-500">
                {docSource.size}
                {docSource.pages ? ` · ${docSource.pages} 页` : ""} · {docSource.updated}
              </span>
              <button
                type="button"
                onClick={changeDocument}
                disabled={busy}
                className="flex h-8 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-2.5 text-xs font-medium text-foreground-600 transition-colors hover:bg-background-200 hover:text-primary-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <i className="ri-swap-line text-sm"></i>
                更换文件
              </button>
            </div>
          </div>

      {/* 项目选择 + 风险灯 */}
      <div className="mb-4 flex flex-col gap-3 rounded-lg border border-background-300 bg-background-100 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <button
            type="button"
            onClick={goBackToList}
            className="flex h-8 shrink-0 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-2.5 text-xs font-medium text-foreground-600 transition-colors hover:bg-background-200 hover:text-primary-600"
          >
            <i className="ri-arrow-left-s-line text-sm"></i>
            返回项目列表
          </button>
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-accent-400 to-accent-500 text-background-50">
            <i className="ri-error-warning-line text-lg"></i>
          </span>
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-foreground-900">{currentProject.name}</div>
            <div className="text-[11px] text-foreground-500">
              编号 {currentProject.code}
              {report ? ` · 第 ${report.round} 轮预审` : " · 尚未运行预审"}
            </div>
          </div>
          {report && (
            <div className="ml-2 flex items-center gap-1.5 rounded-lg bg-background-50 px-3 py-1.5">
              <span className="relative flex h-2 w-2">
                <span
                  className="absolute inline-flex h-full w-full rounded-full opacity-50 animate-ping"
                  style={{ backgroundColor: lightColor[report.light] }}
                />
                <span className="relative inline-flex h-2 w-2 rounded-full" style={{ backgroundColor: lightColor[report.light] }} />
              </span>
              <span className="font-label text-xs font-semibold" style={{ color: lightColor[report.light] }}>
                风险灯 · {report.light}
              </span>
            </div>
          )}
        </div>
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
      </div>

      {docSource?.source === "修改闭环二次评审" && (
        <div className="mb-4 flex items-start gap-2 rounded-lg border border-accent-200 bg-accent-50/70 px-4 py-3 text-xs text-foreground-700">
          <i className="ri-information-line mt-0.5 text-accent-500"></i>
          <span>
            当前预审文件来自修改闭环已保存版本，不会审到上一轮原文。
            {searchParams.get("resolved")
              ? ` 上一轮已标记修复 ${searchParams.get("resolved")!.split(",").filter(Boolean).length} 项，请对照新报告确认是否消除。`
              : ""}
          </span>
        </div>
      )}

      {/* 二次评审对比条 */}
      {report && report.round > 1 && prevTrendPoint && (
        <div className="mb-4 flex flex-col gap-3 rounded-lg border border-primary-300 bg-primary-50/50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
            <span className="font-label flex items-center gap-1.5 text-foreground-600">
              相比第 {prevTrendPoint.round} 轮：
            </span>
            <span className="font-label flex items-center gap-1 text-foreground-600">
              综合得分 <span className="font-heading text-sm font-bold text-foreground-900">{prevTrendPoint.score}</span>
              <i className="ri-arrow-right-line text-primary-500"></i>
              <span className="font-heading text-sm font-bold text-primary-600">{report.overall}</span>
              <span className="rounded bg-primary-100 px-1.5 py-0.5 text-[10px] font-medium text-primary-600">
                {report.overall - prevTrendPoint.score >= 0 ? "+" : ""}
                {Math.round((report.overall - prevTrendPoint.score) * 10) / 10}
              </span>
            </span>
            <span className="font-label flex items-center gap-1 text-foreground-600">
              问题数 <span className="font-heading text-sm font-bold text-foreground-900">{prevTrendPoint.issues}</span>
              <i className="ri-arrow-right-line text-primary-500"></i>
              <span className="font-heading text-sm font-bold text-primary-600">{report.waste + report.risk + report.suggest}</span>
            </span>
          </div>
          <span className="font-label shrink-0 rounded-md bg-primary-500 px-2.5 py-1 text-[11px] font-semibold text-background-50">
            第 {report.round} 轮 · 最新评审
          </span>
        </div>
      )}

      {/* 选项卡 */}
      <div className="mb-4 flex rounded-md border border-background-300 bg-background-100 p-0.5">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`font-label flex cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md px-4 py-2 text-sm font-medium transition-all ${
              activeTab === tab.key
                ? "bg-gradient-to-r from-primary-500 to-primary-600 text-background-50"
                : "text-foreground-600 hover:text-foreground-900"
            }`}
          >
            <i className={`${tab.icon} text-sm`}></i>
            {tab.label}
          </button>
        ))}
      </div>

      {!report ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-background-300 bg-background-100 px-6 py-16 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-primary-50 text-primary-500">
            <i className="ri-shield-flash-line text-2xl"></i>
          </span>
          <p className="text-sm font-medium text-foreground-800">尚未运行预审</p>
          <p className="max-w-md text-xs text-foreground-500">
            点击右上角「发起全量预审」，AI 将对当前投标文件执行 L1-L5 分层扫描（一票否决、商务客观核验、
            技术标五维打分、虚词与模板查重、版式终审），完成后在此查看结果。
          </p>
        </div>
      ) : (
        <>
          {activeTab === "result" && (
            <>
              {/* 总分概览 */}
              <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="flex items-center gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5">
                  <ProgressRing value={report.overall} size={60} stroke={5} />
                  <div>
                    <div className="font-label text-[11px] text-foreground-500">综合预审得分</div>
                    <div className="font-heading text-gradient text-lg font-bold">{report.overall}</div>
                  </div>
                </div>
                <div className="flex items-center gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-accent-50 text-accent-600">
                    <i className="ri-close-circle-line text-xl"></i>
                  </span>
                  <div>
                    <div className="font-label text-[11px] text-foreground-500">废标风险项</div>
                    <div className="font-heading text-gradient text-lg font-bold">{report.waste}</div>
                  </div>
                </div>
                <div className="flex items-center gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-secondary-100 text-secondary-600">
                    <i className="ri-error-warning-line text-xl"></i>
                  </span>
                  <div>
                    <div className="font-label text-[11px] text-foreground-500">扣分 / 建议项</div>
                    <div className="font-heading text-gradient text-lg font-bold">{report.risk} + {report.suggest}</div>
                  </div>
                </div>
                <div className="flex items-center gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary-50 text-primary-600">
                    <i className="ri-lock-line text-xl"></i>
                  </span>
                  <div>
                    <div className="font-label text-[11px] text-foreground-500">导出状态</div>
                    <div className="font-heading text-gradient text-lg font-bold">{exportReady ? "已达标" : "待达标"}</div>
                  </div>
                </div>
              </div>

              {/* 分层预审 */}
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
                <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
                  <div className="border-b border-background-300 bg-background-50 px-4 py-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
                      <i className="ri-stack-line text-primary-500"></i>
                      L1-L5 分层预审 · 第 {report.round} 轮
                    </div>
                  </div>
                  <ul className="divide-y divide-background-200">
                    {report.levels.map((level) => (
                      <li key={level.key} className="flex items-center gap-3 px-4 py-3">
                        <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-gradient-to-br ${levelStyle[level.key]} font-label text-xs font-semibold text-background-50`}>
                          {level.key}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium text-foreground-900">{level.name}</div>
                          <div className="truncate text-[11px] text-foreground-500">{level.desc}</div>
                        </div>
                        <div className="text-right">
                          <div className={`font-heading text-sm font-bold ${level.status === "风险" ? "text-accent-600" : "text-gradient"}`}>
                            {level.score}
                          </div>
                          <div className="font-label text-[10px] text-foreground-500">{level.issues} 项</div>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>

                {/* 五维打分 */}
                <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
                  <div className="border-b border-background-300 bg-background-50 px-4 py-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
                      <i className="ri-focus-3-line text-primary-500"></i>
                      技术标五维打分 · 第 {report.round} 轮
                    </div>
                  </div>
                  <ul className="divide-y divide-background-200">
                    {report.dimensions.map((dim) => (
                      <li key={dim.name} className="flex items-center gap-3 px-4 py-3">
                        <span className="font-label w-20 shrink-0 text-xs text-foreground-600">{dim.name}</span>
                        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-background-200">
                          <div
                            className="h-full rounded-full bg-gradient-to-r from-primary-500 to-primary-400"
                            style={{ width: `${dim.score}%` }}
                          />
                        </div>
                        <span className="font-label w-14 shrink-0 text-right text-xs text-foreground-500">
                          {dim.score} / 权重 {dim.weight}%
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>

                {/* 预审报告问题 */}
                <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100 lg:max-h-[420px] lg:overflow-y-auto">
                  <div className="sticky top-0 border-b border-background-300 bg-background-50 px-4 py-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
                        <i className="ri-file-list-3-line text-primary-500"></i>
                        预审问题清单 · 第 {report.round} 轮
                      </div>
                      <Link
                        to={`/console/review?project=${currentProject.id}`}
                        className="flex h-7 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md bg-primary-500 px-2.5 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
                      >
                        去修改
                        <i className="ri-arrow-right-line"></i>
                      </Link>
                    </div>
                  </div>
                  <ul className="divide-y divide-background-200">
                    {report.issues.map((issue) => (
                      <li key={issue.id}>
                        <Link
                          to={`/console/review?project=${currentProject.id}&issue=${issue.id}`}
                          className="block cursor-pointer px-4 py-3 transition-colors hover:bg-primary-50/60"
                        >
                          <div className="flex items-center justify-between">
                            <span className={`inline-flex items-center whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${severityStyle[issue.severity]}`}>
                              {issue.severity}
                            </span>
                            <span className="font-label text-[10px] text-foreground-500">{issue.level} · {issue.location}</span>
                          </div>
                          <p className="mt-1.5 text-xs leading-relaxed text-foreground-700">「{issue.excerpt}」</p>
                          <p className="mt-1 text-[11px] text-foreground-500">建议：{issue.suggestion}</p>
                          <p className="mt-1.5 text-[11px] text-primary-600">点击定位到修改闭环原文 →</p>
                        </Link>
                      </li>
                    ))}
                    {report.issues.length === 0 && (
                      <li className="px-4 py-10 text-center">
                        <i className="ri-checkbox-circle-line text-3xl text-primary-400"></i>
                        <p className="mt-2 text-sm text-foreground-600">本轮无预审问题，标书已达标</p>
                      </li>
                    )}
                  </ul>
                </div>
              </div>
            </>
          )}

          {activeTab === "trend" && (
            <div className="rounded-lg border border-background-300 bg-background-100 p-5">
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
                  <i className="ri-line-chart-line text-primary-500"></i>
                  各轮预审分数与问题数趋势
                </div>
                <span className="font-label text-xs text-foreground-500">预审中锁定导出，回改后重跑验证效果</span>
              </div>
              {trend.length === 0 ? (
                <p className="py-10 text-center text-sm text-foreground-500">暂无历史轮次数据</p>
              ) : (
                <>
                  <div className="flex items-end justify-around gap-4 px-2 pt-6">
                    {trend.map((d) => (
                      <div key={d.round} className="flex flex-col items-center gap-2">
                        <span className="font-heading text-sm font-bold text-foreground-700">{d.score}</span>
                        <div
                          className={`w-16 rounded-t-md bg-gradient-to-t transition-all ${
                            d.score === maxTrendScore ? "from-primary-500 to-primary-400" : "from-secondary-400 to-secondary-300"
                          }`}
                          style={{ height: `${(d.score / maxTrendScore) * 140}px` }}
                        />
                        <span className="font-label text-xs text-foreground-600">第{d.round}轮</span>
                        <span className="text-[11px] text-foreground-500">{d.issues} 个问题</span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-4 text-xs text-foreground-500">
                    说明：每轮「预审 + 回改」形成快照，可对比第 N 轮与第 N+1 轮报告，观察回改是否生效。
                  </p>
                </>
              )}
            </div>
          )}

          {activeTab === "report" && (
            <PreReviewReport
              projectName={currentProject.name}
              projectCode={currentProject.code}
              levels={report.levels}
              issues={report.issues}
              dimensions={report.dimensions}
              overall={report.overall}
              round={report.round}
              exporting={exporting}
              onExport={() => { if (!exporting) void exportReport(); }}
              onCopy={() => { void copyReportSummary(); }}
            />
          )}
        </>
      )}

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
        </>
      )}
    </div>
  );
}
