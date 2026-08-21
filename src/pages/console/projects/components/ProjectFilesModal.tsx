import { useState } from "react";
import Modal from "../../components/Modal";
import { projectDocGroups, docGroupMeta, type GroupDoc, type DocGroupKey } from "@/mocks/projectDocs";
import type { Project } from "@/mocks/projects";

interface ProjectFilesModalProps {
  open: boolean;
  project: Project | null;
  onClose: () => void;
  onToast: (message: string) => void;
}

const extColor: Record<GroupDoc["ext"], string> = {
  Word: "text-primary-600 bg-primary-50",
  PDF: "text-accent-600 bg-accent-50",
  Excel: "text-secondary-700 bg-secondary-50",
};

export default function ProjectFilesModal({ open, project, onClose, onToast }: ProjectFilesModalProps) {
  const [downloaded, setDownloaded] = useState<Record<string, boolean>>({});

  const totalCount = projectDocGroups.reduce((s, g) => s + g.docs.length, 0);

  const handleDownload = (doc: GroupDoc) => {
    const blob = new Blob([`文件：${doc.name}\n类别：${doc.ext}\n说明：${doc.desc}\n\n内容要点：\n${doc.content.map((c) => `- ${c}`).join("\n")}`], {
      type: "text/plain;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${project?.code || "project"}-${doc.name.replace(/\.\w+$/, "")}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setDownloaded((prev) => ({ ...prev, [doc.id]: true }));
    onToast(`已开始下载「${doc.name}」`);
    window.setTimeout(() => setDownloaded((prev) => ({ ...prev, [doc.id]: false })), 2500);
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="项目文件下载"
      subtitle={project ? `${project.name} · 共 ${totalCount} 份文档可下载` : ""}
      width="max-w-3xl"
    >
      <div className="space-y-4">
        {projectDocGroups.map((group) => {
          const meta = docGroupMeta[group.key as DocGroupKey];
          return (
            <div key={group.key} className="overflow-hidden rounded-lg border border-background-300 bg-background-50">
              <div className="flex items-center gap-2.5 border-b border-background-200 px-3.5 py-2.5">
                <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md ${meta.color}`}>
                  <i className={`${group.icon} text-sm`}></i>
                </span>
                <span className="text-sm font-semibold text-foreground-900">{group.label}</span>
                <span className="font-label rounded-full bg-background-200 px-1.5 py-0.5 text-[10px] text-foreground-600">
                  {group.docs.length} 份
                </span>
              </div>
              <ul className="divide-y divide-background-200">
                {group.docs.map((doc) => (
                  <li key={doc.id} className="flex items-center gap-3 px-3.5 py-2.5">
                    <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${extColor[doc.ext]}`}>
                      <i className={doc.ext === "Word" ? "ri-file-word-2-line text-base" : doc.ext === "PDF" ? "ri-file-pdf-2-line text-base" : "ri-file-excel-2-line text-base"}></i>
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-foreground-900">{doc.name}</div>
                      <div className="text-[11px] text-foreground-500">
                        {doc.ext} · {doc.size}
                        {doc.pages ? ` · ${doc.pages} 页` : ""} · 更新于 {doc.updated}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleDownload(doc)}
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
            </div>
          );
        })}
      </div>
    </Modal>
  );
}