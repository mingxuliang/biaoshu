import { useEffect, useMemo, useRef, useState } from "react";
import type { Checklist } from "@/lib/api";
import { countFilledRows, mergeParseDimensions, type ParseSection } from "@/lib/parseDimensions";
import { parseTargetForKind } from "@/lib/tenderPackage";
import type { LocateTarget } from "@/lib/tenderAnchor";

const BOQ_COLS = ["项目名称", "计量单位", "工程数量", "备注"] as const;
const RISK_COLS = ["风险点", "详细描述", "风险等级", "来源/依据"] as const;
const COMPOSE_COLS = ["序号", "文件名称", "格式要求", "是否必须", "备注"] as const;
const QUAL_COLS = ["资料类别", "具体资料", "是否必须", "备注"] as const;
const ADDENDUM_MARK = "【答疑补遗为准】";

function ContractTechNote({ itemId }: { itemId?: string }) {
  if (itemId !== "contract-tech") return null;
  return (
    <div className="rounded-md border border-primary-100 bg-primary-50/60 px-3 py-2 text-[12px] leading-5 text-foreground-700">
      已通读全部招标文件中的<strong>专用合同条款 / 发包人要求 / 技术标准</strong>
      ，提炼与技术评审相关的时限、材料工艺、验收检测等指标。这些条款往往也是技术标加分项，锁定尺子后会进入 AI 预审。
      市政、房建及其他专业各有一组重点字段，不相关项保持空白。
    </div>
  );
}

function FieldContent({
  label,
  content,
  original,
  onLocate,
}: {
  label?: string;
  content: string;
  original?: string;
  onLocate?: (target: LocateTarget) => void;
}) {
  const text = content.trim();
  const body = text.startsWith(ADDENDUM_MARK) ? text.slice(ADDENDUM_MARK.length).trim() : text;
  const orig = (original || "").trim();
  const origBody = orig.startsWith(ADDENDUM_MARK) ? orig.slice(ADDENDUM_MARK.length).trim() : orig;
  const locateText = origBody || body;
  const showOriginal = Boolean(origBody && origBody !== body);
  const locatable = Boolean(onLocate && locateText && !locateText.includes("未从招标文件中抽取到该项内容"));
  const inner = (
    <div>
      {text.startsWith(ADDENDUM_MARK) ? (
        <span className="mb-1 inline-block rounded bg-primary-50 px-1.5 py-0.5 text-[10px] font-medium text-primary-700">
          答疑补遗为准
        </span>
      ) : null}
      <div className="whitespace-pre-wrap">{body}</div>
      {showOriginal ? (
        <details
          className="mt-1.5"
          onClick={(e) => e.stopPropagation()}
        >
          <summary className="cursor-pointer select-none text-[11px] text-foreground-400 hover:text-foreground-600">
            招标原文
          </summary>
          <div className="mt-1 whitespace-pre-wrap rounded bg-background-50 px-2 py-1.5 text-[12px] leading-5 text-foreground-600">
            {origBody}
          </div>
        </details>
      ) : null}
    </div>
  );
  if (!locatable) return inner;
  return (
    <button
      type="button"
      onClick={() => onLocate?.({ content: locateText, label })}
      title="定位到招标原文对应条款并高亮"
      className="w-full cursor-pointer rounded-sm text-left transition-colors hover:bg-primary-50/80"
    >
      {inner}
    </button>
  );
}

function hasCols(sec: ParseSection, cols: readonly string[]): boolean {
  const labels = new Set(sec.rows.map((r) => r.label));
  return cols.every((label) => labels.has(label));
}

function isBoqSection(sec: ParseSection): boolean {
  return hasCols(sec, BOQ_COLS);
}

function isRiskSection(sec: ParseSection): boolean {
  return hasCols(sec, RISK_COLS);
}

function MustBadge({ value }: { value: string }) {
  const v = value.trim();
  if (!v) return <span>—</span>;
  const tone =
    v === "是" || (v.includes("必须") && !v.includes("非") && !v.includes("不"))
      ? "bg-secondary-50 text-secondary-700"
      : v === "否" || v.includes("非必须")
        ? "bg-background-200 text-foreground-600"
        : "bg-primary-50 text-primary-700";
  return <span className={`inline-block rounded px-1.5 py-0.5 text-[11px] font-medium ${tone}`}>{v}</span>;
}

function AlignedItemsTable({
  title,
  cols,
  items,
  originals,
  countLabel,
  onLocate,
  locateIndex = 0,
  locateLabel,
  colClass,
}: {
  title: string;
  cols: readonly string[];
  items: string[][];
  originals?: string[][];
  countLabel: string;
  onLocate?: (target: LocateTarget) => void;
  locateIndex?: number;
  locateLabel?: string;
  colClass?: Record<string, string>;
}) {
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold text-foreground-900">
        {title}
        <span className="ml-2 text-[11px] font-normal text-foreground-500">
          共 {items.length} {countLabel}
        </span>
      </h3>
      {items.length ? (
        <div className="max-h-[560px] overflow-auto rounded-md border border-background-200">
          <table className="w-full min-w-[720px] border-collapse text-[13px]">
            <thead className="sticky top-0 bg-background-50">
              <tr>
                {cols.map((label) => (
                  <th
                    key={label}
                    className="border-b border-background-200 px-2.5 py-2 text-left font-medium text-foreground-700"
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((row, idx) => {
                const origRow = originals?.[idx] || [];
                const needle = origRow[locateIndex] || origRow.find(Boolean) || row[locateIndex] || row.find(Boolean) || "";
                const clickable = Boolean(onLocate && needle);
                return (
                  <tr
                    key={`${needle}-${idx}`}
                    className={`align-top ${clickable ? "cursor-pointer hover:bg-primary-50/70" : ""}`}
                    onClick={clickable ? () => onLocate?.({ content: needle, label: locateLabel || cols[locateIndex] }) : undefined}
                    title={clickable ? "定位到招标原文对应条款并高亮" : undefined}
                  >
                    {row.map((cell, colIdx) => {
                      const label = cols[colIdx];
                      const width = colClass?.[label] || "";
                      const isMust = label === "是否必须";
                      return (
                        <td
                          key={`${label}-${colIdx}`}
                          className={`border-b border-background-100 px-2.5 py-2 text-foreground-800 ${width} ${
                            label === "序号" || isMust ? "whitespace-nowrap" : ""
                          } ${label === "文件名称" || label === "资料类别" ? "font-medium text-foreground-900" : ""}`}
                        >
                          {isMust ? (
                            <MustBadge value={cell} />
                          ) : cell ? (
                            <div className="whitespace-pre-wrap">{cell}</div>
                          ) : (
                            "—"
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-md border border-dashed border-background-200 px-3 py-6 text-center text-[13px] text-foreground-400">
          未从招标文件中抽取到该项内容
        </div>
      )}
    </section>
  );
}

function alignedLineItems(sec: ParseSection, cols: readonly string[], field: "content" | "original" = "content") {
  const values = cols.map((label) => {
    const row = sec.rows.find((r) => r.label === label);
    const text = field === "original" ? row?.original || row?.content || "" : row?.content || "";
    return text.split("\n");
  });
  const n = Math.max(0, ...values.map((c) => c.length));
  const rows: string[][] = [];
  for (let i = 0; i < n; i += 1) {
    const item = values.map((col) => (col[i] || "").trim());
    if (item.some(Boolean)) rows.push(item);
  }
  return rows;
}

function SectionFields({ sec, onLocate }: { sec: ParseSection; onLocate?: (target: LocateTarget) => void }) {
  if (hasCols(sec, COMPOSE_COLS)) {
    return (
      <AlignedItemsTable
        title={sec.title}
        cols={COMPOSE_COLS}
        items={alignedLineItems(sec, COMPOSE_COLS)}
        originals={alignedLineItems(sec, COMPOSE_COLS, "original")}
        countLabel="份文件"
        onLocate={onLocate}
        locateIndex={1}
        locateLabel="文件名称"
        colClass={{ 序号: "w-14", 文件名称: "w-48", 是否必须: "w-20", 备注: "w-52" }}
      />
    );
  }
  if (hasCols(sec, QUAL_COLS)) {
    return (
      <AlignedItemsTable
        title={sec.title}
        cols={QUAL_COLS}
        items={alignedLineItems(sec, QUAL_COLS)}
        originals={alignedLineItems(sec, QUAL_COLS, "original")}
        countLabel="份资料"
        onLocate={onLocate}
        locateIndex={1}
        locateLabel="具体资料"
        colClass={{ 资料类别: "w-36", 是否必须: "w-20", 备注: "w-52" }}
      />
    );
  }
  if (isRiskSection(sec)) {
    const items = alignedLineItems(sec, RISK_COLS);
    const originals = alignedLineItems(sec, RISK_COLS, "original");
    return (
      <section>
        <h3 className="mb-2 text-sm font-semibold text-foreground-900">
          {sec.title}
          <span className="ml-2 text-[11px] font-normal text-foreground-500">共 {items.length} 条风险点</span>
        </h3>
        {items.length ? (
          <div className="max-h-[560px] overflow-auto rounded-md border border-background-200">
            <table className="w-full min-w-[720px] border-collapse text-[13px]">
              <thead className="sticky top-0 bg-background-50">
                <tr>
                  {RISK_COLS.map((label) => (
                    <th
                      key={label}
                      className="border-b border-background-200 px-2.5 py-2 text-left font-medium text-foreground-700"
                    >
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((row, idx) => {
                  const [point, desc, level, source] = row;
                  const orig = originals[idx] || [];
                  const needle = orig[3] || orig[0] || orig[1] || source || point || desc;
                  const clickable = Boolean(onLocate && needle);
                  const levelTone =
                    level.includes("高")
                      ? "bg-accent-50 text-accent-700"
                      : level.includes("中")
                        ? "bg-primary-50 text-primary-700"
                        : "bg-background-200 text-foreground-600";
                  return (
                    <tr
                      key={`${point}-${idx}`}
                      className={`align-top ${clickable ? "cursor-pointer hover:bg-primary-50/70" : ""}`}
                      onClick={clickable ? () => onLocate?.({ content: needle, label: point || "风险点" }) : undefined}
                      title={clickable ? "定位到招标原文对应条款并高亮" : undefined}
                    >
                      <td className="w-40 border-b border-background-100 px-2.5 py-2 font-medium text-foreground-900">
                        {point || "—"}
                      </td>
                      <td className="border-b border-background-100 px-2.5 py-2 text-foreground-800">
                        {desc ? <div className="whitespace-pre-wrap">{desc}</div> : "—"}
                      </td>
                      <td className="w-20 whitespace-nowrap border-b border-background-100 px-2.5 py-2">
                        {level ? (
                          <span className={`inline-block rounded px-1.5 py-0.5 text-[11px] font-medium ${levelTone}`}>
                            {level}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="w-44 border-b border-background-100 px-2.5 py-2 text-foreground-700">
                        {source || "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="rounded-md border border-dashed border-background-200 px-3 py-6 text-center text-[13px] text-foreground-400">
            未从招标文件中抽取到该项内容
          </div>
        )}
      </section>
    );
  }
  const items = isBoqSection(sec) ? alignedLineItems(sec, BOQ_COLS).map((row) => ({
    name: row[0],
    unit: row[1],
    qty: row[2],
    remark: row[3],
  })) : [];
  const boqOriginals = isBoqSection(sec) ? alignedLineItems(sec, BOQ_COLS, "original") : [];
  if (items.length) {
    return (
      <section>
        <h3 className="mb-2 text-sm font-semibold text-foreground-900">
          {sec.title}
          <span className="ml-2 text-[11px] font-normal text-foreground-500">共 {items.length} 条</span>
        </h3>
        <div className="max-h-[520px] overflow-auto rounded-md border border-background-200">
          <table className="w-full min-w-[640px] border-collapse text-[13px]">
            <thead className="sticky top-0 bg-background-50">
              <tr>
                {BOQ_COLS.map((label) => (
                  <th
                    key={label}
                    className="border-b border-background-200 px-2.5 py-2 text-left font-medium text-foreground-700"
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((row, idx) => {
                const orig = boqOriginals[idx] || [];
                const needle = orig[0] || row.name || [row.unit, row.qty].filter(Boolean).join(" ");
                const clickable = Boolean(onLocate && needle);
                return (
                <tr
                  key={`${row.name}-${idx}`}
                  className={`align-top ${clickable ? "cursor-pointer hover:bg-primary-50/70" : ""}`}
                  onClick={clickable ? () => onLocate?.({ content: needle, label: "项目名称" }) : undefined}
                  title={clickable ? "定位到招标原文对应条款并高亮" : undefined}
                >
                  <td className="border-b border-background-100 px-2.5 py-2 text-foreground-800">
                    {row.name || "—"}
                  </td>
                  <td className="w-24 whitespace-nowrap border-b border-background-100 px-2.5 py-2 text-foreground-800">
                    {row.unit || "—"}
                  </td>
                  <td className="w-28 whitespace-nowrap border-b border-background-100 px-2.5 py-2 text-foreground-800">
                    {row.qty || "—"}
                  </td>
                  <td className="border-b border-background-100 px-2.5 py-2 text-foreground-700">
                    {row.remark ? <div className="whitespace-pre-wrap">{row.remark}</div> : "—"}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    );
  }
  return (
    <section>
        <h3 className="mb-2 text-sm font-semibold text-foreground-900">{sec.title}</h3>
      <table className="w-full border-collapse text-[13px]">
        <tbody>
          {sec.rows.map((row) => (
            <tr key={row.label} className="align-top">
              <td className="w-40 border border-background-200 bg-background-50 px-2.5 py-2 font-medium text-foreground-700">
                {row.label}
              </td>
              <td className="border border-background-200 px-2.5 py-2 text-foreground-800">
                {row.content.trim() ? (
                  <FieldContent label={row.label} content={row.content} original={row.original} onLocate={onLocate} />
                ) : (
                  <span className="text-foreground-400">未从招标文件中抽取到该项内容</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

interface ParseResultsProps {
  checklist: Checklist | null;
  parsing: boolean;
  locking: boolean;
  category?: "软件服务类" | "工程类" | string;
  focusKind?: string;
  focusFileId?: string;
  onLock: () => void;
  onShare: () => void;
  onDownload: () => void;
  onLocate?: (target: LocateTarget) => void;
}

const DIM_ICONS: Record<string, string> = {
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
  focusKind,
  focusFileId,
  onLock,
  onShare,
  onDownload,
  onLocate,
}: ParseResultsProps) {
  const dimensions = useMemo(() => mergeParseDimensions(checklist?.dimensions, category), [checklist, category]);
  const [activeKey, setActiveKey] = useState("basic");
  const [activeItemId, setActiveItemId] = useState("");
  const jumpedFor = useRef("");

  const currentDim = dimensions.find((d) => d.key === activeKey) ?? dimensions[0];
  const currentItem = currentDim?.items.find((i) => i.id === activeItemId) ?? currentDim?.items[0];

  const hasChecklist = !!checklist && checklist.status === "done";
  const { filled, total } = countFilledRows(dimensions);

  useEffect(() => {
    const token = `${focusFileId || ""}:${focusKind || ""}`;
    if (!token.replace(":", "") || !dimensions.length) return;
    if (token === jumpedFor.current) return;
    jumpedFor.current = token;
    const { dimKey, itemId } = parseTargetForKind(focusKind || "", category);
    const dim = dimensions.find((d) => d.key === dimKey) ?? dimensions.find((d) => d.key === "basic") ?? dimensions[0];
    if (!dim) return;
    setActiveKey(dim.key);
    const preferred = itemId ? dim.items.find((i) => i.id === itemId) : dim.items[0];
    setActiveItemId(preferred?.id ?? dim.items[0]?.id ?? "");
  }, [focusKind, focusFileId, category, dimensions]);

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
          页面展示提炼后的招标要求，便于快速扫读；招标原文另行保存。点击条目可定位左侧对应条款。锁定评标尺子时使用原文。
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
            AI 正在按固定指标逐项抽取，并提取施工图纸中的设计说明，请稍候…
          </div>
        )}
        {checklist?.error && (
          <div className="mb-3 rounded-md border border-accent-200 bg-accent-50 px-3 py-2 text-xs text-accent-700">{checklist.error}</div>
        )}
        {currentItem ? (
          <div className="space-y-4">
            <ContractTechNote itemId={currentItem.id} />
            {currentItem.sections.map((sec) => (
              <SectionFields key={sec.id} sec={sec} onLocate={onLocate} />
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
