import { useEffect, useRef, useState } from "react";
import { listProjectBidDocuments, uploadBidDocument, type BidDocumentSummary } from "@/lib/api";

export interface PreReviewDoc {
  kind: "existing" | "upload";
  name: string;
  source: string; // 来源说明：真实文件来源或「手动上传」
  size: string;
  updated: string;
  pages?: number;
  /** 后端真实文档 ID，五大预审引擎基于该 ID 对应的文件运行 */
  bidDocumentId: string;
}

interface DocumentSourceGateProps {
  projectId: string;
  projectName: string;
  projectCode: string;
  onContinue: (doc: PreReviewDoc) => void;
}

const SOURCE_LABELS: Record<string, string> = {
  upload: "手动上传",
  workbench: "预审示例文档",
  writer: "撰写工作台导出",
  revision: "修改闭环保存版本",
  "export-anon": "导出中心（暗标版）",
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

const ACCEPT = ".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export default function DocumentSourceGate({ projectId, projectName, projectCode, onContinue }: DocumentSourceGateProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [existingDocs, setExistingDocs] = useState<BidDocumentSummary[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [selected, setSelected] = useState<PreReviewDoc | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [existingId, setExistingId] = useState<string | null>(null);
  const [uploadName, setUploadName] = useState<string | null>(null);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitErr, setSubmitErr] = useState<string | null>(null);

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

  const pickExisting = (doc: BidDocumentSummary) => {
    setExistingId(doc.id);
    setUploadName(null);
    setUploadErr(null);
    setSubmitErr(null);
    setPendingFile(null);
    setSelected({
      kind: "existing",
      name: doc.filename,
      source: sourceLabel(doc.source),
      size: formatSize(doc.sizeBytes),
      updated: formatTime(doc.uploadedAt),
      bidDocumentId: doc.id,
    });
  };

  const pickUpload = (file: File) => {
    const valid = /\.docx$/i.test(file.name);
    if (!valid) {
      setUploadErr("仅支持 .docx 格式的 Word 文档（暂不支持旧版 .doc，请另存为 .docx 后重新上传）");
      return;
    }
    const mb = (file.size / 1024 / 1024).toFixed(1);
    setExistingId(null);
    setUploadErr(null);
    setSubmitErr(null);
    setUploadName(file.name);
    setPendingFile(file);
    setSelected({
      kind: "upload",
      name: file.name,
      source: "手动上传",
      size: `${mb} MB`,
      updated: "刚刚",
      bidDocumentId: "",
    });
  };

  const handleContinue = async () => {
    if (!selected || submitting) return;
    setSubmitting(true);
    setSubmitErr(null);
    try {
      if (selected.kind === "upload" && pendingFile) {
        const uploaded = await uploadBidDocument(projectId, pendingFile);
        onContinue({ ...selected, bidDocumentId: uploaded.id });
      } else {
        onContinue(selected);
      }
    } catch (err) {
      setSubmitErr(err instanceof Error ? err.message : "文件处理失败，请重试");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
      {/* 头 */}
      <div className="flex flex-col gap-2.5 border-b border-background-300 bg-background-50 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-accent-400 to-accent-500 text-background-50">
            <i className="ri-file-shield-2-line text-lg"></i>
          </span>
          <div>
            <div className="font-label text-sm font-semibold text-foreground-900">第一步 · 选择预审投标文件</div>
            <div className="text-xs text-foreground-500">
              预审前需先确定分析对象：从该项目已有的真实投标文件中选择，或手动上传您自己的 Word 文档
            </div>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="truncate text-xs font-medium text-foreground-700">{projectName}</div>
          <div className="text-[11px] text-foreground-500">编号 {projectCode}</div>
        </div>
      </div>

      {/* 两种来源 */}
      <div className="grid grid-cols-1 gap-3 p-5 lg:grid-cols-2">
        {/* 已有文件 */}
        <div className="flex flex-col overflow-hidden rounded-lg border border-background-300 bg-background-50">
          <div className="flex items-center gap-2 border-b border-background-300 bg-background-100 px-4 py-2.5">
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary-50 text-primary-600">
              <i className="ri-file-list-3-line text-sm"></i>
            </span>
            <span className="text-sm font-medium text-foreground-800">从已有投标文件中选择</span>
            <span className="font-label ml-auto rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">
              {docsLoading ? "加载中…" : `共 ${existingDocs.length} 份`}
            </span>
          </div>
          <ul className="flex-1 divide-y divide-background-200">
            {!docsLoading && existingDocs.length === 0 && (
              <li className="px-4 py-8 text-center text-xs text-foreground-500">
                该项目暂无已上传/已生成的投标文件，请手动上传或先在撰写工作台导出
              </li>
            )}
            {existingDocs.map((doc) => (
              <li key={doc.id}>
                <button
                  type="button"
                  onClick={() => pickExisting(doc)}
                  className={`flex w-full cursor-pointer items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-background-100 ${
                    existingId === doc.id ? "bg-primary-50/60" : ""
                  }`}
                >
                  <span
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${
                      existingId === doc.id ? "bg-primary-500 text-background-50" : "bg-secondary-100 text-secondary-600"
                    }`}
                  >
                    <i className="ri-file-word-2-line text-base"></i>
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-foreground-800">{doc.filename}</div>
                    <div className="mt-0.5 flex items-center gap-2 text-[11px] text-foreground-500">
                      <span>{sourceLabel(doc.source)}</span>
                      <span>·</span>
                      <span>{formatSize(doc.sizeBytes)}</span>
                      <span>·</span>
                      <span>{formatTime(doc.uploadedAt)}</span>
                    </div>
                  </div>
                  <span
                    className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-xs ${
                      existingId === doc.id
                        ? "border-primary-500 bg-primary-500 text-background-50"
                        : "border-background-300 text-transparent"
                    }`}
                  >
                    <i className="ri-check-line"></i>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>

        {/* 手动上传 */}
        <div className="flex flex-col overflow-hidden rounded-lg border border-background-300 bg-background-50">
          <div className="flex items-center gap-2 border-b border-background-300 bg-background-100 px-4 py-2.5">
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-accent-50 text-accent-600">
              <i className="ri-upload-2-line text-sm"></i>
            </span>
            <span className="text-sm font-medium text-foreground-800">手动上传 Word 文档</span>
            <span className="font-label ml-auto rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">仅支持 .docx</span>
          </div>
          <div className="flex flex-1 flex-col p-4">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className={`flex flex-1 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-10 text-center transition-colors ${
                uploadName
                  ? "border-accent-300 bg-accent-50/50"
                  : "border-background-300 hover:border-accent-300 hover:bg-background-100"
              }`}
            >
              <span className={`flex h-11 w-11 items-center justify-center rounded-lg ${uploadName ? "bg-accent-500 text-background-50" : "bg-secondary-100 text-secondary-600"}`}>
                <i className={`${uploadName ? "ri-file-word-2-line" : "ri-upload-cloud-2-line"} text-xl`}></i>
              </span>
              {uploadName ? (
                <>
                  <span className="max-w-full truncate px-2 text-sm font-medium text-foreground-800">{uploadName}</span>
                  <span className="text-[11px] text-foreground-500">已就绪，可点击重新选择</span>
                </>
              ) : (
                <>
                  <span className="text-sm font-medium text-foreground-700">点击选择或拖拽 Word 文档到此处</span>
                  <span className="text-[11px] text-foreground-500">上传您自己写好的投标书 / 商务标 Word 文档，AI 将对其执行预审</span>
                </>
              )}
            </button>
            {uploadErr && (
              <p className="mt-2 flex items-center gap-1.5 text-xs text-accent-600">
                <i className="ri-error-warning-line"></i>
                {uploadErr}
              </p>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPT}
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) pickUpload(file);
                e.target.value = "";
              }}
            />
          </div>
        </div>
      </div>

      {/* 底部：已选 + 进入分析 */}
      <div className="flex flex-col gap-2 border-t border-background-300 bg-background-50 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex min-w-0 items-center gap-2 text-xs text-foreground-500">
            {selected ? (
              <>
                <i className="ri-checkbox-circle-line text-primary-500"></i>
                <span className="shrink-0">已选择：</span>
                <span className="truncate font-medium text-foreground-700">{selected.name}</span>
                <span className="font-label shrink-0 rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">{selected.source}</span>
              </>
            ) : (
              <span className="flex items-center gap-1.5">
                <i className="ri-information-line text-secondary-500"></i>
                请从上方选择一份投标文件后，方可进入预审分析
              </span>
            )}
          </div>
          {submitErr && (
            <p className="flex items-center gap-1 text-[11px] text-accent-600">
              <i className="ri-error-warning-line"></i>
              {submitErr}
            </p>
          )}
        </div>
        <button
          type="button"
          disabled={!selected || submitting}
          onClick={handleContinue}
          className="flex h-9 shrink-0 cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-md bg-gradient-to-r from-primary-500 to-primary-600 px-5 text-sm font-semibold text-background-50 transition-all hover:from-primary-600 hover:to-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <i className={`${submitting ? "ri-loader-4-line animate-spin" : "ri-arrow-right-line"} text-sm`}></i>
          {submitting ? "正在处理文件…" : "进入预审分析"}
        </button>
      </div>
    </div>
  );
}
