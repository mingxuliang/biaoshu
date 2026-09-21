import { useEffect, useRef, useState } from "react";
import { listProjectBidDocuments, uploadBidDocument, type BidDocumentSummary } from "@/lib/api";

export type BidSlot = "business" | "tech";

export interface PreReviewDoc {
  kind: "existing" | "upload";
  name: string;
  source: string;
  size: string;
  updated: string;
  pages?: number;
  bidDocumentId: string;
  slot: BidSlot;
  docKind?: string;
}

export interface PreReviewDocs {
  business?: PreReviewDoc;
  tech?: PreReviewDoc;
}

interface DocumentSourceGateProps {
  projectId: string;
  projectName: string;
  projectCode: string;
  onContinue: (docs: PreReviewDocs) => void;
}

const SOURCE_LABELS: Record<string, string> = {
  upload: "手动上传",
  workbench: "预审示例文档",
  writer: "撰写工作台导出",
  revision: "修改闭环保存版本",
  "export-anon": "导出中心（暗标版）",
};

const SLOT_META: Record<BidSlot, { label: string; hint: string; icon: string }> = {
  business: { label: "商务标", hint: "投标函、资质、业绩、财务、人员", icon: "ri-briefcase-line" },
  tech: { label: "技术标", hint: "施工组织设计、技术方案、暗标正文", icon: "ri-tools-line" },
};

function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] || source;
}

function formatSize(bytes: number): string {
  if (!bytes) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(iso: string): string {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 16);
}

function guessKindFromName(filename: string): "business" | "tech" | "combined" {
  const name = filename || "";
  const biz = /商务|资格|业绩|资信|投标函/.test(name);
  const tech = /技术标|技术部分|技术文件|施工组织|技术方案|施工方案|施组/.test(name);
  if (biz && tech) return "combined";
  if (biz) return "business";
  if (tech) return "tech";
  return "combined";
}

function resolvedKind(doc: BidDocumentSummary): "business" | "tech" | "combined" {
  const stored = (doc.kind || "").toLowerCase();
  if (stored === "business" || stored === "tech") return stored;
  return guessKindFromName(doc.filename);
}

function docsForSlot(docs: BidDocumentSummary[], slot: BidSlot): BidDocumentSummary[] {
  return docs.filter((doc) => {
    const kind = resolvedKind(doc);
    return kind === slot || kind === "combined";
  });
}

const ACCEPT = ".docx,.pdf,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const MISSING = "未能上传该类型文件";

export default function DocumentSourceGate({ projectId, projectName, projectCode, onContinue }: DocumentSourceGateProps) {
  const [existingDocs, setExistingDocs] = useState<BidDocumentSummary[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [picked, setPicked] = useState<PreReviewDocs>({});
  const [pending, setPending] = useState<Partial<Record<BidSlot, File>>>({});
  const [uploadErr, setUploadErr] = useState<Partial<Record<BidSlot, string>>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitErr, setSubmitErr] = useState<string | null>(null);
  const businessInput = useRef<HTMLInputElement>(null);
  const techInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    setDocsLoading(true);
    listProjectBidDocuments(projectId)
      .then((docs) => {
        if (!cancelled) setExistingDocs(docs);
      })
      .catch(() => {
        if (!cancelled) setExistingDocs([]);
      })
      .finally(() => {
        if (!cancelled) setDocsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const pickExisting = (slot: BidSlot, doc: BidDocumentSummary) => {
    setUploadErr((e) => ({ ...e, [slot]: undefined }));
    setSubmitErr(null);
    setPending((p) => ({ ...p, [slot]: undefined }));
    setPicked((prev) => ({
      ...prev,
      [slot]: {
        kind: "existing",
        name: doc.filename,
        source: sourceLabel(doc.source),
        size: formatSize(doc.sizeBytes),
        updated: formatTime(doc.uploadedAt),
        bidDocumentId: doc.id,
        slot,
        docKind: resolvedKind(doc),
      },
    }));
  };

  const pickUpload = (slot: BidSlot, file: File) => {
    if (!/\.(docx|pdf)$/i.test(file.name)) {
      setUploadErr((e) => ({ ...e, [slot]: "仅支持 .docx 或 PDF" }));
      return;
    }
    const mb = (file.size / 1024 / 1024).toFixed(1);
    setUploadErr((e) => ({ ...e, [slot]: undefined }));
    setSubmitErr(null);
    setPending((p) => ({ ...p, [slot]: file }));
    setPicked((prev) => ({
      ...prev,
      [slot]: {
        kind: "upload",
        name: file.name,
        source: "手动上传",
        size: `${mb} MB`,
        updated: "刚刚",
        bidDocumentId: "",
        slot,
        docKind: slot,
      },
    }));
  };

  const clearSlot = (slot: BidSlot) => {
    setPending((p) => ({ ...p, [slot]: undefined }));
    setPicked((prev) => {
      const next = { ...prev };
      delete next[slot];
      return next;
    });
  };

  const ready = !!(picked.business || picked.tech);

  const handleContinue = async () => {
    if (!ready || submitting) return;
    setSubmitting(true);
    setSubmitErr(null);
    try {
      const next: PreReviewDocs = { ...picked };
      for (const slot of ["business", "tech"] as BidSlot[]) {
        const file = pending[slot];
        const current = next[slot];
        if (current?.kind === "upload" && file) {
          const uploaded = await uploadBidDocument(projectId, file, slot);
          next[slot] = { ...current, bidDocumentId: uploaded.id, docKind: uploaded.kind || slot };
        }
      }
      onContinue(next);
    } catch (err) {
      setSubmitErr(err instanceof Error ? err.message : "文件处理失败，请重试");
    } finally {
      setSubmitting(false);
    }
  };

  const renderSlot = (slot: BidSlot) => {
    const meta = SLOT_META[slot];
    const selected = picked[slot];
    const inputRef = slot === "business" ? businessInput : techInput;
    return (
      <div className="flex flex-col overflow-hidden rounded-lg border border-background-300 bg-background-50">
        <div className="flex items-center gap-2 border-b border-background-300 bg-background-100 px-4 py-2.5">
          <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary-50 text-primary-600">
            <i className={`${meta.icon} text-sm`}></i>
          </span>
          <div className="min-w-0">
            <div className="text-sm font-medium text-foreground-800">{meta.label}</div>
            <div className="text-[11px] text-foreground-500">{meta.hint}</div>
          </div>
          {selected && (
            <button
              type="button"
              onClick={() => clearSlot(slot)}
              className="ml-auto cursor-pointer text-[11px] text-foreground-500 hover:text-accent-600"
            >
              清除
            </button>
          )}
        </div>
        <div className="flex flex-1 flex-col gap-3 p-3">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className={`flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed px-3 py-6 text-center transition-colors ${
              selected?.kind === "upload"
                ? "border-primary-300 bg-primary-50/50"
                : "border-background-300 hover:border-primary-300 hover:bg-background-100"
            }`}
          >
            <i className={`${selected?.kind === "upload" ? "ri-file-word-2-line" : "ri-upload-cloud-2-line"} text-xl text-primary-500`}></i>
            <span className="text-xs font-medium text-foreground-700">
              {selected?.kind === "upload" ? selected.name : `上传${meta.label}`}
            </span>
            <span className="text-[11px] text-foreground-500">.docx 或 PDF</span>
          </button>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) pickUpload(slot, file);
              e.target.value = "";
            }}
          />
          {uploadErr[slot] && <p className="text-[11px] text-accent-600">{uploadErr[slot]}</p>}
          <div className="max-h-40 overflow-auto rounded-md border border-background-200">
            {docsLoading ? (
              <p className="px-3 py-4 text-center text-[11px] text-foreground-500">加载已有文件…</p>
            ) : docsForSlot(existingDocs, slot).length === 0 ? (
              <p className="px-3 py-4 text-center text-[11px] text-foreground-500">暂无{meta.label}文件</p>
            ) : (
              <ul className="divide-y divide-background-200">
                {docsForSlot(existingDocs, slot).map((doc) => {
                  const active = selected?.kind === "existing" && selected.bidDocumentId === doc.id;
                  const kind = resolvedKind(doc);
                  return (
                    <li key={`${slot}-${doc.id}`}>
                      <button
                        type="button"
                        onClick={() => pickExisting(slot, doc)}
                        className={`flex w-full cursor-pointer items-start gap-2 px-3 py-2 text-left text-xs hover:bg-background-100 ${
                          active ? "bg-primary-50/70" : ""
                        }`}
                      >
                        <i className="ri-file-word-2-line mt-0.5 text-secondary-500"></i>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-medium text-foreground-800">{doc.filename}</span>
                          <span className="text-[11px] text-foreground-500">
                            {sourceLabel(doc.source)}
                            {kind === "tech" ? " · 技术标" : kind === "business" ? " · 商务标" : " · 合订"}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
          {!selected && <p className="text-[11px] text-accent-600">{MISSING}</p>}
        </div>
      </div>
    );
  };

  return (
    <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
      <div className="flex flex-col gap-2.5 border-b border-background-300 bg-background-50 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-accent-400 to-accent-500 text-background-50">
            <i className="ri-file-shield-2-line text-lg"></i>
          </span>
          <div>
            <div className="font-label text-sm font-semibold text-foreground-900">第一步 · 分册选择预审文件</div>
            <div className="text-xs text-foreground-500">商务标与技术标分开上传、分开预审。至少选择一册即可进入。</div>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="truncate text-xs font-medium text-foreground-700">{projectName}</div>
          <div className="text-[11px] text-foreground-500">编号 {projectCode}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 p-5 lg:grid-cols-2">
        {renderSlot("business")}
        {renderSlot("tech")}
      </div>

      <div className="flex flex-col gap-2 border-t border-background-300 bg-background-50 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-xs text-foreground-500">
          {ready ? (
            <span>
              已选 {picked.business ? "商务标" : ""}
              {picked.business && picked.tech ? " + " : ""}
              {picked.tech ? "技术标" : ""}
            </span>
          ) : (
            <span>请至少选择商务标或技术标中的一册</span>
          )}
          {submitErr && <p className="mt-1 text-accent-600">{submitErr}</p>}
        </div>
        <button
          type="button"
          disabled={!ready || submitting}
          onClick={() => void handleContinue()}
          className="flex h-9 shrink-0 cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-md bg-gradient-to-r from-primary-500 to-primary-600 px-5 text-sm font-semibold text-background-50 transition-all hover:from-primary-600 hover:to-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <i className={`${submitting ? "ri-loader-4-line animate-spin" : "ri-arrow-right-line"} text-sm`}></i>
          {submitting ? "正在处理文件…" : "进入分册预审"}
        </button>
      </div>
    </div>
  );
}
