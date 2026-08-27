import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Modal from "../../components/Modal";
import { useAuth } from "@/context/AuthContext";
import {
  downloadBidDocumentFile,
  downloadTenderDocument,
  getProjectDocuments,
  triggerFileDownload,
  type BidDocumentSummary,
  type TenderDocumentSummary,
} from "@/lib/api";

interface ProjectDocumentsProps {
  projectId: string;
}

const SOURCE_LABELS: Record<string, string> = {
  upload: "手动上传",
  workbench: "预审示例文档",
  writer: "撰写工作台导出",
  revision: "修改闭环保存版本",
  "export-anon": "导出中心（暗标版）",
};

function formatSize(bytes: number): string {
  if (!bytes) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(iso: string): string {
  if (!iso) return "—";
  return iso.slice(0, 10);
}

type PreviewDoc = {
  id: string;
  name: string;
  kind: "tender" | "bid";
  sourceLabel: string;
  size: string;
  updated: string;
};

export default function ProjectDocuments({ projectId }: ProjectDocumentsProps) {
  const { token } = useAuth();
  const [tenderDocs, setTenderDocs] = useState<TenderDocumentSummary[]>([]);
  const [bidDocs, setBidDocs] = useState<BidDocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [preview, setPreview] = useState<PreviewDoc | null>(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    getProjectDocuments(token, projectId)
      .then((data) => {
        if (cancelled) return;
        setTenderDocs(data.tenderDocuments);
        setBidDocs(data.bidDocuments);
      })
      .catch(() => {
        if (cancelled) return;
        setTenderDocs([]);
        setBidDocs([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, projectId]);

  const totalCount = tenderDocs.length + bidDocs.length;

  const handleDownload = async (doc: PreviewDoc) => {
    setDownloading(true);
    try {
      const blob = doc.kind === "tender" ? await downloadTenderDocument(doc.id) : await downloadBidDocumentFile(doc.id);
      triggerFileDownload(blob, doc.name);
    } finally {
      setDownloading(false);
    }
  };

  const groups = [
    {
      key: "tender",
      label: "招标文件",
      desc: "本项目已上传的招标文件，可供招标解析直接选用",
      icon: "ri-file-list-3-line",
      color: "bg-primary-50 text-primary-600",
      docs: tenderDocs.map((d) => ({
        id: d.id,
        name: d.filename,
        kind: "tender" as const,
        sourceLabel: "招标文件",
        size: formatSize(d.sizeBytes),
        updated: formatTime(d.uploadedAt),
      })),
    },
    {
      key: "bid",
      label: "投标文件与工作台产出",
      desc: "手动上传、撰写工作台导出、修改闭环保存版本等真实文件",
      icon: "ri-file-word-2-line",
      color: "bg-accent-50 text-accent-600",
      docs: bidDocs.map((d) => ({
        id: d.id,
        name: d.filename,
        kind: "bid" as const,
        sourceLabel: SOURCE_LABELS[d.source] || d.source,
        size: formatSize(d.sizeBytes),
        updated: formatTime(d.uploadedAt),
      })),
    },
  ];

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
            <i className="ri-folder-2-line text-primary-500 text-sm"></i>
            全部文档
          </h3>
          <p className="mt-1 text-xs text-foreground-500">
            按当前项目聚合真实招标文件与投标文件，点击可查看元数据并下载原文件
          </p>
        </div>
        <span className="rounded-full border border-background-300 bg-background-50 px-2.5 py-1 text-xs text-foreground-500">
          {loading ? "加载中" : `${totalCount} 份文档`}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {groups.map((group) => (
          <div
            key={group.key}
            className="group overflow-hidden rounded-lg border border-background-300 bg-background-100 transition-colors hover:border-primary-300/60"
          >
            <div className="relative flex items-center gap-3 border-b border-background-200 px-4 py-3">
              <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-md ${group.color}`}>
                <i className={`${group.icon} text-base`}></i>
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-foreground-900">{group.label}</span>
                  <span className="font-label rounded-full bg-background-200 px-1.5 py-0.5 text-[10px] text-foreground-600">
                    {group.docs.length} 份
                  </span>
                </div>
                <p className="mt-0.5 truncate text-[11px] text-foreground-500">{group.desc}</p>
              </div>
            </div>
            <div className="divide-y divide-background-200">
              {group.docs.length === 0 ? (
                <div className="px-4 py-8 text-center text-xs text-foreground-500">该项目暂无此类文件</div>
              ) : (
                group.docs.map((doc) => (
                  <button
                    key={doc.id}
                    type="button"
                    onClick={() => setPreview(doc)}
                    className="flex w-full cursor-pointer items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-background-50"
                  >
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary-50 text-primary-600">
                      <i className="ri-file-word-2-line text-base"></i>
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-foreground-900">{doc.name}</span>
                      <span className="block text-[11px] text-foreground-500">
                        DOCX · {doc.size} · {doc.sourceLabel} · {doc.updated}
                      </span>
                    </span>
                    <i className="ri-download-2-line shrink-0 text-sm text-foreground-400"></i>
                  </button>
                ))
              )}
            </div>
          </div>
        ))}

        <div className="flex flex-col items-start justify-center gap-3 rounded-lg border border-dashed border-background-300 bg-background-100/60 p-5">
          <div className="text-sm font-medium text-foreground-800">需要继续推进这个项目？</div>
          <p className="text-xs text-foreground-500">
            从招标解析到技术标撰写、AI 预审与修改闭环，全流程在此项目下串联完成。
          </p>
          <div className="mt-1 flex flex-wrap gap-2">
            <Link
              to={`/console/parse?project=${projectId}`}
              className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-3.5 text-xs font-medium text-foreground-700 transition-colors hover:bg-background-200"
            >
              <i className="ri-file-settings-line text-sm"></i>
              招标解析
            </Link>
            <Link
              to={`/console/writer?project=${projectId}`}
              className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-3.5 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
            >
              <i className="ri-edit-2-line text-sm"></i>
              进入撰写工作台
            </Link>
            <Link
              to={`/console/audit?project=${projectId}`}
              className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-accent-200 bg-accent-50 px-3.5 text-xs font-medium text-accent-600 transition-colors hover:bg-accent-100"
            >
              <i className="ri-shield-check-line text-sm"></i>
              AI 预审
            </Link>
          </div>
        </div>
      </div>

      <Modal
        open={!!preview}
        onClose={() => setPreview(null)}
        title={preview?.name ?? ""}
        subtitle={preview ? `${preview.sourceLabel} · DOCX · ${preview.size} · ${preview.updated}` : ""}
      >
        {preview && (
          <div className="space-y-4">
            <div className="rounded-md bg-background-50 px-3 py-2.5 text-sm text-foreground-700">
              真实文件已落库，可直接下载原始 .docx，系统不生成内容摘要。
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-background-200 pt-3">
              <button
                type="button"
                onClick={() => setPreview(null)}
                className="h-8 cursor-pointer rounded-md border border-background-300 px-3 text-xs text-foreground-600"
              >
                关闭
              </button>
              <button
                type="button"
                disabled={downloading}
                onClick={() => handleDownload(preview)}
                className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:opacity-60"
              >
                <i className={`${downloading ? "ri-loader-4-line animate-spin" : "ri-download-2-line"} text-sm`}></i>
                {downloading ? "下载中…" : "下载文件"}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
