import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Toast from "../components/Toast";
import ProgressRing from "../components/ProgressRing";
import DuplicateReport from "./components/DuplicateReport";
import { ApiError, runDuplicateCheck, type DuplicateCheckReport } from "@/lib/api";
import {
  clearDuplicateReport,
  loadDuplicateReport,
  saveDuplicateReport,
  type DuplicateUploadState,
} from "./session";

type TabKey = "result" | "report";

const tabs: { key: TabKey; label: string; icon: string }[] = [
  { key: "result", label: "分析结果", icon: "ri-file-shield-2-line" },
  { key: "report", label: "查重报告", icon: "ri-file-chart-line" },
];

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

function isUploadState(value: unknown): value is DuplicateUploadState {
  if (!value || typeof value !== "object") return false;
  const rec = value as Record<string, unknown>;
  return rec.fileA instanceof File && rec.fileB instanceof File;
}

export default function DuplicateResultPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const incoming = isUploadState(location.state) ? location.state : null;
  const [report, setReport] = useState<DuplicateCheckReport | null>(() => (incoming ? null : loadDuplicateReport()));
  const [analyzing, setAnalyzing] = useState(() => !!incoming);
  const [activeTab, setActiveTab] = useState<TabKey>("result");
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });
  const started = useRef(false);
  const incomingRef = useRef(incoming);
  incomingRef.current = incoming;

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const run = async (fileA: File, fileB: File) => {
    setAnalyzing(true);
    setReport(null);
    try {
      const next = await runDuplicateCheck(fileA, fileB);
      saveDuplicateReport(next);
      setReport(next);
      setActiveTab("result");
      showToast(`查重完成，风险灯 ${next.light}，整体相似度 ${next.wholePct}%`);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "查重失败，请稍后重试";
      showToast(message, "error");
      window.setTimeout(() => navigate("/console/duplicate", { replace: true }), 1200);
    } finally {
      setAnalyzing(false);
    }
  };

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const files = incomingRef.current;
    if (files) {
      void run(files.fileA, files.fileB);
      return;
    }
    if (!loadDuplicateReport()) {
      navigate("/console/duplicate", { replace: true });
    }
    // 仅在进入结果页时跑一次：有上传文件则比对，否则读上次结果或退回上传页。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigate]);

  const copyReport = async () => {
    if (!report) return;
    const lines = [
      `技术标查重报告 · ${report.fileA.name} ↔ ${report.fileB.name}`,
      `整体 ${report.wholePct}% · 段落 ${report.paragraphPct}% · 灯 ${report.light}`,
      report.conclusion,
      "",
      "阈值对照：",
      ...report.checks.map((c) => {
        const val = c.applicable && c.value != null ? `${c.value}%` : "不适用";
        return `${c.label}：实测 ${val} / 青天 ${c.threshold}% · ${c.triggered ? `触发${c.severity}` : "未触发"}`;
      }),
    ];
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      showToast("查重报告摘要已复制到剪贴板");
    } catch {
      showToast("复制失败，请检查浏览器剪贴板权限", "error");
    }
  };

  const backToUpload = () => {
    clearDuplicateReport();
    navigate("/console/duplicate");
  };

  return (
    <div>
      <PageHeader
        title="查重结果"
        description="通读两份技术标全部抽出正文，对照青天查重阈值。更换文件请返回上传页重新比对。"
        actions={
          <button
            type="button"
            onClick={backToUpload}
            className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-4 text-sm font-medium text-foreground-700 transition-colors hover:bg-background-200"
          >
            <i className="ri-upload-cloud-2-line text-sm"></i>
            更换文件
          </button>
        }
      />

      {analyzing && (
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-background-300 bg-background-100 px-6 py-24 text-center">
          <i className="ri-loader-4-line animate-spin text-2xl text-primary-500"></i>
          <p className="text-sm font-medium text-foreground-800">正在通读两份技术标全文并对照青天阈值…</p>
          <p className="text-xs text-foreground-500">整体、段落与重难点均覆盖全部抽出正文，不审商务标。</p>
        </div>
      )}

      {report && !analyzing && (
        <>
          <div className="mb-4 flex flex-col gap-3 rounded-lg border border-background-300 bg-background-100 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-center gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-accent-400 to-accent-500 text-background-50">
                <i className="ri-file-copy-2-line text-lg"></i>
              </span>
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-foreground-900">
                  {report.fileA.name} ↔ {report.fileB.name}
                </div>
                <div className="text-[11px] text-foreground-500">仅技术标 · {report.method}</div>
              </div>
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
            </div>
          </div>

          <div className="mb-4 flex gap-1 overflow-x-auto rounded-lg border border-background-300 bg-background-100 p-1">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setActiveTab(tab.key)}
                className={`flex h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-md px-3 text-sm font-medium transition-colors ${
                  activeTab === tab.key
                    ? "bg-primary-50 text-primary-600"
                    : "text-foreground-600 hover:bg-background-200"
                }`}
              >
                <i className={`${tab.icon} text-sm`}></i>
                {tab.label}
              </button>
            ))}
          </div>

          {activeTab === "result" && (
            <>
              <div className="mb-4 flex flex-col gap-3 rounded-lg border border-primary-200 bg-primary-50/30 p-3.5 sm:flex-row sm:items-center">
                <ProgressRing
                  value={Math.round(report.wholePct)}
                  size={72}
                  stroke={6}
                  color={report.light === "绿" ? "primary" : "accent"}
                />
                <div className="min-w-0 flex-1">
                  <div className="font-label text-[11px] text-foreground-500">
                    整体相似度（全文）· 对照青天 30% / 42% 与跨项目 80%
                  </div>
                  <div className="font-heading text-gradient text-2xl font-bold">{report.wholePct}%</div>
                  <div className="text-[11px] text-foreground-500">
                    甲 {report.fileA.chars} 字 · 乙 {report.fileB.chars} 字 · 段落最高 {report.paragraphPct}% · 重难点{" "}
                    {report.keySectionPct == null ? "未适用" : `${report.keySectionPct}%`} · 降档 {report.waste} · 扣分{" "}
                    {report.risk}
                  </div>
                </div>
              </div>

              <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
                <StatCard icon="ri-close-circle-line" iconClass="bg-accent-50 text-accent-600" label="降档阈值" value={report.waste} />
                <StatCard icon="ri-error-warning-line" iconClass="bg-secondary-100 text-secondary-600" label="扣分阈值" value={report.risk} />
                <StatCard icon="ri-file-list-3-line" iconClass="bg-primary-50 text-primary-600" label="相似段落" value={report.issues.length} />
              </div>

              <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
                <div className="border-b border-background-300 bg-background-50 px-4 py-3">
                  <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
                    <i className="ri-scales-3-line text-primary-500"></i>
                    青天查重阈值对照
                  </div>
                </div>
                <ul className="divide-y divide-background-200">
                  {report.checks.map((item) => (
                    <li key={item.key} className="flex items-center gap-3 px-4 py-3">
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium text-foreground-900">{item.label}</div>
                        <div className="truncate text-[11px] text-foreground-500">{item.meaning}</div>
                      </div>
                      <div className="text-right">
                        <div
                          className={`font-heading text-sm font-bold ${
                            item.triggered ? "text-accent-600" : "text-gradient"
                          }`}
                        >
                          {item.applicable && item.value != null ? `${item.value}%` : "—"}
                        </div>
                        <div className="font-label text-[10px] text-foreground-500">
                          {item.triggered ? `触发${item.severity}` : item.applicable ? `线 ${item.threshold}%` : "不适用"}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}

          {activeTab === "report" && <DuplicateReport report={report} onCopy={() => void copyReport()} />}
        </>
      )}

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}

function StatCard({
  icon,
  iconClass,
  label,
  value,
}: {
  icon: string;
  iconClass: string;
  label: string;
  value: number;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5">
      <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-lg ${iconClass}`}>
        <i className={`${icon} text-xl`}></i>
      </span>
      <div>
        <div className="font-label text-[11px] text-foreground-500">{label}</div>
        <div className="font-heading text-gradient text-lg font-bold">{value}</div>
      </div>
    </div>
  );
}
