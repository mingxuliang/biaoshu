import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import Modal from "../../components/Modal";
import { projectTypes, type Project, type ProjectType } from "@/mocks/projects";
import { useAuth } from "@/context/AuthContext";
import { listUsers, type TeamMember } from "@/lib/api";

export interface ProjectFormValues {
  name: string;
  code: string;
  type: ProjectType;
  budget: string;
  deadline: string;
  owner: string;
  memberIds: string[];
  tenderFile?: File;
}

interface ProjectFormModalProps {
  open: boolean;
  mode: "create" | "edit";
  initial?: Project | null;
  initialMemberIds?: string[];
  onClose: () => void;
  onSubmit: (values: ProjectFormValues) => void;
}

const inputCls =
  "h-9 w-full rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500";
const labelCls = "mb-1.5 block text-xs font-medium text-foreground-600";

const ACCEPT = ".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function parseBudget(budget?: string): string {
  if (!budget) return "";
  return budget.replace(/[^\d.]/g, "");
}

export default function ProjectFormModal({
  open,
  mode,
  initial,
  initialMemberIds = [],
  onClose,
  onSubmit,
}: ProjectFormModalProps) {
  const { token, user } = useAuth();
  const [users, setUsers] = useState<TeamMember[]>([]);
  const [form, setForm] = useState({
    name: "",
    code: "",
    type: "工程" as ProjectType,
    budget: "",
    deadline: "",
    owner: "",
  });
  const [memberIds, setMemberIds] = useState<string[]>(initialMemberIds);
  const [openPanel, setOpenPanel] = useState(false);
  const [tenderFile, setTenderFile] = useState<File | undefined>();
  const [existingTenderName, setExistingTenderName] = useState<string | undefined>();
  const [tenderErr, setTenderErr] = useState<string | null>(null);
  const tenderInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open || !token) return;
    let cancelled = false;
    listUsers(token).then((list) => {
      if (!cancelled) setUsers(list);
    }).catch(() => {
      if (!cancelled) setUsers([]);
    });
    return () => {
      cancelled = true;
    };
  }, [open, token]);

  useEffect(() => {
    if (!open) return;
    const defaultOwner = initial?.owner || user?.name || "";
    setForm({
      name: initial?.name ?? "",
      code: initial?.code ?? "",
      type: initial?.type ?? "工程",
      budget: parseBudget(initial?.budget),
      deadline: initial?.deadline ?? "",
      owner: defaultOwner,
    });
    setMemberIds(initialMemberIds);
    setOpenPanel(false);
    setTenderFile(undefined);
    setExistingTenderName(initial?.tenderDoc?.name);
    setTenderErr(null);
    if (tenderInputRef.current) tenderInputRef.current.value = "";
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const grouped = useMemo(() => {
    const roles = Array.from(new Set(users.map((u) => u.role || "成员")));
    return roles
      .map((role) => ({ role, list: users.filter((u) => (u.role || "成员") === role) }))
      .filter((g) => g.list.length > 0);
  }, [users]);

  const ownerCandidates = useMemo(() => {
    const preferred = users.filter((u) => u.role === "项目经理" || u.role === "管理员");
    return preferred.length > 0 ? preferred : users;
  }, [users]);

  const userMap = useMemo(() => {
    const map: Record<string, TeamMember> = {};
    users.forEach((u) => {
      map[u.id] = u;
    });
    return map;
  }, [users]);

  const toggleMember = (id: string) => {
    setMemberIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const handleTenderPick = (file: File) => {
    if (!/\.docx$/i.test(file.name)) {
      setTenderErr("仅支持 .docx 格式的招标文件（暂不支持 .doc / .pdf，请另存为 .docx 后重新上传）");
      return;
    }
    setTenderErr(null);
    setTenderFile(file);
    setExistingTenderName(undefined);
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit({
      name: form.name,
      code: form.code,
      type: form.type,
      budget: form.budget,
      deadline: form.deadline,
      owner: form.owner,
      memberIds,
      tenderFile,
    });
  };

  const isEdit = mode === "edit";
  const displayTenderName = tenderFile?.name || existingTenderName;
  const displayTenderSize = tenderFile ? `${(tenderFile.size / 1024 / 1024).toFixed(1)} MB` : initial?.tenderDoc?.size;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? "编辑投标项目" : "新建投标项目"}
      subtitle={
        isEdit
          ? `更新项目基本信息与人员分配 · ${initial?.code ?? ""}`
          : "创建后可上传招标文件并进入招标解析"
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className={labelCls} htmlFor="np-name">
            项目名称 <span className="text-accent-500">*</span>
          </label>
          <input
            id="np-name"
            type="text"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            placeholder="例如：市智慧交通信号控制系统升级改造"
            className={inputCls}
          />
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className={labelCls} htmlFor="np-code">
              招标编号 <span className="text-accent-500">*</span>
            </label>
            <input
              id="np-code"
              type="text"
              value={form.code}
              onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))}
              placeholder="例如：CG-2026-1022"
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls} htmlFor="np-type">
              项目类型
            </label>
            <select
              id="np-type"
              value={form.type}
              onChange={(e) => setForm((f) => ({ ...f, type: e.target.value as ProjectType }))}
              className={`${inputCls} cursor-pointer`}
            >
              {projectTypes.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelCls} htmlFor="np-budget">
              预算金额（万元）
            </label>
            <input
              id="np-budget"
              type="text"
              value={form.budget}
              onChange={(e) => setForm((f) => ({ ...f, budget: e.target.value }))}
              placeholder="例如：2980"
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls} htmlFor="np-deadline">
              投标截止日期
            </label>
            <input
              id="np-deadline"
              type="date"
              value={form.deadline}
              onChange={(e) => setForm((f) => ({ ...f, deadline: e.target.value }))}
              className={inputCls}
            />
          </div>
        </div>
        <div>
          <label className={labelCls} htmlFor="np-owner">
            项目负责人
          </label>
          <select
            id="np-owner"
            value={form.owner}
            onChange={(e) => setForm((f) => ({ ...f, owner: e.target.value }))}
            className={`${inputCls} cursor-pointer`}
          >
            {form.owner && !ownerCandidates.some((m) => m.name === form.owner) && (
              <option value={form.owner}>{form.owner}</option>
            )}
            {ownerCandidates.map((m) => (
              <option key={m.id} value={m.name}>
                {m.name}（{m.role}）
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls} htmlFor="np-members">
            分配项目人员
          </label>
          <div className="relative">
            <button
              id="np-members"
              type="button"
              onClick={() => setOpenPanel((v) => !v)}
              className="flex h-9 w-full cursor-pointer items-center justify-between gap-2 rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20"
            >
              <span className="flex min-w-0 items-center gap-2">
                <i className="ri-team-line text-sm text-foreground-500"></i>
                {memberIds.length > 0 ? (
                  <span className="truncate">
                    已选{" "}
                    {memberIds
                      .map((id) => userMap[id]?.name)
                      .filter(Boolean)
                      .join("、")}
                  </span>
                ) : (
                  <span className="text-foreground-500">从已注册用户中选择成员（可多选）</span>
                )}
              </span>
              <span className="flex shrink-0 items-center gap-1.5">
                {memberIds.length > 0 && (
                  <span className="rounded-full bg-primary-50 px-1.5 py-0.5 text-[10px] font-medium text-primary-600">
                    {memberIds.length} 人
                  </span>
                )}
                <i
                  className={`ri-arrow-down-s-line text-sm text-foreground-500 transition-transform ${
                    openPanel ? "rotate-180" : ""
                  }`}
                ></i>
              </span>
            </button>

            {openPanel && (
              <>
                <div className="fixed inset-0 z-40 cursor-default" onClick={() => setOpenPanel(false)} />
                <div className="absolute left-0 right-0 top-[calc(100%+6px)] z-50 max-h-72 overflow-y-auto rounded-lg border border-background-300 bg-background-100 p-2 shadow-lg">
                  <div className="mb-2 flex items-center justify-between px-1">
                    <span className="text-xs font-medium text-foreground-600">已注册用户</span>
                    {memberIds.length > 0 && (
                      <button
                        type="button"
                        onClick={() => setMemberIds([])}
                        className="cursor-pointer text-[11px] text-foreground-500 transition-colors hover:text-accent-500"
                      >
                        清空选择
                      </button>
                    )}
                  </div>
                  {grouped.map((group) => (
                    <div key={group.role} className="mb-1 last:mb-0">
                      <div className="flex items-center gap-1.5 px-1 py-1">
                        <span className="text-[11px] font-medium text-foreground-500">{group.role}</span>
                        <span className="rounded-full bg-background-200 px-1.5 py-0.5 text-[10px] text-foreground-500">
                          {group.list.length}
                        </span>
                      </div>
                      <div className="mb-1 grid grid-cols-1 gap-1 sm:grid-cols-2">
                        {group.list.map((member) => {
                          const active = memberIds.includes(member.id);
                          return (
                            <label
                              key={member.id}
                              className={`flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-1.5 transition-all ${
                                active
                                  ? "border-primary-300 bg-primary-50"
                                  : "border-background-200 bg-background-50 hover:border-background-300"
                              }`}
                            >
                              <input
                                type="checkbox"
                                checked={active}
                                onChange={() => toggleMember(member.id)}
                                className="h-3.5 w-3.5 accent-primary-500"
                              />
                              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-secondary-100 text-[10px] font-medium text-secondary-700">
                                {member.name.charAt(0)}
                              </span>
                              <span className="min-w-0 flex-1">
                                <span className="block truncate text-xs font-medium text-foreground-900">
                                  {member.name}
                                </span>
                                <span className="block truncate text-[10px] text-foreground-500">{member.email}</span>
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
        <div>
          <label className={labelCls} htmlFor="np-tender">
            招标文件
            <span className="ml-1 font-normal text-foreground-500">
              （{isEdit ? "重新选择可替换为真实 .docx 文件" : "可选，后续可在招标解析中上传"}）
            </span>
          </label>
          <input
            ref={tenderInputRef}
            id="np-tender"
            type="file"
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleTenderPick(file);
            }}
          />
          {displayTenderName ? (
            <div className="flex items-center gap-3 rounded-md border border-primary-200 bg-primary-50/60 px-3 py-2.5">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-500 text-background-50">
                <i className="ri-file-text-line text-base"></i>
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-foreground-900">{displayTenderName}</div>
                <div className="mt-0.5 text-[11px] text-foreground-500">
                  DOCX{displayTenderSize ? ` · ${displayTenderSize}` : ""}
                  {tenderFile ? " · 待上传" : " · 已归档"}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  title="替换文件"
                  onClick={() => tenderInputRef.current?.click()}
                  className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-colors hover:bg-primary-100 hover:text-primary-600"
                >
                  <i className="ri-refresh-line text-sm"></i>
                </button>
                <button
                  type="button"
                  title="移除文件"
                  onClick={() => {
                    setTenderFile(undefined);
                    setExistingTenderName(undefined);
                    if (tenderInputRef.current) tenderInputRef.current.value = "";
                  }}
                  className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-colors hover:bg-secondary-100 hover:text-secondary-700"
                >
                  <i className="ri-close-line text-sm"></i>
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => tenderInputRef.current?.click()}
              className="flex w-full cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed border-background-300 bg-background-50 px-3 py-3 text-sm text-foreground-500 transition-colors hover:border-primary-300 hover:bg-primary-50/40 hover:text-primary-600"
            >
              <i className="ri-upload-cloud-2-line text-base"></i>
              点击上传招标文件（仅支持 .docx）
            </button>
          )}
          {tenderErr && (
            <p className="mt-1.5 flex items-center gap-1 text-xs text-accent-600">
              <i className="ri-error-warning-line"></i>
              {tenderErr}
            </p>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="h-9 cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
          >
            取消
          </button>
          <button
            type="submit"
            className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
          >
            {isEdit ? (
              <>
                <i className="ri-check-double-line text-sm"></i>
                保存修改
              </>
            ) : (
              <>
                <i className="ri-sparkling-2-line text-sm"></i>
                创建并解析
              </>
            )}
          </button>
        </div>
      </form>
    </Modal>
  );
}
