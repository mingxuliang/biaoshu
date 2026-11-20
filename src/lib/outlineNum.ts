import type { OutlineNode } from "@/lib/api";

const DIGIT = "零一二三四五六七八九";
const TENS = ["", "十", "二十", "三十", "四十", "五十", "六十", "七十", "八十", "九十"];

const TITLE_NUM_PREFIX =
  /^(?:第[0-9一二三四五六七八九十百]+[章节篇]\s*|[一二三四五六七八九十百]+、\s*|[（(]\s*[一二三四五六七八九十百]+\s*[）)]\s*|\d+\.\d+(?:\.\d+)*[.．、]?\s*|\d+[.．、）)]\s*)/;

export function cnNum(n: number): string {
  if (n <= 0) return String(n);
  if (n <= 10) return "一二三四五六七八九十"[n - 1];
  if (n < 20) return `十${DIGIT[n - 10]}`;
  if (n < 100) {
    const tens = Math.floor(n / 10);
    const ones = n % 10;
    return ones === 0 ? TENS[tens] : `${TENS[tens]}${DIGIT[ones]}`;
  }
  return String(n);
}

export function stripTitleNum(title: string, num?: string): string {
  let t = (title || "").trim();
  const n = (num || "").trim();
  if (n && t.startsWith(n)) t = t.slice(n.length).trim();
  let prev = "";
  while (t && t !== prev) {
    prev = t;
    t = t.replace(TITLE_NUM_PREFIX, "").trim();
  }
  return t;
}

function isRequirementSentence(text: string): boolean {
  const t = (text || "").trim();
  if (!t) return false;
  if (/[。；;？?]$/.test(t)) return true;
  if (/^(支持|须|必须|应当|应能|包括|因|对于|若|当)/.test(t)) return true;
  if (/提供.{0,24}(?:咨询|受理|支持|服务)|全天候|无间断|小时内|接到采购人|组织架构调整/.test(t)) return true;
  return t.length > 24;
}

/** 把误当作目录的招标原句收成短标题；已是目录名的保持不动。 */
export function compactCatalogTitle(title: string): string {
  let t = stripTitleNum(title).replace(/[。；;，,：: ]+$/g, "");
  if (!t) return t;
  if (!isRequirementSentence(t) && t.length <= 24) return t;
  if (/服务热线|客户服务热线/.test(t) && /提供|全天候|24小时|7\s*天/.test(t)) {
    return "全天候服务热线";
  }
  if (t.includes("基础数据") && /须对|须在|组织架构|人员变动/.test(t)) {
    return "组织变更数据修改";
  }
  const seps = [
    "须包含",
    "必须包含",
    "应包含",
    "支持对",
    "包括但不限于",
    "提供",
    "须对",
    "须在",
    "应当",
    "应能",
    "必须",
    "支持",
    "包括",
    "须",
  ];
  for (const sep of seps) {
    const idx = t.indexOf(sep);
    if (idx < 0) continue;
    const head = t.slice(0, idx).replace(/[ ，,的]+$/g, "");
    const tail = t.slice(idx + sep.length);
    if (head.length >= 2 && head.length <= 16) return head;
    if ((sep === "须对" || sep === "须在") && tail) {
      if (tail.includes("基础数据")) {
        return /组织|架构|人员/.test(t) ? "组织变更数据修改" : "基础数据修改";
      }
      const m = tail.match(/([^、，,]{2,10})(?:等)?(?:基础数据)?(?:修改|完成|调整|变更)/);
      if (m) {
        const word = m[1].replace(/^的|的$/g, "");
        if (word.length >= 2 && word.length <= 10) {
          return tail.includes("修改") ? `${word}修改` : word;
        }
      }
    }
    if (!head && sep === "支持") {
      const m = tail.match(/进行([^，,。；;]{2,12})/);
      if (m) {
        const word = m[1].replace(/[的与及]+$/g, "");
        if (word.length >= 2 && word.length <= 12) return word;
      }
    }
  }
  const doing = t.match(/进行([^，,。；;]{2,12})/);
  if (doing) {
    const word = doing[1].replace(/[的与及]+$/g, "");
    if (word.length >= 2 && word.length <= 12) return word;
  }
  const cut = t.split(/[，,、；;]/, 1)[0].trim();
  if (cut.length >= 4 && cut.length <= 16) return cut;
  if (t.length > 12) return t.slice(0, 12).replace(/[、，,的与及]+$/g, "");
  return t;
}

export function displayOutlineTitle(title: string, num?: string): string {
  return compactCatalogTitle(stripTitleNum(title, num));
}

export function nodeDisplayTitle(node: Pick<OutlineNode, "title" | "num" | "engKind">): string {
  return node.engKind ? stripTitleNum(node.title, node.num) : displayOutlineTitle(node.title, node.num);
}

export function isOriginalFormTitle(title: string, num?: string): boolean {
  const t = stripTitleNum(title, num).replace(/\s+/g, "");
  if (!t) return false;
  return /承诺书|承诺函|授权委托|投标函|开标一览/.test(t);
}

export function isCertificateTitle(title: string, num?: string): boolean {
  const t = stripTitleNum(title, num).replace(/\s+/g, "");
  return /营业执照|资质证书|财务报告|财务报表|审计报告|业绩证明|类似业绩/.test(t);
}

export function isBusinessSkipChapter(
  node: Pick<OutlineNode, "title" | "num" | "part" | "requirement">,
): boolean {
  if (isOriginalFormTitle(node.title, node.num) || node.part === "form") return false;
  if (node.part === "tech") return false;
  if (isCertificateTitle(node.title, node.num)) return true;
  if ((node.requirement || "").trim()) return false;
  if (node.part === "business") return true;
  const t = stripTitleNum(node.title, node.num).replace(/\s+/g, "");
  return /商务标|商务部分|商务文件|资格审查|资格证明|资格文件|投标函|法定代表人|企业资质|营业执照|财务报告|类似业绩|投标文件组成|响应文件组成|响应文件格式|投标文件格式/.test(
    t,
  );
}

export function isSkipAiWrite(
  node: Pick<OutlineNode, "title" | "num" | "part" | "status" | "requirement">,
): boolean {
  if (isOriginalFormTitle(node.title, node.num) || node.part === "form" || isCertificateTitle(node.title, node.num)) {
    return true;
  }
  if ((node.requirement || "").trim()) return false;
  return node.status === "用原文" || isBusinessSkipChapter(node);
}

export function compactOutlineTitles(nodes: OutlineNode[]): OutlineNode[] {
  // 工程施工组织设计的章名就是评分项原文，不能截短
  if (isEngineeringOutline(nodes)) return nodes;
  const compacted = nodes.map((n) => ({
    ...n,
    title: displayOutlineTitle(n.title, n.num),
  }));
  const formIds = new Set(compacted.filter((n) => isOriginalFormTitle(n.title, n.num)).map((n) => n.id));
  const drop = new Set<string>();
  const walkDrop = (id: string) => {
    for (const n of compacted) {
      if (n.parentId === id) {
        drop.add(n.id);
        walkDrop(n.id);
      }
    }
  };
  for (const id of formIds) walkDrop(id);
  return compacted
    .filter((n) => !drop.has(n.id))
    .map((n) =>
      formIds.has(n.id)
        ? { ...n, status: "用原文" as const, expanded: false }
        : n,
    );
}

export function isEngineeringOutline(nodes: Pick<OutlineNode, "engKind">[]): boolean {
  return nodes.length > 0 && nodes.some((n) => !!n.engKind);
}

export function formatOutlineNum(depth: number, index: number, parentNum: string): string {
  if (depth === 0) return `${cnNum(index)}、`;
  if (depth === 1) return `（${cnNum(index)}）`;
  if (depth === 2) return `${index}.`;
  const base = (parentNum || "").replace(/[、.）\s]+$/g, "").replace(/^（/, "");
  if (/^\d+(\.\d+)*$/.test(base)) return `${base}.${index}`;
  return `${index}.`;
}

export function renumberOutline(nodes: OutlineNode[]): OutlineNode[] {
  const result = nodes.map((n) => ({ ...n }));
  const walk = (parentId: string | null, depth: number, parentNum: string) => {
    const kids = result.filter((n) => n.parentId === parentId);
    kids.forEach((k, i) => {
      k.num = formatOutlineNum(depth, i + 1, parentNum);
      walk(k.id, depth + 1, k.num);
    });
  };
  walk(null, 0, "");
  return result;
}
