/** 未响应的星号/约定对照项：招标条款不得显示在「投标书原文」。 */
export function splitBidAndTender(
  excerpt?: string,
  tenderQuote?: string,
  rule?: string,
): { excerpt: string; tenderQuote: string } {
  const ex = (excerpt || "").trim();
  const qu = (tenderQuote || "").trim();
  const dump = /F02\.06|招标解析约定/.test(rule || "");
  if (dump) {
    return { excerpt: "", tenderQuote: ex.length > qu.length ? ex : qu };
  }
  const nEx = ex.replace(/\s+/g, "");
  const nQu = qu.replace(/\s+/g, "");
  if (ex && qu && qu.length <= 24 && ex.length >= 40 && nQu && nEx.includes(nQu)) {
    return { excerpt: "", tenderQuote: ex };
  }
  if (ex && nQu && (nEx === nQu || (nQu.length >= 8 && nEx.includes(nQu)) || (nEx.length >= 8 && nQu.includes(nEx)))) {
    return { excerpt: "", tenderQuote: qu || ex };
  }
  return { excerpt: ex, tenderQuote: qu };
}

const FIGURE_MARK = /【附图\d+[：:]([^】｜|]+)/;
const DOTTED_HEAD = /^(\d+(?:\.\d+)+)\s*/;

export function visibleNeedles(excerpt = "", location = ""): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  const add = (text: string) => {
    const raw = (text || "").trim().replace(/^[「」『』“”"']+|[「」『』“”"']+$/g, "");
    if (raw.length < 4 || raw.includes("【附图")) return;
    const key = raw.replace(/\s+/g, "");
    if (!key || seen.has(key)) return;
    seen.add(key);
    out.push(raw);
  };
  for (const blob of [excerpt, location]) {
    if (!blob) continue;
    const mark = blob.match(FIGURE_MARK);
    if (mark) add(mark[1]);
    const tail = blob.includes("/") ? blob.split("/").pop()!.trim() : blob.trim();
    const markTail = tail.match(FIGURE_MARK);
    if (markTail) add(markTail[1]);
    else add(tail);
  }
  for (const item of [...out]) {
    const m = item.match(DOTTED_HEAD);
    if (!m) continue;
    const rest = item.slice(m[0].length).replace(/^[ .、:：]+/, "");
    if (rest.replace(/\s/g, "").length >= 6) add(rest);
  }
  out.sort((a, b) => b.replace(/\s+/g, "").length - a.replace(/\s+/g, "").length || b.length - a.length);
  return out;
}

export function sourceVisibleText(excerpt = "", location = ""): string {
  const needles = visibleNeedles(excerpt, location);
  if (needles.length) return needles[0];
  const cleaned = (excerpt || "").trim();
  return cleaned.includes("【附图") ? "" : cleaned;
}

const SKIP_CHAPTER = new Set([
  "技术标",
  "商务标",
  "投标文件",
  "评分细则",
  "资格文件",
  "资格条件",
  "证件识读",
  "技术评分模块",
]);
const NUM_CHAPTER = /^(\d+(?:\.\d+)+)|^第[0-9一二三四五六七八九十百零]+[章节篇]|^[（(][一二三四五六七八九十]+[）)]|^[一二三四五六七八九十]+、/;
const STRATEGY_BY_KEY: Record<string, string> = {
  checklist_map: "高分策略：清单化对标响应",
  quantify: "高分策略：数据代替定性空话",
  originality: "高分策略：原创度控制红线",
  local_first: "高分策略：本地化策略优先",
  structured_layout: "高分策略：严格结构化排版",
  data_loop: "高分策略：数据链逻辑闭环",
  chart_meta: "高分策略：图表自制规范",
  code_cite: "高分策略：规范引用精准",
};
const STRATEGY_ALIAS: Record<string, string> = {
  数字代替定性空话: "数据代替定性空话",
  数据代替定性空话: "数据代替定性空话",
  清单化对标响应: "清单化对标响应",
  本地化策略优先: "本地化策略优先",
  本地化策略: "本地化策略优先",
  原创度控制红线: "原创度控制红线",
  严格结构化排版: "严格结构化排版",
  数据链逻辑闭环: "数据链逻辑闭环",
  图表自制规范: "图表自制规范",
  规范引用精准: "规范引用精准",
};

export function issueChapter(location?: string): string {
  const parts = (location || "")
    .split(/[／/]/)
    .map((p) => p.trim())
    .filter((p) => p && !SKIP_CHAPTER.has(p));
  if (!parts.length) return (location || "").trim();
  const rest = parts.length >= 2 ? parts.slice(1) : parts;
  const numbered = rest.filter((p) => NUM_CHAPTER.test(p));
  if (numbered.length) return numbered[numbered.length - 1];
  return rest[rest.length - 1];
}

export type IssueRuleKind = "tender" | "review";

/** 招标解析约定、自定义规则 → 招标问题；其余 F 码/版式/虚词等 → 预审规则问题。 */
export function issueRuleKind(issue: { rule?: string; location?: string }): IssueRuleKind {
  const blob = `${issue.rule || ""}\n${issue.location || ""}`;
  if (/招标解析约定|自定义规则/.test(blob)) return "tender";
  return "review";
}

export function issueRuleSourceLabel(issue: { rule?: string; location?: string }): string {
  const blob = `${issue.rule || ""}\n${issue.location || ""}`;
  if (blob.includes("自定义规则")) return "自定义规则";
  if (issueRuleKind(issue) === "tender") return "招标条款";
  return "预审规则";
}

/** 没有招标条款可对标时，用白话说明这项检查在看什么。 */
export const NO_TENDER_CLAUSE_HINT =
  "此项不对照某一条招标条款，而是检查投标书自身写得是否清楚：前后有没有矛盾、有没有空话套话、版式是否规范。";

/** 投标书侧没有可引用原文时的说明。避免「命中句 / 检索 / 定位」等检索口吻，以免被理解成全文关键词查找。 */
export const NO_BID_EXCERPT_HINT = "对照招标要求，投标书中未见相应的响应内容。";
export const BID_EXCERPT_HIT_LABEL = "投标书原文（对应内容）";
export const BID_EXCERPT_MISS_LABEL = "投标书原文（未见对应响应）";

export function issueRuleLabel(issue: { rule?: string; suggestion?: string; strategyKey?: string; strategyCategory?: string }): string {
  if (issue.strategyCategory) {
    const name = STRATEGY_ALIAS[issue.strategyCategory] || issue.strategyCategory;
    return name.startsWith("高分策略") ? name : `高分策略：${name}`;
  }
  if (issue.strategyKey && STRATEGY_BY_KEY[issue.strategyKey]) return STRATEGY_BY_KEY[issue.strategyKey];
  const mark = (issue.suggestion || "").match(/【预审规则[-—]([^】]+)】/);
  if (mark) {
    const body = mark[1].trim();
    const book = body.match(/《([^》]+)》/);
    let name = (book ? book[1] : body).trim();
    name = STRATEGY_ALIAS[name] || name;
    if (body.includes("高分策略") || book) {
      return name.startsWith("高分策略") ? name : `高分策略：${name}`;
    }
    return body;
  }
  const raw = (issue.rule || "").trim();
  if (!raw || /五维语义评审/.test(raw)) return raw.replace(/（AI 生成，供参考）/g, "").trim() || "五维语义评审";
  return raw.replace(/^F\d{2}\.\d{2}\s+/, "").trim() || raw;
}
