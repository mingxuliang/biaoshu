import { useMemo, useState, type FormEvent } from "react";
import PageHeader from "../components/PageHeader";
import Modal from "../components/Modal";
import Toast from "../components/Toast";
import {
  members as mockMembers,
  memberRoles,
  rolePermissions,
  type Member,
  type MemberRole,
  type MemberStatus,
} from "@/mocks/members";

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

const roleStyles: Record<MemberRole, string> = {
  管理员: "bg-primary-50 text-primary-600 border-primary-200",
  项目经理: "bg-accent-50 text-accent-600 border-accent-200",
  撰写专家: "bg-secondary-100 text-secondary-700 border-secondary-200",
  评标专家: "bg-secondary-100 text-secondary-700 border-secondary-200",
};

const statusDot: Record<MemberStatus, string> = {
  在线: "bg-primary-500",
  忙碌: "bg-accent-500",
  离线: "bg-foreground-400",
};

export default function TeamPage() {
  const [memberList, setMemberList] = useState<Member[]>(mockMembers);
  const [keyword, setKeyword] = useState("");
  const [roleFilter, setRoleFilter] = useState<string>("全部");
  const [inviteOpen, setInviteOpen] = useState(false);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });
  const [disabled, setDisabled] = useState<Record<string, boolean>>({});

  const [form, setForm] = useState({
    name: "",
    email: "",
    phone: "",
    role: "撰写专家" as MemberRole,
    note: "",
  });

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const stats = useMemo(() => {
    const online = memberList.filter((m) => m.status === "在线").length;
    const busy = memberList.filter((m) => m.status === "忙碌").length;
    return { total: memberList.length, online, busy, roles: memberRoles.length };
  }, [memberList]);

  const filtered = useMemo(
    () =>
      memberList.filter((m) => {
        const matchKeyword = m.name.includes(keyword) || m.email.toLowerCase().includes(keyword.toLowerCase());
        const matchRole = roleFilter === "全部" || m.role === roleFilter;
        return matchKeyword && matchRole;
      }),
    [memberList, keyword, roleFilter]
  );

  const handleInvite = (e: FormEvent) => {
    e.preventDefault();
    if (!form.name.trim() || !form.email.trim()) {
      showToast("请填写姓名与邮箱", "error");
      return;
    }
    const newMember: Member = {
      id: `m-${Date.now()}`,
      name: form.name.trim(),
      role: form.role,
      email: form.email.trim(),
      phone: form.phone || "未填写",
      status: "离线",
      lastActive: "尚未登录",
      projectCount: 0,
      joinedAt: "2026-08-14",
    };
    setMemberList((prev) => [newMember, ...prev]);
    setInviteOpen(false);
    setForm({ name: "", email: "", phone: "", role: "撰写专家", note: "" });
    showToast(`邀请已发送至 ${newMember.email}`);
  };

  const inputCls =
    "h-9 w-full rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500";
  const labelCls = "mb-1.5 block text-xs font-medium text-foreground-600";

  const statCards = [
    { label: "成员总数", value: stats.total, icon: "ri-team-line", gradient: "from-primary-400 to-primary-600", bar: "from-primary-500 to-primary-400" },
    { label: "在线成员", value: stats.online, icon: "ri-wifi-line", gradient: "from-primary-400 to-primary-600", bar: "from-primary-500 to-primary-400" },
    { label: "角色类型", value: stats.roles, icon: "ri-user-settings-line", gradient: "from-accent-400 to-accent-500", bar: "from-accent-500 to-accent-400" },
    { label: "活跃成员", value: stats.online + stats.busy, icon: "ri-user-heart-line", gradient: "from-secondary-400 to-secondary-500", bar: "from-secondary-400 to-secondary-300" },
  ];

  return (
    <div>
      <PageHeader
        title="团队与账号管理"
        description="管理团队成员、分配角色权限，确保标书撰写与评标工作有序协作。"
        actions={
          <button
            type="button"
            onClick={() => setInviteOpen(true)}
            className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
          >
            <i className="ri-user-add-line text-sm"></i>
            邀请成员
          </button>
        }
      />

      {/* 统计 */}
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

      {/* 筛选 */}
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

      {/* 成员表格 */}
      <div className="mb-5 overflow-hidden rounded-lg border border-background-300 bg-background-100">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-left">
            <thead>
              <tr className="font-label border-b border-background-300 bg-background-50 text-xs text-foreground-500">
                <th className="px-4 py-3 font-medium">成员</th>
                <th className="px-3 py-3 font-medium">角色</th>
                <th className="px-3 py-3 font-medium">参与项目</th>
                <th className="px-3 py-3 font-medium">状态</th>
                <th className="px-3 py-3 font-medium">最近活跃</th>
                <th className="px-3 py-3 font-medium">加入时间</th>
                <th className="px-3 py-3 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((member) => {
                const isDisabled = disabled[member.id];
                return (
                  <tr
                    key={member.id}
                    className={`border-b border-background-200 transition-colors last:border-0 hover:bg-primary-50/30 ${
                      isDisabled ? "opacity-50" : ""
                    }`}
                  >
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-2.5">
                        <span className="relative flex h-8 w-8 items-center justify-center rounded-full bg-secondary-100 text-sm font-medium text-secondary-700">
                          {member.name.charAt(0)}
                          <span
                            className={`absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border-2 border-background-100 ${
                              statusDot[member.status]
                            }`}
                          />
                        </span>
                        <div>
                          <div className="text-sm font-medium text-foreground-900">
                            {member.name}
                            {isDisabled && (
                              <span className="ml-2 rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-foreground-500">
                                已停用
                              </span>
                            )}
                          </div>
                          <div className="text-xs text-foreground-500">{member.email}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3.5">
                      <span
                        className={`inline-flex whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium ${roleStyles[member.role]}`}
                      >
                        {member.role}
                      </span>
                    </td>
                    <td className="font-label px-3 py-3.5 text-sm text-foreground-500">{member.projectCount}</td>
                    <td className="px-3 py-3.5">
                      <span className="flex items-center gap-1.5 text-sm text-foreground-500">
                        <span className={`relative flex h-2 w-2 ${member.status === "在线" ? "" : ""}`}>
                          {member.status === "在线" && <span className="absolute inline-flex h-full w-full rounded-full bg-primary-400 opacity-60 animate-ping" />}
                          <span className={`relative inline-flex h-2 w-2 rounded-full ${statusDot[member.status]}`} />
                        </span>
                        {member.status}
                      </span>
                    </td>
                    <td className="px-3 py-3.5 whitespace-nowrap text-sm text-foreground-500">{member.lastActive}</td>
                    <td className="px-3 py-3.5 whitespace-nowrap text-sm text-foreground-500">{member.joinedAt}</td>
                    <td className="px-3 py-3.5">
                      <div className="flex items-center justify-end gap-0.5">
                        <button
                          type="button"
                          title="编辑成员"
                          onClick={() => showToast(`${member.name} 的资料编辑功能即将开放`, "info")}
                          className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-primary-50 hover:text-primary-600"
                        >
                          <i className="ri-pencil-line text-sm"></i>
                        </button>
                        <button
                          type="button"
                          title={isDisabled ? "启用成员" : "停用成员"}
                          onClick={() => {
                            setDisabled((prev) => ({ ...prev, [member.id]: !isDisabled }));
                            showToast(isDisabled ? `${member.name} 已重新启用` : `${member.name} 已停用`);
                          }}
                          className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-accent-50 hover:text-accent-600"
                        >
                          <i className={`${isDisabled ? "ri-play-circle-line" : "ri-pause-circle-line"} text-sm`}></i>
                        </button>
                        <button
                          type="button"
                          title="移除成员"
                          onClick={() => {
                            setMemberList((prev) => prev.filter((m) => m.id !== member.id));
                            showToast(`${member.name} 已从团队移除`, "info");
                          }}
                          className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-red-50 hover:text-red-600"
                        >
                          <i className="ri-delete-bin-line text-sm"></i>
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-16 text-center">
                    <i className="ri-user-unfollow-line text-3xl text-foreground-400"></i>
                    <p className="mt-3 text-sm text-foreground-500">没有找到匹配的成员</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 角色权限矩阵 */}
      <div className="rounded-lg border border-background-300 bg-background-100 p-5">
        <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
            <i className="ri-shield-check-line text-primary-500 text-sm"></i>
            角色权限矩阵
          </h3>
          <p className="text-xs text-foreground-500">权限调整后立即生效，影响成员对新数据的操作范围</p>
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
              {rolePermissions[0].permissions.map((permission, idx) => (
                <tr key={permission.name} className="border-b border-background-200 last:border-0">
                  <td className="py-3 pr-4 text-sm text-foreground-600">{permission.name}</td>
                  {rolePermissions.map((rp) => {
                    const granted = rp.permissions[idx].granted;
                    return (
                      <td key={rp.role} className="px-3 py-3 text-center">
                        {granted ? (
                          <i className="ri-checkbox-circle-line text-base text-primary-500"></i>
                        ) : (
                          <i className="ri-close-circle-line text-base text-foreground-400"></i>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 邀请成员弹窗 */}
      <Modal
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        title="邀请新成员"
        subtitle="通过邮件发送邀请链接，对方登录后自动加入团队"
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
          <div>
            <label className={labelCls} htmlFor="inv-note">
              邀请备注
            </label>
            <textarea
              id="inv-note"
              value={form.note}
              onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
              rows={3}
              maxLength={200}
              placeholder="例如：负责交通类项目标书撰写"
              className={`${inputCls} resize-none py-2`}
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
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
            >
              <i className="ri-send-plane-line text-sm"></i>
              发送邀请
            </button>
          </div>
        </form>
      </Modal>

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}