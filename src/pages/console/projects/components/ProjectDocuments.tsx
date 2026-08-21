import { useState } from "react";
import { Link } from "react-router-dom";
import Modal from "../../components/Modal";
import { projectDocGroups, docGroupMeta, type GroupDoc, type DocGroupKey } from "@/mocks/projectDocs";

const extColor: Record<GroupDoc["ext"], string> = {
  Word: "text-primary-600 bg-primary-50",
  PDF: "text-accent-600 bg-accent-50",
  Excel: "text-secondary-700 bg-secondary-50",
};

const statusColor: Record<string, string> = {
  已解析: "bg-primary-100 text-primary-600",
  已完成: "bg-secondary-100 text-secondary-700",
  修订中: "bg-accent-100 text-accent-600",
};

export default function ProjectDocuments() {
  const [preview, setPreview] = useState<{ doc: GroupDoc; groupLabel: string } | null>(null);

  const totalCount = projectDocGroups.reduce((s, g) => s + g.docs.length, 0);

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
            <i className="ri-folder-2-line text-primary-500 text-sm"></i>
            全部文档
          </h3>
          <p className="mt-1 text-xs text-foreground-500">
            共 {totalCount} 份文档，按招标文件、招标解析、技术标、商务标四大类归档，点击可查看内容详情
          </p>
        </div>
        <span className="rounded-full border border-background-300 bg-background-50 px-2.5 py-1 text-xs text-foreground-500">
          {totalCount} 份文档
        </span>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {projectDocGroups.map((group) => {
          const meta = docGroupMeta[group.key as DocGroupKey];
          return (
            <div
              key={group.key}
              className="group overflow-hidden rounded-lg border border-background-300 bg-background-100 transition-colors hover:border-primary-300/60"
            >
              {/* 分组头 */}
              <div className="relative flex items-center gap-3 border-b border-background-200 px-4 py-3">
                <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-md ${meta.color}`}>
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
                <i className="ri-folder-line text-lg text-foreground-300 transition-colors group-hover:text-primary-400"></i>
              </div>

              {/* 文档列表 */}
              <div className="divide-y divide-background-200">
                {group.docs.map((doc) => (
                  <button
                    key={doc.id}
                    type="button"
                    onClick={() => setPreview({ doc, groupLabel: group.label })}
                    className="flex w-full cursor-pointer items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-background-50"
                  >
                    <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${extColor[doc.ext]}`}>
                      <i className={doc.ext === "Word" ? "ri-file-word-2-line text-base" : doc.ext === "PDF" ? "ri-file-pdf-2-line text-base" : "ri-file-excel-2-line text-base"}></i>
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-foreground-900">
                        {doc.name}
                      </span>
                      <span className="block text-[11px] text-foreground-500">
                        {doc.ext} · {doc.size}
                        {doc.pages ? ` · ${doc.pages} 页` : ""} · 更新于 {doc.updated}
                      </span>
                    </span>
                    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${statusColor[doc.status] ?? "bg-background-200 text-foreground-600"}`}>
                      {doc.status}
                    </span>
                    <i className="ri-eye-line shrink-0 text-sm text-foreground-400 transition-colors hover:text-primary-500"></i>
                  </button>
                ))}
              </div>
            </div>
          );
        })}

        {/* 操作卡片 */}
        <div className="flex flex-col items-start justify-center gap-3 rounded-lg border border-dashed border-background-300 bg-background-100/60 p-5">
          <div className="text-sm font-medium text-foreground-800">需要继续推进这个项目？</div>
          <p className="text-xs text-foreground-500">
            从招标解析到技术标撰写、AI 预审与修改闭环，全流程在此项目下串联完成。
          </p>
          <div className="mt-1 flex flex-wrap gap-2">
            <Link
              to="/console/parse"
              className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-3.5 text-xs font-medium text-foreground-700 transition-colors hover:bg-background-200"
            >
              <i className="ri-file-settings-line text-sm"></i>
              招标解析
            </Link>
            <Link
              to="/console/writer"
              className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-3.5 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
            >
              <i className="ri-edit-2-line text-sm"></i>
              进入撰写工作台
            </Link>
            <Link
              to="/console/audit"
              className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-accent-200 bg-accent-50 px-3.5 text-xs font-medium text-accent-600 transition-colors hover:bg-accent-100"
            >
              <i className="ri-shield-check-line text-sm"></i>
              AI 预审
            </Link>
          </div>
        </div>
      </div>

      {/* 文档详情预览弹窗 */}
      <Modal
        open={!!preview}
        onClose={() => setPreview(null)}
        title={preview?.doc.name ?? ""}
        subtitle={preview ? `${preview.groupLabel} · ${preview.doc.ext} · ${preview.doc.size} · ${preview.doc.pages ?? "—"} 页 · 更新于 ${preview.doc.updated}` : ""}
      >
        {preview && (
          <div className="space-y-4">
            <div>
              <div className="font-label mb-1.5 text-xs text-foreground-500">文件说明</div>
              <p className="rounded-md bg-background-50 px-3 py-2.5 text-sm leading-relaxed text-foreground-800">
                {preview.doc.desc}
              </p>
            </div>
            <div>
              <div className="font-label mb-1.5 text-xs text-foreground-500">内容要点</div>
              <ul className="space-y-2">
                {preview.doc.content.map((item, i) => (
                  <li key={i} className="flex items-start gap-2.5 rounded-md bg-background-50 px-3 py-2 text-sm leading-relaxed text-foreground-700">
                    <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-primary-50 text-[10px] font-bold text-primary-500">
                      {i + 1}
                    </span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-background-200 pt-3">
              <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${statusColor[preview.doc.status] ?? "bg-background-200 text-foreground-600"}`}>
                {preview.doc.status}
              </span>
              <button
                type="button"
                onClick={() => setPreview(null)}
                className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
              >
                <i className="ri-download-2-line text-sm"></i>
                下载文件
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}