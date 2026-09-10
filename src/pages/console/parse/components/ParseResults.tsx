import { useEffect, useMemo, useState } from "react";
import type { Checklist, TenderPackageSlot } from "@/lib/api";
import { countFilledRows, mergeParseDimensions } from "@/lib/parseDimensions";
import {
  TENDER_KIND_DISPLAY,
  TENDER_KIND_JUMP,
  TENDER_KIND_LABELS,
  TENDER_KIND_SLOTS,
  TENDER_MISSING_HINT,
  parseTargetForKind,
} from "@/lib/tenderPackage";

interface ParseResultsProps {
  checklist: Checklist | null;
  parsing: boolean;
  locking: boolean;
  category?: "软件服务类" | "工程类" | string;
  packageSlots?: TenderPackageSlot[];
  focusKind?: string;
  focusFileName?: string;
  focusFileId?: string;
  onLock: () => void;
  onShare: () => void;
  onDownload: () => void;
}

const PACKAGE_TAB = "package";
const FILE_TAB = "file";

const DIM_ICONS: Record<string, string> = {
  [PACKAGE_TAB]: "ri-archive-line",
  [FILE_TAB]: "ri-file-list-2-line",
  basic: "ri-information-line",
  qualification: "ri-award-line",
  evalMethod: "ri-scales-3-line",
  review: "ri-star-line",
  business: "ri-briefcase-line",
  reject: "ri-alarm-warning-line",
  bidReq: "ri-file-list-3-line",
  rejectCheck: "ri-file-check-line",
  docReview: "ri-search-eye-line",
  process: "ri-flow-chart",
  envelope: "ri-briefcase-line",
  quantity: "ri-file-list-3-line",
};

export default function ParseResults({
  checklist,
  parsing,
  locking,
  category,
  packageSlots,
  focusKind,
  focusFileName,
  focusFileId,
  onLock,
  onShare,
  onDownload,
}: ParseResultsProps) {
  const dimensions = useMemo(() => mergeParseDimensions(checklist?.dimensions, category), [checklist, category]);
  const [activeKey, setActiveKey] = useState(focusKind ? FILE_TAB : PACKAGE_TAB);
  const [activeItemId, setActiveItemId] = useState("");

  const showingPackage = activeKey === PACKAGE_TAB;
  const showingFile = activeKey === FILE_TAB;
  const currentDim = showingPackage || showingFile ? null : dimensions.find((d) => d.key === activeKey) ?? dimensions[0];
  const currentItem =
    currentDim?.items.find((i) => i.id === activeItemId) ?? currentDim?.items[0];

  const hasChecklist = !!checklist && checklist.status === "done";
  const { filled, total } = countFilledRows(dimensions);

  const parsedPackage = checklist?.package?.length ? checklist.package : packageSlots ?? [];
  const focusSlot = parsedPackage.find((s) => s.kind === focusKind);

  const focusItems = useMemo(() => {
    if (!focusKind) return [];
    const { dimKey, itemId } = parseTargetForKind(focusKind, category);
    const dim = dimensions.find((d) => d.key === dimKey);
    if (!dim) return [];
    if (itemId) {
      const hit = dim.items.find((i) => i.id === itemId);
      if (focusKind === "quote") {
        const extras = dim.items.filter((i) => i.id === "env-calc" || i.id === "env-price");
        return extras.length ? extras : hit ? [hit] : dim.items;
      }
      return hit ? [hit] : dim.items;
    }
    return dim.items;
  }, [focusKind, category, dimensions]);

  useEffect(() => {
    if (!focusKind && !focusFileId) return;
    setActiveKey(FILE_TAB);
    const first = focusItems[0];
    if (first) setActiveItemId(first.id);
  }, [focusKind, focusFileId, focusFileName]);

  const fileItem = focusItems.find((i) => i.id === activeItemId) ?? focusItems[0];

  const selectDimension = (key: string) => {
    setActiveKey(key);
    if (key === PACKAGE_TAB || key === FILE_TAB) return;
    const dim = dimensions.find((d) => d.key === key);
    setActiveItemId(dim?.items[0]?.id ?? "");
  };

  const jumpTo = (slot: TenderPackageSlot) => {
    const key = slot.jumpKey || TENDER_KIND_JUMP[slot.kind] || "basic";
    const dim = dimensions.find((d) => d.key === key) ?? dimensions.find((d) => d.key === "basic");
    if (!dim) return;
    setActiveKey(dim.key);
    const preferred =
      slot.kind === "boq"
        ? dim.items.find((i) => i.id === "qty-boq")
        : slot.kind === "drawing"
          ? dim.items.find((i) => i.id === "qty-drawing")
          : dim.items[0];
    setActiveItemId(preferred?.id ?? dim.items[0]?.id ?? "");
  };

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-background-300 bg-background-100">
      <div className="shrink-0 border-b border-background-300 bg-background-50 px-3 py-2">
        <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-thin">
          <button
            type="button"
            onClick={() => selectDimension(FILE_TAB)}
            className={`flex shrink-0 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-medium transition-all ${
              showingFile
                ? "bg-primary-500 text-background-50"
                : "border border-background-300 bg-background-50 text-foreground-600 hover:bg-background-200"
            }`}
          >
            <i className={`${DIM_ICONS[FILE_TAB]} text-sm`}></i>
            本文件解读
          </button>
          <button
            type="button"
            onClick={() => selectDimension(PACKAGE_TAB)}
            className={`flex shrink-0 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-medium transition-all ${
              showingPackage
                ? "bg-primary-500 text-background-50"
                : "border border-background-300 bg-background-50 text-foreground-600 hover:bg-background-200"
            }`}
          >
            <i className={`${DIM_ICONS[PACKAGE_TAB]} text-sm`}></i>
            文件包总览
          </button>
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
        {showingFile && focusItems.length > 0 && (
          <div className="mt-2 flex gap-1.5 overflow-x-auto pb-1 scrollbar-thin">
            {focusItems.map((item) => {
              const selected = item.id === (focusItems.find((i) => i.id === activeItemId)?.id ?? focusItems[0].id);
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
          {showingFile
            ? "左侧点哪个文件，这里展示该文件抽出的结构化字段（原文请看左侧）"
            : showingPackage
            ? "五种文件类型的上传与摘录总览；点左侧标签可查看单份文件的解析字段"
            : "一级/二级分析指标固定展示；未在招标文件中出现的字段保持空白，不编造内容"}
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
            AI 正在按固定指标逐项抽取，并识读施工图纸，请稍候…
          </div>
        )}
        {checklist?.error && (
          <div className="mb-3 rounded-md border border-accent-200 bg-accent-50 px-3 py-2 text-xs text-accent-700">{checklist.error}</div>
        )}
        {showingFile ? (
          <div className="space-y-4">
            <div className="rounded-lg border border-primary-100 bg-primary-50/50 px-3 py-2">
              <div className="text-sm font-semibold text-foreground-900">
                {TENDER_KIND_LABELS[focusKind || ""] || "当前文件"}
              </div>
              <div className="mt-0.5 truncate text-[12px] text-foreground-700" title={focusFileName}>
                {focusFileName || "未选择文件"}
              </div>
              <div className="mt-1 text-[11px] text-foreground-500">
                {focusSlot?.displayIn || TENDER_KIND_DISPLAY[focusKind || ""] || ""}
              </div>
            </div>
            {!focusSlot?.uploaded && focusKind ? (
              <div className="text-[13px] text-accent-600">{TENDER_MISSING_HINT}</div>
            ) : !hasChecklist ? (
              <div className="text-[13px] text-foreground-400">请先点击「开始解析文件包」，再查看该文件的解析字段</div>
            ) : !fileItem ? (
              <div className="text-[13px] text-foreground-400">该文件类型暂无对应结构化字段，原文请直接查看左侧。</div>
            ) : null}
            {fileItem ? (
              <div className="space-y-4">
                {fileItem.sections.map((sec) => (
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
                                <span className="text-foreground-400">未从该文件中抽取到该项内容</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </section>
                ))}
              </div>
            ) : null}
          </div>
        ) : showingPackage ? (
          <div className="space-y-3">
            {(parsedPackage.length ? parsedPackage : TENDER_KIND_SLOTS.map((s) => ({
              kind: s.key,
              label: s.label,
              uploaded: false,
              missingHint: TENDER_MISSING_HINT,
              files: [],
            }))).map((slot) => {
              const displayIn = slot.displayIn || TENDER_KIND_DISPLAY[slot.kind] || "";
              const excerpt = (slot.excerpt || "").trim();
              return (
                <section key={slot.kind} className="overflow-hidden rounded-lg border border-background-200">
                  <div className="flex items-start justify-between gap-2 bg-background-50 px-3 py-2">
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-foreground-900">{slot.label}</div>
                      <div className="mt-0.5 text-[11px] text-foreground-500">{displayIn}</div>
                      {slot.files.length > 0 && (
                        <div className="mt-1 truncate text-[11px] text-foreground-600">
                          {slot.files.map((f) => f.filename).join("；")}
                        </div>
                      )}
                    </div>
                    {slot.uploaded && dimensions.some((d) => d.key === (slot.jumpKey || TENDER_KIND_JUMP[slot.kind])) && (
                      <button
                        type="button"
                        onClick={() => jumpTo(slot)}
                        className="flex h-7 shrink-0 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border border-background-300 bg-background-100 px-2 text-[11px] text-foreground-600 hover:border-primary-300 hover:text-primary-700"
                      >
                        查看对应指标
                        <i className="ri-arrow-right-s-line"></i>
                      </button>
                    )}
                  </div>
                  <div className="px-3 py-2.5 text-[13px]">
                    {!slot.uploaded ? (
                      <span className="text-accent-600">{slot.missingHint || TENDER_MISSING_HINT}</span>
                    ) : excerpt ? (
                      <div className="max-h-64 overflow-auto whitespace-pre-wrap text-foreground-800">{excerpt}</div>
                    ) : hasChecklist ? (
                      <span className="text-foreground-400">已上传。请点击「重新解析文件包」，将在此展示该类型抽取内容</span>
                    ) : (
                      <span className="text-foreground-400">已上传，点击「开始解析文件包」后将在此展示抽取内容</span>
                    )}
                  </div>
                </section>
              );
            })}
          </div>
        ) : currentItem ? (
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
