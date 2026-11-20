import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import PageHeader from "@/pages/console/components/PageHeader";
import Modal from "@/pages/console/components/Modal";
import { createTenant, listAdminPlans, listTenants, type AdminPlan, type AdminTenant, type Paged } from "../api";
import { useCan } from "../auth";
import { ACCOUNT_KINDS, btnGhost, btnPrimary, Card, Empty, Filter, inputCls, KindTag, num, PaginationBar, StatusTag, tdCls, theadCls, thCls, trCls, useUi } from "../ui";

const STATUS = [
  { id: "", label: "全部状态" },
  { id: "试用", label: "试用" },
  { id: "正常", label: "正常" },
  { id: "停用", label: "停用" },
  { id: "已注销", label: "已注销" },
] as const;

const VERIFY = [
  { id: "", label: "全部认证" },
  { id: "待审核", label: "待审核" },
  { id: "已认证", label: "已认证" },
  { id: "未认证", label: "未认证" },
  { id: "已驳回", label: "已驳回" },
] as const;

const KINDS = ACCOUNT_KINDS;

const EMPTY_FORM = { kind: "企业" as "企业" | "个人", name: "", adminName: "", adminLogin: "", planCode: "trial", contactPhone: "", contactEmail: "" };

export default function TenantsPage() {
  const { fail, ask } = useUi();
  const can = useCan();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const status = params.get("status") || "";
  const verify = params.get("verify") || "";
  const kind = params.get("kind") || "";
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Paged<AdminTenant>>({ total: 0, items: [] });
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [plans, setPlans] = useState<AdminPlan[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    listTenants({ q, status, verify, kind, page }).then(setData).catch(fail);
  }, [q, status, verify, kind, page, fail]);

  useEffect(() => {
    const t = window.setTimeout(load, 250);
    return () => window.clearTimeout(t);
  }, [load]);

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setPage(1);
  };

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setCreating(true);
    listAdminPlans().then((p) => setPlans(p.filter((x) => x.kind === "套餐"))).catch(fail);
  };

  const plansForKind = plans.filter((p) => p.audience === "通用" || p.audience === form.kind);

  const submit = async () => {
    setBusy(true);
    try {
      const res = await createTenant(form);
      setCreating(false);
      load();
      await ask({
        title: form.kind === "个人" ? "个人账号已开通" : "企业已开通",
        message: `编号：${res.id}\n${form.kind === "个人" ? "登录账号" : "管理员账号"}：${res.adminLogin}\n初始密码：${res.initialPassword}\n\n密码仅显示这一次，请通过安全渠道告知客户，并提醒其首次登录后修改。`,
        required: false,
        confirmText: "我已记录",
      });
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="企业管理"
        description="企业和个人账号各自拥有独立的数据库 schema、对象存储 bucket 和积分钱包，互不可见。企业成员共享一个积分池，个人账号只有本人。"
        actions={
          can.ops && (
            <button type="button" className={btnPrimary} onClick={openCreate}>
              <i className="ri-add-line"></i>开通账号
            </button>
          )
        }
      />
      <Card>
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <input
            className={`${inputCls} max-w-xs`}
            placeholder="搜索企业名称、编号、联系电话或邮箱"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
          <Filter options={KINDS} value={kind as (typeof KINDS)[number]["id"]} onChange={(v) => setFilter("kind", v)} />
          <Filter options={STATUS} value={status as (typeof STATUS)[number]["id"]} onChange={(v) => setFilter("status", v)} />
          <Filter options={VERIFY} value={verify as (typeof VERIFY)[number]["id"]} onChange={(v) => setFilter("verify", v)} />
        </div>
        {data.items.length ? (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px]">
                <thead className={theadCls}>
                  <tr>
                    <th className={thCls}>企业</th>
                    <th className={thCls}>状态</th>
                    <th className={thCls}>认证</th>
                    <th className={thCls}>套餐</th>
                    <th className={thCls}>席位</th>
                    <th className={`${thCls} text-right`}>积分余额</th>
                    <th className={thCls}>到期</th>
                    <th className={thCls}>开通时间</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((t) => (
                    <tr key={t.id} className={trCls}>
                      <td className={tdCls}>
                        <Link to={`/tenants/${t.id}`} className="font-medium text-primary-700 hover:underline">
                          {t.name}
                        </Link>
                        <KindTag kind={t.kind} />
                        <div className="font-mono text-[11px] text-foreground-500">{t.id}</div>
                      </td>
                      <td className={tdCls}>
                        <StatusTag status={t.status} />
                      </td>
                      <td className={tdCls}>
                        <StatusTag status={t.verifyStatus} />
                      </td>
                      <td className={tdCls}>{t.planCode}</td>
                      <td className={tdCls}>{t.kind === "个人" ? "本人" : `${t.seatsUsed ?? "—"} / ${t.seats}`}</td>
                      <td className={`${tdCls} text-right`}>{t.wallet ? num(t.wallet.balance - t.wallet.held) : "—"}</td>
                      <td className={`${tdCls} text-xs`}>{(t.status === "试用" ? t.trialEndsAt : t.expiresAt) || "长期"}</td>
                      <td className={`${tdCls} text-xs text-foreground-500`}>{t.createdAt}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <PaginationBar page={page} pageSize={20} total={data.total} onPageChange={setPage} />
          </>
        ) : (
          <Empty text="没有符合条件的企业" />
        )}
      </Card>

      {creating && (
        <Modal open onClose={() => setCreating(false)} title="开通账号" subtitle="为线下签约客户直接开通，系统生成登录账号的初始密码">
          <div className="space-y-3">
            <div className="flex gap-4 text-sm">
              {(["企业", "个人"] as const).map((k) => (
                <label key={k} className="flex cursor-pointer items-center gap-1.5">
                  <input type="radio" checked={form.kind === k} onChange={() => setForm({ ...form, kind: k, planCode: "trial" })} />
                  {k === "企业" ? "企业（多成员共享积分池）" : "个人（无单位，仅本人使用）"}
                </label>
              ))}
            </div>
            {(
              [
                ["name", form.kind === "个人" ? "空间名称（如：张三的个人空间）" : "企业名称（与营业执照一致）"],
                ["adminName", form.kind === "个人" ? "姓名" : "管理员姓名"],
                ["adminLogin", form.kind === "个人" ? "登录账号（手机号或邮箱）" : "管理员登录账号（手机号或邮箱）"],
                ["contactPhone", "联系电话"],
                ["contactEmail", "联系邮箱"],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="block">
                <span className="mb-1 block text-xs text-foreground-500">{label}</span>
                <input className={inputCls} value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
              </label>
            ))}
            <label className="block">
              <span className="mb-1 block text-xs text-foreground-500">初始套餐</span>
              <select className={inputCls} value={form.planCode} onChange={(e) => setForm({ ...form, planCode: e.target.value })}>
                {plansForKind.map((p) => (
                  <option key={p.code} value={p.code}>
                    {p.name}（{p.code}）
                  </option>
                ))}
                {!plansForKind.some((p) => p.code === "trial") && <option value="trial">试用（trial）</option>}
              </select>
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" className={btnGhost} onClick={() => setCreating(false)}>
                取消
              </button>
              <button type="button" className={btnPrimary} disabled={busy || form.name.trim().length < 2 || form.adminLogin.trim().length < 3} onClick={submit}>
                开通
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
