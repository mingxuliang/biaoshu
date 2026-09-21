import { useEffect, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Toast from "../components/Toast";
import ProgressRing from "../components/ProgressRing";
import PreReviewReport, { CustomRulesReviewBlock } from "./components/PreReviewReport";
import TenderRuleReportView from "./components/TenderRuleReport";
import DocumentSourceGate, { type PreReviewDoc, type PreReviewDocs } from "./components/DocumentSourceGate";
import ProjectSelectionGate from "../components/ProjectSelectionGate";
import { useProjects } from "@/context/ProjectContext";
import {
  ApiError,
  createPrereviewJob,
  exportLatestReviewReport,
  getBidDocument,
  getLatestReviewPair,
  getReviewRunTrend,
  pollJobUntilDone,
  triggerFileDownload,
  type BidScope,
  type ReviewReport,
  type ReviewReportPair,
  type TrendPoint,
} from "@/lib/api";
import { issueChapter, issueRuleKind, issueRuleLabel, NO_BID_EXCERPT_HINT, splitBidAndTender, type IssueRuleKind } from "@/lib/excerpt";

type TabKey = "result" | "trend" | "report" | "tender";

const tabs: { key: TabKey; label: string; icon: string }[] = [
  { key: "result", label: "预审结果", icon: "ri-file-shield-2-line" },
  { key: "trend", label: "历史趋势", icon: "ri-line-chart-line" },
  { key: "report", label: "青天预审报告", icon: "ri-file-chart-line" },
  { key: "tender", label: "招标规则预审报告", icon: "ri-auction-line" },
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

function formatDocSize(bytes: number): string {
  if (!bytes) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

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
  const [issueKind, setIssueKind] = useState<IssueRuleKind>("tender");
  const [reviewing, setReviewing] = useState(false);
  const [secondReviewing, setSecondReviewing] = useState(false);
  const [docs, setDocs] = useState<PreReviewDocs | null>(null);
  const [reports, setReports] = useState<ReviewReportPair>({ business: null, tech: null, full: null });
  const reportScope: "business" | "tech" = searchParams.get("scope") === "tech" ? "tech" : "business";
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });
  const [exporting, setExporting] = useState(false);
  const [loadingReport, setLoadingReport] = useState(false);

  const hasDocs = !!(docs?.business || docs?.tech);
  const bizReport = docs?.business ? reports.business : null;
  const techReport = docs?.tech ? reports.tech : null;
  const activeReport = reportScope === "business" ? bizReport : techReport;
  const report = bizReport || techReport;
  const view = activeReport;
  const busy = reviewing || secondReviewing;
  const scopeLevelKeys = reportScope === "business" ? ["L1", "L2"] : ["L3", "L4", "L5"];
  const resultIssues = (view?.issues || []).filter(
    (issue) =>
      scopeLevelKeys.includes(issue.level) ||
      (issue.rule || "").startsWith("自定义规则") ||
      (issue.location || "").startsWith("自定义规则"),
  );
  const tenderIssues = resultIssues.filter((issue) => issueRuleKind(issue) === "tender");
  const reviewIssues = resultIssues.filter((issue) => issueRuleKind(issue) === "review");
  const listedIssues = issueKind === "tender" ? tenderIssues : reviewIssues;

  useEffect(() => {
    const bidDocumentId = searchParams.get("bidDocumentId");
    if (!bidDocumentId) return;
    let cancelled = false;
    getBidDocument(bidDocumentId)
      .then((d) => {
        if (cancelled) return;
        const base = (slot: "business" | "tech"): PreReviewDoc => ({
          kind: "existing",
          name: d.filename,
          source: "修改闭环二次评审",
          size: formatDocSize(d.sizeBytes),
          updated: "刚刚",
          bidDocumentId: d.id,
          slot,
          docKind: d.kind || "combined",
        });
        if (d.kind === "business") setDocs({ business: base("business") });
        else if (d.kind === "tech") setDocs({ tech: base("tech") });
        else setDocs({ business: base("business"), tech: base("tech") });
      })
      .catch(() => {
        if (!cancelled) {
          setDocs({
            tech: {
              kind: "existing",
              name: "投标书修改版（来自修改闭环）",
              source: "修改闭环二次评审",
              size: "-",
              updated: "刚刚",
              bidDocumentId,
              slot: "tech",
              docKind: "combined",
            },
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [searchParams]);

  // 进入页面/切换项目/确定预审文件后，先尝试读取该项目已完成的最新一轮预审结果，
  // 而不是每次都要求手动点「发起分册预审」才能看到上次跑的结果；
  // 只有真正需要新一轮结论（如回改后二次评审）时才会调用 runPrereview 重新起任务。
  useEffect(() => {
    if (!currentProject || !hasDocs) return;
    let cancelled = false;
    setLoadingReport(true);
    setReports({ business: null, tech: null, full: null });
    (async () => {
      try {
        const pair = await getLatestReviewPair(currentProject.id);
        if (!cancelled) {
          setReports(pair);
        }
      } catch {
        // 暂无已完成预审
      } finally {
        if (!cancelled) setLoadingReport(false);
      }
      try {
        const trendPoints = await getReviewRunTrend(currentProject.id);
        if (!cancelled) setTrend(trendPoints);
      } catch {
        // 趋势加载失败不阻塞主流程
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentProject?.id, docs?.business?.bidDocumentId, docs?.tech?.bidDocumentId, hasDocs]);

  useEffect(() => {
    if (!docs) return;
    if (reportScope === "business" && !docs.business && docs.tech) setReportScope("tech");
    else if (reportScope === "tech" && !docs.tech && docs.business) setReportScope("business");
  }, [docs, reportScope]);

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const setReportScope = (scope: "business" | "tech") => {
    const next = new URLSearchParams(searchParams);
    next.set("scope", scope);
    setSearchParams(next, { replace: true });
  };

  const selectProject = (id: string) => {
    const next = new URLSearchParams();
    next.set("project", id);
    next.set("scope", reportScope);
    setSearchParams(next);
  };

  const goBackToList = () => setSearchParams({}, { replace: true });

  const refreshTrend = async (projectId: string) => {
    try {
      setTrend(await getReviewRunTrend(projectId));
    } catch {
      // 趋势加载失败不阻塞主流程
    }
  };

  const runPrereview = async (kind: "first" | "second", onlySlot?: "business" | "tech") => {
    if (!currentProject || !hasDocs || !docs) return;
    const setBusy = kind === "first" ? setReviewing : setSecondReviewing;
    let jobs: { scope: BidScope; doc: PreReviewDoc; slot: "business" | "tech" }[] = [];
    if (docs.business) jobs.push({ scope: "business", doc: docs.business, slot: "business" });
    if (docs.tech) jobs.push({ scope: "tech", doc: docs.tech, slot: "tech" });
    if (onlySlot) jobs = jobs.filter((j) => j.slot === onlySlot);
    if (!jobs.length) return;
    setBusy(true);
    showToast(`正在分册预审：${jobs.map((j) => (j.scope === "tech" ? "技术标" : "商务标")).join("、")}…`, "info");
    try {
      const results = await Promise.all(
        jobs.map(async (job) => {
          const created = await createPrereviewJob(currentProject.id, job.doc.bidDocumentId, job.scope);
          return pollJobUntilDone(created.job_id, { intervalMs: 2500, timeoutMs: 30 * 60 * 1000 });
        }),
      );
      const failed = results.find((r) => r.status === "failed");
      if (failed) {
        showToast(`预审失败：${failed.error ?? "未知错误"}`, "error");
      }
      const pair = await getLatestReviewPair(currentProject.id);
      setReports(pair);
      await refreshTrend(currentProject.id);
      const parts = [
        pair.business ? `商务 ${pair.business.overall} 分` : "",
        pair.tech ? `技术 ${pair.tech.overall} 分` : "",
      ].filter(Boolean);
      showToast(`分册预审完成：${parts.join("；") || "已生成报告"}`);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "预审任务执行异常，请重试", "error");
    } finally {
      setBusy(false);
    }
  };

  const startReview = () => {
    if (busy || !hasDocs) return;
    void runPrereview("first", reportScope);
  };

  const startSecondReview = () => {
    if (busy || !hasDocs || !view) return;
    void runPrereview("second", reportScope);
  };

  const changeDocument = () => {
    setDocs(null);
    setReports({ business: null, tech: null, full: null });
  };

  const bookletTrend = trend.filter((d) => (d.scope || reportScope) === reportScope);
  const maxTrendScore = bookletTrend.length ? Math.max(...bookletTrend.map((d) => d.score), 1) : 100;
  const levelScore = (key: string) => view?.levels.find((lv) => lv.key === key)?.score ?? 0;
  const scoreFormula =
    reportScope === "business"
      ? `L1 ${levelScore("L1")}×40% + L2 ${levelScore("L2")}×60%`
      : `L3 ${levelScore("L3")}×55% + L4 ${levelScore("L4")}×25% + L5 ${levelScore("L5")}×20%`;
  const prevTrendPoint = bookletTrend.length >= 2 ? bookletTrend[bookletTrend.length - 2] : null;
  const exportReady = !!view && view.overall >= 90 && view.waste === 0;

  const exportReport = async (scope?: BidScope) => {
    const usedScope: BidScope = scope === "tech" || reportScope === "tech" ? "tech" : "business";
    const target = usedScope === "tech" ? techReport : bizReport;
    if (!currentProject || !target) return;
    setExporting(true);
    const label = usedScope === "tech" ? "技术标" : "商务标";
    showToast(`正在导出${label}第 ${target.round} 轮预审报告…`, "info");
    try {
      const blob = await exportLatestReviewReport(currentProject.id, usedScope);
      triggerFileDownload(blob, `${currentProject.code || currentProject.name}-${label}-第${target.round}轮-预审报告.docx`);
      showToast("预审报告已开始下载");
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "导出报告失败，请稍后重试", "error");
    } finally {
      setExporting(false);
    }
  };

  const copyReportSummary = async () => {
    const target = activeReport || report;
    if (!target || !currentProject) return;
    const lines = [
      `${target.scope === "tech" ? "技术标" : "商务标"}预审报告 · ${currentProject.name}（${currentProject.code}）`,
      `第 ${target.round} 轮 · 本册得分 ${target.overall} · 风险灯 ${target.light}`,
      `废标 ${target.waste} 项 · 扣分 ${target.risk} 项 · 建议 ${target.suggest} 项`,
      ...(target.levels || []).map((lv) => `${lv.key} ${lv.name}：${lv.score} 分，${lv.issues} 项，${lv.status}`),
      "",
      "问题摘要：",
      ...target.issues.slice(0, 20).map((issue, i) => {
        const { excerpt } = splitBidAndTender(issue.excerpt, issue.tenderQuote, issue.rule);
        return `${i + 1}. [${issue.severity}] ${issueRuleLabel(issue)} @ ${issueChapter(issue.location) || issue.location}：${excerpt || NO_BID_EXCERPT_HINT}`;
      }),
      ...(target.customRules || []).length
        ? [
            "",
            "自定义规则对照：",
            ...(target.customRules || []).map(
              (rule, i) =>
                `${i + 1}. [${rule.status}] ${rule.title}（${rule.severity} · ${rule.sourceLabel || "—"}）：${rule.reason || ""}`,
            ),
          ]
        : [],
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
        actions={hasDocs ? (
          <>
            <button
              type="button"
              onClick={startReview}
              disabled={busy}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <i className={`${reviewing ? "ri-loader-4-line animate-spin" : "ri-shield-flash-line"} text-sm`}></i>
              {reviewing ? "预审中…" : reportScope === "tech" ? "预审技术标" : "预审商务标"}
            </button>
            <button
              type="button"
              onClick={startSecondReview}
              disabled={busy || !view}
              title={!view ? "请先完成当前分册预审，回改标书后再发起二次评审" : undefined}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <i className={`${secondReviewing ? "ri-loader-4-line animate-spin" : "ri-refresh-line"} text-sm`}></i>
              {secondReviewing ? "二次评审中…" : "对修改后标书发起二次评审"}
            </button>
          </>) : undefined}
      />

      {/* 未选择文件：先选择预审投标文件 */}
      {!hasDocs ? (
        <DocumentSourceGate
          projectId={currentProject.id}
          projectName={currentProject.name}
          projectCode={currentProject.code}
          onContinue={setDocs}
        />
      ) : (
        <>
          <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {(["business", "tech"] as const).map((slot) => {
              const item = docs?.[slot];
              const active = reportScope === slot;
              return (
                <button
                  key={slot}
                  type="button"
                  disabled={!item}
                  onClick={() => item && setReportScope(slot)}
                  className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-left transition-colors ${
                    active ? "border-primary-300 bg-primary-50/50" : "border-background-300 bg-background-100"
                  } ${item ? "cursor-pointer" : "cursor-not-allowed opacity-60"}`}
                >
                  <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${
                    slot === "business" ? "bg-accent-50 text-accent-600" : "bg-primary-50 text-primary-600"
                  }`}>
                    <i className={`${slot === "business" ? "ri-briefcase-line" : "ri-tools-line"} text-base`}></i>
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-[11px] text-foreground-500">{slot === "business" ? "商务标" : "技术标"}</div>
                    <div className="truncate text-sm font-medium text-foreground-900">{item?.name || "未能上传该类型文件"}</div>
                  </div>
                  {item && <span className="shrink-0 text-[11px] text-foreground-500">{item.size}</span>}
                </button>
              );
            })}
          </div>
          <div className="mb-4 flex justify-end">
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
              {view ? ` · ${reportScope === "tech" ? "技术标" : "商务标"}第 ${view.round} 轮` : " · 尚未运行预审"}
            </div>
          </div>
          {view && (
            <div className="ml-2 flex items-center gap-1.5 rounded-lg bg-background-50 px-3 py-1.5">
              <span className="relative flex h-2 w-2">
                <span
                  className="absolute inline-flex h-full w-full rounded-full opacity-50 animate-ping"
                  style={{ backgroundColor: lightColor[view.light] }}
                />
                <span className="relative inline-flex h-2 w-2 rounded-full" style={{ backgroundColor: lightColor[view.light] }} />
              </span>
              <span className="font-label text-xs font-semibold" style={{ color: lightColor[view.light] }}>
                风险灯 · {view.light}
              </span>
            </div>
          )}
        </div>
        <select
          value={reportScope}
          onChange={(e) => setReportScope(e.target.value as "business" | "tech")}
          className="h-8 w-full cursor-pointer rounded-md border border-primary-300 bg-background-50 px-2.5 text-xs font-medium text-foreground-800 outline-none focus:border-primary-400 sm:w-auto sm:min-w-[200px]"
        >
          <option value="business" disabled={!docs?.business}>
            商务标{bizReport ? ` · ${bizReport.overall} 分` : ""}
          </option>
          <option value="tech" disabled={!docs?.tech}>
            技术标{techReport ? ` · ${techReport.overall} 分` : ""}
          </option>
        </select>
      </div>

      {(docs?.business?.source === "修改闭环二次评审" || docs?.tech?.source === "修改闭环二次评审") && (
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
      {view && view.round > 1 && prevTrendPoint && (
        <div className="mb-4 flex flex-col gap-3 rounded-lg border border-primary-300 bg-primary-50/50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
            <span className="font-label flex items-center gap-1.5 text-foreground-600">
              {reportScope === "business" ? "商务标" : "技术标"}相比第 {prevTrendPoint.round} 轮：
            </span>
            <span className="font-label flex items-center gap-1 text-foreground-600">
              本册得分 <span className="font-heading text-sm font-bold text-foreground-900">{prevTrendPoint.score}</span>
              <i className="ri-arrow-right-line text-primary-500"></i>
              <span className="font-heading text-sm font-bold text-primary-600">{view.overall}</span>
              <span className="rounded bg-primary-100 px-1.5 py-0.5 text-[10px] font-medium text-primary-600">
                {view.overall - prevTrendPoint.score >= 0 ? "+" : ""}
                {Math.round((view.overall - prevTrendPoint.score) * 10) / 10}
              </span>
            </span>
            <span className="font-label flex items-center gap-1 text-foreground-600">
              问题数 <span className="font-heading text-sm font-bold text-foreground-900">{prevTrendPoint.issues}</span>
              <i className="ri-arrow-right-line text-primary-500"></i>
              <span className="font-heading text-sm font-bold text-primary-600">{view.waste + view.risk + view.suggest}</span>
            </span>
          </div>
          <span className="font-label shrink-0 rounded-md bg-primary-500 px-2.5 py-1 text-[11px] font-semibold text-background-50">
            第 {view.round} 轮 · 最新评审
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

      {loadingReport ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-background-300 bg-background-100 px-6 py-16 text-center">
          <i className="ri-loader-4-line animate-spin text-2xl text-primary-500"></i>
          <p className="text-sm font-medium text-foreground-800">正在读取上次预审结果…</p>
        </div>
      ) : !report ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-background-300 bg-background-100 px-6 py-16 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-primary-50 text-primary-500">
            <i className="ri-shield-flash-line text-2xl"></i>
          </span>
          <p className="text-sm font-medium text-foreground-800">尚未运行分册预审</p>
          <p className="max-w-md text-xs text-foreground-500">
            点击右上角「预审商务标 / 预审技术标」。商务标只评 L1+L2，技术标只评 L3–L5，两册各自满分 100，互不加权。
          </p>
        </div>
      ) : (
        <>
          {activeTab === "result" && (
            <>
              {/* 当前分册得分 */}
              <div className="mb-4 flex flex-col gap-3 rounded-lg border border-primary-200 bg-primary-50/30 p-3.5 sm:flex-row sm:items-center">
                {view ? (
                  <ProgressRing value={view.overall} size={72} stroke={6} />
                ) : (
                  <span className="flex h-[72px] w-[72px] items-center justify-center rounded-full border border-dashed border-background-300 text-[11px] text-foreground-400">
                    {docs?.[reportScope] ? "未预审" : "未上传"}
                  </span>
                )}
                <div className="min-w-0 flex-1">
                  <div className="font-label text-[11px] text-foreground-500">
                    {reportScope === "business" ? "商务标得分" : "技术标得分"} · 满分 100 · 不与另一册加权
                  </div>
                  <div className="font-heading text-gradient text-2xl font-bold">{view ? view.overall : "—"}</div>
                  {view && (
                    <>
                      <div className="text-[11px] text-foreground-500">
                        第 {view.round} 轮 · 灯 {view.light} · 废标 {view.waste} · 扣分 {view.risk} · 建议 {view.suggest}
                      </div>
                      <div className="mt-1 text-[11px] text-foreground-500">计分：{scoreFormula}</div>
                    </>
                  )}
                  {docs?.[reportScope] && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => { if (!busy) void runPrereview("first", reportScope); }}
                      className="mt-1 inline-flex cursor-pointer items-center gap-0.5 text-[11px] text-primary-600 hover:underline disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      单独再审此册
                    </button>
                  )}
                </div>
              </div>

              {view ? (
              <>
              <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
                <div className="flex items-center gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-accent-50 text-accent-600">
                    <i className="ri-close-circle-line text-xl"></i>
                  </span>
                  <div>
                    <div className="font-label text-[11px] text-foreground-500">当前分册废标项</div>
                    <div className="font-heading text-gradient text-lg font-bold">{view.waste}</div>
                  </div>
                </div>
                <div className="flex items-center gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-secondary-100 text-secondary-600">
                    <i className="ri-error-warning-line text-xl"></i>
                  </span>
                  <div>
                    <div className="font-label text-[11px] text-foreground-500">扣分 / 建议项</div>
                    <div className="font-heading text-gradient text-lg font-bold">{view.risk} + {view.suggest}</div>
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
                      {reportScope === "business" ? "L1-L2 商务分册" : "L3-L5 技术分册"} · 第 {view.round} 轮
                    </div>
                  </div>
                  <ul className="divide-y divide-background-200">
                    {view.levels.filter((level) => (reportScope === "business" ? ["L1", "L2"] : ["L3", "L4", "L5"]).includes(level.key)).map((level) => (
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

                {/* 五维打分 / 本册计分 */}
                <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
                  <div className="border-b border-background-300 bg-background-50 px-4 py-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
                      <i className={`${reportScope === "business" ? "ri-percent-line" : "ri-focus-3-line"} text-primary-500`}></i>
                      {reportScope === "business" ? "商务标计分说明" : `技术标五维打分 · 第 ${view.round} 轮`}
                    </div>
                  </div>
                  {reportScope === "business" ? (
                    <ul className="divide-y divide-background-200">
                      <li className="flex items-center justify-between px-4 py-3 text-sm">
                        <span className="text-foreground-700">L1 一票否决</span>
                        <span className="font-heading font-bold text-foreground-900">{levelScore("L1")} × 40%</span>
                      </li>
                      <li className="flex items-center justify-between px-4 py-3 text-sm">
                        <span className="text-foreground-700">L2 商务核验</span>
                        <span className="font-heading font-bold text-foreground-900">{levelScore("L2")} × 60%</span>
                      </li>
                      <li className="px-4 py-3 text-xs leading-relaxed text-foreground-500">
                        商务标满分 100，只评 L1+L2，不与技术标加权。当前 {view.overall} = {scoreFormula}。
                      </li>
                    </ul>
                  ) : (
                  <ul className="divide-y divide-background-200">
                    {!(view.dimensions || []).length ? (
                      <li className="px-4 py-8 text-center text-xs text-foreground-500">
                        本册暂无五维得分。
                      </li>
                    ) : view.dimensions.map((dim) => (
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
                    <li className="px-4 py-3 text-xs leading-relaxed text-foreground-500">
                      技术标满分 100，只评 L3+L4+L5，不与商务标加权。当前 {view.overall} = {scoreFormula}。
                    </li>
                  </ul>
                  )}
                </div>

                {/* 预审报告问题 */}
                <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100 lg:max-h-[420px] lg:overflow-y-auto">
                  <div className="sticky top-0 border-b border-background-300 bg-background-50 px-4 py-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
                        <i className="ri-file-list-3-line text-primary-500"></i>
                        预审问题清单 · 第 {view.round} 轮
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="inline-flex rounded-lg border border-background-300 bg-background-100 p-0.5">
                          {([
                            ["tender", "招标问题", tenderIssues.length],
                            ["review", "预审规则问题", reviewIssues.length],
                          ] as const).map(([key, label, count]) => (
                            <button
                              key={key}
                              type="button"
                              onClick={() => setIssueKind(key)}
                              className={`cursor-pointer rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
                                issueKind === key
                                  ? "bg-gradient-to-r from-primary-500 to-primary-600 text-background-50"
                                  : "text-foreground-600 hover:text-foreground-900"
                              }`}
                            >
                              {label} · {count}
                            </button>
                          ))}
                        </div>
                        <Link
                          to={`/console/review?project=${currentProject.id}&scope=${reportScope}`}
                          className="flex h-7 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md bg-primary-500 px-2.5 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
                        >
                          去修改
                          <i className="ri-arrow-right-line"></i>
                        </Link>
                      </div>
                    </div>
                  </div>
                  <ul className="divide-y divide-background-200">
                    {listedIssues.map((issue) => {
                      const { excerpt } = splitBidAndTender(issue.excerpt, issue.tenderQuote, issue.rule);
                      const ruleLabel = issueRuleLabel(issue);
                      return (
                      <li key={issue.id}>
                        <Link
                          to={`/console/review?project=${currentProject.id}&scope=${reportScope}&issue=${issue.id}`}
                          className="block cursor-pointer px-4 py-3 transition-colors hover:bg-primary-50/60"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className={`inline-flex items-center whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${severityStyle[issue.severity]}`}>
                              {issue.severity}
                            </span>
                            <span className="font-label text-[10px] text-foreground-500">{issue.level} · {issueChapter(issue.location) || "未标注章节"}</span>
                          </div>
                          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 rounded-md border border-accent-200 bg-accent-50 px-2 py-1.5">
                            <span className="inline-flex items-center gap-0.5 rounded bg-accent-500 px-1.5 py-0.5 text-[10px] font-semibold text-background-50">
                              命中规则
                            </span>
                            <span className="text-xs font-semibold leading-snug text-accent-800">{ruleLabel}</span>
                          </div>
                          <p className="mt-1.5 text-xs leading-relaxed text-foreground-700">
                            {excerpt ? `「${excerpt}」` : NO_BID_EXCERPT_HINT}
                          </p>
                          <p className="mt-1 text-[11px] text-foreground-500">建议：{issue.suggestion}</p>
                          <p className="mt-1.5 text-[11px] text-primary-600">点击定位到修改闭环原文 →</p>
                        </Link>
                      </li>
                      );
                    })}
                    {listedIssues.length === 0 && (
                      <li className="px-4 py-10 text-center">
                        {resultIssues.length === 0 && (view.waste + view.risk + view.suggest > 0 || view.overall < 90) ? (
                          <>
                            <i className="ri-error-warning-line text-3xl text-accent-400"></i>
                            <p className="mt-2 text-sm text-foreground-600">分层得分已扣分，问题明细未写入。请重新发起预审。</p>
                          </>
                        ) : resultIssues.length === 0 ? (
                          <>
                            <i className="ri-checkbox-circle-line text-3xl text-primary-400"></i>
                            <p className="mt-2 text-sm text-foreground-600">本轮无预审问题，标书已达标</p>
                          </>
                        ) : (
                          <>
                            <i className="ri-file-list-3-line text-3xl text-foreground-300"></i>
                            <p className="mt-2 text-sm text-foreground-600">
                              {issueKind === "tender" ? "当前暂无招标问题" : "当前暂无预审规则问题"}
                            </p>
                          </>
                        )}
                      </li>
                    )}
                  </ul>
                </div>
              </div>

              {/* 技术评分模块逐项核验：与规则页「技术评分」tab 一一对应 */}
              {reportScope === "tech" && view.techModules && view.techModules.length > 0 && (
                <div className="mt-3 overflow-hidden rounded-lg border border-background-300 bg-background-100">
                  <div className="border-b border-background-300 bg-background-50 px-4 py-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
                      <i className="ri-cpu-line text-primary-500"></i>
                      技术评分模块核验 · 第 {view.round} 轮
                    </div>
                  </div>
                  <ul className="grid grid-cols-1 divide-y divide-background-200 sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4">
                    {view.techModules.map((m) => (
                      <li key={m.key} className="border-b border-background-200 px-4 py-3 sm:border-b-0 sm:border-r sm:last:border-r-0 lg:[&:nth-child(4n)]:border-r-0">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-medium text-foreground-900">{m.module}</span>
                          <span
                            className={`font-label whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium ${
                              m.status === "达标"
                                ? "bg-primary-50 text-primary-600"
                                : m.status === "建议" || m.status === "无法比对"
                                  ? "bg-secondary-100 text-secondary-600"
                                  : "bg-accent-50 text-accent-600"
                            }`}
                          >
                            {m.status}
                          </span>
                        </div>
                        <div className="mt-1 flex items-baseline gap-1">
                          <span className="font-heading text-sm font-bold text-foreground-900">{m.score}</span>
                          <span className="text-[11px] text-foreground-500">/ 满分 {m.maxScore} 分</span>
                        </div>
                        <p className="mt-1 text-[11px] leading-relaxed text-foreground-500">{m.summary}</p>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="mt-3 overflow-hidden rounded-lg border border-background-300 bg-background-100">
                <div className="border-b border-background-300 bg-background-50 px-4 py-3">
                  <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
                    <i className="ri-list-check-3 text-primary-500"></i>
                    自定义规则对照 · 第 {view.round} 轮
                  </div>
                </div>
                <div className="px-4 py-3">
                  <CustomRulesReviewBlock rules={view.customRules} />
                </div>
              </div>
              </>
              ) : (
                <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-background-300 bg-background-100 px-6 py-12 text-center">
                  <p className="text-sm font-medium text-foreground-800">
                    {reportScope === "business" ? "商务标" : "技术标"}尚未预审
                  </p>
                  <p className="text-xs text-foreground-500">
                    {docs?.[reportScope] ? "可使用右上角「预审」按钮审当前分册。" : "未能上传该类型文件。"}
                  </p>
                </div>
              )}
            </>
          )}

          {activeTab === "trend" && (
            <div className="rounded-lg border border-background-300 bg-background-100 p-5">
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
                  <i className="ri-line-chart-line text-primary-500"></i>
                  各轮{reportScope === "business" ? "商务标" : "技术标"}分数与问题数趋势
                </div>
                <span className="font-label text-xs text-foreground-500">预审中锁定导出，回改后重跑验证效果</span>
              </div>
              {bookletTrend.length === 0 ? (
                <p className="py-10 text-center text-sm text-foreground-500">当前分册暂无历史轮次数据</p>
              ) : (
                <>
                  <div className="flex items-end justify-around gap-4 px-2 pt-6">
                    {bookletTrend.map((d) => (
                      <div key={`${d.scope || reportScope}-${d.round}`} className="flex flex-col items-center gap-2">
                        <span className="font-heading text-sm font-bold text-foreground-700">{d.score}</span>
                        <div
                          className={`w-16 rounded-t-md bg-gradient-to-t transition-all ${
                            d.score === maxTrendScore ? "from-primary-500 to-primary-400" : "from-secondary-400 to-secondary-300"
                          }`}
                          style={{ height: `${(d.score / maxTrendScore) * 140}px` }}
                        />
                        <span className="font-label text-xs text-foreground-600">
                          {reportScope === "business" ? "商务" : "技术"}·第{d.round}轮
                        </span>
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
            <div>
              {view ? (
              <PreReviewReport
                projectName={currentProject.name}
                projectCode={currentProject.code}
                levels={view.levels}
                issues={view.issues}
                dimensions={view.dimensions}
                techModules={view.techModules}
                overall={view.overall}
                round={view.round}
                waste={view.waste}
                risk={view.risk}
                suggest={view.suggest}
                scope={reportScope}
                tenderRules={view.tenderRules}
                customRules={view.customRules}
                exporting={exporting}
                onExport={() => { if (!exporting) void exportReport((view.scope as BidScope) || reportScope); }}
                onCopy={() => { void copyReportSummary(); }}
              />
              ) : (
                <p className="rounded-lg border border-dashed border-background-300 bg-background-100 px-4 py-10 text-center text-sm text-foreground-500">
                  当前分册暂无预审报告。
                </p>
              )}
            </div>
          )}

          {activeTab === "tender" && (
            view ? (
            <TenderRuleReportView
              projectName={currentProject.name}
              projectCode={currentProject.code}
              round={view.round}
              data={view.tenderRules}
            />
            ) : (
              <p className="rounded-lg border border-dashed border-background-300 bg-background-100 px-4 py-10 text-center text-sm text-foreground-500">
                当前分册暂无招标规则预审结果。
              </p>
            )
          )}
        </>
      )}

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
        </>
      )}
    </div>
  );
}
