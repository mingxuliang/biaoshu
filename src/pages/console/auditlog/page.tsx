import { useMemo, useState } from "react";
import PageHeader from "../components/PageHeader";
import { auditLogs } from "@/mocks/auditLog";

const actionIcon: Record<string, string> = {
  导出: "ri-download-2-line",
  改写接受: "ri-check-double-line",
  "AI 改写": "ri-sparkling-2-line",
  发起预审: "ri-shield-check-line",
  引用知识: "ri-quill-pen-line",
  确认对标: "ri-lock-2-line",
  解析: "ri-file-settings-line",
};

const actionColor: Record<string, string> = {
  导出: "from-primary-400 to-primary-600",
  改写接受: "from-primary-400 to-primary-600",
  "AI 改写": "from-accent-400 to-accent-500",
  发起预审: "from-accent-400 to-accent-500",
  引用知识: "from-secondary-400 to-secondary-500",
  确认对标: "from-primary-400 to-primary-600",
  解析: "from-secondary-400 to-secondary-500",
};

const actionFilters = ["全部", "解析", "确认对标", "引用知识", "发起预审", "AI 改写", "改写接受", "导出"];

export default function AuditLogPage() {
  const [action, setAction] = useState("全部");
  const [keyword, setKeyword] = useState("");

  const filtered = useMemo(() => {
    let list = auditLogs;
    if (action !== "全部") list = list.filter((l) => l.action === action);
    if (keyword.trim()) {
      list = list.filter((l) => l.target.includes(keyword.trim()) || l.user.includes(keyword.trim()));
    }
    return list;
  }, [action, keyword]);

  const inputCls =
    "h-9 w-full rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500";

  return (
    <div>
      <PageHeader
        title="操作审计"
        description="解析、引用知识、预审、改写接受、导出全程留痕（操作者、对象、版本），满足内部审计与数据最小化要求。"
      />

      {/* 统计 */}
      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="flex items-center gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
            <i className="ri-file-history-line text-xl"></i>
          </span>
          <div>
            <div className="font-label text-[11px] text-foreground-500">本周操作记录</div>
            <div className="font-heading text-gradient text-lg font-bold">{auditLogs.length + 132}</div>
          </div>
        </div>
        <div className="flex items-center gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-accent-50 text-accent-600">
            <i className="ri-download-2-line text-xl"></i>
          </span>
          <div>
            <div className="font-label text-[11px] text-foreground-500">本周导出次数</div>
            <div className="font-heading text-gradient text-lg font-bold">18</div>
          </div>
        </div>
        <div className="flex items-center gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-secondary-100 text-secondary-600">
            <i className="ri-ai-generate text-xl"></i>
          </span>
          <div>
            <div className="font-label text-[11px] text-foreground-500">AI 改写 / 引用次数</div>
            <div className="font-heading text-gradient text-lg font-bold">96</div>
          </div>
        </div>
      </div>

      {/* 筛选 */}
      <div className="mb-4 flex flex-col gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5 lg:flex-row lg:items-center">
        <div className="flex flex-wrap items-center gap-1.5">
          {actionFilters.map((a) => (
            <button
              key={a}
              type="button"
              onClick={() => setAction(a)}
              className={`cursor-pointer whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-medium transition-all ${
                action === a
                  ? "border-primary-200 bg-primary-50 text-primary-600"
                  : "border-background-300 bg-transparent text-foreground-600 hover:border-background-400 hover:text-foreground-700"
              }`}
            >
              {a}
            </button>
          ))}
        </div>
        <div className="relative flex-1 lg:max-w-xs lg:ml-auto">
          <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-xs text-foreground-500"></i>
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索操作对象 / 操作人…"
            className={`${inputCls} pl-9`}
          />
        </div>
      </div>

      {/* 时间线 */}
      <div className="rounded-lg border border-background-300 bg-background-100 p-5">
        <ul className="relative space-y-0">
          {filtered.map((log) => (
            <li key={log.id} className="relative flex gap-4 pb-5 last:pb-0">
              {/* 时间线竖线 */}
              <span className="absolute left-[15px] top-8 bottom-0 w-px bg-background-300" />
              <span className={`relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${actionColor[log.action] || "from-secondary-400 to-secondary-500"} text-background-50`}>
                <i className={`${actionIcon[log.action] || "ri-history-line"} text-sm`}></i>
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-foreground-900">{log.action}</span>
                    <span className="whitespace-nowrap text-xs text-foreground-500">{log.target}</span>
                    <span className="inline-flex items-center whitespace-nowrap rounded bg-secondary-100 px-1.5 py-0.5 font-label text-[10px] text-secondary-700">
                      版本 {log.version}
                    </span>
                  </div>
                  <span className="font-label whitespace-nowrap text-xs text-foreground-500">{log.time}</span>
                </div>
                <p className="mt-1 text-xs text-foreground-600">{log.detail}</p>
                <div className="mt-1 flex items-center gap-1.5 text-[11px] text-foreground-500">
                  <span className="flex h-4 w-4 items-center justify-center rounded-full bg-secondary-100 text-[9px] font-medium text-secondary-700">
                    {log.user.charAt(0)}
                  </span>
                  {log.user}
                </div>
              </div>
            </li>
          ))}
          {filtered.length === 0 && (
            <li className="py-16 text-center">
              <i className="ri-inbox-line text-3xl text-foreground-400"></i>
              <p className="mt-3 text-sm text-foreground-500">没有匹配的审计记录</p>
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}