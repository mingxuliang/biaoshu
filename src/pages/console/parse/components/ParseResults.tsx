import { useMemo, useState } from "react";
import type { Checklist } from "@/lib/api";
import { countFilledRows, mergeParseDimensions } from "@/lib/parseDimensions";

interface ParseResultsProps {
  checklist: Checklist | null;
  parsing: boolean;
  locking: boolean;
  onLock: () => void;
  onShare: () => void;
  onDownload: () => void;
}

const DIM_ICONS: Record<string, string> = {
  basic: "ri-information-line",
  qualification: "ri-award-line",
  review: "ri-star-line",
  business: "ri-briefcase-line",
  reject: "ri-alarm-warning-line",
  bidReq: "ri-file-list-3-line",
  rejectCheck: "ri-file-check-line",
  docReview: "ri-search-eye-line",
  process: "ri-flow-chart",
};

export default function ParseResults({ checklist, parsing, locking, onLock, onShare, onDownload }: ParseResultsProps) {
  const dimensions = useMemo(() => mergeParseDimensions(checklist?.dimensions), [checklist]);
  const [activeKey, setActiveKey] = useState(dimensions[0]?.key ?? "basic");
  const activeDim = dimensions.find((d) => d.key === activeKey) ?? dimensions[0];
  const [activeItemId, setActiveItemId] = useState(activeDim?.items[0]?.id ?? "");

  const currentDim = dimensions.find((d) => d.key === activeKey) ?? dimensions[0];
  const currentItem =
    currentDim?.items.find((i) => i.id === activeItemId) ?? currentDim?.items[0];

  const hasChecklist = !!checklist && checklist.status === "done";
  const { filled, total } = countFilledRows(dimensions);

  const selectDimension = (key: string) => {
    setActiveKey(key);
    const dim = dimensions.find((d) => d.key === key);
    setActiveItemId(dim?.items[0]?.id ?? "");
  };

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-background-300 bg-background-100">
      <div className="shrink-0 border-b border-background-300 bg-background-50 px-3 py-2">
        <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-thin">
          {dimensions.map((dim) => {
            const isActive = dim.key === (currentDim?.key ?? "");
            return (
              <button
                key={dim.key}
                type="button"
                onClick={() => selectDimension(dim.key)}
                className={`flex shrink-0 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-medium transition-all ${
                  isActive
                    ? "bg-primary-500 text-background-50"
                    : "border border-background-300 bg-background-50 text-foreground-600 hover:bg-background-200"
                }`}
              >
                <i className={`${DIM_ICONS[dim.key] || "ri-bookmark-line"} text-sm`}></i>
                {dim.label}
                {dim.completed && <i className={`ri-checkbox-circle-fill text-xs ${isActive ? "text-background-50" : "text-secondary-500"}`}></i>}
              </button>
            );
          })}
        </div>
        {currentDim && (
          <div className="mt-2 flex gap-1.5 overflow-x-auto pb-1 scrollbar-thin">
            {currentDim.items.map((item) => {
              const selected = item.id === currentItem?.id;
              const itemFilled = item.sections.some((sec) => sec.rows.some((row) => row.content.trim()));
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setActiveItemId(item.id)}
                  className={`flex shrink-0 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md px-2.5 py-1 text-[11px] font-medium transition-all ${
                    selected
                      ? "bg-primary-50 text-primary-700 ring-1 ring-primary-200"
                      : "bg-background-100 text-foreground-600 hover:bg-background-200"
                  }`}
                >
                  {item.label}
                  {itemFilled && <span className="h-1.5 w-1.5 rounded-full bg-secondary-500"></span>}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="shrink-0 flex items-center gap-2 border-b border-background-200/60 bg-background-50/60 px-4 py-2">
        <span className="flex h-5 w-5 items-center justify-center rounded bg-secondary-100 text-[10px] font-bold text-secondary-600">AI</span>
        <span className="text-[11px] text-foreground-500">
          一级/二级分析指标固定展示；未在招标文件中出现的字段保持空白，不编造内容
        </span>
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

      <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
        {parsing && (
          <div className="mb-3 flex items-center gap-2 rounded-md border border-primary-100 bg-primary-50/60 px-3 py-2 text-xs text-primary-700">
            <i className="ri-loader-4-line animate-spin"></i>
            AI 正在按固定指标逐项抽取，请稍候…
          </div>
        )}
        {checklist?.error && (
          <div className="mb-3 rounded-md border border-accent-200 bg-accent-50 px-3 py-2 text-xs text-accent-700">{checklist.error}</div>
        )}
        {currentItem ? (
          <div className="space-y-4">
            {currentItem.sections.map((sec) => (
              <section key={sec.id}>
                <h3 className="mb-2 text-sm font-semibold text-foreground-900">{sec.title}</h3>
                <table className="w-full border-collapse text-[13px]">
                  <tbody>
                    {sec.rows.map((row) => (
                      <tr key={row.label} className="align-top">
                        <td className="w-32 border border-background-200 bg-background-50 px-2.5 py-2 font-medium text-foreground-700">
                          {row.label}
                        </td>
                        <td className="border border-background-200 px-2.5 py-2 text-foreground-800">
                          {row.content.trim() ? (
                            <div className="whitespace-pre-wrap">{row.content}</div>
                          ) : (
                            <span className="text-foreground-400">未从招标文件中抽取到该项内容</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            ))}
          </div>
        ) : (
          <div className="py-16 text-center text-sm text-foreground-500">请选择二级分析项目</div>
        )}
      </div>

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
          <span className="hidden text-[11px] text-foreground-400 sm:inline">
            已填 {filled}/{total} 项
          </span>
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
