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
    label: "其他",
    accept: "",
    formats: "任意格式",
    hint: "补遗之外的补充材料，评审条款将写入评分尺子",
    icon: "ri-folder-unknow-line",
  },
  {
    key: "drawing",
    label: "施工图纸",
    accept: ".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp,image/png,image/jpeg,image/webp,image/tiff,application/pdf",
    formats: "PDF / 图片",
    hint: "只抽取设计说明，不识读图面与国标",
    icon: "ri-image-2-line",
  },
];

export const TENDER_KIND_LABELS: Record<string, string> = Object.fromEntries(
  TENDER_KIND_SLOTS.map((s) => [s.key, s.label]),
);

export const TENDER_KIND_DISPLAY: Record<string, string> = {
  main: "写入右侧全部固定指标；专用合同条款中的技术要求与加分项写入「技术评分」",
  addendum: "与正文冲突时以补遗为准；合同技术指标以答疑最新口径覆盖",
  boq: "「清单、图纸与其他」→ 工程量清单（项目名称、计量单位、工程数量、备注）",
  quote: "「其他材料」提炼摘要；含评审条款时写入评分尺子，不写入报价评审",
  drawing: "「清单、图纸与其他」→ 图纸（仅抽取设计说明，多页合并）",
};

export const TENDER_KIND_JUMP: Record<string, string> = {
  main: "basic",
  addendum: "basic",
  boq: "quantity",
  quote: "quantity",
  drawing: "quantity",
};

export const TENDER_KIND_ITEM: Record<string, string> = {
  main: "",
  addendum: "",
  boq: "qty-boq",
  quote: "misc-other",
  drawing: "qty-drawing",
};

/** 左侧文件标签对应的右侧解析落点。 */
export function parseTargetForKind(kind: string, category?: string): { dimKey: string; itemId: string } {
  if (kind === "boq") return { dimKey: "quantity", itemId: "qty-boq" };
  if (kind === "drawing") return { dimKey: "quantity", itemId: "qty-drawing" };
  if (kind === "quote") {
    if (category === "工程类") return { dimKey: "quantity", itemId: "misc-other" };
    return { dimKey: "bidReq", itemId: "misc-other" };
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

const BLOCKED_EXTS = new Set([".exe", ".bat", ".cmd", ".com", ".msi", ".dll", ".scr", ".ps1"]);

export function isAllowedTenderFile(filename: string, kind?: TenderKind): boolean {
  const ext = fileExt(filename);
  if (!ext || BLOCKED_EXTS.has(ext)) return false;
  if (kind === "quote") return true;
  if (ext === ".doc") return false;
  const allowed = [".docx", ".pdf", ".xlsx", ".xls", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"];
  if (!allowed.includes(ext)) return false;
  if (!kind) return true;
  const accept = SLOT_ACCEPT.get(kind) || "";
  if (!accept) return true;
  return accept.includes(ext);
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
  if (ext === ".xlsx" || ext === ".xls" || ext === ".csv") return "ri-file-excel-2-line";
  if (ext === ".pptx" || ext === ".ppt") return "ri-file-ppt-2-line";
  if (ext === ".zip" || ext === ".rar" || ext === ".7z") return "ri-file-zip-line";
  if ([".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"].includes(ext)) return "ri-image-line";
  if (ext === ".txt" || ext === ".md" || ext === ".html" || ext === ".htm") return "ri-file-text-line";
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
