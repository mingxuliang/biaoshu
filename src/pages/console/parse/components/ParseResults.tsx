import { useState } from "react";
import type { Checklist } from "@/lib/api";

interface ParseResultsProps {
  checklist: Checklist | null;
  parsing: boolean;
  locking: boolean;
  onLock: () => void;
  onShare: () => void;
  onDownload: () => void;
}

type TabKey = "scoreRules" | "mustRespond" | "qualification" | "formatRequirements";

const TABS: { key: TabKey; label: string; icon: string }[] = [
  { key: "scoreRules", label: "评分规则", icon: "ri-percent-line" },
  { key: "mustRespond", label: "必响应/否决条款", icon: "ri-alarm-warning-line" },
  { key: "qualification", label: "资格要求", icon: "ri-award-line" },
  { key: "formatRequirements", label: "格式与暗标要求", icon: "ri-file-list-3-line" },
];

const levelStyle: Record<string, string> = {
  星号: "bg-accent-50 text-accent-600 border-accent-200",
  废标: "bg-red-50 text-red-500 border-red-200",
  强制: "bg-secondary-100 text-secondary-600 border-secondary-200",
  建议: "bg-primary-50 text-primary-600 border-primary-200",
  星号条款: "bg-accent-50 text-accent-600 border-accent-200",
  废标条款: "bg-red-50 text-red-500 border-red-200",
  实质性条款: "bg-primary-50 text-primary-600 border-primary-200",
};

export default function ParseResults({ checklist, parsing, locking, onLock, onShare, onDownload }: ParseResultsProps) {
  const [activeTab, setActiveTab] = useState<TabKey>("scoreRules");

  const hasChecklist = !!checklist && checklist.status === "done";
  const weightTotal = checklist?.scoreRules.reduce((sum, r) => sum + r.weight, 0) ?? 0;

  const renderEmpty = (text: string) => (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 px-4 py-16 text-center">
      <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-background-100 text-foreground-400">
        <i className={`${parsing ? "ri-loader-4-line animate-spin" : "ri-file-search-line"} text-xl`}></i>
      </span>
      <div className="text-sm font-medium text-foreground-700">{text}</div>
    </div>
  );

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-background-300 bg-background-100">
      {/* 顶部标签栏 */}
      <div className="shrink-0 border-b border-background-300 bg-background-50 px-3 py-2">
        <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-thin">
          {TABS.map((tab) => {
            const isActive = tab.key === activeTab;
            return (
              <button
                key={tab.key}
                type="button"
                onClick={() => setActiveTab(tab.key)}
                className={`flex shrink-0 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-medium transition-all ${
                  isActive
                    ? "bg-primary-500 text-background-50"
                    : "border border-background-300 bg-background-50 text-foreground-600 hover:bg-background-200"
                }`}
              >
                <i className={`${tab.icon} text-sm`}></i>
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* AI 提示条 */}
      <div className="shrink-0 flex items-center gap-2 border-b border-background-200/60 bg-background-50/60 px-4 py-2">
        <span className="flex h-5 w-5 items-center justify-center rounded bg-secondary-100 text-[10px] font-bold text-secondary-600">AI</span>
        <span className="text-[11px] text-foreground-500">以下内容由AI从招标文件正文中自动抽取，仅供参考，请仔细核对原文后再锁定</span>
        {checklist && (
          <span
            className={`font-label ml-auto shrink-0 rounded px-1.5 py-0.5 text-[10px] ${
              checklist.locked ? "bg-secondary-100 text-secondary-700" : "bg-background-200 text-foreground-500"
            }`}
          >
            {checklist.locked ? `已锁定 v${checklist.version}` : `草稿 v${checklist.version}`}
          </span>
        )}
      </div>

      {/* 内容区 */}
      <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
        {!hasChecklist ? (
          renderEmpty(parsing ? "AI 正在解析招标文件，请稍候…" : "请先在上方上传招标文件并发起解析")
        ) : checklist?.error && !checklist.scoreRules.length && !checklist.mustRespond.length ? (
          renderEmpty(checklist.error)
        ) : (
          <>
            {activeTab === "scoreRules" &&
              (checklist!.scoreRules.length ? (
                <table className="w-full border-collapse text-[13px]">
                  <thead>
                    <tr className="bg-background-100 text-foreground-600">
                      <th className="border border-background-200 px-2.5 py-2 text-left font-medium">评分维度</th>
                      <th className="w-16 border border-background-200 px-2 py-2 text-center font-medium">分值</th>
                      <th className="border border-background-200 px-2.5 py-2 text-left font-medium">评分细则</th>
                      <th className="w-28 border border-background-200 px-2 py-2 text-left font-medium">原文定位</th>
                    </tr>
                  </thead>
                  <tbody>
                    {checklist!.scoreRules.map((r) => (
                      <tr key={r.id} className="align-top">
                        <td className="border border-background-200 px-2.5 py-2">
                          <div className="font-medium text-foreground-900">{r.dimension}</div>
                          {r.isEssential && (
                            <span className="font-label mt-0.5 inline-block rounded bg-accent-50 px-1.5 py-0.5 text-[10px] text-accent-600">必响应</span>
                          )}
                        </td>
                        <td className="border border-background-200 px-2 py-2 text-center font-semibold text-primary-600">{r.weight}</td>
                        <td className="border border-background-200 px-2.5 py-2 text-foreground-700">{r.detail}</td>
                        <td className="border border-background-200 px-2 py-2 text-[11px] text-foreground-400">{r.sectionPath}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td colSpan={4} className="border border-background-200 bg-background-100/60 px-2.5 py-1.5 text-[12px] text-foreground-500">
                        权重合计 {weightTotal} 分 · 共 {checklist!.scoreRules.length} 条评分规则
                      </td>
                    </tr>
                  </tfoot>
                </table>
              ) : (
                renderEmpty("未从招标文件中抽取到评分规则")
              ))}

            {activeTab === "mustRespond" &&
              (checklist!.mustRespond.length ? (
                <ul className="space-y-2">
                  {checklist!.mustRespond.map((m) => (
                    <li key={m.id} className="flex items-start gap-2.5 rounded-md border border-background-200 px-3 py-2.5">
                      <span className={`font-label mt-0.5 shrink-0 whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] font-medium ${levelStyle[m.type]}`}>
                        {m.type}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="text-[13px] text-foreground-800">{m.clause}</div>
                        <div className="text-[11px] text-foreground-400">原文位置：{m.original}</div>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                renderEmpty("未从招标文件中抽取到必响应/否决条款")
              ))}

            {activeTab === "qualification" &&
              (checklist!.qualification.length ? (
                <table className="w-full border-collapse text-[13px]">
                  <tbody>
                    {checklist!.qualification.map((q, idx) => (
                      <tr key={idx} className="align-top">
                        <td className="w-32 border border-background-200 px-2.5 py-2">
                          <div className="font-medium text-foreground-900">{q.title}</div>
                          <span className={`font-label mt-0.5 inline-block rounded border px-1.5 py-0.5 text-[10px] font-medium ${levelStyle[q.level]}`}>{q.level}</span>
                        </td>
                        <td className="border border-background-200 px-2.5 py-2 text-foreground-700">
                          <div>{q.desc}</div>
                          <div className="mt-0.5 text-[11px] text-foreground-400">原文位置：{q.source}</div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                renderEmpty("未从招标文件中抽取到资格要求")
              ))}

            {activeTab === "formatRequirements" &&
              (checklist!.formatRequirements.length ? (
                <ul className="space-y-2">
                  {checklist!.formatRequirements.map((f, idx) => (
                    <li key={idx} className="flex items-start gap-2.5 rounded-md border border-background-200 px-3 py-2">
                      <span className={`font-label mt-0.5 shrink-0 whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] font-medium ${levelStyle[f.level]}`}>{f.level}</span>
                      <div className="min-w-0 flex-1">
                        <div className="text-[13px] text-foreground-800">
                          <span className="font-medium">{f.title}：</span>
                          {f.desc}
                        </div>
                        <div className="text-[11px] text-foreground-400">原文位置：{f.source}</div>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                renderEmpty("未从招标文件中抽取到格式与暗标要求")
              ))}
          </>
        )}
      </div>

      {/* 底部操作栏 */}
      <div className="shrink-0 flex items-center justify-between border-t border-background-300 bg-background-50 px-4 py-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onShare}
            className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 px-3 text-xs font-medium text-foreground-600 transition-colors hover:bg-background-200"
          >
            <i className="ri-share-forward-line text-sm"></i>
            分享解读结果
          </button>
          <button
            type="button"
            onClick={onDownload}
            className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 px-3 text-xs font-medium text-foreground-600 transition-colors hover:bg-background-200"
          >
            <i className="ri-download-2-line text-sm"></i>
            下载解读结果
          </button>
        </div>
        <button
          type="button"
          disabled={!hasChecklist || locking || checklist?.locked}
          onClick={onLock}
          className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-3 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <i className={`${locking ? "ri-loader-4-line animate-spin" : checklist?.locked ? "ri-lock-line" : "ri-lock-unlock-line"} text-sm`}></i>
          {checklist?.locked ? `已锁定评标尺子 v${checklist.version}` : locking ? "锁定中…" : "锁定评标尺子"}
        </button>
      </div>
    </div>
  );
}
