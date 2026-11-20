import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Toast from "../components/Toast";
import Modal from "../components/Modal";
import { useAuth } from "@/context/AuthContext";
import { hasPerm } from "@/lib/permissions";
import { isPersonal, listUsers, type TeamMember } from "@/lib/api";
import {
  createCustomRole,
  createDepartment,
  createSupportGrant,
  deleteCustomRole,
  deleteDepartment,
  getPermCatalog,
  getTenantProfile,
  listCustomRoles,
  listDepartments,
  listSupportGrants,
  revokeSupportGrant,
  submitTenantVerify,
  updateCustomRole,
  updateDepartment,
  updateTenantProfile,
  upgradeToEnterprise,
  type CustomRole,
  type Department,
  type SupportGrant,
  type TenantProfile,
} from "@/lib/saasApi";
import { btnGhost, btnPrimary, Card, Empty, inputCls, StatusTag } from "../billing/ui";

const TABS = [
  { id: "profile", label: "企业资料与认证" },
  { id: "departments", label: "部门" },
  { id: "roles", label: "自定义角色" },
  { id: "support", label: "平台支持授权" },
] as const;
type TabId = (typeof TABS)[number]["id"];

type Notify = (msg: string, type?: "success" | "error") => void;

const errMsg = (e: unknown) => (e instanceof Error ? e.message : "操作失败");

export default function OrgPage() {
  const { user } = useAuth();
  const canEdit = hasPerm(user, "org");
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id || "profile") as TabId;
  const [toast, setToast] = useState<{ message: string; type: "success" | "error"; visible: boolean }>({ message: "", type: "success", visible: false });

  const notify = useCallback<Notify>((message, type = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  }, []);

  if (isPersonal(user)) {
    return (
      <div>
        <PageHeader title="升级为企业" description="个人账号的项目、资料库、积分和套餐都在你自己的独立空间里。升级后保留全部数据，可以邀请同事共用积分池。" />
        <UpgradePanel canEdit={canEdit} notify={notify} />
        <Toast message={toast.message} type={toast.type} visible={toast.visible} />
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="企业与组织" description="本企业的资料、部门架构与角色权限。企业之间的成员、组织架构和资料库完全隔离，互不可见。" />
      <div className="mb-4 flex gap-1 overflow-x-auto border-b border-background-300">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setParams(t.id === "profile" ? {} : { tab: t.id }, { replace: true })}
            className={`-mb-px cursor-pointer whitespace-nowrap border-b-2 px-4 py-2 text-sm transition-colors ${tab === t.id ? "border-primary-500 font-medium text-primary-600" : "border-transparent text-foreground-600 hover:text-foreground-900"}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "profile" && <ProfilePanel canEdit={canEdit} notify={notify} />}
      {tab === "departments" && <DepartmentsPanel canEdit={canEdit} notify={notify} />}
      {tab === "roles" && <RolesPanel canEdit={canEdit} notify={notify} />}
      {tab === "support" && <SupportPanel canEdit={user?.role === "管理员"} notify={notify} />}
      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}

const UPGRADE_BENEFITS = [
  { icon: "ri-team-line", title: "邀请同事", desc: "按套餐席位邀请成员，所有人共用一个企业积分池" },
  { icon: "ri-organization-chart", title: "部门与角色", desc: "部门树、自定义角色和数据范围，控制谁能看哪些项目" },
  { icon: "ri-bill-line", title: "企业发票", desc: "认证营业执照后可开具增值税专用发票" },
  { icon: "ri-safe-2-line", title: "数据原样保留", desc: "项目、资料库、余额和已购套餐全部保留，无需迁移" },
];

function UpgradePanel({ canEdit, notify }: { canEdit: boolean; notify: Notify }) {
  const { refreshUser } = useAuth();
  const navigate = useNavigate();
  const [companyName, setCompanyName] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const name = companyName.trim();
    if (name.length < 2) {
      notify("请填写企业名称", "error");
      return;
    }
    if (!window.confirm(`确定将当前个人账号升级为「${name}」？升级后不能再改回个人账号。`)) return;
    setBusy(true);
    try {
      await upgradeToEnterprise(name);
      await refreshUser();
      notify("已升级为企业，你现在是企业管理员");
      navigate("/console/org", { replace: true });
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
      <Card title="升级后可以">
        <div className="grid gap-3 sm:grid-cols-2">
          {UPGRADE_BENEFITS.map((b) => (
            <div key={b.title} className="flex gap-3 rounded-lg border border-background-300 bg-background-50 p-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
                <i className={`${b.icon} text-base`}></i>
              </span>
              <div>
                <div className="text-sm font-medium text-foreground-900">{b.title}</div>
                <div className="mt-0.5 text-xs leading-5 text-foreground-500">{b.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </Card>
      <Card title="填写企业信息">
        <label className="block">
          <span className="mb-1 block text-xs text-foreground-500">企业名称（与营业执照一致）</span>
          <input className={inputCls} value={companyName} onChange={(e) => setCompanyName(e.target.value)} placeholder="例如：某某工程咨询有限公司" disabled={!canEdit} />
        </label>
        <p className="mt-2 text-xs leading-5 text-foreground-500">升级后默认 3 个席位，购买企业套餐可增加席位；个人套餐在到期前继续有效。</p>
        <button type="button" className={`${btnPrimary} mt-4 w-full`} onClick={submit} disabled={busy || !canEdit}>
          {busy ? "正在升级…" : "升级为企业"}
        </button>
      </Card>
    </div>
  );
}

function ProfilePanel({ canEdit, notify }: { canEdit: boolean; notify: Notify }) {
  const [profile, setProfile] = useState<TenantProfile | null>(null);
  const [form, setForm] = useState({ name: "", contactName: "", contactPhone: "", contactEmail: "", lowBalanceThreshold: 0 });
  const [licenseNo, setLicenseNo] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);

  const apply = (p: TenantProfile) => {
    setProfile(p);
    setForm({ name: p.name, contactName: p.contactName, contactPhone: p.contactPhone, contactEmail: p.contactEmail, lowBalanceThreshold: p.lowBalanceThreshold });
    setLicenseNo(p.licenseNo);
  };

  useEffect(() => {
    getTenantProfile().then(apply).catch((e) => notify(errMsg(e), "error"));
  }, [notify]);

  const save = async () => {
    if (profile?.verifyStatus === "已认证" && form.name.trim() !== profile.name && !window.confirm("修改企业名称后需要重新提交认证，确定继续？")) return;
    setBusy(true);
    try {
      apply(await updateTenantProfile(form));
      notify("企业资料已保存");
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    if (!file) return;
    setBusy(true);
    try {
      apply(await submitTenantVerify(licenseNo.trim(), file));
      setFile(null);
      notify("认证资料已提交，平台审核后生效");
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };

  if (!profile) return <Empty text="加载中…" />;

  const input = (key: keyof typeof form, label: string, type = "text") => (
    <label className="block">
      <span className="mb-1 block text-xs text-foreground-500">{label}</span>
      <input
        className={inputCls}
        type={type}
        disabled={!canEdit}
        value={form[key]}
        onChange={(e) => setForm({ ...form, [key]: type === "number" ? Number(e.target.value || 0) : e.target.value })}
      />
    </label>
  );

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="企业资料">
        <div className="space-y-3">
          {input("name", "企业名称")}
          <div className="grid grid-cols-2 gap-3">
            {input("contactName", "联系人")}
            {input("contactPhone", "联系电话")}
          </div>
          {input("contactEmail", "联系邮箱")}
          {input("lowBalanceThreshold", "积分余额低于多少时提醒", "number")}
          <div className="grid grid-cols-3 gap-3 rounded-lg bg-background-50 p-3 text-xs text-foreground-600">
            <div>
              企业编号
              <div className="mt-0.5 font-mono text-foreground-900">{profile.id}</div>
            </div>
            <div>
              席位上限
              <div className="mt-0.5 text-foreground-900">{profile.seats}</div>
            </div>
            <div>
              开通时间
              <div className="mt-0.5 text-foreground-900">{profile.createdAt.slice(0, 10)}</div>
            </div>
          </div>
          {canEdit && (
            <div className="flex justify-end">
              <button type="button" className={btnPrimary} disabled={busy || !form.name.trim()} onClick={save}>
                保存
              </button>
            </div>
          )}
        </div>
      </Card>

      <Card title="企业认证" extra={<StatusTag status={profile.verifyStatus} />}>
        <div className="space-y-3 text-sm">
          <p className="text-xs leading-5 text-foreground-500">
            上传营业执照完成企业认证。认证后可开具增值税专用发票，并在投标文件中使用经核验的企业主体信息。执照仅存放在本企业的独立存储空间中。
          </p>
          {profile.verifyNote && <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">审核意见：{profile.verifyNote}</p>}
          {profile.verifyStatus === "已认证" ? (
            <div className="rounded-lg bg-emerald-50 px-3 py-2.5 text-emerald-800">
              <i className="ri-shield-check-line mr-1"></i>已认证 · 统一社会信用代码 {profile.licenseNo}
            </div>
          ) : profile.verifyStatus === "待审核" ? (
            <div className="rounded-lg bg-amber-50 px-3 py-2.5 text-amber-800">认证资料审核中，一般 1 个工作日内完成。</div>
          ) : canEdit ? (
            <div className="space-y-2">
              <input className={inputCls} placeholder="统一社会信用代码（18 位）" value={licenseNo} onChange={(e) => setLicenseNo(e.target.value.toUpperCase())} />
              <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-background-300 px-3 py-3 text-xs text-foreground-600 hover:border-primary-300">
                <i className="ri-upload-2-line text-base"></i>
                {file ? file.name : "上传营业执照（PDF / JPG / PNG）"}
                <input type="file" accept=".pdf,.jpg,.jpeg,.png" className="hidden" onChange={(e) => setFile(e.target.files?.[0] || null)} />
              </label>
              <button type="button" className={`${btnPrimary} w-full`} disabled={busy || !file || licenseNo.trim().length !== 18} onClick={verify}>
                提交认证
              </button>
            </div>
          ) : (
            <p className="text-xs text-foreground-500">请联系企业管理员提交认证。</p>
          )}
        </div>
      </Card>
    </div>
  );
}

interface DeptNode extends Department {
  depth: number;
}

function flattenTree(depts: Department[]): DeptNode[] {
  const byParent = new Map<string, Department[]>();
  for (const d of depts) {
    const key = d.parentId || "";
    byParent.set(key, [...(byParent.get(key) || []), d]);
  }
  const ids = new Set(depts.map((d) => d.id));
  const out: DeptNode[] = [];
  const walk = (parent: string, depth: number) => {
    for (const d of byParent.get(parent) || []) {
      out.push({ ...d, depth });
      walk(d.id, depth + 1);
    }
  };
  walk("", 0);
  for (const d of depts) if (d.parentId && !ids.has(d.parentId) && !out.some((o) => o.id === d.id)) out.push({ ...d, depth: 0 });
  return out;
}

function DepartmentsPanel({ canEdit, notify }: { canEdit: boolean; notify: Notify }) {
  const { token } = useAuth();
  const [depts, setDepts] = useState<Department[]>([]);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [editing, setEditing] = useState<{ id: string | null; name: string; parentId: string; leaderId: string; sortOrder: number } | null>(null);

  const load = useCallback(() => {
    listDepartments().then(setDepts).catch((e) => notify(errMsg(e), "error"));
  }, [notify]);

  useEffect(() => {
    load();
    if (token) listUsers(token).then(setMembers).catch(() => setMembers([]));
  }, [load, token]);

  const tree = useMemo(() => flattenTree(depts), [depts]);

  const descendants = useMemo(() => {
    if (!editing?.id) return new Set<string>();
    const set = new Set<string>([editing.id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const d of depts) if (d.parentId && set.has(d.parentId) && !set.has(d.id)) { set.add(d.id); grew = true; }
    }
    return set;
  }, [editing?.id, depts]);

  const save = async () => {
    if (!editing) return;
    const payload = { name: editing.name.trim(), parentId: editing.parentId || null, leaderId: editing.leaderId || null, sortOrder: editing.sortOrder };
    try {
      if (editing.id) await updateDepartment(editing.id, payload);
      else await createDepartment(payload);
      setEditing(null);
      notify("部门已保存");
      load();
    } catch (e) {
      notify(errMsg(e), "error");
    }
  };

  const remove = async (d: Department) => {
    if (!window.confirm(`删除部门「${d.name}」？`)) return;
    try {
      await deleteDepartment(d.id);
      notify("部门已删除");
      load();
    } catch (e) {
      notify(errMsg(e), "error");
    }
  };

  return (
    <Card
      title="部门架构"
      extra={
        canEdit && (
          <button type="button" className={btnGhost} onClick={() => setEditing({ id: null, name: "", parentId: "", leaderId: "", sortOrder: 0 })}>
            <i className="ri-add-line"></i>新建部门
          </button>
        )
      }
    >
      <p className="mb-3 text-xs text-foreground-500">
        部门用于划分「本部门」数据范围和部门资料库。成员的所属部门在「成员管理」中设置。
      </p>
      {tree.length ? (
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-foreground-500">
            <tr>
              <th className="py-2 font-normal">部门名称</th>
              <th className="py-2 font-normal">负责人</th>
              <th className="py-2 text-right font-normal">成员数</th>
              <th className="py-2"></th>
            </tr>
          </thead>
          <tbody>
            {tree.map((d) => (
              <tr key={d.id} className="border-t border-background-300">
                <td className="py-2 text-foreground-900" style={{ paddingLeft: d.depth * 20 }}>
                  <i className={`${d.depth ? "ri-corner-down-right-line" : "ri-building-line"} mr-1.5 text-foreground-400`}></i>
                  {d.name}
                </td>
                <td className="py-2 text-foreground-600">{d.leaderName || "—"}</td>
                <td className="py-2 text-right text-foreground-700">{d.memberCount}</td>
                <td className="space-x-3 py-2 text-right text-xs">
                  {canEdit && (
                    <>
                      <button type="button" className="cursor-pointer text-primary-600 hover:underline" onClick={() => setEditing({ id: null, name: "", parentId: d.id, leaderId: "", sortOrder: 0 })}>
                        添加子部门
                      </button>
                      <button
                        type="button"
                        className="cursor-pointer text-primary-600 hover:underline"
                        onClick={() => setEditing({ id: d.id, name: d.name, parentId: d.parentId || "", leaderId: d.leaderId || "", sortOrder: d.sortOrder })}
                      >
                        编辑
                      </button>
                      <button type="button" className="cursor-pointer text-red-600 hover:underline" onClick={() => remove(d)}>
                        删除
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <Empty text="还没有部门" />
      )}

      {editing && (
        <Modal open onClose={() => setEditing(null)} title={editing.id ? "编辑部门" : "新建部门"}>
          <div className="space-y-3">
            <label className="block">
              <span className="mb-1 block text-xs text-foreground-500">部门名称</span>
              <input className={inputCls} value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-foreground-500">上级部门</span>
              <select className={inputCls} value={editing.parentId} onChange={(e) => setEditing({ ...editing, parentId: e.target.value })}>
                <option value="">无（一级部门）</option>
                {tree
                  .filter((d) => !descendants.has(d.id))
                  .map((d) => (
                    <option key={d.id} value={d.id}>
                      {"　".repeat(d.depth)}
                      {d.name}
                    </option>
                  ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-foreground-500">负责人</span>
              <select className={inputCls} value={editing.leaderId} onChange={(e) => setEditing({ ...editing, leaderId: e.target.value })}>
                <option value="">未指定</option>
                {members
                  .filter((m) => !m.disabled)
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}（{m.email}）
                    </option>
                  ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-foreground-500">排序（越小越靠前）</span>
              <input className={inputCls} type="number" value={editing.sortOrder} onChange={(e) => setEditing({ ...editing, sortOrder: Number(e.target.value || 0) })} />
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" className={btnGhost} onClick={() => setEditing(null)}>
                取消
              </button>
              <button type="button" className={btnPrimary} disabled={!editing.name.trim()} onClick={save}>
                保存
              </button>
            </div>
          </div>
        </Modal>
      )}
    </Card>
  );
}

const SCOPE_HINT: Record<string, string> = {
  本人: "只能看到自己创建或被加入的项目",
  本部门: "还可以看到本部门创建的全部项目",
  全企业: "可以看到企业内全部项目",
};

function RolesPanel({ canEdit, notify }: { canEdit: boolean; notify: Notify }) {
  const [roles, setRoles] = useState<CustomRole[]>([]);
  const [catalog, setCatalog] = useState<{ perms: { id: string; name: string }[]; scopes: string[] }>({ perms: [], scopes: [] });
  const [editing, setEditing] = useState<{ id: string | null; name: string; perms: string[]; dataScope: string } | null>(null);

  const load = useCallback(() => {
    Promise.all([listCustomRoles(), getPermCatalog()])
      .then(([r, c]) => {
        setRoles(r);
        setCatalog(c);
      })
      .catch((e) => notify(errMsg(e), "error"));
  }, [notify]);
  useEffect(load, [load]);

  const permName = (id: string) => catalog.perms.find((p) => p.id === id)?.name || id;

  const save = async () => {
    if (!editing) return;
    const payload = { name: editing.name.trim(), perms: editing.perms, dataScope: editing.dataScope };
    try {
      if (editing.id) await updateCustomRole(editing.id, payload);
      else await createCustomRole(payload);
      setEditing(null);
      notify("角色已保存");
      load();
    } catch (e) {
      notify(errMsg(e), "error");
    }
  };

  const remove = async (r: CustomRole) => {
    if (!window.confirm(`删除角色「${r.name}」？使用该角色的成员将恢复为其内置角色权限。`)) return;
    try {
      await deleteCustomRole(r.id);
      load();
    } catch (e) {
      notify(errMsg(e), "error");
    }
  };

  return (
    <Card
      title="自定义角色"
      extra={
        canEdit && (
          <button type="button" className={btnGhost} onClick={() => setEditing({ id: null, name: "", perms: [], dataScope: catalog.scopes[0] || "本人" })}>
            <i className="ri-add-line"></i>新建角色
          </button>
        )
      }
    >
      <p className="mb-3 text-xs text-foreground-500">
        内置角色（管理员、项目经理、撰写专家、评标专家、成员）不可修改。自定义角色可以精确组合功能权限和数据范围，在「成员管理」中分配给成员。
      </p>
      {roles.length ? (
        <div className="grid gap-3 md:grid-cols-2">
          {roles.map((r) => (
            <div key={r.id} className="rounded-lg border border-background-300 bg-background-50 p-3 text-sm">
              <div className="flex items-center gap-2">
                <span className="font-medium text-foreground-900">{r.name}</span>
                <span className="rounded bg-sky-50 px-1.5 text-[11px] text-sky-700">{r.dataScope}</span>
                <span className="ml-auto text-xs text-foreground-500">{r.memberCount} 人</span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {r.perms.length ? (
                  r.perms.map((p) => (
                    <span key={p} className="rounded bg-background-200 px-1.5 py-0.5 text-[11px] text-foreground-700">
                      {permName(p)}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-foreground-500">仅查看</span>
                )}
              </div>
              {canEdit && (
                <div className="mt-2 flex gap-3 text-xs">
                  <button type="button" className="cursor-pointer text-primary-600 hover:underline" onClick={() => setEditing({ id: r.id, name: r.name, perms: [...r.perms], dataScope: r.dataScope })}>
                    编辑
                  </button>
                  <button type="button" className="cursor-pointer text-red-600 hover:underline" onClick={() => remove(r)}>
                    删除
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <Empty text="还没有自定义角色" />
      )}

      {editing && (
        <Modal open onClose={() => setEditing(null)} title={editing.id ? "编辑角色" : "新建角色"} width="max-w-xl">
          <div className="space-y-4">
            <label className="block">
              <span className="mb-1 block text-xs text-foreground-500">角色名称</span>
              <input className={inputCls} value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
            </label>
            <div>
              <div className="mb-1.5 text-xs text-foreground-500">功能权限</div>
              <div className="grid grid-cols-2 gap-2">
                {catalog.perms.map((p) => (
                  <label key={p.id} className="flex cursor-pointer items-center gap-2 rounded-lg border border-background-300 px-3 py-2 text-sm">
                    <input
                      type="checkbox"
                      checked={editing.perms.includes(p.id)}
                      onChange={(e) => setEditing({ ...editing, perms: e.target.checked ? [...editing.perms, p.id] : editing.perms.filter((x) => x !== p.id) })}
                    />
                    {p.name}
                  </label>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-1.5 text-xs text-foreground-500">数据范围</div>
              <div className="space-y-1.5">
                {catalog.scopes.map((s) => (
                  <label key={s} className="flex cursor-pointer items-center gap-2 text-sm">
                    <input type="radio" checked={editing.dataScope === s} onChange={() => setEditing({ ...editing, dataScope: s })} />
                    <span className="text-foreground-800">{s}</span>
                    <span className="text-xs text-foreground-500">{SCOPE_HINT[s]}</span>
                  </label>
                ))}
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button type="button" className={btnGhost} onClick={() => setEditing(null)}>
                取消
              </button>
              <button type="button" className={btnPrimary} disabled={!editing.name.trim()} onClick={save}>
                保存
              </button>
            </div>
          </div>
        </Modal>
      )}
    </Card>
  );
}

function SupportPanel({ canEdit, notify }: { canEdit: boolean; notify: Notify }) {
  const [grants, setGrants] = useState<SupportGrant[]>([]);
  const [hours, setHours] = useState(24);
  const [reason, setReason] = useState("");

  const load = useCallback(() => {
    listSupportGrants().then(setGrants).catch((e) => notify(errMsg(e), "error"));
  }, [notify]);
  useEffect(load, [load]);

  const grant = async () => {
    try {
      await createSupportGrant(hours, reason.trim());
      setReason("");
      notify("已授权平台支持人员临时查看");
      load();
    } catch (e) {
      notify(errMsg(e), "error");
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
      <Card title="授权平台排查问题">
        <div className="space-y-3 text-sm">
          <p className="text-xs leading-5 text-foreground-500">
            默认情况下，平台运营人员<b>无法查看</b>本企业的资质库、知识库、产品库和标书内容。遇到问题需要平台协助排查时，可在此临时授权，到期自动失效，平台每次查看都会留痕。
          </p>
          {canEdit ? (
            <>
              <label className="block">
                <span className="mb-1 block text-xs text-foreground-500">授权时长</span>
                <select className={inputCls} value={hours} onChange={(e) => setHours(Number(e.target.value))}>
                  {[2, 24, 72, 168].map((h) => (
                    <option key={h} value={h}>
                      {h < 24 ? `${h} 小时` : `${h / 24} 天`}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-foreground-500">原因</span>
                <input className={inputCls} placeholder="例如：知识库文档解析异常" value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
              <button type="button" className={`${btnPrimary} w-full`} disabled={!reason.trim()} onClick={grant}>
                授权
              </button>
            </>
          ) : (
            <p className="text-xs text-foreground-500">仅企业管理员可以授权。</p>
          )}
        </div>
      </Card>
      <Card title="授权记录">
        {grants.length ? (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-foreground-500">
              <tr>
                <th className="py-2 font-normal">授权时间</th>
                <th className="py-2 font-normal">原因</th>
                <th className="py-2 font-normal">到期</th>
                <th className="py-2 font-normal">状态</th>
                <th className="py-2"></th>
              </tr>
            </thead>
            <tbody>
              {grants.map((g) => (
                <tr key={g.id} className="border-t border-background-300">
                  <td className="py-2 text-foreground-600">{g.createdAt}</td>
                  <td className="py-2 text-foreground-800">{g.reason}</td>
                  <td className="py-2 text-foreground-600">{g.expiresAt}</td>
                  <td className="py-2 text-xs">{g.active ? <span className="text-emerald-600">生效中</span> : <span className="text-foreground-500">{g.revoked ? "已撤销" : "已过期"}</span>}</td>
                  <td className="py-2 text-right text-xs">
                    {g.active && canEdit && (
                      <button type="button" className="cursor-pointer text-red-600 hover:underline" onClick={() => revokeSupportGrant(g.id).then(load).catch((e) => notify(errMsg(e), "error"))}>
                        撤销
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty text="暂无授权记录" />
        )}
      </Card>
    </div>
  );
}
