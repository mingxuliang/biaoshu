import { useEffect, useMemo, useState, type FormEvent } from "react";
import PageHeader from "../components/PageHeader";
import Modal from "../components/Modal";
import Toast from "../components/Toast";
import { useAuth } from "@/context/AuthContext";
import { ApiError, inviteUser, listUsers, updateUser, type TeamMember } from "@/lib/api";
import { hasPerm } from "@/lib/permissions";

type MemberRole = "管理员" | "项目经理" | "撰写专家" | "评标专家";

const memberRoles: MemberRole[] = ["管理员", "项目经理", "撰写专家", "评标专家"];

const roleStyles: Record<string, string> = {
  管理员: "bg-primary-50 text-primary-600 border-primary-200",
  项目经理: "bg-accent-50 text-accent-600 border-accent-200",
  撰写专家: "bg-secondary-100 text-secondary-700 border-secondary-200",
  评标专家: "bg-secondary-100 text-secondary-700 border-secondary-200",
  成员: "bg-secondary-100 text-secondary-700 border-secondary-200",
};

const rolePermissions = [
  {
    role: "管理员",
    desc: "全部功能与成员管理权限",
    permissions: [true, true, true, true, true],
  },
  {
    role: "项目经理",
    desc: "负责项目全流程统筹与提交",
    permissions: [true, true, true, false, false],
  },
  {
    role: "撰写专家",
    desc: "专注标书内容撰写与修订",
    permissions: [false, true, true, false, false],
  },
  {
    role: "评标专家",
    desc: "参与标书质量复核",
    permissions: [false, false, true, false, false],
  },
];

const permissionNames = ["项目创建与编辑", "AI 标书撰写", "报告导出", "成员与权限管理", "系统设置"];

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

export default function TeamPage() {
  const { token, user: me } = useAuth();
  const canManage = hasPerm(me?.role, "members");
  const [memberList, setMemberList] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [roleFilter, setRoleFilter] = useState<string>("全部");
  const [inviteOpen, setInviteOpen] = useState(false);
  const [editMember, setEditMember] = useState<TeamMember | null>(null);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });
  const [submitting, setSubmitting] = useState(false);

  const [form, setForm] = useState({
    name: "",
    email: "",
    phone: "",
    role: "撰写专家" as MemberRole,
  });
  const [editForm, setEditForm] = useState({ name: "", phone: "", role: "撰写专家" as string });

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const reload = async () => {
    if (!token) return;
    const list = await listUsers(token);
    setMemberList(list);
  };

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    listUsers(token)
      .then((list) => {
        if (!cancelled) setMemberList(list);
      })
      .catch((err) => {
        if (!cancelled) showToast(err instanceof ApiError ? err.message : "无法加载成员列表", "error");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const stats = useMemo(() => {
    const active = memberList.filter((m) => !m.disabled).length;
    const disabled = memberList.filter((m) => m.disabled).length;
    const roles = new Set(memberList.map((m) => m.role || "成员")).size;
    return { total: memberList.length, active, disabled, roles };
  }, [memberList]);

  const filtered = useMemo(
    () =>
      memberList.filter((m) => {
        const matchKeyword =
          m.name.includes(keyword) || m.email.toLowerCase().includes(keyword.toLowerCase());
        const matchRole = roleFilter === "全部" || m.role === roleFilter;
        return matchKeyword && matchRole;
      }),
    [memberList, keyword, roleFilter],
  );

  const handleInvite = async (e: FormEvent) => {
    e.preventDefault();
    if (!token) return;
    if (!form.name.trim() || !form.email.trim()) {
      showToast("请填写姓名与邮箱", "error");
      return;
    }
    setSubmitting(true);
    try {
      const created = await inviteUser(token, {
        name: form.name.trim(),
        email: form.email.trim(),
        phone: form.phone.trim(),
        role: form.role,
      });
      setInviteOpen(false);
      setForm({ name: "", email: "", phone: "", role: "撰写专家" });
      await reload();
      showToast(`已创建账号 ${created.email}，初始密码 ${created.initialPassword}（请自行告知对方）`);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "邀请失败", "error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleEdit = async (e: FormEvent) => {
    e.preventDefault();
    if (!token || !editMember) return;
    setSubmitting(true);
    try {
      await updateUser(token, editMember.id, {
        name: editForm.name.trim(),
        phone: editForm.phone.trim(),
        role: editForm.role,
      });
      setEditMember(null);
      await reload();
      showToast("成员资料已更新");
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "保存失败", "error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggleDisabled = async (member: TeamMember) => {
    if (!token) return;
    if (member.id === me?.id) {
      showToast("不能停用当前登录账号", "error");
      return;
    }
    try {
      await updateUser(token, member.id, { disabled: !member.disabled });
      await reload();
      showToast(member.disabled ? `${member.name} 已重新启用` : `${member.name} 已停用`);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "操作失败", "error");
    }
  };

  const inputCls =
    "h-9 w-full rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500";
  const labelCls = "mb-1.5 block text-xs font-medium text-foreground-600";

  const statCards = [
    { label: "成员总数", value: stats.total, icon: "ri-team-line", gradient: "from-primary-400 to-primary-600", bar: "from-primary-500 to-primary-400" },
    { label: "启用账号", value: stats.active, icon: "ri-user-follow-line", gradient: "from-primary-400 to-primary-600", bar: "from-primary-500 to-primary-400" },
    { label: "已停用", value: stats.disabled, icon: "ri-user-unfollow-line", gradient: "from-accent-400 to-accent-500", bar: "from-accent-500 to-accent-400" },
    { label: "角色类型", value: stats.roles, icon: "ri-user-settings-line", gradient: "from-secondary-400 to-secondary-500", bar: "from-secondary-400 to-secondary-300" },
  ];

  return (
    <div>
      <PageHeader
        title="团队与账号管理"
        description="按角色强制鉴权：管理员可邀请、改角色与停用账号；其他角色无法进入本页。"
        actions={
          canManage ? (
          <button
            type="button"
            onClick={() => setInviteOpen(true)}
            className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
          >
            <i className="ri-user-add-line text-sm"></i>
            邀请成员
          </button>
          ) : undefined
        }
      />

      <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {statCards.map((card) => (
          <div
            key={card.label}
            className="group relative flex items-center gap-3 overflow-hidden rounded-lg border border-background-300 bg-background-100 p-3.5 transition-all duration-300 hover:border-primary-300/60"
          >
            <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${card.gradient} text-background-50`}>
              <i className={`${card.icon} text-lg`}></i>
            </span>
            <div className="min-w-0 flex-1">
              <div className="font-label text-[11px] text-foreground-500">{card.label}</div>
              <div className="font-heading text-gradient mt-0.5 text-xl font-bold tracking-wide">{card.value}</div>
            </div>
            <div className={`absolute bottom-0 left-0 right-0 h-[2px] bg-gradient-to-r ${card.bar} opacity-0 transition-opacity duration-300 group-hover:opacity-100`} />
          </div>
        ))}
      </div>

      <div className="mb-4 flex flex-col gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5 lg:flex-row lg:items-center">
        <div className="relative flex-1">
          <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-xs text-foreground-500"></i>
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索成员姓名或邮箱…"
            className={`${inputCls} pl-9`}
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {["全部", ...memberRoles].map((role) => (
            <button
              key={role}
              type="button"
              onClick={() => setRoleFilter(role)}
              className={`cursor-pointer whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-medium transition-all ${
                roleFilter === role
                  ? "border-primary-200 bg-primary-50 text-primary-600"
                  : "border-background-300 bg-transparent text-foreground-600 hover:border-background-400 hover:text-foreground-700"
              }`}
            >
              {role}
            </button>
          ))}
        </div>
      </div>

      <div className="mb-5 overflow-hidden rounded-lg border border-background-300 bg-background-100">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left">
            <thead>
              <tr className="font-label border-b border-background-300 bg-background-50 text-xs text-foreground-500">
                <th className="px-4 py-3 font-medium">成员</th>
                <th className="px-3 py-3 font-medium">角色</th>
                <th className="px-3 py-3 font-medium">参与项目</th>
                <th className="px-3 py-3 font-medium">账号状态</th>
                <th className="px-3 py-3 font-medium">加入时间</th>
                <th className="px-3 py-3 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((member) => (
                <tr
                  key={member.id}
                  className={`border-b border-background-200 transition-colors last:border-0 hover:bg-primary-50/30 ${
                    member.disabled ? "opacity-50" : ""
                  }`}
                >
                  <td className="px-4 py-3.5">
                    <div className="flex items-center gap-2.5">
                      <span className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary-100 text-sm font-medium text-secondary-700">
                        {member.name.charAt(0)}
                      </span>
                      <div>
                        <div className="text-sm font-medium text-foreground-900">{member.name}</div>
                        <div className="text-xs text-foreground-500">{member.email}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-3.5">
                    <span
                      className={`inline-flex whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium ${
                        roleStyles[member.role] || roleStyles["成员"]
                      }`}
                    >
                      {member.role}
                    </span>
                  </td>
                  <td className="font-label px-3 py-3.5 text-sm text-foreground-500">{member.projectCount ?? 0}</td>
                  <td className="px-3 py-3.5">
                    <span className="flex items-center gap-1.5 text-sm text-foreground-500">
                      <span className={`inline-flex h-2 w-2 rounded-full ${member.disabled ? "bg-foreground-400" : "bg-primary-500"}`} />
                      {member.disabled ? "已停用" : "启用"}
                    </span>
                  </td>
                  <td className="px-3 py-3.5 whitespace-nowrap text-sm text-foreground-500">{member.joinedAt || "—"}</td>
                  <td className="px-3 py-3.5">
                    <div className="flex items-center justify-end gap-0.5">
                      <button
                        type="button"
                        title="编辑成员"
                        onClick={() => {
                          setEditMember(member);
                          setEditForm({
                            name: member.name,
                            phone: member.phone || "",
                            role: (memberRoles.includes(member.role as MemberRole) ? member.role : "撰写专家") as string,
                          });
                        }}
                        className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-primary-50 hover:text-primary-600"
                      >
                        <i className="ri-pencil-line text-sm"></i>
                      </button>
                      <button
                        type="button"
                        title={member.disabled ? "启用成员" : "停用成员"}
                        onClick={() => void handleToggleDisabled(member)}
                        className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-accent-50 hover:text-accent-600"
                      >
                        <i className={`${member.disabled ? "ri-play-circle-line" : "ri-pause-circle-line"} text-sm`}></i>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {!loading && filtered.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-16 text-center">
                    <i className="ri-user-unfollow-line text-3xl text-foreground-400"></i>
                    <p className="mt-3 text-sm text-foreground-500">没有找到匹配的成员</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-lg border border-background-300 bg-background-100 p-5">
        <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
            <i className="ri-shield-check-line text-primary-500 text-sm"></i>
            角色说明
          </h3>
          <p className="text-xs text-foreground-500">对照表仅作职责说明，当前未做接口级强制鉴权</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left">
            <thead>
              <tr className="border-b border-background-300 text-xs text-foreground-500">
                <th className="py-2.5 pr-4 font-medium">权限项</th>
                {rolePermissions.map((rp) => (
                  <th key={rp.role} className="px-3 py-2.5 text-center font-medium">
                    {rp.role}
                    <span className="block text-[10px] font-normal text-foreground-500">{rp.desc}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {permissionNames.map((name, idx) => (
                <tr key={name} className="border-b border-background-200 last:border-0">
                  <td className="py-3 pr-4 text-sm text-foreground-600">{name}</td>
                  {rolePermissions.map((rp) => (
                    <td key={rp.role} className="px-3 py-3 text-center">
                      {rp.permissions[idx] ? (
                        <i className="ri-checkbox-circle-line text-base text-primary-500"></i>
                      ) : (
                        <i className="ri-close-circle-line text-base text-foreground-400"></i>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Modal
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        title="邀请新成员"
        subtitle="将直接创建可登录账号，初始密码为 123456，请自行告知对方（系统不发送邮件）"
      >
        <form onSubmit={handleInvite} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className={labelCls} htmlFor="inv-name">
                成员姓名 <span className="text-accent-500">*</span>
              </label>
              <input
                id="inv-name"
                type="text"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="例如：张伟"
                className={inputCls}
              />
            </div>
            <div>
              <label className={labelCls} htmlFor="inv-role">
                分配角色
              </label>
              <select
                id="inv-role"
                value={form.role}
                onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as MemberRole }))}
                className={`${inputCls} cursor-pointer`}
              >
                {memberRoles.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <label className={labelCls} htmlFor="inv-email">
              工作邮箱 <span className="text-accent-500">*</span>
            </label>
            <input
              id="inv-email"
              type="email"
              value={form.email}
              onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
              placeholder="name@company.com"
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls} htmlFor="inv-phone">
              手机号码
            </label>
            <input
              id="inv-phone"
              type="text"
              value={form.phone}
              onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
              placeholder="选填"
              className={inputCls}
            />
          </div>
          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => setInviteOpen(false)}
              className="h-9 cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:opacity-50"
            >
              <i className="ri-user-add-line text-sm"></i>
              {submitting ? "创建中…" : "创建账号"}
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={!!editMember}
        onClose={() => setEditMember(null)}
        title="编辑成员"
        subtitle={editMember?.email || ""}
      >
        <form onSubmit={handleEdit} className="space-y-4">
          <div>
            <label className={labelCls} htmlFor="edit-name">
              姓名
            </label>
            <input
              id="edit-name"
              type="text"
              value={editForm.name}
              onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls} htmlFor="edit-phone">
              手机号码
            </label>
            <input
              id="edit-phone"
              type="text"
              value={editForm.phone}
              onChange={(e) => setEditForm((f) => ({ ...f, phone: e.target.value }))}
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls} htmlFor="edit-role">
              角色
            </label>
            <select
              id="edit-role"
              value={editForm.role}
              onChange={(e) => setEditForm((f) => ({ ...f, role: e.target.value }))}
              className={`${inputCls} cursor-pointer`}
            >
              {memberRoles.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => setEditMember(null)}
              className="h-9 cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="h-9 cursor-pointer whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:opacity-50"
            >
              保存
            </button>
          </div>
        </form>
      </Modal>

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}
