import type { OutlineNode, TenderParagraph } from "@/lib/api";

export function compactText(s: string): string {
  return (s || "").replace(/\s+/g, "").replace(/[：:、，,。；;．.]/g, "");
}

export function tenderHeadingLevel(p: TenderParagraph): 0 | 1 | 2 | 3 {
  const t = (p.text || "").trim();
  if (!t) return 0;
  const style = p.style || "";
  if (/^第[0-9一二三四五六七八九十百零]+[章节篇]/.test(t) && t.length <= 48) return 1;
  if (/^[一二三四五六七八九十]+、/.test(t) && t.length <= 40) return 1;
  if (/^[（(][一二三四五六七八九十]+[）)]/.test(t) && t.length <= 40) return 2;
  if (/^\d+\.\d+\.\d+/.test(t) && t.length <= 120) return 3;
  if (/^\d+\.\d+/.test(t) && t.length <= 80) return 2;
  if (/^\d{1,2}[.．、](?!\d)/.test(t) && t.length <= 48) return 2;
  if (/^Heading 1/i.test(style) || /^标题\s*1/.test(style) || p.outlineLevel === 0) return 1;
  if (/^Heading 2/i.test(style) || /^标题\s*2/.test(style) || p.outlineLevel === 1) return 2;
  if (/^Heading/i.test(style) || /^标题/.test(style) || (p.outlineLevel != null && p.outlineLevel <= 3)) {
    return 3;
  }
  return 0;
}

export function splitHeadingBody(text: string): { heading: string; body: string } {
  const t = (text || "").trim();
  for (const sep of ["：", ":"]) {
    const idx = t.indexOf(sep);
    if (idx > 0 && idx <= 40) {
      return { heading: t.slice(0, idx).trim(), body: t.slice(idx + 1).trim() };
    }
  }
  return { heading: t, body: "" };
}

export function findTenderAnchor(node: OutlineNode | undefined, paragraphs: TenderParagraph[]): number | null {
  if (!node || !paragraphs.length) return null;
  if (typeof node.sourceIndex === "number") {
    const exact = paragraphs.find((p) => p.index === node.sourceIndex);
    if (exact) return exact.index;
  }

  const clause = (node.idea || "").match(/【对应招标\s*([^】]+)】/)?.[1]?.trim() || "";
  const mapped = (node.idea || "").match(/对标招标「([^」]+)」/)?.[1]?.trim() || "";
  const title = (node.title || "").trim();
  const titleC = compactText(title);
  let best: { index: number; score: number } | null = null;

  for (const p of paragraphs) {
    const raw = (p.text || "").trim();
    if (!raw) continue;
    const c = compactText(raw);
    let score = 0;
    if (clause) {
      const clauseC = compactText(clause);
      if (raw.startsWith(clause) || c.startsWith(clauseC)) score += 10;
      else if (c.includes(clauseC) && raw.length < 160) score += 5;
    }
    if (mapped) {
      const mapC = compactText(mapped);
      if (c.includes(mapC) && raw.length < 80) score += 8;
    }
    if (titleC.length >= 2 && (c.includes(titleC) || raw.includes(title))) {
      score += titleC.length >= 4 ? 6 : 3;
      if (raw.length < 80) score += 2;
      if (tenderHeadingLevel(p) > 0) score += 2;
    }
    if (score > (best?.score ?? 0)) best = { index: p.index, score };
  }

  if (best && best.score >= 6) return best.index;
  return typeof node.sourceIndex === "number" ? node.sourceIndex : null;
}
