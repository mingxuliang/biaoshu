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

export interface LocateTarget {
  content: string;
  label?: string;
}

export function plainLocateValue(content: string): string {
  let raw = (content || "").trim();
  if (raw.startsWith("【答疑补遗为准】")) raw = raw.slice("【答疑补遗为准】".length).trim();
  const stripped = raw.replace(/[（(][^）)]{0,80}[）)]/g, "").trim();
  return stripped || raw.split(/[（(]/)[0].trim() || raw;
}

export function locateNeedles(content: string, label?: string): string[] {
  let raw = (content || "").trim();
  if (raw.startsWith("【答疑补遗为准】")) raw = raw.slice("【答疑补遗为准】".length).trim();
  if (!raw || raw.includes("未从招标文件中抽取到该项内容")) return [];
  const field = (label || "").trim();
  const cleaned = plainLocateValue(raw);
  const lines = raw.split(/[\n；;]+/).map((s) => s.trim()).filter(Boolean);
  const out: string[] = [];
  if (field && cleaned) {
    out.push(`${field}：${cleaned.slice(0, 48)}`);
    out.push(`${field}${cleaned.slice(0, 48)}`);
  }
  if (cleaned && cleaned !== raw) out.push(cleaned.slice(0, 48));
  if (field.length >= 2) out.push(field);
  for (const line of lines.slice(0, 12)) {
    const piece = plainLocateValue(line) || line;
    const c = compactText(piece);
    if (c.length >= 6) out.push(c.slice(0, 18));
    if (piece.length >= 4 && piece.length <= 80) out.push(piece.slice(0, 80));
    const quoted = line.match(/[「『“"]([^」』”"]{4,40})/g) || [];
    for (const q of quoted) out.push(q.replace(/^[「『“"]|[」』”"]$/g, ""));
  }
  const seen = new Set<string>();
  const uniq: string[] = [];
  for (const item of out.sort((a, b) => compactText(b).length - compactText(a).length)) {
    const key = compactText(item) || item;
    if (seen.has(key) || key.length < 2) continue;
    seen.add(key);
    uniq.push(item);
    if (uniq.length >= 12) break;
  }
  return uniq;
}

export function findSheetRow(
  sheets: { name: string; rows: string[][] }[],
  query: string,
): { sheet: number; row: number } | null {
  const q = (query || "").trim();
  if (!q || !sheets.length) return null;
  const keys = locateNeedles(q);
  const raw = compactText(q);
  if (raw.length >= 2 && !keys.some((k) => compactText(k) === raw)) keys.push(q);
  let best: { sheet: number; row: number; score: number } | null = null;
  sheets.forEach((sheet, si) => {
    sheet.rows.forEach((row, ri) => {
      const blob = compactText(row.join(""));
      if (!blob) return;
      for (const key of keys) {
        const k = compactText(key);
        if (k.length < 2) continue;
        if (!blob.includes(k)) continue;
        const score = k.length + (row.some((c) => compactText(c) === k) ? 12 : 0);
        if (!best || score > best.score) best = { sheet: si, row: ri, score };
      }
    });
  });
  return best;
}

export function findContentAnchor(
  content: string,
  paragraphs: TenderParagraph[],
  label?: string,
): { index: number; page: number | null; text: string } | null {
  const keys = locateNeedles(content, label);
  if (!keys.length || !paragraphs.length) return null;
  const labelC = compactText(label || "");
  const valueC = compactText(plainLocateValue(content));
  let best: { index: number; page: number | null; text: string; score: number } | null = null;
  for (const p of paragraphs) {
    const raw = (p.text || "").trim();
    if (!raw) continue;
    const c = compactText(raw);
    let score = 0;
    for (const key of keys) {
      const kc = compactText(key);
      if (kc.length < 2) continue;
      if (c.includes(kc)) score = Math.max(score, kc.length + (raw.length < 80 ? 8 : 0));
      else if (kc.includes(c) && c.length >= 6) score = Math.max(score, c.length);
    }
    if (valueC.length >= 4 && c.includes(valueC)) score += 18;
    if (labelC && c.includes(labelC)) {
      score += 16;
      if (/[：:]/.test(raw)) score += 8;
    }
    if (/^\d+\.\d+/.test(raw) || /^第[0-9一二三四五六七八九十百]+[章节篇]/.test(raw)) score += 12;
    if (score > (best?.score ?? 0)) {
      best = { index: p.index, page: p.page ?? null, text: raw, score };
    }
  }
  return best && best.score >= 8 ? best : null;
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
