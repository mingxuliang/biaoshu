import { useMemo, useState } from "react";
import Modal from "../../components/Modal";
import { members, memberRoles, type Member } from "@/mocks/members";
import type { Project } from "@/mocks/projects";

interface AssignMembersModalProps {
  open: boolean;
  project: Project | null;
  selected: string[];
  onClose: () => void;
  onSave: (memberIds: string[]) => void;
}

const roleColor: Record<string, string> = {
  管理员: "bg-primary-50 text-primary-600",
  项目经理: "bg-accent-50 text-accent-600",
  撰写专家: "bg-secondary-100 text-secondary-700",
  评标专家: "bg-primary-50 text-primary-600",
};

const statusDot: Record<string, string> = {
  在线: "bg-primary-500",
  忙碌: "bg-accent-500",
  离线: "bg-secondary-400",
};

export default function AssignMembersModal({
  open,
  project,
  selected,
  onClose,
  onSave,
}: AssignMembersModalProps) {
  const [picked, setPicked] = useState<string[]>(selected);

  // 弹窗打开时同步外部选中的成员
  const isOpen = open;
  const draft = useMemo(() => (isOpen ? [...picked] : []), [isOpen, picked]);

  const grouped = useMemo(() => {
    return memberRoles
      .map((role) => ({ role, list: members.filter((m) => m.role === role) }))
      .filter((g) => g.list.length > 0);
  }, []);

  const toggle = (id: string) => {
    setPicked((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const selectedMembers = useMemo(
    () => members.filter((m) => draft.includes(m.id)) as Member[],
    [draft],
  );

  const handleClose = () => {
    setPicked(selected);
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="分配项目人员"
      subtitle={project ? `${project.name} · 编号 ${project.code}` : ""}
      width="max-w-2xl"
    >
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* 成员候选区 */}
        <div className="space-y-4 md:col-span-2">
          {grouped.map((group) => (
            <div key={group.role}>
              <div className="mb-1.5 flex items-center gap-2">
                <span className="text-xs font-medium text-foreground-700">{group.role}</span>
                <span className="rounded-full bg-background-200 px-1.5 py-0.5 text-[10px] text-foreground-500">
                  {group.list.length}
                </span>
              </div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {group.list.map((member) => {
                  const active = picked.includes(member.id);
                  return (
                    <button
                      key={member.id}
                      type="button"
                      onClick={() => toggle(member.id)}
                      className={`flex cursor-pointer items-center gap-2.5 rounded-lg border px-3 py-2 text-left transition-all ${
                        active
                          ? "border-primary-300 bg-primary-50"
                          : "border-background-300 bg-background-50 hover:border-background-400"
                      }`}
                    >
                      <span className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary-100 text-sm font-medium text-secondary-700">
                        {member.name.charAt(0)}
                        <span
                          className={`absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border-2 border-background-50 ${statusDot[member.status]}`}
                        />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-foreground-900">
                          {member.name}
                        </span>
                        <span className="block text-[11px] text-foreground-500">{member.email}</span>
                      </span>
                      <span
                        className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                          active ? "border-primary-500 bg-primary-500 text-background-50" : "border-background-300"
                        }`}
                      >
                        {active && <i className="ri-check-line text-[10px]"></i>}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        {/* 已选成员 */}
        <div className="rounded-lg border border-background-300 bg-background-50 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-medium text-foreground-700">已分配成员</span>
            <span className="rounded-full bg-primary-50 px-1.5 py-0.5 text-[10px] font-medium text-primary-600">
              {selectedMembers.length} 人
            </span>
          </div>
          {selectedMembers.length === 0 ? (
            <p className="py-6 text-center text-xs text-foreground-500">尚未选择成员</p>
          ) : (
            <ul className="space-y-2">
              {selectedMembers.map((m) => (
                <li key={m.id} className="flex items-center gap-2">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-secondary-100 text-xs font-medium text-secondary-700">
                    {m.name.charAt(0)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-medium text-foreground-900">{m.name}</div>
                    <span className={`mt-0.5 inline-block rounded px-1.5 py-0.5 text-[10px] font-medium ${roleColor[m.role]}`}>
                      {m.role}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => toggle(m.id)}
                    className="flex h-6 w-6 cursor-pointer items-center justify-center rounded-md text-foreground-400 transition-colors hover:bg-accent-50 hover:text-accent-500"
                    aria-label={`移除 ${m.name}`}
                  >
                    <i className="ri-close-line text-sm"></i>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="mt-5 flex items-center justify-between border-t border-background-200 pt-4">
        <p className="text-xs text-foreground-500">
          已选 <span className="font-medium text-primary-600">{selectedMembers.length}</span> 人参与本项目
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleClose}
            className="h-9 cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => onSave(picked)}
            className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
          >
            <i className="ri-check-double-line text-sm"></i>
            保存分配
          </button>
        </div>
      </div>
    </Modal>
  );
}