import { useEffect, useState } from "react";
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
import type { Project } from "@/mocks/projects";

interface ProjectFilesModalProps {
  open: boolean;
  project: Project | null;
  onClose: () => void;
  onToast: (message: string, type?: "success" | "error") => void;
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

export default function ProjectFilesModal({ open, project, onClose, onToast }: ProjectFilesModalProps) {
  const { token } = useAuth();
  const [tenderDocs, setTenderDocs] = useState<TenderDocumentSummary[]>([]);
  const [bidDocs, setBidDocs] = useState<BidDocumentSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [downloaded, setDownloaded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!open || !project || !token) return;
    let cancelled = false;
    setLoading(true);
    getProjectDocuments(token, project.id)
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
  }, [open, project, token]);

  const totalCount = tenderDocs.length + bidDocs.length;

  const handleDownload = async (kind: "tender" | "bid", id: string, name: string) => {
    try {
      const blob = kind === "tender" ? await downloadTenderDocument(id) : await downloadBidDocumentFile(id);
      triggerFileDownload(blob, name);
      setDownloaded((prev) => ({ ...prev, [id]: true }));
      onToast(`已开始下载「${name}」`);
      window.setTimeout(() => setDownloaded((prev) => ({ ...prev, [id]: false })), 2500);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "下载失败，请稍后重试", "error");
    }
  };

  const groups = [
    {
      key: "tender",
      label: "招标文件",
      icon: "ri-file-list-3-line",
      color: "bg-primary-50 text-primary-600",
      docs: tenderDocs.map((d) => ({
        id: d.id,
        name: d.filename,
        kind: "tender" as const,
        meta: `DOCX · ${formatSize(d.sizeBytes)} · ${formatTime(d.uploadedAt)}`,
      })),
    },
    {
      key: "bid",
      label: "投标文件与工作台产出",
      icon: "ri-file-word-2-line",
      color: "bg-accent-50 text-accent-600",
      docs: bidDocs.map((d) => ({
        id: d.id,
        name: d.filename,
        kind: "bid" as const,
        meta: `DOCX · ${formatSize(d.sizeBytes)} · ${SOURCE_LABELS[d.source] || d.source} · ${formatTime(d.uploadedAt)}`,
      })),
    },
  ];

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="项目文件下载"
      subtitle={project ? `${project.name} · ${loading ? "加载中" : `共 ${totalCount} 份真实文档`}` : ""}
      width="max-w-3xl"
    >
      <div className="space-y-4">
        {groups.map((group) => (
          <div key={group.key} className="overflow-hidden rounded-lg border border-background-300 bg-background-50">
            <div className="flex items-center gap-2.5 border-b border-background-200 px-3.5 py-2.5">
              <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md ${group.color}`}>
                <i className={`${group.icon} text-sm`}></i>
              </span>
              <span className="text-sm font-semibold text-foreground-900">{group.label}</span>
              <span className="font-label rounded-full bg-background-200 px-1.5 py-0.5 text-[10px] text-foreground-600">
                {group.docs.length} 份
              </span>
            </div>
            {group.docs.length === 0 ? (
              <div className="px-3.5 py-6 text-center text-xs text-foreground-500">该项目暂无此类文件</div>
            ) : (
              <ul className="divide-y divide-background-200">
                {group.docs.map((doc) => (
                  <li key={doc.id} className="flex items-center gap-3 px-3.5 py-2.5">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary-50 text-primary-600">
                      <i className="ri-file-word-2-line text-base"></i>
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-foreground-900">{doc.name}</div>
                      <div className="text-[11px] text-foreground-500">{doc.meta}</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleDownload(doc.kind, doc.id, doc.name)}
                      className={`flex h-8 shrink-0 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md px-3 text-xs font-medium transition-colors ${
                        downloaded[doc.id]
                          ? "bg-secondary-100 text-secondary-700"
                          : "bg-primary-500 text-background-50 hover:bg-primary-600"
                      }`}
                    >
                      <i className={downloaded[doc.id] ? "ri-check-line text-sm" : "ri-download-2-line text-sm"}></i>
                      {downloaded[doc.id] ? "已下载" : "下载"}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </Modal>
  );
}
