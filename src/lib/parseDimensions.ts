import { parseDimensions, type ParseDimension, type ParseSection, type ParseSubItem } from "@/mocks/parse";
import { parseDimensionsEngineering } from "@/mocks/parseEngineering";

export type { ParseDimension, ParseSection, ParseSubItem };

export type ParseCategory = "软件服务类" | "工程类" | string | undefined;

const RISK_COLS = ["风险点", "详细描述", "风险等级", "来源/依据"] as const;
const COMPOSE_COLS = ["序号", "文件名称", "格式要求", "是否必须", "备注"] as const;
const QUAL_COLS = ["资料类别", "具体资料", "是否必须", "备注"] as const;
const OLD_RISK_LABEL = "废标风险点（风险点/描述/等级/条款号）";
const OLD_COMPOSE_LABEL = "投标文件组成清单（文件名/格式/是否必须/备注）";
const OLD_QUALDOC_LABEL = "资格审查资料详细清单（资料类别/具体资料/是否必须/备注）";

/** 按项目标书类别选用对应的固定骨架：软件服务类走 parse.ts，工程类走 parseEngineering.ts。 */
function baseDimensionsFor(category?: ParseCategory): ParseDimension[] {
  return category === "工程类" ? parseDimensionsEngineering : parseDimensions;
}

/** 早期演示的一级/二级指标骨架，内容一律为空，供解析页始终展示。 */
export function emptyParseDimensions(category?: ParseCategory): ParseDimension[] {
  return baseDimensionsFor(category).map((dim) => ({
    ...dim,
    completed: false,
    items: dim.items.map((item) => ({
      ...item,
      sections: item.sections.map((sec) => ({
        ...sec,
        rows: sec.rows.map((row) => ({ ...row, content: "", original: "" })),
      })),
    })),
  }));
}

function splitLegacyLines(blob: string): string[] {
  const text = (blob || "").replace("【答疑补遗为准】", "").trim();
  if (!text) return [];
  let lines = text.split(/\n+/).map((ln) => ln.replace(/^[；;·\s]+|[；;·\s]+$/g, "").trim()).filter(Boolean);
  if (lines.length === 1 && /[；;]/.test(lines[0])) {
    lines = lines[0].split(/[；;]/).map((x) => x.trim()).filter(Boolean);
  }
  return lines;
}

function parseLegacyRisk(blob: string): string[][] {
  const rows: string[][] = [];
  for (const line of splitLegacyLines(blob)) {
    let point = "";
    let rest = line;
    const named = line.match(/^([^：:]{2,40})[：:](.+)$/);
    if (named) {
      point = named[1].trim();
      rest = named[2].trim();
    }
    let level = "";
    let source = "";
    const tail = rest.match(/[（(]([^）)]+)[）)]\s*$/);
    if (tail) {
      rest = rest.slice(0, tail.index).trim();
      for (const part of tail[1].split(/[，,、]/).map((p) => p.trim()).filter(Boolean)) {
        if ("高中低".includes(part[0] || "") && !level) level = part[0];
        else source = source ? `${source}、${part}` : part;
      }
    }
    if (!point) point = rest.slice(0, 18) || line.slice(0, 18);
    if (point || rest) rows.push([point, rest || point, level, source]);
  }
  return rows;
}

function parseLegacyCompose(blob: string): string[][] {
  const rows: string[][] = [];
  splitLegacyLines(blob).forEach((raw, idx) => {
    const line = raw.replace(/^[\d一二三四五六七八九十]+[.、．)）]\s*/, "");
    const slash = line.split(/\s*\/\s*/).map((p) => p.trim()).filter(Boolean);
    let name = "";
    let fmt = "";
    let must = "";
    let remark = "";
    if (slash.length >= 2) {
      [name, fmt, must] = [slash[0], slash[1], slash[2] || ""];
      remark = slash.slice(3).join(" / ");
    } else {
      const named = line.match(/^(.+?)[：:](.+)$/);
      name = named ? named[1].trim() : line;
      fmt = named ? named[2].trim() : "";
    }
    if (must.includes("必须") || must === "是" || must === "须") must = "是";
    else if (must === "否" || must === "非必须") must = "否";
    else if (must.includes("按需") || must.includes("如有")) must = "按需";
    if (name) rows.push([String(idx + 1), name, fmt, must, remark]);
  });
  return rows;
}

function parseLegacyQualdoc(blob: string): string[][] {
  const rows: string[][] = [];
  let lastKind = "";
  for (const line of splitLegacyLines(blob)) {
    const slash = line.split(/\s*\/\s*/).map((p) => p.trim()).filter(Boolean);
    let kind = "";
    let name = "";
    let must = "";
    let remark = "";
    if (slash.length >= 2) {
      [kind, name, must] = [slash[0], slash[1], slash[2] || ""];
      remark = slash.slice(3).join(" / ");
    } else {
      const named = line.match(/^(.+?)[：:](.+)$/);
      kind = named ? named[1].trim() : "";
      name = named ? named[2].trim() : line;
    }
    if (kind) lastKind = kind;
    else kind = lastKind;
    if (name) rows.push([kind, name, must, remark]);
  }
  return rows;
}

function alreadyAligned(rows: { label: string; content: string }[], cols: readonly string[]): boolean {
  const counts = cols
    .map((col) => (rows.find((r) => r.label === col)?.content || "").split("\n").filter((ln) => ln.trim()).length)
    .filter((n) => n > 0);
  if (counts.length < 2) return false;
  const peak = Math.max(...counts);
  return peak >= 2 && counts.filter((n) => n >= peak - 1).length >= 2;
}

function overlayAlignedRows(
  destRows: { label: string; content: string }[],
  srcRows: { label: string; content: string }[],
  cols: readonly string[],
  oldLabel: string,
  parser: (blob: string) => string[][],
): { label: string; content: string }[] {
  const colSet = new Set<string>(cols);
  if (!cols.every((col) => destRows.some((row) => row.label === col))) return destRows;
  if (alreadyAligned(destRows, cols)) return destRows;
  let blob = srcRows.find((row) => row.label === oldLabel)?.content || "";
  if (!blob.trim()) {
    blob = srcRows
      .filter((row) => !colSet.has(row.label) && row.content.trim())
      .map((row) => row.content)
      .join("\n");
  }
  if (!blob.trim()) {
    const nonempty = destRows.filter((row) => colSet.has(row.label) && row.content.trim()).map((row) => row.content);
    if (nonempty.length === 1) blob = nonempty[0];
  }
  const parsed = parser(blob);
  if (!parsed.length) return destRows;
  const by = Object.fromEntries(cols.map((col, i) => [col, parsed.map((row) => row[i] || "").join("\n")]));
  return destRows.map((row) => ({
    ...row,
    content: by[row.label] ?? row.content,
    original: row.original || by[row.label] || row.content,
  }));
}

function overlayLegacyTables(
  destRows: { label: string; content: string }[],
  srcRows: { label: string; content: string }[],
): { label: string; content: string }[] {
  let rows = destRows;
  rows = overlayAlignedRows(rows, srcRows, RISK_COLS, OLD_RISK_LABEL, parseLegacyRisk);
  rows = overlayAlignedRows(rows, srcRows, COMPOSE_COLS, OLD_COMPOSE_LABEL, parseLegacyCompose);
  rows = overlayAlignedRows(rows, srcRows, QUAL_COLS, OLD_QUALDOC_LABEL, parseLegacyQualdoc);
  return rows;
}

export function mergeParseDimensions(filled?: ParseDimension[] | null, category?: ParseCategory): ParseDimension[] {
  const base = emptyParseDimensions(category);
  if (!filled?.length) return base;
  const byKey = new Map(filled.map((d) => [d.key, d]));
  const itemById = new Map<string, ParseSubItem>();
  for (const dim of filled) {
    for (const item of dim.items) itemById.set(item.id, item);
  }
  return base.map((dim) => {
    const src = byKey.get(dim.key);
    const itemMap = new Map((src?.items || []).map((i) => [i.id, i]));
    const items = dim.items.map((item) => {
      const si = itemMap.get(item.id) || itemById.get(item.id);
      if (!si) return item;
      const secMap = new Map(si.sections.map((s) => [s.id, s]));
      return {
        ...item,
        sections: item.sections.map((sec) => {
          const ss = secMap.get(sec.id);
          if (!ss) return sec;
          const rowMap = new Map(ss.rows.map((r) => [r.label, r.content]));
          const origMap = new Map(ss.rows.map((r) => [r.label, r.original || ""]));
          const merged = sec.rows.map((row) => ({
            ...row,
            content: rowMap.get(row.label) ?? "",
            original: origMap.get(row.label) ?? "",
          }));
          return {
            ...sec,
            rows: overlayLegacyTables(merged, ss.rows),
          };
        }),
      };
    });
    const completed = items.some((item) =>
      item.sections.some((sec) => sec.rows.some((row) => row.content.trim())),
    );
    return { ...dim, completed, items };
  });
}

export function countFilledRows(dims: ParseDimension[]): { filled: number; total: number } {
  let filled = 0;
  let total = 0;
  for (const dim of dims) {
    for (const item of dim.items) {
      for (const sec of item.sections) {
        for (const row of sec.rows) {
          total += 1;
          if (row.content.trim()) filled += 1;
        }
      }
    }
  }
  return { filled, total };
}
