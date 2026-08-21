import { useMemo, useRef, useState } from "react";
import { projectDocGroups } from "@/mocks/projectDocs";
import { fetchSampleDocument, uploadBidDocument } from "@/lib/api";

export interface PreReviewDoc {
  kind: "workbench" | "upload";
  name: string;
  source: string; // 来源说明：文档分组或「手动上传」
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

interface WorkbenchFile {
  id: string;
  name: string;
  group: string;
  size: string;
  updated: string;
  pages?: number;
}

const ACCEPT = ".doc,.docx,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export default function DocumentSourceGate({ projectId, projectName, projectCode, onContinue }: DocumentSourceGateProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<PreReviewDoc | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [workbenchId, setWorkbenchId] = useState<string | null>(null);
  const [uploadName, setUploadName] = useState<string | null>(null);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitErr, setSubmitErr] = useState<string | null>(null);

  const workbenchFiles = useMemo<WorkbenchFile[]>(
    () =>
      projectDocGroups
        .filter((g) => g.key === "technical" || g.key === "commercial")
        .flatMap((g) =>
          g.docs.map((d) => ({
            id: d.id,
            name: d.name,
            group: g.label,
            size: d.size,
            updated: d.updated,
            pages: d.pages,
          })),
        ),
    [],
  );

  const pickWorkbench = (f: WorkbenchFile) => {
    setWorkbenchId(f.id);
    setUploadName(null);
    setUploadErr(null);
    setSubmitErr(null);
    setPendingFile(null);
    setSelected({
      kind: "workbench",
      name: f.name,
      source: f.group,
      size: f.size,
      updated: f.updated,
      pages: f.pages,
      bidDocumentId: "",
    });
  };

  const pickUpload = (file: File) => {
    const valid = /\.docx$/i.test(file.name);
    if (!valid) {
      setUploadErr("仅支持 .docx 格式的 Word 文档（暂不支持旧版 .doc，请另存为 .docx 后重新上传）");
      return;
    }
    const mb = (file.size / 1024 / 1024).toFixed(1);
    setWorkbenchId(null);
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
      const uploaded =
        selected.kind === "upload" && pendingFile
          ? await uploadBidDocument(projectId, pendingFile)
          : await fetchSampleDocument(projectId);
      onContinue({ ...selected, bidDocumentId: uploaded.id });
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
              预审前需先确定分析对象：从撰写工作台选择已写好的投标文件，或手动上传您自己的 Word 文档
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
        {/* 撰写工作台 */}
        <div className="flex flex-col overflow-hidden rounded-lg border border-background-300 bg-background-50">
          <div className="flex items-center gap-2 border-b border-background-300 bg-background-100 px-4 py-2.5">
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary-50 text-primary-600">
              <i className="ri-edit-2-line text-sm"></i>
            </span>
            <span className="text-sm font-medium text-foreground-800">从撰写工作台选择</span>
            <span className="font-label ml-auto rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">工作台已生成</span>
          </div>
          <ul className="flex-1 divide-y divide-background-200">
            {workbenchFiles.map((f) => (
              <li key={f.id}>
                <button
                  type="button"
                  onClick={() => pickWorkbench(f)}
                  className={`flex w-full cursor-pointer items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-background-100 ${
                    workbenchId === f.id ? "bg-primary-50/60" : ""
                  }`}
                >
                  <span
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${
                      workbenchId === f.id ? "bg-primary-500 text-background-50" : "bg-secondary-100 text-secondary-600"
                    }`}
                  >
                    <i className="ri-file-word-2-line text-base"></i>
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-foreground-800">{f.name}</div>
                    <div className="mt-0.5 flex items-center gap-2 text-[11px] text-foreground-500">
                      <span>{f.group}</span>
                      <span>·</span>
                      <span>{f.size}</span>
                      {f.pages ? (
                        <>
                          <span>·</span>
                          <span>{f.pages} 页</span>
                        </>
                      ) : null}
                    </div>
                  </div>
                  <span
                    className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-xs ${
                      workbenchId === f.id
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
            <span className="font-label ml-auto rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">支持 .doc / .docx</span>
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
          {selected?.kind === "workbench" && (
            <p className="text-[11px] text-secondary-600">
              提示：撰写工作台生成内容尚未接入真实引擎，此处将使用内置示例投标书运行五大预审引擎进行演示
            </p>
          )}
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