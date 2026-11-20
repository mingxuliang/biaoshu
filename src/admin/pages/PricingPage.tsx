import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import PageHeader from "@/pages/console/components/PageHeader";
import Modal from "@/pages/console/components/Modal";
import { yuan } from "@/lib/saasApi";
import {
  listAdminPlans,
  listAdminPrices,
  listModelRatios,
  savePlan,
  setModelRatio,
  updatePrice,
  type AdminPlan,
  type AdminPriceRule,
  type ModelRatio,
  type PlanInput,
} from "../api";
import { useCan } from "../auth";
import { btnGhost, btnPrimary, Card, Empty, inputCls, linkBtn, num, Tabs, tdCls, theadCls, thCls, trCls, useUi } from "../ui";

const TABS = [
  { id: "prices", label: "扣费规则" },
  { id: "ratios", label: "模型倍率" },
  { id: "plans", label: "套餐与加油包" },
] as const;
type TabId = (typeof TABS)[number]["id"];

const MODE_LABEL: Record<AdminPriceRule["mode"], string> = { per_1k_tokens: "按千 Token", per_call: "按次", free: "免费" };

export default function PricingPage() {
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id || "prices") as TabId;
  return (
    <div>
      <PageHeader
        title="扣费规则与套餐"
        description="实际扣费 = 功能单价 × 用量 × 模型倍率。AI 任务开始前按「预占」冻结积分，完成后按实际用量结算，失败自动退回。"
      />
      <Tabs tabs={TABS} value={tab} onChange={(t) => setParams(t === "prices" ? {} : { tab: t }, { replace: true })} />
      {tab === "prices" && <Prices />}
      {tab === "ratios" && <Ratios />}
      {tab === "plans" && <Plans />}
    </div>
  );
}

function Prices() {
  const { notify, fail } = useUi();
  const can = useCan();
  const [rows, setRows] = useState<AdminPriceRule[]>([]);
  const [edits, setEdits] = useState<Record<string, AdminPriceRule>>({});

  const load = useCallback(() => {
    listAdminPrices()
      .then((r) => {
        setRows(r);
        setEdits({});
      })
      .catch(fail);
  }, [fail]);
  useEffect(load, [load]);

  const edit = (r: AdminPriceRule, patch: Partial<AdminPriceRule>) => setEdits({ ...edits, [r.feature]: { ...(edits[r.feature] || r), ...patch } });

  const save = async (feature: string) => {
    const r = edits[feature];
    try {
      await updatePrice(feature, { name: r.name, mode: r.mode, unitPrice: r.unitPrice, estimate: r.estimate, enabled: r.enabled });
      notify("扣费规则已保存，新任务立即生效");
      load();
    } catch (e) {
      fail(e);
    }
  };

  return (
    <Card>
      {rows.length ? (
        <table className="w-full">
          <thead className={theadCls}>
            <tr>
              <th className={thCls}>功能</th>
              <th className={thCls}>计费方式</th>
              <th className={`${thCls} text-right`}>单价（积分）</th>
              <th className={`${thCls} text-right`}>预占（积分）</th>
              <th className={thCls}>启用</th>
              <th className={thCls}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const r = edits[row.feature] || row;
              const dirty = !!edits[row.feature];
              return (
                <tr key={row.feature} className={trCls}>
                  <td className={tdCls}>
                    <input className={`${inputCls} h-8`} disabled={!can.finance} value={r.name} onChange={(e) => edit(row, { name: e.target.value })} />
                    <div className="mt-0.5 font-mono text-[11px] text-foreground-500">{row.feature}</div>
                  </td>
                  <td className={tdCls}>
                    <select className={`${inputCls} h-8`} disabled={!can.finance} value={r.mode} onChange={(e) => edit(row, { mode: e.target.value as AdminPriceRule["mode"] })}>
                      {Object.entries(MODE_LABEL).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className={tdCls}>
                    <input className={`${inputCls} h-8 text-right`} type="number" step="0.01" min={0} disabled={!can.finance || r.mode === "free"} value={r.unitPrice} onChange={(e) => edit(row, { unitPrice: Number(e.target.value) })} />
                  </td>
                  <td className={tdCls}>
                    <input className={`${inputCls} h-8 text-right`} type="number" min={0} disabled={!can.finance || r.mode === "free"} value={r.estimate} onChange={(e) => edit(row, { estimate: Number(e.target.value) })} />
                  </td>
                  <td className={tdCls}>
                    <input type="checkbox" disabled={!can.finance} checked={r.enabled} onChange={(e) => edit(row, { enabled: e.target.checked })} />
                  </td>
                  <td className={`${tdCls} text-right`}>
                    {dirty && (
                      <button type="button" className={linkBtn} onClick={() => save(row.feature)}>
                        保存
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : (
        <Empty text="暂无扣费规则" />
      )}
    </Card>
  );
}

function Ratios() {
  const { notify, fail, ask } = useUi();
  const can = useCan();
  const [rows, setRows] = useState<ModelRatio[]>([]);

  const load = useCallback(() => {
    listModelRatios().then(setRows).catch(fail);
  }, [fail]);
  useEffect(load, [load]);

  const change = async (r: ModelRatio) => {
    const v = await ask({ title: `设置「${r.name}」的计费倍率`, message: "1 表示按标准单价；贵的模型可设为 2、3，便宜的可设为 0.5。", initial: String(r.ratio), inputType: "number" });
    if (v === null) return;
    const ratio = Number(v);
    if (!(ratio > 0)) return fail(new Error("倍率必须大于 0"));
    try {
      await setModelRatio(r.key, ratio, r.note);
      notify("倍率已更新");
      load();
    } catch (e) {
      fail(e);
    }
  };

  return (
    <Card>
      {rows.length ? (
        <table className="w-full">
          <thead className={theadCls}>
            <tr>
              <th className={thCls}>模型</th>
              <th className={thCls}>接口模型名</th>
              <th className={thCls}>用途</th>
              <th className={`${thCls} text-right`}>倍率</th>
              <th className={thCls}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className={trCls}>
                <td className={tdCls}>{r.name}</td>
                <td className={`${tdCls} font-mono text-xs`}>{r.apiModel}</td>
                <td className={tdCls}>{r.task === "image" ? "生图" : r.task ? "对话" : "—"}</td>
                <td className={`${tdCls} text-right font-medium`}>× {r.ratio}</td>
                <td className={`${tdCls} text-right`}>
                  {can.finance && (
                    <button type="button" className={linkBtn} onClick={() => change(r)}>
                      修改
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <Empty text="还没有接入模型" />
      )}
    </Card>
  );
}

const AUDIENCE_LABEL: Record<string, string> = { 企业: "企业", 个人: "个人", 通用: "企业和个人" };

const EMPTY_PLAN: PlanInput & { code: string } = {
  code: "",
  kind: "套餐",
  audience: "企业",
  name: "",
  priceCents: 0,
  durationDays: 365,
  seats: 0,
  credits: 0,
  bonusCredits: 0,
  storageMb: 0,
  rechargeBonusPct: 0,
  features: {},
  description: "",
  enabled: true,
  sortOrder: 0,
};

function Plans() {
  const { notify, fail } = useUi();
  const can = useCan();
  const [rows, setRows] = useState<AdminPlan[]>([]);
  const [editing, setEditing] = useState<(PlanInput & { code: string; isNew: boolean }) | null>(null);

  const load = useCallback(() => {
    listAdminPlans().then(setRows).catch(fail);
  }, [fail]);
  useEffect(load, [load]);

  const submit = async () => {
    if (!editing) return;
    const { code, isNew: _isNew, ...rest } = editing;
    try {
      await savePlan(code.trim(), rest);
      setEditing(null);
      notify("套餐已保存");
      load();
    } catch (e) {
      fail(e);
    }
  };

  const numField = (key: keyof PlanInput, label: string, scale = 1) =>
    editing && (
      <label className="block">
        <span className="mb-1 block text-xs text-foreground-500">{label}</span>
        <input
          className={inputCls}
          type="number"
          min={0}
          value={(editing[key] as number) / scale}
          onChange={(e) => setEditing({ ...editing, [key]: Math.round(Number(e.target.value || 0) * scale) })}
        />
      </label>
    );

  return (
    <Card
      extra={
        can.finance && (
          <button type="button" className={btnGhost} onClick={() => setEditing({ ...EMPTY_PLAN, isNew: true })}>
            <i className="ri-add-line"></i>新增
          </button>
        )
      }
      title="套餐与加油包"
    >
      <table className="w-full">
        <thead className={theadCls}>
          <tr>
            <th className={thCls}>名称</th>
            <th className={thCls}>类型</th>
            <th className={thCls}>适用</th>
            <th className={`${thCls} text-right`}>价格</th>
            <th className={`${thCls} text-right`}>时长</th>
            <th className={`${thCls} text-right`}>席位</th>
            <th className={`${thCls} text-right`}>积分（+赠送）</th>
            <th className={`${thCls} text-right`}>存储</th>
            <th className={`${thCls} text-right`}>充值加赠</th>
            <th className={thCls}>状态</th>
            <th className={thCls}></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.code} className={`${trCls} ${p.enabled ? "" : "opacity-50"}`}>
              <td className={tdCls}>
                {p.name}
                <div className="font-mono text-[11px] text-foreground-500">{p.code}</div>
              </td>
              <td className={tdCls}>{p.kind}</td>
              <td className={tdCls}>{AUDIENCE_LABEL[p.audience] || p.audience}</td>
              <td className={`${tdCls} text-right`}>{yuan(p.priceCents)}</td>
              <td className={`${tdCls} text-right`}>{p.durationDays} 天</td>
              <td className={`${tdCls} text-right`}>{p.seats || "—"}</td>
              <td className={`${tdCls} text-right`}>
                {num(p.credits)}
                {p.bonusCredits > 0 && ` + ${num(p.bonusCredits)}`}
              </td>
              <td className={`${tdCls} text-right`}>{p.storageMb ? `${p.storageMb} MB` : "—"}</td>
              <td className={`${tdCls} text-right`}>{p.rechargeBonusPct ? `${p.rechargeBonusPct}%` : "—"}</td>
              <td className={tdCls}>{p.enabled ? "上架" : "下架"}</td>
              <td className={`${tdCls} text-right`}>
                {can.finance && (
                  <button type="button" className={linkBtn} onClick={() => setEditing({ ...p, isNew: false })}>
                    编辑
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {editing && (
        <Modal open onClose={() => setEditing(null)} title={editing.isNew ? "新增套餐/加油包" : `编辑 ${editing.name}`} width="max-w-2xl">
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="block">
                <span className="mb-1 block text-xs text-foreground-500">编码（小写字母、数字、横线）</span>
                <input className={inputCls} disabled={!editing.isNew} value={editing.code} onChange={(e) => setEditing({ ...editing, code: e.target.value.toLowerCase() })} />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-foreground-500">名称</span>
                <input className={inputCls} value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-foreground-500">类型</span>
                <select className={inputCls} value={editing.kind} onChange={(e) => setEditing({ ...editing, kind: e.target.value as PlanInput["kind"] })}>
                  <option>套餐</option>
                  <option>加油包</option>
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-foreground-500">适用对象</span>
                <select className={inputCls} value={editing.audience} onChange={(e) => setEditing({ ...editing, audience: e.target.value as PlanInput["audience"] })}>
                  {Object.entries(AUDIENCE_LABEL).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
              {numField("priceCents", "价格（元）", 100)}
              {numField("durationDays", editing.kind === "套餐" ? "服务时长（天）" : "积分有效期（天）")}
              {numField("sortOrder", "排序")}
              {numField("credits", "包含积分")}
              {numField("bonusCredits", "额外赠送积分")}
              {editing.kind === "套餐" && editing.audience !== "个人" && numField("seats", "席位数（企业成员共享积分池）")}
              {editing.kind === "套餐" && numField("storageMb", "存储配额（MB）")}
              {editing.kind === "套餐" && numField("rechargeBonusPct", "充值额外赠送 %")}
            </div>
            <label className="block">
              <span className="mb-1 block text-xs text-foreground-500">说明</span>
              <input className={inputCls} value={editing.description} onChange={(e) => setEditing({ ...editing, description: e.target.value })} />
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={editing.enabled} onChange={(e) => setEditing({ ...editing, enabled: e.target.checked })} />
              上架（对应的企业或个人账号可在费用中心购买）
            </label>
            <div className="flex justify-end gap-2">
              <button type="button" className={btnGhost} onClick={() => setEditing(null)}>
                取消
              </button>
              <button type="button" className={btnPrimary} disabled={!editing.code.trim() || !editing.name.trim()} onClick={submit}>
                保存
              </button>
            </div>
          </div>
        </Modal>
      )}
    </Card>
  );
}
