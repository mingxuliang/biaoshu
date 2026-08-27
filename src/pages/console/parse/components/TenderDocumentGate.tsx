import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import {
  listProjectTenderDocuments,
  uploadTenderDocument,
  type TenderDocumentSummary,
} from "@/lib/api";

export interface TenderDocSource {
  kind: "project" | "upload";
  name: string;
  source: string;
  size: string;
  format: string;
  tenderDocumentId: string;
}

interface TenderDocumentGateProps {
  projectId: string;
  projectName: string;
  projectCode: string;
  onContinue: (doc: TenderDocSource) => void;
}

function formatSize(bytes: number): string {
  if (!bytes) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const ACCEPT = ".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export default function TenderDocumentGate({
  projectId,
  projectName,
  projectCode,
  onContinue,
}: TenderDocumentGateProps) {
  const { token } = useAuth();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [projectDocs, setProjectDocs] = useState<TenderDocumentSummary[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [selected, setSelected] = useState<TenderDocSource | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [selectedProjectFileId, setSelectedProjectFileId] = useState<string | null>(null);
  const [uploadName, setUploadName] = useState<string | null>(null);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitErr, setSubmitErr] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setDocsLoading(true);
    listProjectTenderDocuments(token, projectId)
      .then((docs) => {
        if (!cancelled) setProjectDocs(docs);
      })
      .catch(() => {
        if (!cancelled) setProjectDocs([]);
      })
      .finally(() => {
        if (!cancelled) setDocsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, projectId]);

  const pickProject = (doc: TenderDocumentSummary) => {
    setSelectedProjectFileId(doc.id);
    setUploadName(null);
    setUploadErr(null);
    setSubmitErr(null);
    setPendingFile(null);
    setSelected({
      kind: "project",
      name: doc.filename,
      source: "项目招标文件",
      size: formatSize(doc.sizeBytes),
      format: "DOCX",
      tenderDocumentId: doc.id,
    });
  };

  const pickUpload = (file: File) => {
    const valid = /\.docx$/i.test(file.name);
    if (!valid) {
      setUploadErr("仅支持 .docx 格式的招标文件（暂不支持 .doc / .pdf，请另存为 .docx 后重新上传）");
      return;
    }
    const mb = (file.size / 1024 / 1024).toFixed(1);
    setSelectedProjectFileId(null);
    setUploadErr(null);
    setSubmitErr(null);
    setUploadName(file.name);
    setPendingFile(file);
    setSelected({
      kind: "upload",
      name: file.name,
      source: "手动上传",
      size: `${mb} MB`,
      format: "DOCX",
      tenderDocumentId: "",
    });
  };

  const handleContinue = async () => {
    if (!selected || submitting) return;
    if (selected.kind === "project" && selected.tenderDocumentId) {
      onContinue(selected);
      return;
    }
    if (!pendingFile) return;
    setSubmitting(true);
    setSubmitErr(null);
    try {
      const uploaded = await uploadTenderDocument(projectId, pendingFile);
      onContinue({ ...selected, tenderDocumentId: uploaded.id });
    } catch (err) {
      setSubmitErr(err instanceof Error ? err.message : "文件上传失败，请重试");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
      <div className="flex flex-col gap-2.5 border-b border-background-300 bg-background-50 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
            <i className="ri-file-list-3-line text-lg"></i>
          </span>
          <div>
            <div className="font-label text-sm font-semibold text-foreground-900">第一步 · 上传招标文件</div>
            <div className="text-xs text-foreground-500">
              解析前需先确定招标文件：从项目已归档的招标文档中选择，或手动上传 .docx
            </div>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="truncate text-xs font-medium text-foreground-700">{projectName}</div>
          <div className="text-[11px] text-foreground-500">编号 {projectCode}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 p-5 lg:grid-cols-2">
        <div className="flex flex-col overflow-hidden rounded-lg border border-background-300 bg-background-50">
          <div className="flex items-center gap-2 border-b border-background-300 bg-background-100 px-4 py-2.5">
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary-50 text-primary-600">
              <i className="ri-folder-open-line text-sm"></i>
            </span>
            <span className="text-sm font-medium text-foreground-800">从项目招标文档选择</span>
            <span
              className={`font-label ml-auto rounded px-1.5 py-0.5 text-[10px] ${
                projectDocs.length > 0 ? "bg-secondary-100 text-secondary-700" : "bg-background-200 text-foreground-500"
              }`}
            >
              {docsLoading ? "加载中" : projectDocs.length > 0 ? `${projectDocs.length} 份` : "未上传"}
            </span>
          </div>
          {docsLoading ? (
            <div className="flex flex-1 items-center justify-center px-4 py-8 text-xs text-foreground-500">
              正在加载项目招标文件…
            </div>
          ) : projectDocs.length > 0 ? (
            <ul className="flex-1 divide-y divide-background-200">
              {projectDocs.map((doc) => (
                <li key={doc.id}>
                  <button
                    type="button"
                    onClick={() => pickProject(doc)}
                    className={`flex w-full cursor-pointer items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-background-100 ${
                      selectedProjectFileId === doc.id ? "bg-primary-50/60" : ""
                    }`}
                  >
                    <span
                      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${
                        selectedProjectFileId === doc.id ? "bg-primary-500 text-background-50" : "bg-secondary-100 text-secondary-600"
                      }`}
                    >
                      <i className="ri-file-word-2-line text-base"></i>
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-foreground-800">{doc.filename}</div>
                      <div className="mt-0.5 flex items-center gap-2 text-[11px] text-foreground-500">
                        <span>DOCX</span>
                        <span>·</span>
                        <span>{formatSize(doc.sizeBytes)}</span>
                      </div>
                    </div>
                    <span
                      className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-xs ${
                        selectedProjectFileId === doc.id
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
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 px-4 py-8 text-center">
              <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-background-100 text-foreground-400">
                <i className="ri-folder-forbid-line text-xl"></i>
              </span>
              <div className="text-sm font-medium text-foreground-700">该项目尚未上传招标文件</div>
              <p className="max-w-[240px] text-xs leading-relaxed text-foreground-500">
                新建项目时可一并上传招标文件，也可在右侧「手动上传招标文件」直接上传后继续解析
              </p>
            </div>
          )}
        </div>

        <div className="flex flex-col overflow-hidden rounded-lg border border-background-300 bg-background-50">
          <div className="flex items-center gap-2 border-b border-background-300 bg-background-100 px-4 py-2.5">
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-accent-50 text-accent-600">
              <i className="ri-upload-2-line text-sm"></i>
            </span>
            <span className="text-sm font-medium text-foreground-800">手动上传招标文件</span>
            <span className="font-label ml-auto rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">
              支持 .docx
            </span>
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
              <span
                className={`flex h-11 w-11 items-center justify-center rounded-lg ${
                  uploadName ? "bg-accent-500 text-background-50" : "bg-secondary-100 text-secondary-600"
                }`}
              >
                <i className={`${uploadName ? "ri-file-list-3-line" : "ri-upload-cloud-2-line"} text-xl`}></i>
              </span>
              {uploadName ? (
                <>
                  <span className="max-w-full truncate px-2 text-sm font-medium text-foreground-800">{uploadName}</span>
                  <span className="text-[11px] text-foreground-500">已就绪，可点击重新选择</span>
                </>
              ) : (
                <>
                  <span className="text-sm font-medium text-foreground-700">点击选择或拖拽招标文件到此处</span>
                  <span className="text-[11px] text-foreground-500">
                    上传 .docx 格式的招标文件 / 评标办法，AI 将对其抽取评标尺子
                  </span>
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

      <div className="flex flex-col gap-2 border-t border-background-300 bg-background-50 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex min-w-0 items-center gap-2 text-xs text-foreground-500">
            {selected ? (
              <>
                <i className="ri-checkbox-circle-line text-primary-500"></i>
                <span className="shrink-0">已选择：</span>
                <span className="truncate font-medium text-foreground-700">{selected.name}</span>
                <span className="font-label shrink-0 rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">
                  {selected.source}
                </span>
              </>
            ) : (
              <span className="flex items-center gap-1.5">
                <i className="ri-information-line text-secondary-500"></i>
                请从上方选择一份招标文件后，方可进入解析工作台
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
          {submitting ? "正在上传文件…" : "进入招标解析"}
        </button>
      </div>
    </div>
  );
}
