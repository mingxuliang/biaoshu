export const TENDER_MISSING_HINT = "未能上传该类型文件";

export type TenderKind = "main" | "addendum" | "boq" | "quote" | "drawing";

export interface TenderKindSlot {
  key: TenderKind;
  label: string;
  accept: string;
  formats: string;
  hint: string;
  icon: string;
}

export const TENDER_KIND_SLOTS: TenderKindSlot[] = [
  {
    key: "main",
    label: "招标文件正文",
    accept: ".docx,.pdf,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    formats: "Word / PDF",
    hint: "投标人须知、评标办法、合同条款",
    icon: "ri-file-text-line",
  },
  {
    key: "addendum",
    label: "答疑补遗",
    accept: ".docx,.pdf,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    formats: "Word / PDF",
    hint: "澄清、补遗、答疑纪要",
    icon: "ri-question-answer-line",
  },
  {
    key: "boq",
    label: "工程量清单",
    accept: ".xlsx,.xls,.docx,.pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    formats: "Excel / Word / PDF",
    hint: "清单、控制价、工程量明细",
    icon: "ri-table-line",
  },
  {
    key: "quote",
    label: "报价文件",
    accept: ".xlsx,.xls,.docx,.pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    formats: "Excel / Word / PDF",
    hint: "报价表、投标报价文件",
    icon: "ri-money-cny-circle-line",
  },
  {
    key: "drawing",
    label: "施工图纸",
    accept: ".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp,.docx,image/png,image/jpeg,application/pdf",
    formats: "PDF / 图片 / Word",
    hint: "图纸、图册、扫描件",
    icon: "ri-image-2-line",
  },
];

export const TENDER_KIND_LABELS: Record<string, string> = Object.fromEntries(
  TENDER_KIND_SLOTS.map((s) => [s.key, s.label]),
);

export const TENDER_KIND_DISPLAY: Record<string, string> = {
  main: "写入右侧全部固定指标（基本信息、资格与门槛、评标办法等）",
  addendum: "与正文冲突时以补遗为准，覆盖写入各相关维度；原文摘录见「文件包解读」",
  boq: "「清单、图纸与技术标准」→ 工程量清单规则",
  quote: "「商务/技术/报价评审」中的报价相关字段",
  drawing: "「清单、图纸与技术标准」→ 图纸（图号目录、设计说明与施工要点）",
};

export const TENDER_KIND_JUMP: Record<string, string> = {
  main: "basic",
  addendum: "basic",
  boq: "quantity",
  quote: "envelope",
  drawing: "quantity",
};

export const TENDER_KIND_ITEM: Record<string, string> = {
  main: "",
  addendum: "",
  boq: "qty-boq",
  quote: "env-price",
  drawing: "qty-drawing",
};

/** 左侧文件标签对应的右侧解析落点。 */
export function parseTargetForKind(kind: string, category?: string): { dimKey: string; itemId: string } {
  if (kind === "boq") return { dimKey: "quantity", itemId: "qty-boq" };
  if (kind === "drawing") return { dimKey: "quantity", itemId: "qty-drawing" };
  if (kind === "quote") {
    if (category === "工程类") return { dimKey: "envelope", itemId: "env-price" };
    return { dimKey: "evalMethod", itemId: "eval-business" };
  }
  return { dimKey: "basic", itemId: "" };
}

const SLOT_ACCEPT = new Map(TENDER_KIND_SLOTS.map((s) => [s.key, s.accept]));

export function guessTenderKind(filename: string): TenderKind {
  const name = (filename || "").toLowerCase();
  if (/答疑|补遗|澄清|addendum|clarif/.test(name)) return "addendum";
  if (/报价|投标报价|quote/.test(name)) return "quote";
  if (/图纸|图册|施工图|drawing|dwg/.test(name)) return "drawing";
  if (/清单|工程量|boq|控制价/.test(name)) return "boq";
  const ext = fileExt(filename);
  if ([".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"].includes(ext)) return "drawing";
  if ([".xlsx", ".xls"].includes(ext)) return "boq";
  return "main";
}

export function effectiveTenderKind(stored: string | undefined, filename: string): TenderKind {
  const raw = (stored || "").trim();
  if (raw && raw !== "main" && TENDER_KIND_LABELS[raw]) return raw as TenderKind;
  const guessed = guessTenderKind(filename);
  if (raw === "main" && guessed !== "main") return guessed;
  if (TENDER_KIND_LABELS[raw]) return raw as TenderKind;
  return guessed;
}

export function fileExt(filename: string): string {
  const m = (filename || "").toLowerCase().match(/(\.[a-z0-9]+)$/);
  return m ? m[1] : "";
}

export function isAllowedTenderFile(filename: string, kind?: TenderKind): boolean {
  const ext = fileExt(filename);
  if (!ext || ext === ".doc") return false;
  const allowed = [".docx", ".pdf", ".xlsx", ".xls", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"];
  if (!allowed.includes(ext)) return false;
  if (!kind) return true;
  return (SLOT_ACCEPT.get(kind) || "").includes(ext);
}

export function formatFileSize(bytes: number): string {
  if (!bytes) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatOf(filename: string): string {
  const ext = fileExt(filename).replace(".", "").toUpperCase();
  if (!ext) return "文件";
  if (ext === "JPEG") return "JPG";
  if (ext === "TIF") return "TIFF";
  return ext;
}

export function fileIcon(filename: string): string {
  const ext = fileExt(filename);
  if (ext === ".pdf") return "ri-file-pdf-2-line";
  if (ext === ".xlsx" || ext === ".xls") return "ri-file-excel-2-line";
  if ([".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"].includes(ext)) return "ri-image-line";
  return "ri-file-word-2-line";
}

export function isPdfFile(filename: string): boolean {
  return fileExt(filename) === ".pdf";
}

export function isDocxFile(filename: string): boolean {
  return fileExt(filename) === ".docx";
}

export function isImageFile(filename: string): boolean {
  return [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"].includes(fileExt(filename));
}

export function isSpreadsheetFile(filename: string): boolean {
  return [".xlsx", ".xls"].includes(fileExt(filename));
}

const MIME_BY_EXT: Record<string, string> = {
  ".pdf": "application/pdf",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".xls": "application/vnd.ms-excel",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".bmp": "image/bmp",
  ".tif": "image/tiff",
  ".tiff": "image/tiff",
};

export function mimeFromFilename(filename: string): string {
  return MIME_BY_EXT[fileExt(filename)] || "";
}

/** 预览/下载必须带对的 MIME，否则 Chrome 会把 blob 存成一串 UUID。 */
export async function ensureBlobMime(blob: Blob, filename: string): Promise<Blob> {
  const wanted = mimeFromFilename(filename);
  const current = (blob.type || "").split(";")[0].trim();
  if (wanted && current === wanted) return blob;
  const head = new Uint8Array(await blob.slice(0, 5).arrayBuffer());
  const pdfMagic = head.length >= 4 && head[0] === 0x25 && head[1] === 0x50 && head[2] === 0x44 && head[3] === 0x46;
  const type = pdfMagic ? "application/pdf" : wanted || current || "application/octet-stream";
  if (current === type) return blob;
  return new Blob([blob], { type });
}
