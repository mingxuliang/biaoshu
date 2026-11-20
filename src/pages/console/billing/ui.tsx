import type { ReactNode } from "react";

export const btnPrimary =
  "inline-flex h-9 cursor-pointer items-center justify-center gap-1.5 rounded-lg bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-50";
export const btnGhost =
  "inline-flex h-9 cursor-pointer items-center justify-center gap-1.5 rounded-lg border border-background-300 bg-background-100 px-4 text-sm text-foreground-700 transition-colors hover:bg-background-200 disabled:cursor-not-allowed disabled:opacity-50";
export const inputCls =
  "h-9 w-full rounded-lg border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all placeholder:text-foreground-400 focus:border-primary-400 focus:ring-2 focus:ring-primary-400/20";

export function Card({ title, extra, children, className = "" }: { title?: string; extra?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-background-300 bg-background-100 ${className}`}>
      {title && (
        <div className="flex items-center justify-between border-b border-background-300 px-4 py-3">
          <h3 className="text-sm font-semibold text-foreground-900">{title}</h3>
          {extra}
        </div>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, tone = "default" }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "default" | "warn" }) {
  return (
    <div className={`rounded-xl border px-4 py-3 ${tone === "warn" ? "border-amber-200 bg-amber-50" : "border-background-300 bg-background-100"}`}>
      <div className="text-xs text-foreground-500">{label}</div>
      <div className={`mt-1 text-xl font-semibold ${tone === "warn" ? "text-amber-700" : "text-foreground-950"}`}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-foreground-500">{hint}</div>}
    </div>
  );
}

const STATUS_TONE: Record<string, string> = {
  已支付: "bg-emerald-50 text-emerald-700 border-emerald-200",
  已开具: "bg-emerald-50 text-emerald-700 border-emerald-200",
  已认证: "bg-emerald-50 text-emerald-700 border-emerald-200",
  正常: "bg-emerald-50 text-emerald-700 border-emerald-200",
  待支付: "bg-sky-50 text-sky-700 border-sky-200",
  待确认: "bg-amber-50 text-amber-700 border-amber-200",
  待审核: "bg-amber-50 text-amber-700 border-amber-200",
  开具中: "bg-sky-50 text-sky-700 border-sky-200",
  试用: "bg-sky-50 text-sky-700 border-sky-200",
  已关闭: "bg-background-200 text-foreground-500 border-background-300",
  已驳回: "bg-red-50 text-red-700 border-red-200",
  已红冲: "bg-red-50 text-red-700 border-red-200",
  已退款: "bg-red-50 text-red-700 border-red-200",
  停用: "bg-red-50 text-red-700 border-red-200",
};

export function StatusTag({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${STATUS_TONE[status] || "border-background-300 bg-background-200 text-foreground-600"}`}>
      {status}
    </span>
  );
}

export function Empty({ text }: { text: string }) {
  return <p className="py-10 text-center text-sm text-foreground-500">{text}</p>;
}

export const CHANNEL_LABEL: Record<string, string> = {
  alipay: "支付宝",
  wechat: "微信支付",
  bank: "对公转账",
  mock: "模拟支付",
};
