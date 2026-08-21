import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { ApiError } from "@/lib/api";

const featureHighlights = [
  {
    icon: "ri-edit-2-line",
    title: "AI 定向撰写",
    desc: "按评分点 + 项目特征定向生成，杜绝空话",
  },
  {
    icon: "ri-shield-check-line",
    title: "五维智能预审",
    desc: "否决项 / 商务 / 技术 / 虚词 / 版式全量扫描",
  },
  {
    icon: "ri-lock-2-line",
    title: "防串稿去标识",
    desc: "自动替换他项项目名、地名、招标人",
  },
  {
    icon: "ri-file-download-line",
    title: "一键 Word 导出",
    desc: "分册导出、暗标剥离、附件包一键打包",
  },
];

export default function LoginPage() {
  const navigate = useNavigate();
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [remember, setRemember] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading) return;
    setError("");
    if (mode === "register" && !name.trim()) {
      setError("请填写姓名");
      return;
    }
    if (!email.trim() || !password) {
      setError("请填写邮箱和密码");
      return;
    }
    setLoading(true);
    try {
      if (mode === "register") {
        await register({ name: name.trim(), email: email.trim(), password });
      } else {
        await login(email.trim(), password);
      }
      navigate("/console/projects");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "登录失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen w-full bg-background-50">
      {/* ===== 左侧品牌科技区 ===== */}
      <div className="relative hidden flex-1 overflow-hidden lg:flex">
        {/* 科技网格底纹 */}
        <div className="absolute inset-0 bg-grid" />
        {/* 顶部光晕 */}
        <div className="absolute -top-32 -left-32 h-96 w-96 rounded-full bg-primary-400/20 blur-3xl" />
        <div className="absolute bottom-0 right-0 h-80 w-80 rounded-full bg-accent-400/20 blur-3xl" />

        <div className="relative z-10 flex w-full flex-col px-14 py-10">
          {/* Brand */}
          <div className="flex items-center gap-3">
            <div className="relative flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
              <i className="ri-sparkling-2-line text-xl"></i>
              <span className="absolute inset-0 rounded-xl ring-2 ring-primary-400/30" />
            </div>
            <div>
              <div className="font-heading text-xl font-bold tracking-widest text-foreground-950">
                智标云
              </div>
              <div className="font-label text-[11px] text-foreground-500">
                AI 智能标书系统
              </div>
            </div>
          </div>

          {/* Hero copy */}
          <div className="mt-20">
            <span className="font-label inline-flex items-center gap-1.5 rounded-full border border-primary-200 bg-primary-50/70 px-3 py-1 text-xs font-medium text-primary-700">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full rounded-full bg-primary-400 opacity-70 animate-ping" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary-500" />
              </span>
              已服务 260+ 家建筑企业 · 累计投标 4,800 次
            </span>

            <h1 className="mt-6 max-w-xl font-heading text-4xl font-bold leading-snug tracking-wide text-foreground-950">
              智能标书
              <span className="text-gradient mx-1.5">一站制胜</span>
              投标更从容
            </h1>
            <p className="mt-4 max-w-md text-[15px] leading-relaxed text-foreground-600">
              贯通招标解析、定向撰写、五维预审与 Word 交付全流程，
              让每一份标书都精准命中评分点。
            </p>
          </div>

          {/* Feature highlights */}
          <div className="mt-8 grid grid-cols-2 gap-4">
            {featureHighlights.map((f, i) => (
              <div
                key={f.title}
                className="group flex items-start gap-3 rounded-xl border border-background-300/70 bg-background-100/70 p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary-300 hover:bg-background-100"
              >
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary-400 to-primary-600 text-background-50 transition-transform duration-200 group-hover:scale-105">
                  <i className={`${f.icon} text-lg`}></i>
                </span>
                <span>
                  <span className="font-label block text-sm font-semibold text-foreground-900">
                    {f.title}
                  </span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-foreground-500">
                    {f.desc}
                  </span>
                </span>
              </div>
            ))}
          </div>

          {/* 底部数据带 */}
          <div className="mt-auto flex items-center gap-8 border-t border-background-300/80 pt-6 pb-2">
            {[
              { value: "98.6%", label: "中标率提升" },
              { value: "60%", label: "撰写耗时降低" },
              { value: "24h", label: "报告响应速度" },
            ].map((s) => (
              <div key={s.label}>
                <div className="font-heading text-2xl font-bold text-gradient tracking-wide">
                  {s.value}
                </div>
                <div className="font-label mt-0.5 text-xs text-foreground-500">
                  {s.label}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ===== 右侧登录卡片区 ===== */}
      <div className="flex w-full flex-col items-center justify-center bg-background-50 px-6 py-10 lg:w-[480px] lg:border-l lg:border-background-300">
        {/* 移动端品牌 */}
        <div className="mb-8 flex items-center gap-3 lg:hidden">
          <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
            <i className="ri-sparkling-2-line text-lg"></i>
            <span className="absolute inset-0 rounded-xl ring-2 ring-primary-400/30" />
          </div>
          <div>
            <div className="font-heading text-lg font-bold tracking-widest text-foreground-950">
              智标云
            </div>
            <div className="font-label text-[11px] text-foreground-500">
              AI 智能标书系统
            </div>
          </div>
        </div>

        <div className="w-full max-w-sm">
          <div className="mb-8">
            <h2 className="font-heading text-[26px] font-bold tracking-wide text-foreground-950">
              {mode === "login" ? "欢迎回来" : "创建你的账号"}
            </h2>
            <p className="font-label mt-1.5 text-sm text-foreground-500">
              {mode === "login" ? "登录你的智标云工作台，继续高效的投标之旅" : "注册新账号，开启智能标书之旅"}
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5" data-readdy-form="login-form">
            {/* 反垃圾辅助字段 */}
            <input
              type="text"
              name="website_alt"
              tabIndex={-1}
              autoComplete="off"
              aria-hidden="true"
              readOnly
            />

            {error && (
              <div className="flex items-center gap-2 rounded-lg border border-secondary-300 bg-secondary-50 px-3 py-2 text-xs text-secondary-800">
                <i className="ri-error-warning-line text-sm"></i>
                {error}
              </div>
            )}

            {mode === "register" && (
              <div>
                <label className="font-label mb-1.5 block text-[13px] font-semibold text-foreground-800">
                  姓名
                </label>
                <div className="relative">
                  <i className="ri-user-line absolute left-3 top-1/2 -translate-y-1/2 text-sm text-foreground-500"></i>
                  <input
                    type="text"
                    name="name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="请输入姓名"
                    className="h-11 w-full rounded-lg border border-background-300 bg-background-100 pl-9 pr-3 text-sm text-foreground-900 placeholder:text-foreground-500 outline-none transition-all focus:border-primary-400 focus:ring-2 focus:ring-primary-400/20"
                  />
                </div>
              </div>
            )}

            {/* 邮箱 */}
            <div>
              <label className="font-label mb-1.5 block text-[13px] font-semibold text-foreground-800">
                邮箱账号
              </label>
              <div className="relative">
                <i className="ri-mail-line absolute left-3 top-1/2 -translate-y-1/2 text-sm text-foreground-500"></i>
                <input
                  type="email"
                  name="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@company.com"
                  className="h-11 w-full rounded-lg border border-background-300 bg-background-100 pl-9 pr-3 text-sm text-foreground-900 placeholder:text-foreground-500 outline-none transition-all focus:border-primary-400 focus:ring-2 focus:ring-primary-400/20"
                />
              </div>
            </div>

            {/* 密码 */}
            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <label className="font-label text-[13px] font-semibold text-foreground-800">
                  {mode === "login" ? "登录密码" : "设置密码"}
                </label>
                {mode === "login" && (
                  <button
                    type="button"
                    className="font-label cursor-pointer text-xs text-primary-600 transition-colors hover:text-primary-700"
                  >
                    忘记密码？
                  </button>
                )}
              </div>
              <div className="relative">
                <i className="ri-lock-2-line absolute left-3 top-1/2 -translate-y-1/2 text-sm text-foreground-500"></i>
                <input
                  type={showPwd ? "text" : "password"}
                  name="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={mode === "login" ? "请输入登录密码" : "至少 6 位密码"}
                  className="h-11 w-full rounded-lg border border-background-300 bg-background-100 pl-9 pr-11 text-sm text-foreground-900 placeholder:text-foreground-500 outline-none transition-all focus:border-primary-400 focus:ring-2 focus:ring-primary-400/20"
                />
                <button
                  type="button"
                  onClick={() => setShowPwd((v) => !v)}
                  className="absolute right-3 top-1/2 flex h-6 w-6 -translate-y-1/2 cursor-pointer items-center justify-center text-foreground-500 transition-colors hover:text-foreground-800"
                  aria-label={showPwd ? "隐藏密码" : "显示密码"}
                >
                  <i className={`${showPwd ? "ri-eye-off-line" : "ri-eye-line"} text-base`}></i>
                </button>
              </div>
            </div>

            {/* 记住我 + 安全提示 */}
            <div className="flex items-center justify-between">
              <label className="flex cursor-pointer items-center gap-2 text-[13px] text-foreground-700">
                <span className="relative inline-flex">
                  <input
                    type="checkbox"
                    checked={remember}
                    onChange={(e) => setRemember(e.target.checked)}
                    className="peer h-4 w-4 cursor-pointer appearance-none rounded border border-background-400 bg-background-100 transition-colors checked:border-primary-500 checked:bg-primary-500"
                  />
                  <i className="ri-check-line absolute left-0 top-0 h-4 w-4 text-[11px] leading-4 text-background-50 opacity-0 transition-opacity peer-checked:opacity-100"></i>
                </span>
                记住我
              </label>
              <span className="font-label flex items-center gap-1 text-[11px] text-foreground-500">
                <i className="ri-shield-keyhole-line text-xs text-primary-500"></i>
                SSL 加密传输
              </span>
            </div>

            {/* 登录/注册按钮 */}
            <button
              type="submit"
              className="relative flex h-11 w-full cursor-pointer items-center justify-center overflow-hidden rounded-lg bg-gradient-to-r from-primary-500 to-primary-600 text-sm font-medium text-background-50 transition-all duration-200 hover:from-primary-600 hover:to-primary-700 disabled:opacity-70"
              disabled={loading}
            >
              {loading ? (
                <>
                  <span className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-background-50/40 border-t-background-50"></span>
                  {mode === "login" ? "正在安全登录…" : "正在创建账号…"}
                </>
              ) : (
                <>
                  {mode === "login" ? "登 录" : "注 册"}
                  <i className="ri-arrow-right-line ml-1.5 text-base transition-transform duration-200 group-hover:translate-x-0.5"></i>
                </>
              )}
            </button>
          </form>

          {/* 分隔线 */}
          <div className="my-6 flex items-center gap-3">
            <span className="h-px flex-1 bg-background-300" />
            <span className="font-label text-xs text-foreground-500">或</span>
            <span className="h-px flex-1 bg-background-300" />
          </div>

          {/* 快捷登录 */}
          <div className="grid grid-cols-3 gap-3">
            <button
              type="button"
              className="font-label flex h-11 cursor-pointer items-center justify-center gap-2 rounded-lg border border-background-300 bg-background-100 text-sm text-foreground-800 transition-all hover:border-primary-300 hover:bg-background-50 hover:text-primary-700"
            >
              <i className="ri-wechat-line text-lg text-primary-500"></i>
              微信
            </button>
            <button
              type="button"
              className="font-label flex h-11 cursor-pointer items-center justify-center gap-2 rounded-lg border border-background-300 bg-background-100 text-sm text-foreground-800 transition-all hover:border-primary-300 hover:bg-background-50 hover:text-primary-700"
            >
              <i className="ri-qr-code-line text-lg text-primary-500"></i>
              扫码
            </button>
            <button
              type="button"
              className="font-label flex h-11 cursor-pointer items-center justify-center gap-2 rounded-lg border border-background-300 bg-background-100 text-sm text-foreground-800 transition-all hover:border-primary-300 hover:bg-background-50 hover:text-primary-700"
            >
              <i className="ri-mail-lock-line text-lg text-primary-500"></i>
              手机号
            </button>
          </div>

          {/* 注册引导 */}
          <p className="font-label mt-8 text-center text-[13px] text-foreground-500">
            {mode === "login" ? "还没有账号？" : "已有账号？"}
            <button
              type="button"
              onClick={() => {
                setError("");
                setMode((m) => (m === "login" ? "register" : "login"));
              }}
              className="font-semibold text-primary-600 transition-colors hover:text-primary-700"
            >
              {mode === "login" ? "立即注册" : "直接登录"}
            </button>
          </p>
        </div>

        {/* 底部版权 */}
        <p className="font-label mt-auto pt-8 text-center text-xs text-foreground-500">
          © 2026 智标云 · 让每一次投标更从容
        </p>
      </div>
    </div>
  );
}