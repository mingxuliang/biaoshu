import { useEffect, useMemo, useState } from "react";
import {
  createOrder,
  listPayChannels,
  listPlans,
  listPrices,
  quoteOrder,
  tokensLabel,
  yuan,
  type Order,
  type OrderKind,
  type PayChannel,
  type Plan,
  type PriceRule,
} from "@/lib/saasApi";
import { btnPrimary, Card, inputCls } from "./ui";

const PRESET_YUAN = [100, 500, 1000, 5000];

interface Props {
  currentPlanCode?: string;
  canManage: boolean;
  tokensPerCredit: number;
  personal: boolean;
  onOrder: (order: Order) => void;
  onError: (msg: string) => void;
}

type Selection = { kind: OrderKind; itemCode?: string; amountCents?: number };

export default function RechargePanel({ currentPlanCode, canManage, tokensPerCredit, personal, onOrder, onError }: Props) {
  const tokens = (credits: number) => tokensLabel(credits, tokensPerCredit);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [channels, setChannels] = useState<{ id: PayChannel; name: string; ready: boolean }[]>([]);
  const [prices, setPrices] = useState<{ creditsPerYuan: number; tokensPerCredit: number; rules: PriceRule[] }>({ creditsPerYuan: 0, tokensPerCredit: 1000, rules: [] });
  const [sel, setSel] = useState<Selection>({ kind: "充值", amountCents: 50000 });
  const [custom, setCustom] = useState("");
  const [channel, setChannel] = useState<PayChannel | "">("");
  const [quote, setQuote] = useState<{ amountCents: number; credits: number; bonusCredits: number; subject: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([listPlans(), listPayChannels(), listPrices()])
      .then(([p, c, pr]) => {
        setPlans(p);
        setChannels(c);
        setPrices(pr);
        const first = c.find((x) => x.ready);
        if (first) setChannel(first.id);
      })
      .catch((e) => onError(e instanceof Error ? e.message : "加载失败"));
  }, [onError]);

  useEffect(() => {
    let cancelled = false;
    setQuote(null);
    if (sel.kind === "充值" && (!sel.amountCents || sel.amountCents < 1000)) return;
    quoteOrder(sel)
      .then((q) => !cancelled && setQuote(q))
      .catch(() => !cancelled && setQuote(null));
    return () => {
      cancelled = true;
    };
  }, [sel]);

  const subscriptions = useMemo(() => plans.filter((p) => p.kind === "套餐" && p.priceCents > 0), [plans]);
  const packs = useMemo(() => plans.filter((p) => p.kind === "加油包"), [plans]);

  const submit = async () => {
    if (!channel) return onError("暂无可用的支付方式，请联系平台");
    setBusy(true);
    try {
      onOrder(await createOrder({ ...sel, channel }));
    } catch (e) {
      onError(e instanceof Error ? e.message : "下单失败");
    } finally {
      setBusy(false);
    }
  };

  const isSel = (kind: OrderKind, code?: string, cents?: number) =>
    sel.kind === kind && (code ? sel.itemCode === code : sel.amountCents === cents);
  const tile = (active: boolean) =>
    `cursor-pointer rounded-xl border p-4 text-left transition-all ${active ? "border-primary-400 bg-primary-50 ring-2 ring-primary-400/20" : "border-background-300 bg-background-50 hover:border-primary-300"}`;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
      <div className="space-y-4">
        <Card title="积分充值">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {PRESET_YUAN.map((y) => (
              <button key={y} type="button" className={tile(isSel("充值", undefined, y * 100))} onClick={() => { setCustom(""); setSel({ kind: "充值", amountCents: y * 100 }); }}>
                <div className="text-lg font-semibold text-foreground-950">¥{y}</div>
                <div className="text-xs text-foreground-500">{(y * prices.creditsPerYuan).toLocaleString("zh-CN")} 积分</div>
                <div className="text-[11px] text-foreground-400">{tokens(y * prices.creditsPerYuan)}</div>
              </button>
            ))}
          </div>
          <div className="mt-3 flex items-center gap-2">
            <span className="shrink-0 text-sm text-foreground-600">自定义金额</span>
            <input
              className={`${inputCls} max-w-[180px]`}
              inputMode="decimal"
              placeholder="最低 10 元"
              value={custom}
              onChange={(e) => {
                const v = e.target.value.replace(/[^\d.]/g, "");
                setCustom(v);
                setSel({ kind: "充值", amountCents: Math.round(Number(v || 0) * 100) });
              }}
            />
            <span className="text-xs text-foreground-500">元，1 元 = {prices.creditsPerYuan} 积分</span>
          </div>
        </Card>

        <Card
          title={personal ? "个人套餐" : "企业套餐"}
          extra={
            <span className="text-xs text-foreground-500">
              {personal ? "积分仅本人使用" : "套餐积分进入企业积分池，全体成员共用"} · 续订同一套餐自动顺延
            </span>
          }
        >
          <div className="grid gap-3 sm:grid-cols-3">
            {subscriptions.map((p) => (
              <button key={p.code} type="button" className={tile(isSel("套餐", p.code))} onClick={() => setSel({ kind: "套餐", itemCode: p.code })}>
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-foreground-950">{p.name}</span>
                  {p.code === currentPlanCode && <span className="rounded bg-primary-100 px-1.5 text-[11px] text-primary-700">当前</span>}
                </div>
                <div className="mt-1 text-xl font-semibold text-primary-600">
                  {yuan(p.priceCents)}
                  <span className="text-xs font-normal text-foreground-500"> / {p.durationDays >= 365 ? "年" : `${p.durationDays}天`}</span>
                </div>
                <ul className="mt-2 space-y-0.5 text-xs text-foreground-600">
                  <li>{personal ? "本人使用" : `${p.seats} 个席位共享积分池`}</li>
                  <li>
                    含 {p.credits.toLocaleString("zh-CN")} 积分（{tokens(p.credits)}）
                  </li>
                  <li>{p.storageMb >= 1024 ? `${(p.storageMb / 1024).toFixed(0)} GB` : `${p.storageMb} MB`} 存储空间</li>
                  {p.rechargeBonusPct > 0 && <li>充值额外赠送 {p.rechargeBonusPct}%</li>}
                </ul>
              </button>
            ))}
          </div>
        </Card>

        {packs.length > 0 && (
          <Card title="积分加油包">
            <div className="grid gap-3 sm:grid-cols-3">
              {packs.map((p) => (
                <button key={p.code} type="button" className={tile(isSel("加油包", p.code))} onClick={() => setSel({ kind: "加油包", itemCode: p.code })}>
                  <div className="font-semibold text-foreground-950">{p.name}</div>
                  <div className="mt-1 text-lg font-semibold text-primary-600">{yuan(p.priceCents)}</div>
                  <div className="text-xs text-foreground-500">
                    {(p.credits + p.bonusCredits).toLocaleString("zh-CN")} 积分 · {p.durationDays} 天有效
                  </div>
                  <div className="text-[11px] text-foreground-400">{tokens(p.credits + p.bonusCredits)}</div>
                </button>
              ))}
            </div>
          </Card>
        )}

        <Card title="计费标准">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-foreground-500">
              <tr>
                <th className="py-1.5 font-normal">功能</th>
                <th className="py-1.5 font-normal">计费方式</th>
                <th className="py-1.5 text-right font-normal">单价</th>
              </tr>
            </thead>
            <tbody>
              {prices.rules.map((r) => (
                <tr key={r.feature} className="border-t border-background-300">
                  <td className="py-1.5 text-foreground-800">{r.name}</td>
                  <td className="py-1.5 text-foreground-600">{r.mode === "per_call" ? "按次" : r.mode === "free" ? "免费" : "按 Token"}</td>
                  <td className="py-1.5 text-right text-foreground-800">
                    {r.mode === "free" ? "—" : r.mode === "per_call" ? `${r.unitPrice} 积分/次` : `${r.unitPrice} 积分/千 Token`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-foreground-500">
            按标准模型估算，1 积分约合 {tokensPerCredit.toLocaleString("zh-CN")} Token；不同模型按平台设定的倍率折算。AI 任务失败自动退回积分。
          </p>
        </Card>
      </div>

      <div className="lg:sticky lg:top-4 lg:self-start">
        <Card title="确认订单">
          <div className="space-y-3 text-sm">
            <div className="rounded-lg bg-background-50 p-3">
              <div className="text-foreground-800">{quote?.subject || "请选择充值金额或套餐"}</div>
              {quote && (
                <>
                  <div className="mt-2 text-2xl font-semibold text-foreground-950">{yuan(quote.amountCents)}</div>
                  <div className="mt-1 text-xs text-foreground-500">
                    到账 {quote.credits.toLocaleString("zh-CN")} 积分
                    {quote.bonusCredits > 0 && <span className="text-primary-600">，赠送 {quote.bonusCredits.toLocaleString("zh-CN")}</span>}
                    <span className="block text-foreground-400">{tokens(quote.credits + quote.bonusCredits)}</span>
                  </div>
                </>
              )}
            </div>
            <div>
              <div className="mb-1.5 text-xs text-foreground-500">支付方式</div>
              <div className="space-y-1.5">
                {channels.map((c) => (
                  <label key={c.id} className={`flex items-center gap-2 rounded-lg border px-3 py-2 ${c.ready ? "cursor-pointer" : "cursor-not-allowed opacity-50"} ${channel === c.id ? "border-primary-400 bg-primary-50" : "border-background-300"}`}>
                    <input type="radio" name="channel" disabled={!c.ready} checked={channel === c.id} onChange={() => setChannel(c.id)} />
                    <span className="text-foreground-800">{c.name}</span>
                    {!c.ready && <span className="ml-auto text-[11px] text-foreground-500">未开通</span>}
                  </label>
                ))}
              </div>
            </div>
            <button type="button" className={`${btnPrimary} w-full`} disabled={!canManage || !quote || !channel || busy} onClick={submit}>
              立即支付
            </button>
            {!canManage && <p className="text-xs text-amber-700">只有具备「费用中心」权限的成员可以下单，请联系企业管理员。</p>}
          </div>
        </Card>
      </div>
    </div>
  );
}
