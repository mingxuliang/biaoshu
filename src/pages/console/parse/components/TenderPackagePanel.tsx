import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import {
  deleteTenderDocument,
  listProjectTenderDocuments,
  uploadTenderDocument,
  type TenderDocumentSummary,
} from "@/lib/api";
import {
  TENDER_KIND_SLOTS,
  TENDER_MISSING_HINT,
  effectiveTenderKind,
  fileIcon,
  formatFileSize,
  formatOf,
  isAllowedTenderFile,
  type TenderKind,
} from "@/lib/tenderPackage";

interface TenderPackagePanelProps {
  projectId: string;
  docs: TenderDocumentSummary[];
  loading: boolean;
  onDocsChange: (docs: TenderDocumentSummary[]) => void;
}

export default function TenderPackagePanel({ projectId, docs, loading, onDocsChange }: TenderPackagePanelProps) {
  const { token } = useAuth();
  const inputRefs = useRef<Record<string, HTMLInputElement | null>>({});
  const [uploadingKind, setUploadingKind] = useState<TenderKind | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const refresh = async () => {
    if (!token) return;
    const latest = await listProjectTenderDocuments(token, projectId);
    onDocsChange(latest);
  };

  const filesOf = (kind: TenderKind) =>
    docs.filter((d) => effectiveTenderKind(d.kind, d.filename) === kind);

  const handlePick = async (kind: TenderKind, files: FileList | null) => {
    if (!files?.length) return;
    setErr(null);
    const accepted: File[] = [];
    for (const file of Array.from(files)) {
      if (!isAllowedTenderFile(file.name, kind)) {
        setErr(`「${file.name}」格式不受该类型支持，请上传 ${TENDER_KIND_SLOTS.find((s) => s.key === kind)?.formats}`);
        continue;
      }
      accepted.push(file);
    }
    if (!accepted.length) return;
    setUploadingKind(kind);
    try {
      for (const file of accepted) {
        await uploadTenderDocument(projectId, file, kind);
      }
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "上传失败，请重试");
    } finally {
      setUploadingKind(null);
    }
  };

  const handleRemove = async (id: string) => {
    setErr(null);
    setRemovingId(id);
    try {
      await deleteTenderDocument(id);
      onDocsChange(docs.filter((d) => d.id !== id));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "删除失败");
    } finally {
      setRemovingId(null);
    }
  };

  useEffect(() => {
    setErr(null);
  }, [projectId]);

  const uploadedCount = TENDER_KIND_SLOTS.filter((s) => filesOf(s.key).length > 0).length;

  return (
    <div className="overflow-hidden">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-[11px] text-foreground-500">
          工程标可将正文、施工图纸、答疑补遗、工程量清单与其他材料一并上传并一同解析。其他槽支持任意格式。未上传的类型将标明「{TENDER_MISSING_HINT}」。
        </p>
        <span className="font-label ml-3 shrink-0 rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">
          {loading ? "加载中" : `已上传 ${uploadedCount}/${TENDER_KIND_SLOTS.length} 类`}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {TENDER_KIND_SLOTS.map((slot) => {
          const files = filesOf(slot.key);
          const busy = uploadingKind === slot.key;
          return (
            <div key={slot.key} className="flex min-h-[168px] flex-col overflow-hidden rounded-lg border border-background-300 bg-background-50">
              <div className="flex items-start gap-2 border-b border-background-200 px-3 py-2">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary-50 text-primary-600">
                  <i className={`${slot.icon} text-sm`}></i>
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-xs font-semibold text-foreground-900">{slot.label}</div>
                  <div className="truncate text-[10px] text-foreground-500">{slot.formats} · {slot.hint}</div>
                </div>
              </div>
              <div className="flex min-h-0 flex-1 flex-col px-3 py-2">
                {files.length > 0 ? (
                  <ul className="min-h-0 flex-1 space-y-1.5 overflow-auto">
                    {files.map((doc) => (
                      <li key={doc.id} className="flex items-start gap-1.5 rounded-md bg-background-100 px-1.5 py-1">
                        <i className={`${fileIcon(doc.filename)} mt-0.5 shrink-0 text-sm text-primary-500`}></i>
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[11px] font-medium text-foreground-800" title={doc.filename}>
                            {doc.filename}
                          </div>
                          <div className="text-[10px] text-foreground-500">
                            {formatOf(doc.filename)} · {formatFileSize(doc.sizeBytes)}
                          </div>
                        </div>
                        <button
                          type="button"
                          title="移除"
                          disabled={removingId === doc.id}
                          onClick={() => handleRemove(doc.id)}
                          className="flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center rounded text-foreground-400 hover:bg-accent-50 hover:text-accent-600 disabled:opacity-50"
                        >
                          <i className={`${removingId === doc.id ? "ri-loader-4-line animate-spin" : "ri-close-line"} text-xs`}></i>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="flex flex-1 flex-col items-center justify-center gap-1 py-3 text-center">
                    <i className="ri-file-forbid-line text-lg text-foreground-300"></i>
                    <div className="text-[11px] font-medium text-accent-600">{TENDER_MISSING_HINT}</div>
                  </div>
                )}
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => inputRefs.current[slot.key]?.click()}
                  className="mt-2 flex h-7 w-full cursor-pointer items-center justify-center gap-1 rounded-md border border-dashed border-background-300 text-[11px] font-medium text-foreground-600 transition-colors hover:border-primary-300 hover:bg-primary-50/40 hover:text-primary-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <i className={`${busy ? "ri-loader-4-line animate-spin" : "ri-upload-2-line"} text-xs`}></i>
                  {busy ? "上传中…" : files.length ? "继续添加" : "上传该类型"}
                </button>
                <input
                  ref={(el) => {
                    inputRefs.current[slot.key] = el;
                  }}
                  type="file"
                  multiple
                  accept={slot.accept || undefined}
                  className="hidden"
                  onChange={(e) => {
                    handlePick(slot.key, e.target.files);
                    e.target.value = "";
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
      {err && (
        <div className="mt-3 rounded-md border border-accent-200 bg-accent-50 px-3 py-2 text-xs text-accent-700">
          <i className="ri-error-warning-line mr-1"></i>
          {err}
        </div>
      )}
    </div>
  );
}
