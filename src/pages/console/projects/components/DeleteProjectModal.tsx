import Modal from "../../components/Modal";
import type { Project } from "@/mocks/projects";

interface DeleteProjectModalProps {
  open: boolean;
  project: Project | null;
  onClose: () => void;
  onConfirm: () => void;
}

export default function DeleteProjectModal({ open, project, onClose, onConfirm }: DeleteProjectModalProps) {
  if (!project) return null;

  return (
    <Modal
      open={open}
      title="删除项目"
      subtitle="此操作不可撤销，请谨慎确认"
      onClose={onClose}
      width="max-w-md"
    >
      <div className="flex items-start gap-3 rounded-lg border border-secondary-300 bg-secondary-50 p-3.5">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-secondary-200 text-secondary-800">
          <i className="ri-error-warning-line text-lg"></i>
        </span>
        <div className="text-sm leading-relaxed text-secondary-900">
          <p className="font-medium">⚠️ 即将删除项目「{project.name}」</p>
          <p className="mt-1 text-xs text-secondary-700">
            删除后该项目将无法恢复，包括：撰写进度、AI 预测评分、人员分配记录，以及上传的全部项目文件（招标文件、解析结果、投标文档等）将<span className="font-semibold">同步永久删除</span>。
          </p>
        </div>
      </div>
      <div className="mt-4 flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="h-9 cursor-pointer whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-4 text-sm text-foreground-700 transition-colors hover:bg-background-200"
        >
          取消
        </button>
        <button
          type="button"
          onClick={onConfirm}
          className="h-9 cursor-pointer whitespace-nowrap rounded-md bg-secondary-600 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-secondary-700"
        >
          确认删除
        </button>
      </div>
    </Modal>
  );
}