import { parseDimensions, type ParseDimension, type ParseSection, type ParseSubItem } from "@/mocks/parse";

export type { ParseDimension, ParseSection, ParseSubItem };

/** 早期演示的一级/二级指标骨架，内容一律为空，供解析页始终展示。 */
export function emptyParseDimensions(): ParseDimension[] {
  return parseDimensions.map((dim) => ({
    ...dim,
    completed: false,
    items: dim.items.map((item) => ({
      ...item,
      sections: item.sections.map((sec) => ({
        ...sec,
        rows: sec.rows.map((row) => ({ ...row, content: "" })),
      })),
    })),
  }));
}

export function mergeParseDimensions(filled?: ParseDimension[] | null): ParseDimension[] {
  const base = emptyParseDimensions();
  if (!filled?.length) return base;
  const byKey = new Map(filled.map((d) => [d.key, d]));
  return base.map((dim) => {
    const src = byKey.get(dim.key);
    if (!src) return dim;
    const itemMap = new Map(src.items.map((i) => [i.id, i]));
    const items = dim.items.map((item) => {
      const si = itemMap.get(item.id);
      if (!si) return item;
      const secMap = new Map(si.sections.map((s) => [s.id, s]));
      return {
        ...item,
        sections: item.sections.map((sec) => {
          const ss = secMap.get(sec.id);
          if (!ss) return sec;
          const rowMap = new Map(ss.rows.map((r) => [r.label, r.content]));
          return {
            ...sec,
            rows: sec.rows.map((row) => ({
              ...row,
              content: rowMap.get(row.label) ?? "",
            })),
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
