import { isBusinessSkipChapter, isOriginalFormTitle } from "@/lib/outlineNum";
import type { OutlineNode } from "@/lib/api";
import type { LayoutConfig, PageConfig } from "@/mocks/writerSteps";
import { layoutFontNamePt } from "@/mocks/writerSteps";

const A4_WIDTH_MM = 210;
const A4_HEIGHT_MM = 297;
const PT_MM = 25.4 / 72;

export function charsPerPage(layout?: Partial<LayoutConfig> | null): number {
  const margins = layout?.margins ?? { top: 2, bottom: 2, left: 2, right: 2 };
  const widthMm = A4_WIDTH_MM - (Number(margins.left) + Number(margins.right)) * 10;
  const heightMm = A4_HEIGHT_MM - (Number(margins.top) + Number(margins.bottom)) * 10;
  if (widthMm < 40 || heightMm < 40) return 800;
  const bodyPt = layout?.bodySizePt ?? layoutFontNamePt[layout?.fontSize || ""] ?? 12;
  const spacing = layout?.lineSpacing || "";
  const fixed = /固定值\s*(\d+(?:\.\d+)?)\s*磅/.exec(spacing);
  let linePt = bodyPt * 1.5;
  if (fixed) {
    linePt = Math.max(Number(fixed[1]), bodyPt);
  } else {
    const mul =
      layout?.lineSpacingMul ??
      (spacing.startsWith("2") ? 2 : spacing.includes("1.5") ? 1.5 : 1.5);
    linePt = Math.max(bodyPt * Math.max(mul, 1), bodyPt);
  }
  const charsLine = Math.max(8, Math.floor(widthMm / (bodyPt * PT_MM)));
  const lines = Math.max(8, Math.floor(heightMm / (linePt * PT_MM)));
  return charsLine * lines;
}

export function resolveBodyPages(page?: Partial<PageConfig> | null): number {
  if (!page) return 0;
  const total = Math.max(0, Number(page.total) || 0);
  const cover = Math.max(0, Number(page.cover) || 0);
  let body = Math.max(0, Number(page.body) || 0);
  const appendix = Math.max(0, Number(page.appendix) || 0);
  if (cover + body + appendix !== total) body = Math.max(0, total - cover - appendix);
  return body;
}

function isTechLeaf(nodes: OutlineNode[], node: OutlineNode): boolean {
  if (nodes.some((item) => item.parentId === node.id)) return false;
  if (node.part === "form" || isOriginalFormTitle(node.title, node.num)) return false;
  if (isBusinessSkipChapter(node)) return false;
  return true;
}

export function chapterCharTargets(
  outline: OutlineNode[],
  page?: Partial<PageConfig> | null,
  layout?: Partial<LayoutConfig> | null,
): Record<string, number> {
  const bodyPages = resolveBodyPages(page);
  const leaves = outline.filter((node) => isTechLeaf(outline, node));
  if (bodyPages <= 0 || leaves.length === 0) return {};
  const totalChars = bodyPages * charsPerPage(layout);
  const weights = leaves.map((node) => Math.max(Number(node.weight) || 0, 0));
  const weightSum = weights.reduce((sum, weight) => sum + weight, 0);
  const raw =
    weightSum <= 0
      ? leaves.map(() => totalChars / leaves.length)
      : weights.map((weight) => (totalChars * weight) / weightSum);
  const floors = raw.map((value) => Math.floor(value));
  let leftover = totalChars - floors.reduce((sum, value) => sum + value, 0);
  const order = raw
    .map((value, index) => ({ index, frac: value - floors[index] }))
    .sort((a, b) => b.frac - a.frac);
  for (const item of order) {
    if (leftover <= 0) break;
    floors[item.index] += 1;
    leftover -= 1;
  }
  const out: Record<string, number> = {};
  leaves.forEach((node, index) => {
    out[node.id] = Math.max(floors[index], 1);
  });
  return out;
}
