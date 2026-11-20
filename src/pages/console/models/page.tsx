import { useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import { listLlmProviders, type LlmProvider } from "@/lib/api";
import { listPrices, type PriceRule } from "@/lib/saasApi";

/** 企业端只读：模型接入、密钥与倍率由平台统一配置，企业只看可用模型和计费标准。 */
export default function ModelsPage() {
  const [providers, setProviders] = useState<LlmProvider[]>([]);
  const [rules, setRules] = useState<PriceRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([listLlmProviders(), listPrices().catch(() => ({ creditsPerYuan: 0, rules: [] as PriceRule[] }))])
      .then(([p, pr]) => {
        setProviders(p.filter((x) => x.enabled));
        setRules(pr.rules);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <PageHeader title="可用模型" description="平台已接入的大模型由平台统一配置和维护，无需在企业侧填写密钥。调用按「费用中心」中的计费标准扣减企业积分。" />
      {error && <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {loading ? (
        <p className="py-10 text-center text-sm text-foreground-500">加载中…</p>
      ) : (
        <div className="space-y-4">
          {providers.map((provider) => (
            <section key={provider.id} className="rounded-xl border border-background-300 bg-background-100">
              <div className="flex items-center gap-2 border-b border-background-300 px-4 py-3">
                <h3 className="text-sm font-semibold text-foreground-900">{provider.name}</h3>
                <span className={`rounded px-1.5 text-[11px] ${provider.ready ? "bg-emerald-50 text-emerald-700" : "bg-background-200 text-foreground-500"}`}>
                  {provider.ready ? "可用" : "暂不可用"}
                </span>
              </div>
              <div className="divide-y divide-background-300">
                {provider.models
                  .filter((m) => m.enabled)
                  .map((m) => (
                    <div key={m.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-sm">
                      <span className="font-medium text-foreground-900">{m.name}</span>
                      {m.isDefault && <span className="rounded bg-primary-100 px-1.5 text-[11px] text-primary-700">默认</span>}
                      {m.thinking && <span className="rounded bg-sky-50 px-1.5 text-[11px] text-sky-700">深度思考</span>}
                      {m.vision && <span className="rounded bg-amber-50 px-1.5 text-[11px] text-amber-700">识图</span>}
                      {m.task === "image" && <span className="rounded bg-violet-50 px-1.5 text-[11px] text-violet-700">生图</span>}
                      <span className="ml-auto text-xs text-foreground-500">
                        {[m.ctx && `上下文 ${m.ctx}`, m.speed].filter(Boolean).join(" · ")}
                      </span>
                    </div>
                  ))}
              </div>
            </section>
          ))}
          {!providers.length && <p className="py-10 text-center text-sm text-foreground-500">平台暂未开放模型，请联系平台运营。</p>}

          {rules.length > 0 && (
            <section className="rounded-xl border border-background-300 bg-background-100 p-4">
              <h3 className="mb-2 text-sm font-semibold text-foreground-900">计费标准</h3>
              <div className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
                {rules.map((r) => (
                  <div key={r.feature} className="flex justify-between border-b border-background-200 py-1">
                    <span className="text-foreground-700">{r.name}</span>
                    <span className="text-foreground-900">
                      {r.mode === "free" ? "免费" : r.mode === "per_call" ? `${r.unitPrice} 积分/次` : `${r.unitPrice} 积分/千 Token`}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
