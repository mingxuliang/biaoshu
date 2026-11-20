import { useState, type FormEvent } from "react";
import { useAdminAuth } from "./auth";
import { errMsg } from "./ui";

const HIGHLIGHTS = [
  { icon: "ri-building-2-line", title: "企业与个人账号", desc: "开通、套餐、认证审核、组织架构与成员" },
  { icon: "ri-coins-line", title: "积分与 Token", desc: "全部企业和人员的充值、消耗与用量" },
  { icon: "ri-bank-card-line", title: "订单与发票", desc: "在线支付、对公转账认领、对账与开票" },
  { icon: "ri-shield-keyhole-line", title: "安全与审计", desc: "二次验证、IP 白名单，所有操作留痕" },
];

const fieldCls =
  "h-11 w-full rounded-lg border border-background-300 bg-background-100 pl-9 pr-3 text-sm text-foreground-900 placeholder:text-foreground-500 outline-none transition-all focus:border-primary-400 focus:ring-2 focus:ring-primary-400/20";

function Brand({ size = "lg" }: { size?: "lg" | "sm" }) {
  return (
    <div className="flex items-center gap-3">
      <div
        className={`relative flex items-center justify-center rounded-xl bg-gradient-to-br from-primary-400 to-primary-600 text-background-50 ${size === "lg" ? "h-11 w-11" : "h-10 w-10"}`}
      >
        <i className={`ri-shield-star-line ${size === "lg" ? "text-xl" : "text-lg"}`}></i>
        <span className="absolute inset-0 rounded-xl ring-2 ring-primary-400/30" />
      </div>
      <div>
        <div className={`font-heading font-bold tracking-widest text-foreground-950 ${size === "lg" ? "text-xl" : "text-lg"}`}>慧投标</div>
        <div className="font-label text-[11px] text-foreground-500">平台管理后台</div>
      </div>
    </div>
  );
}

export default function AdminLoginPage() {
  const { login } = useAdminAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [totp, setTotp] = useState("");
  const [needTotp, setNeedTotp] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await login(email.trim(), password, totp.trim());
    } catch (err) {
      const msg = errMsg(err);
      if (msg.includes("动态验证码")) setNeedTotp(true);
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen w-full bg-background-50">
      <div className="relative hidden flex-1 overflow-hidden lg:flex">
        <div className="absolute inset-0 bg-grid" />
        <div className="absolute -top-32 -left-32 h-96 w-96 rounded-full bg-primary-400/20 blur-3xl" />
        <div className="absolute bottom-0 right-0 h-80 w-80 rounded-full bg-accent-400/20 blur-3xl" />

        <div className="relative z-10 flex w-full flex-col px-14 py-10">
          <Brand />
          <div className="mt-20">
            <span className="font-label inline-flex items-center gap-1.5 rounded-full border border-primary-200 bg-primary-50/70 px-3 py-1 text-xs font-medium text-primary-700">
              <i className="ri-lock-2-line"></i>
              仅限平台运营、财务人员使用
            </span>
            <h1 className="mt-6 max-w-xl font-heading text-4xl font-bold leading-snug tracking-wide text-foreground-950">
              平台运营
              <span className="text-gradient mx-1.5">一处掌控</span>
            </h1>
            <p className="mt-4 max-w-md text-[15px] leading-relaxed text-foreground-600">
              管理所有企业与个人账号、套餐与积分、订单与发票；企业业务数据默认不可见，需企业授权后方可查看。
            </p>
          </div>

          <div className="mt-8 grid grid-cols-2 gap-4">
            {HIGHLIGHTS.map((f) => (
              <div
                key={f.title}
                className="group flex items-start gap-3 rounded-xl border border-background-300/70 bg-background-100/70 p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary-300 hover:bg-background-100"
              >
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary-400 to-primary-600 text-background-50 transition-transform duration-200 group-hover:scale-105">
                  <i className={`${f.icon} text-lg`}></i>
                </span>
                <span>
                  <span className="font-label block text-sm font-semibold text-foreground-900">{f.title}</span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-foreground-500">{f.desc}</span>
                </span>
              </div>
            ))}
          </div>

          <p className="mt-auto border-t border-background-300/80 pt-6 pb-2 text-xs text-foreground-500">
            企业用户请从企业工作台登录，平台后台账号与企业账号互不通用。
          </p>
        </div>
      </div>

      <div className="flex w-full flex-col items-center justify-center bg-background-50 px-6 py-10 lg:w-[480px] lg:border-l lg:border-background-300">
        <div className="mb-8 lg:hidden">
          <Brand size="sm" />
        </div>

        <div className="w-full max-w-sm">
          <div className="mb-8">
            <h2 className="font-heading text-[26px] font-bold tracking-wide text-foreground-950">后台登录</h2>
            <p className="font-label mt-1.5 text-sm text-foreground-500">所有后台操作都会记入平台审计</p>
          </div>

          <form onSubmit={submit} className="space-y-5">
            {error && (
              <div className="flex items-center gap-2 rounded-lg border border-secondary-300 bg-secondary-50 px-3 py-2 text-xs text-secondary-800">
                <i className="ri-error-warning-line text-sm"></i>
                {error}
              </div>
            )}

            <div>
              <label className="font-label mb-1.5 block text-[13px] font-semibold text-foreground-800">后台账号</label>
              <div className="relative">
                <i className="ri-user-line absolute left-3 top-1/2 -translate-y-1/2 text-sm text-foreground-500"></i>
                <input className={fieldCls} autoComplete="username" placeholder="后台账号邮箱" value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
            </div>

            <div>
              <label className="font-label mb-1.5 block text-[13px] font-semibold text-foreground-800">密码</label>
              <div className="relative">
                <i className="ri-lock-password-line absolute left-3 top-1/2 -translate-y-1/2 text-sm text-foreground-500"></i>
                <input
                  className={`${fieldCls} pr-10`}
                  type={showPwd ? "text" : "password"}
                  autoComplete="current-password"
                  placeholder="请输入密码"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  type="button"
                  onClick={() => setShowPwd((v) => !v)}
                  className="absolute right-2 top-1/2 flex h-7 w-7 -translate-y-1/2 cursor-pointer items-center justify-center rounded-md text-foreground-500 hover:bg-background-200"
                  aria-label={showPwd ? "隐藏密码" : "显示密码"}
                >
                  <i className={showPwd ? "ri-eye-off-line" : "ri-eye-line"}></i>
                </button>
              </div>
            </div>

            {needTotp && (
              <div>
                <label className="font-label mb-1.5 block text-[13px] font-semibold text-foreground-800">动态验证码</label>
                <div className="relative">
                  <i className="ri-shield-keyhole-line absolute left-3 top-1/2 -translate-y-1/2 text-sm text-foreground-500"></i>
                  <input
                    className={fieldCls}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    autoFocus
                    placeholder="身份验证器 App 中的 6 位数字"
                    value={totp}
                    onChange={(e) => setTotp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  />
                </div>
              </div>
            )}

            <button
              type="submit"
              className="relative flex h-11 w-full cursor-pointer items-center justify-center overflow-hidden rounded-lg bg-gradient-to-r from-primary-500 to-primary-600 text-sm font-medium text-background-50 transition-all duration-200 hover:from-primary-600 hover:to-primary-700 disabled:opacity-70"
              disabled={busy || !email.trim() || !password}
            >
              {busy ? (
                <>
                  <span className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-background-50/40 border-t-background-50"></span>
                  正在安全登录…
                </>
              ) : (
                <>
                  登 录<i className="ri-arrow-right-line ml-1.5 text-base"></i>
                </>
              )}
            </button>
          </form>
        </div>

        <p className="font-label mt-auto pt-8 text-center text-xs text-foreground-500">© 2026 慧投标 · 平台管理后台</p>
      </div>
    </div>
  );
}
