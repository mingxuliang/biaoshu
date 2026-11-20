import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import PageHeader from "@/pages/console/components/PageHeader";
import Modal from "@/pages/console/components/Modal";
import { formatBytes } from "@/lib/saasApi";
import {
  adjustCredits,
  deregisterTenant,
  getTenant,
  getTenantLibraries,
  getTenantOrg,
  getTenantStorage,
  getUserCredits,
  listAdminPlans,
  listPlatformLedger,
  patchTenant,
  patchTenantUser,
  reviewVerify,
  tenantLicense,
  type AdminPlan,
  type AdminTenantDetail,
  type TenantLibraries,
  type TenantOrg,
} from "../api";
import { useCan } from "../auth";
import {
  btnGhost,
  btnPrimary,
  Card,
  dangerLink,
  Empty,
  inputCls,
  linkBtn,
  num,
  openBlob,
  PaginationBar,
  Stat,
  StatusTag,
  Tabs,
  tdCls,
  theadCls,
  thCls,
  tokens,
  trCls,
  useUi,
} from "../ui";

const TABS = [
  { id: "overview", label: "概况与套餐" },
  { id: "org", label: "组织与成员" },
  { id: "credits", label: "积分与费用" },
  { id: "libraries", label: "资料库" },
  { id: "storage", label: "存储" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export default function TenantDetailPage() {
  const { id = "" } = useParams();
  const { fail } = useUi();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id || "overview") as TabId;
  const [tenant, setTenant] = useState<AdminTenantDetail | null>(null);

  const load = useCallback(() => {
    getTenant(id).then(setTenant).catch(fail);
  }, [id, fail]);
  useEffect(load, [load]);

  if (!tenant) return <Empty text="加载中…" />;

  return (
    <div>
      <div className="mb-2 text-xs text-foreground-500">
        <Link to="/tenants" className="hover:underline">
          企业管理
        </Link>{" "}
        / {tenant.name}
      </div>
      <PageHeader
        title={tenant.name}
        description={`${tenant.kind === "个人" ? "个人账号（仅本人使用）" : "企业（成员共享积分池）"} · 编号 ${tenant.id} · 存储 bucket ${tenant.storage.bucket} · 开通于 ${tenant.createdAt}`}
        actions={
          <div className="flex gap-2">
            <StatusTag status={tenant.status} />
            {tenant.kind !== "个人" && <StatusTag status={tenant.verifyStatus} />}
          </div>
        }
      />
      <Tabs tabs={TABS} value={tab} onChange={(t) => setParams(t === "overview" ? {} : { tab: t }, { replace: true })} />
      {tab === "overview" && <Overview tenant={tenant} reload={load} />}
      {tab === "org" && <OrgTab tenantId={tenant.id} />}
      {tab === "credits" && <CreditsTab tenant={tenant} reload={load} />}
      {tab === "libraries" && <LibrariesTab tenantId={tenant.id} />}
      {tab === "storage" && <StorageTab tenantId={tenant.id} />}
    </div>
  );
}

function Overview({ tenant, reload }: { tenant: AdminTenantDetail; reload: () => void }) {
  const { notify, fail, ask } = useUi();
  const can = useCan();
  const navigate = useNavigate();
  const [plans, setPlans] = useState<AdminPlan[]>([]);
  const [form, setForm] = useState({
    name: tenant.name,
    status: tenant.status,
    planCode: tenant.planCode,
    seats: tenant.seats,
    storageQuotaMb: tenant.storageQuotaMb,
    expiresAt: tenant.expiresAt.slice(0, 10),
    lowBalanceThreshold: tenant.lowBalanceThreshold,
  });
  const [deregOpen, setDeregOpen] = useState(false);
  const [dereg, setDereg] = useState({ confirmName: "", dropData: false });

  useEffect(() => {
    listAdminPlans().then((p) => setPlans(p.filter((x) => x.kind === "套餐"))).catch(() => setPlans([]));
  }, []);

  const save = async () => {
    try {
      await patchTenant(tenant.id, { ...form, expiresAt: form.expiresAt || "" });
      notify("企业信息已更新");
      reload();
    } catch (e) {
      fail(e);
    }
  };

  const review = async (approve: boolean) => {
    const note = approve ? "" : await ask({ title: "驳回企业认证", placeholder: "驳回原因（将展示给企业）" });
    if (!approve && note === null) return;
    try {
      await reviewVerify(tenant.id, approve, note || "");
      notify(approve ? "已通过认证" : "已驳回认证");
      reload();
    } catch (e) {
      fail(e);
    }
  };

  const doDeregister = async () => {
    try {
      await deregisterTenant(tenant.id, dereg.confirmName, dereg.dropData);
      notify("企业已注销");
      navigate("/tenants");
    } catch (e) {
      fail(e);
    }
  };

  const field = (label: string, node: React.ReactNode) => (
    <label className="block">
      <span className="mb-1 block text-xs text-foreground-500">{label}</span>
      {node}
    </label>
  );
  const ro = !can.ops;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
      <div className="space-y-4">
        <Card title="套餐与配额" extra={can.ops && <button type="button" className={btnPrimary} onClick={save}>保存</button>}>
          <div className="grid gap-3 sm:grid-cols-2">
            {field("企业名称", <input className={inputCls} disabled={ro} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />)}
            {field(
              "状态",
              <select className={inputCls} disabled={ro} value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                {["试用", "正常", "停用"].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>,
            )}
            {field(
              "套餐",
              <select className={inputCls} disabled={ro} value={form.planCode} onChange={(e) => setForm({ ...form, planCode: e.target.value })}>
                {!plans.some((p) => p.code === form.planCode) && <option value={form.planCode}>{form.planCode}</option>}
                {plans.map((p) => (
                  <option key={p.code} value={p.code}>
                    {p.name}（{p.code}）
                  </option>
                ))}
              </select>,
            )}
            {field("服务到期日（留空为长期）", <input className={inputCls} disabled={ro} type="date" value={form.expiresAt} onChange={(e) => setForm({ ...form, expiresAt: e.target.value })} />)}
            {field("席位上限", <input className={inputCls} disabled={ro} type="number" min={1} value={form.seats} onChange={(e) => setForm({ ...form, seats: Number(e.target.value || 1) })} />)}
            {field("存储配额（MB，0 为不限）", <input className={inputCls} disabled={ro} type="number" min={0} value={form.storageQuotaMb} onChange={(e) => setForm({ ...form, storageQuotaMb: Number(e.target.value || 0) })} />)}
            {field("低余额提醒阈值（积分）", <input className={inputCls} disabled={ro} type="number" min={0} value={form.lowBalanceThreshold} onChange={(e) => setForm({ ...form, lowBalanceThreshold: Number(e.target.value || 0) })} />)}
          </div>
          {tenant.status === "试用" && <p className="mt-3 text-xs text-foreground-500">试用到期：{tenant.trialEndsAt || "—"}</p>}
        </Card>

        <Card title="订阅记录">
          {tenant.subscriptions.length ? (
            <table className="w-full">
              <thead className={theadCls}>
                <tr>
                  <th className={thCls}>套餐</th>
                  <th className={thCls}>开始</th>
                  <th className={thCls}>结束</th>
                  <th className={thCls}>状态</th>
                  <th className={thCls}>订单</th>
                </tr>
              </thead>
              <tbody>
                {tenant.subscriptions.map((s, i) => (
                  <tr key={i} className={trCls}>
                    <td className={tdCls}>{s.planCode}</td>
                    <td className={tdCls}>{s.startsAt}</td>
                    <td className={tdCls}>{s.endsAt}</td>
                    <td className={tdCls}>{s.status}</td>
                    <td className={`${tdCls} font-mono text-xs`}>{s.orderId || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty text="暂无订阅记录" />
          )}
        </Card>
      </div>

      <div className="space-y-4">
        <Card title="联系人">
          <dl className="grid grid-cols-[64px_1fr] gap-y-1.5 text-sm">
            <dt className="text-foreground-500">联系人</dt>
            <dd>{tenant.contactName || "—"}</dd>
            <dt className="text-foreground-500">电话</dt>
            <dd>{tenant.contactPhone || "—"}</dd>
            <dt className="text-foreground-500">邮箱</dt>
            <dd className="break-all">{tenant.contactEmail || "—"}</dd>
            <dt className="text-foreground-500">席位</dt>
            <dd>
              {tenant.seatsUsed ?? "—"} / {tenant.seats}
            </dd>
          </dl>
        </Card>
        <Card title="企业认证" extra={<StatusTag status={tenant.verifyStatus} />}>
          <div className="space-y-2 text-sm">
            <div>统一社会信用代码：{tenant.licenseNo || "—"}</div>
            {tenant.verifyNote && <div className="text-xs text-red-600">备注：{tenant.verifyNote}</div>}
            {tenant.hasLicense && can.ops && (
              <button type="button" className={linkBtn} onClick={() => tenantLicense(tenant.id).then(openBlob).catch(fail)}>
                查看营业执照（记审计）
              </button>
            )}
            {tenant.verifyStatus === "待审核" && can.ops && (
              <div className="flex gap-2 pt-1">
                <button type="button" className={btnPrimary} onClick={() => review(true)}>
                  通过
                </button>
                <button type="button" className={btnGhost} onClick={() => review(false)}>
                  驳回
                </button>
              </div>
            )}
          </div>
        </Card>
        <Card title="运维授权">
          {tenant.supportGrant ? (
            <p className="text-sm text-emerald-700">
              企业已授权至 {tenant.supportGrant.expiresAt}（{tenant.supportGrant.grantedBy}），可在「资料库」查看明细。
            </p>
          ) : (
            <p className="text-sm text-foreground-500">企业未授权。平台只能看到统计数据，无法查看文件与内容。</p>
          )}
        </Card>
        {can.isSuper && tenant.status !== "已注销" && (
          <Card title="危险操作">
            <button type="button" className={dangerLink} onClick={() => setDeregOpen(true)}>
              注销企业
            </button>
          </Card>
        )}
      </div>

      {deregOpen && (
        <Modal open onClose={() => setDeregOpen(false)} title="注销企业" subtitle="注销后企业成员将无法登录">
          <div className="space-y-3 text-sm">
            <p className="text-foreground-700">
              请输入企业全称 <b>{tenant.name}</b> 确认。
            </p>
            <input className={inputCls} value={dereg.confirmName} onChange={(e) => setDereg({ ...dereg, confirmName: e.target.value })} />
            <label className="flex items-center gap-2 text-red-700">
              <input type="checkbox" checked={dereg.dropData} onChange={(e) => setDereg({ ...dereg, dropData: e.target.checked })} />
              同时永久删除该企业的数据库 schema 和对象存储（不可恢复）
            </label>
            <div className="flex justify-end gap-2">
              <button type="button" className={btnGhost} onClick={() => setDeregOpen(false)}>
                取消
              </button>
              <button type="button" className={`${btnPrimary} bg-red-600 hover:bg-red-700`} disabled={dereg.confirmName.trim() !== tenant.name} onClick={doDeregister}>
                确认注销
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

const BUILTIN_ROLES = ["管理员", "项目经理", "撰写专家", "评标专家", "成员"];

function OrgTab({ tenantId }: { tenantId: string }) {
  const { notify, fail, ask } = useUi();
  const can = useCan();
  const [org, setOrg] = useState<TenantOrg | null>(null);

  const load = useCallback(() => {
    getTenantOrg(tenantId).then(setOrg).catch(fail);
  }, [tenantId, fail]);
  useEffect(load, [load]);

  const act = async (uid: string, patch: Parameters<typeof patchTenantUser>[2], done: string) => {
    try {
      const res = await patchTenantUser(tenantId, uid, patch);
      if (res.initialPassword) {
        await ask({ title: "密码已重置", message: `新密码：${res.initialPassword}\n仅显示这一次，请通过安全渠道告知本人。`, required: false, confirmText: "我已记录" });
      } else notify(done);
      load();
    } catch (e) {
      fail(e);
    }
  };

  if (!org) return <Empty text="加载中…" />;

  const children = (pid: string | null, depth: number): React.ReactNode[] =>
    org.departments
      .filter((d) => (d.parentId || null) === pid)
      .flatMap((d) => [
        <div key={d.id} className="py-1 text-sm text-foreground-800" style={{ paddingLeft: depth * 16 }}>
          <i className={`${depth ? "ri-corner-down-right-line" : "ri-building-line"} mr-1 text-foreground-400`}></i>
          {d.name}
          <span className="ml-1 text-xs text-foreground-500">{org.users.filter((u) => u.departmentId === d.id).length} 人</span>
        </div>,
        ...children(d.id, depth + 1),
      ]);

  return (
    <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
      <Card title="部门架构">{org.departments.length ? children(null, 0) : <Empty text="未建部门" />}</Card>
      <Card title={`成员（${org.users.length}）`}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px]">
            <thead className={theadCls}>
              <tr>
                <th className={thCls}>成员</th>
                <th className={thCls}>角色</th>
                <th className={thCls}>部门</th>
                <th className={`${thCls} text-right`}>本月消耗 / 额度</th>
                <th className={thCls}>最近登录</th>
                <th className={thCls}></th>
              </tr>
            </thead>
            <tbody>
              {org.users.map((u) => (
                <tr key={u.id} className={`${trCls} ${u.disabled ? "opacity-50" : ""}`}>
                  <td className={tdCls}>
                    <div className="font-medium">{u.name}</div>
                    <div className="text-[11px] text-foreground-500">
                      {u.account}
                      {u.phone && ` · ${u.phone}`}
                    </div>
                  </td>
                  <td className={tdCls}>
                    {can.ops ? (
                      <select className="rounded border border-background-300 bg-background-50 px-1 py-0.5 text-xs" value={u.role} onChange={(e) => act(u.id, { role: e.target.value }, "角色已修改")}>
                        {BUILTIN_ROLES.map((r) => (
                          <option key={r}>{r}</option>
                        ))}
                      </select>
                    ) : (
                      u.role
                    )}
                    {u.customRole && <div className="text-[11px] text-foreground-500">{u.customRole}</div>}
                  </td>
                  <td className={tdCls}>{u.departmentName || "—"}</td>
                  <td className={`${tdCls} text-right`}>
                    {num(u.monthSpent)} / {u.monthlyCreditLimit == null ? "不限" : num(u.monthlyCreditLimit)}
                  </td>
                  <td className={`${tdCls} text-xs`}>{u.lastLoginAt || "从未登录"}</td>
                  <td className={`${tdCls} space-x-2 whitespace-nowrap text-right`}>
                    {can.ops && (
                      <>
                        <button
                          type="button"
                          className={linkBtn}
                          onClick={async () => {
                            const v = await ask({ title: `设置 ${u.name} 的月度积分额度`, placeholder: "留空表示不限", initial: u.monthlyCreditLimit?.toString() ?? "", required: false, inputType: "number" });
                            if (v === null) return;
                            act(u.id, { monthlyCreditLimit: v ? Number(v) : -1 }, "额度已更新");
                          }}
                        >
                          额度
                        </button>
                        <button
                          type="button"
                          className={linkBtn}
                          onClick={async () => {
                            if ((await ask({ title: "重置密码", message: `为 ${u.name} 生成新密码？其已登录的会话将失效。`, required: false })) !== null) act(u.id, { resetPassword: true }, "");
                          }}
                        >
                          重置密码
                        </button>
                        <button type="button" className={u.disabled ? linkBtn : dangerLink} onClick={() => act(u.id, { disabled: !u.disabled }, u.disabled ? "已启用" : "已停用")}>
                          {u.disabled ? "启用" : "停用"}
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function CreditsTab({ tenant, reload }: { tenant: AdminTenantDetail; reload: () => void }) {
  const { notify, fail } = useUi();
  const can = useCan();
  const [users, setUsers] = useState<Awaited<ReturnType<typeof getUserCredits>>>([]);
  const [ledger, setLedger] = useState<Awaited<ReturnType<typeof listPlatformLedger>>>({ total: 0, items: [] });
  const [page, setPage] = useState(1);
  const [adj, setAdj] = useState({ delta: "", note: "", expiresAt: "" });

  const loadLedger = useCallback(() => {
    listPlatformLedger({ tenantId: tenant.id, page }).then(setLedger).catch(fail);
  }, [tenant.id, page, fail]);
  useEffect(loadLedger, [loadLedger]);
  useEffect(() => {
    getUserCredits(tenant.id).then(setUsers).catch(fail);
  }, [tenant.id, fail]);

  const submit = async () => {
    const delta = Number(adj.delta);
    if (!delta) return;
    try {
      await adjustCredits(tenant.id, delta, adj.note.trim(), adj.expiresAt);
      setAdj({ delta: "", note: "", expiresAt: "" });
      notify(`已${delta > 0 ? "增加" : "扣减"} ${Math.abs(delta).toLocaleString("zh-CN")} 积分`);
      reload();
      loadLedger();
    } catch (e) {
      fail(e);
    }
  };

  const w = tenant.wallet;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="可用积分" value={num(w?.available ?? (w ? w.balance - w.held : 0))} hint={`冻结 ${num(w?.held ?? 0)}`} />
        <Stat label="30 天内到期" value={num(w?.expiringIn30Days ?? 0)} />
        <Stat label="累计充值/赠送" value={num(w?.totalRecharged ?? 0)} />
        <Stat label="累计消耗" value={num(w?.totalConsumed ?? 0)} />
      </div>
      {can.finance && (
        <Card title="人工调整积分">
          <div className="grid gap-3 sm:grid-cols-[140px_1fr_160px_auto] sm:items-end">
            <label className="block">
              <span className="mb-1 block text-xs text-foreground-500">数量（负数为扣减）</span>
              <input className={inputCls} inputMode="numeric" value={adj.delta} onChange={(e) => setAdj({ ...adj, delta: e.target.value.replace(/[^\d-]/g, "") })} />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-foreground-500">原因（企业可见）</span>
              <input className={inputCls} value={adj.note} onChange={(e) => setAdj({ ...adj, note: e.target.value })} placeholder="如：线下合同赠送、补偿" />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-foreground-500">到期日（增加时可选）</span>
              <input className={inputCls} type="date" value={adj.expiresAt} onChange={(e) => setAdj({ ...adj, expiresAt: e.target.value })} />
            </label>
            <button type="button" className={btnPrimary} disabled={!Number(adj.delta) || adj.note.trim().length < 2} onClick={submit}>
              提交
            </button>
          </div>
        </Card>
      )}
      <div className="space-y-4">
        <Card
          title="成员积分消耗"
          extra={
            <Link to={`/users?tenantId=${tenant.id}`} className={linkBtn}>
              在全员费用中查看明细
            </Link>
          }
        >
          {users.length ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px]">
                <thead className={theadCls}>
                  <tr>
                    <th className={thCls}>成员</th>
                    <th className={thCls}>角色</th>
                    <th className={`${thCls} text-right`}>本月积分</th>
                    <th className={`${thCls} text-right`}>本月 Token</th>
                    <th className={`${thCls} text-right`}>月度额度</th>
                    <th className={`${thCls} text-right`}>累计积分</th>
                    <th className={`${thCls} text-right`}>最近使用</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.userId} className={trCls}>
                      <td className={tdCls}>
                        {u.name}
                        {u.disabled && <span className="ml-1.5 rounded bg-background-200 px-1 text-[11px] text-foreground-500">已停用</span>}
                        <div className="text-[11px] text-foreground-500">{u.account}</div>
                      </td>
                      <td className={`${tdCls} text-xs`}>{u.role}</td>
                      <td className={`${tdCls} text-right font-medium`}>{num(u.monthSpent)}</td>
                      <td className={`${tdCls} text-right`} title={num(u.monthTokens)}>
                        {tokens(u.monthTokens)}
                      </td>
                      <td className={`${tdCls} text-right`}>{u.monthlyCreditLimit == null ? "不限" : num(u.monthlyCreditLimit)}</td>
                      <td className={`${tdCls} text-right`}>{num(u.totalSpent)}</td>
                      <td className={`${tdCls} text-right text-xs text-foreground-500`}>{u.lastUsedAt || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty text="暂无成员" />
          )}
        </Card>
        <Card title="积分流水">
          {ledger.items.length ? (
            <>
              <table className="w-full">
                <thead className={theadCls}>
                  <tr>
                    <th className={thCls}>时间</th>
                    <th className={thCls}>类型</th>
                    <th className={thCls}>说明</th>
                    <th className={`${thCls} text-right`}>变动</th>
                    <th className={`${thCls} text-right`}>余额</th>
                  </tr>
                </thead>
                <tbody>
                  {ledger.items.map((r) => (
                    <tr key={r.id} className={trCls}>
                      <td className={`${tdCls} text-xs`}>{r.createdAt}</td>
                      <td className={tdCls}>{r.kind}</td>
                      <td className={`${tdCls} text-xs`}>{r.note || r.feature} {r.userName && `· ${r.userName}`}</td>
                      <td className={`${tdCls} text-right ${r.amount >= 0 ? "text-emerald-600" : ""}`}>
                        {r.amount >= 0 ? "+" : ""}
                        {num(r.amount)}
                      </td>
                      <td className={`${tdCls} text-right text-foreground-500`}>{num(r.balanceAfter)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <PaginationBar page={page} pageSize={50} total={ledger.total} onPageChange={setPage} />
            </>
          ) : (
            <Empty text="暂无流水" />
          )}
        </Card>
      </div>
    </div>
  );
}

function LibrariesTab({ tenantId }: { tenantId: string }) {
  const { fail } = useUi();
  const [data, setData] = useState<TenantLibraries | null>(null);

  useEffect(() => {
    getTenantLibraries(tenantId).then(setData).catch(fail);
  }, [tenantId, fail]);

  if (!data) return <Empty text="加载中…" />;
  const s = data.stats;
  const knowledgeTotal = Object.values(s.knowledge).reduce((a, b) => a + b.count, 0);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="知识库文档" value={num(knowledgeTotal)} hint={Object.entries(s.knowledge).map(([k, v]) => `${k} ${v.count}`).join(" · ") || undefined} />
        <Stat label="资质证照" value={num(s.qualifications)} />
        <Stat label="产品库" value={num(s.productLibraries)} />
        <Stat label="产品功能条目" value={num(s.productFeatures)} />
        <Stat label="项目" value={num(s.projects)} />
        <Stat label="对话消息" value={num(s.chatMessages)} />
      </div>
      {data.detail ? (
        <>
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
            企业已授权运维查看（至 {data.supportGrant?.expiresAt}）。本次查看已记入平台审计，仅展示目录信息，不含文件内容。
          </p>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="知识库">
              <table className="w-full">
                <tbody>
                  {data.detail.knowledge.map((d) => (
                    <tr key={d.id} className={`${trCls} first:border-0`}>
                      <td className={tdCls}>{d.title}</td>
                      <td className={`${tdCls} text-xs`}>{d.scope}</td>
                      <td className={`${tdCls} text-xs`}>{d.type}</td>
                      <td className={`${tdCls} text-right text-xs`}>{formatBytes(d.sizeBytes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <div className="space-y-4">
              <Card title="资质证照">
                <table className="w-full">
                  <tbody>
                    {data.detail.qualifications.map((q) => (
                      <tr key={q.id} className={`${trCls} first:border-0`}>
                        <td className={tdCls}>{q.name}</td>
                        <td className={`${tdCls} text-xs`}>{q.category}</td>
                        <td className={`${tdCls} text-xs`}>{q.validUntil || "—"}</td>
                        <td className={`${tdCls} text-xs`}>{q.reviewStatus}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
              <Card title="产品库">
                {data.detail.productLibraries.map((p) => (
                  <div key={p.id} className="py-1 text-sm">
                    {p.name} <span className="text-xs text-foreground-500">{p.category}</span>
                  </div>
                ))}
              </Card>
            </div>
          </div>
        </>
      ) : (
        <Card>
          <p className="text-sm text-foreground-600">
            <i className="ri-lock-line mr-1"></i>
            企业资料库内容默认对平台不可见。如需协助排查，请企业管理员在「企业与组织 → 平台支持授权」中临时授权。
          </p>
        </Card>
      )}
    </div>
  );
}

function StorageTab({ tenantId }: { tenantId: string }) {
  const { fail } = useUi();
  const [data, setData] = useState<Awaited<ReturnType<typeof getTenantStorage>> | null>(null);

  useEffect(() => {
    getTenantStorage(tenantId).then(setData).catch(fail);
  }, [tenantId, fail]);

  if (!data) return <Empty text="统计中…（需要遍历 bucket，企业文件多时较慢）" />;
  const quota = data.quotaMb * 1024 * 1024;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Bucket" value={<span className="font-mono text-base">{data.bucket}</span>} />
        <Stat label="对象数" value={num(data.objects)} />
        <Stat label="已用 / 配额" value={`${formatBytes(data.bytes)} / ${quota ? formatBytes(quota) : "不限"}`} tone={quota && data.bytes > quota * 0.9 ? "warn" : "default"} />
      </div>
      <Card title="按目录汇总">
        {data.prefixes.length ? (
          <table className="w-full">
            <thead className={theadCls}>
              <tr>
                <th className={thCls}>目录</th>
                <th className={`${thCls} text-right`}>对象数</th>
                <th className={`${thCls} text-right`}>大小</th>
              </tr>
            </thead>
            <tbody>
              {data.prefixes.map((p) => (
                <tr key={p.prefix} className={trCls}>
                  <td className={`${tdCls} font-mono text-xs`}>{p.prefix}/</td>
                  <td className={`${tdCls} text-right`}>{num(p.objects)}</td>
                  <td className={`${tdCls} text-right`}>{formatBytes(p.bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty text="bucket 为空" />
        )}
      </Card>
    </div>
  );
}
