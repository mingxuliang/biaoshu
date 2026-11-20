import { useCallback, useEffect, useState } from "react";
import QRCode from "qrcode";
import PageHeader from "@/pages/console/components/PageHeader";
import Modal from "@/pages/console/components/Modal";
import { ADMIN_ROLES, changeAdminPassword, createAdmin, listAdmins, patchAdmin, totpDisable, totpEnable, totpSetup, type AdminRole, type AdminUser } from "../api";
import { useAdminAuth } from "../auth";
import { btnGhost, btnPrimary, Card, dangerLink, inputCls, linkBtn, tdCls, theadCls, thCls, trCls, useUi } from "../ui";

const ROLE_DESC: Record<AdminRole, string> = {
  超级管理员: "全部权限，含后台账号、注销企业、补单与退款",
  运营: "企业开通与配置、认证审核、成员管理、模型接入、公告",
  财务: "积分调整、扣费规则与套餐、订单、对公转账、对账、发票",
  只读: "只能查看",
};

export function AdminsPage() {
  const { notify, fail, ask } = useUi();
  const { admin: me } = useAdminAuth();
  const [rows, setRows] = useState<AdminUser[]>([]);
  const [creating, setCreating] = useState<{ email: string; name: string; role: AdminRole } | null>(null);

  const load = useCallback(() => {
    listAdmins().then(setRows).catch(fail);
  }, [fail]);
  useEffect(load, [load]);

  const showPassword = (email: string, password: string) =>
    ask({ title: "初始密码", message: `账号：${email}\n密码：${password}\n\n仅显示这一次，请通过安全渠道交给本人，并要求其登录后开启二次验证。`, required: false, confirmText: "我已记录" });

  const create = async () => {
    if (!creating) return;
    try {
      const res = await createAdmin(creating);
      setCreating(null);
      load();
      await showPassword(res.email, res.initialPassword);
    } catch (e) {
      fail(e);
    }
  };

  const patch = async (a: AdminUser, p: Parameters<typeof patchAdmin>[1], done: string) => {
    try {
      const res = await patchAdmin(a.id, p);
      load();
      if (res.initialPassword) await showPassword(res.email, res.initialPassword);
      else notify(done);
    } catch (e) {
      fail(e);
    }
  };

  return (
    <div>
      <PageHeader
        title="后台账号"
        description="平台后台账号与企业账号完全独立。建议所有账号开启二次验证，生产环境配置 PLATFORM_ADMIN_IP_ALLOWLIST。"
        actions={
          <button type="button" className={btnPrimary} onClick={() => setCreating({ email: "", name: "", role: "运营" })}>
            <i className="ri-add-line"></i>新增账号
          </button>
        }
      />
      <Card>
        <table className="w-full">
          <thead className={theadCls}>
            <tr>
              <th className={thCls}>账号</th>
              <th className={thCls}>角色</th>
              <th className={thCls}>二次验证</th>
              <th className={thCls}>最近登录</th>
              <th className={thCls}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id} className={`${trCls} ${a.disabled ? "opacity-50" : ""}`}>
                <td className={tdCls}>
                  {a.name || "—"}
                  <div className="text-[11px] text-foreground-500">{a.email}</div>
                </td>
                <td className={tdCls}>
                  <select
                    className="rounded border border-background-300 bg-background-50 px-1 py-0.5 text-xs"
                    value={a.role}
                    disabled={a.id === me?.id}
                    onChange={(e) => patch(a, { role: e.target.value as AdminRole }, "角色已修改")}
                  >
                    {ADMIN_ROLES.map((r) => (
                      <option key={r}>{r}</option>
                    ))}
                  </select>
                </td>
                <td className={tdCls}>{a.totpEnabled ? <span className="text-emerald-600">已开启</span> : <span className="text-amber-600">未开启</span>}</td>
                <td className={`${tdCls} text-xs`}>{a.lastLoginAt || "从未登录"}</td>
                <td className={`${tdCls} space-x-2 whitespace-nowrap text-right`}>
                  <button type="button" className={linkBtn} onClick={() => patch(a, { resetPassword: true }, "")}>
                    重置密码
                  </button>
                  {a.totpEnabled && (
                    <button type="button" className={linkBtn} onClick={() => patch(a, { resetTotp: true }, "已清除二次验证")}>
                      清除二次验证
                    </button>
                  )}
                  {a.id !== me?.id && (
                    <button type="button" className={a.disabled ? linkBtn : dangerLink} onClick={() => patch(a, { disabled: !a.disabled }, a.disabled ? "已启用" : "已停用")}>
                      {a.disabled ? "启用" : "停用"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-4 grid gap-2 text-xs text-foreground-500 sm:grid-cols-2">
          {ADMIN_ROLES.map((r) => (
            <div key={r}>
              <b className="text-foreground-700">{r}</b>：{ROLE_DESC[r]}
            </div>
          ))}
        </div>
      </Card>

      {creating && (
        <Modal open onClose={() => setCreating(null)} title="新增后台账号">
          <div className="space-y-3">
            <input className={inputCls} placeholder="邮箱（登录账号）" value={creating.email} onChange={(e) => setCreating({ ...creating, email: e.target.value })} />
            <input className={inputCls} placeholder="姓名" value={creating.name} onChange={(e) => setCreating({ ...creating, name: e.target.value })} />
            <select className={inputCls} value={creating.role} onChange={(e) => setCreating({ ...creating, role: e.target.value as AdminRole })}>
              {ADMIN_ROLES.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
            <p className="text-xs text-foreground-500">{ROLE_DESC[creating.role]}</p>
            <div className="flex justify-end gap-2">
              <button type="button" className={btnGhost} onClick={() => setCreating(null)}>
                取消
              </button>
              <button type="button" className={btnPrimary} disabled={!creating.email.includes("@")} onClick={create}>
                创建
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

export function AccountPage() {
  const { notify, fail, ask } = useUi();
  const { admin, setToken, refresh } = useAdminAuth();
  const [pwd, setPwd] = useState({ old: "", next: "", confirm: "" });
  const [setup, setSetup] = useState<{ secret: string; qr: string; code: string } | null>(null);

  const savePassword = async () => {
    if (pwd.next !== pwd.confirm) return fail(new Error("两次输入的新密码不一致"));
    try {
      const res = await changeAdminPassword(pwd.old, pwd.next);
      setToken(res.token);
      setPwd({ old: "", next: "", confirm: "" });
      notify("密码已修改，其他设备上的登录已失效");
    } catch (e) {
      fail(e);
    }
  };

  const startTotp = async () => {
    try {
      const res = await totpSetup();
      setSetup({ secret: res.secret, qr: await QRCode.toDataURL(res.uri, { width: 200, margin: 1 }), code: "" });
    } catch (e) {
      fail(e);
    }
  };

  const enableTotp = async () => {
    if (!setup) return;
    try {
      await totpEnable(setup.secret, setup.code);
      setSetup(null);
      await refresh();
      notify("二次验证已开启，下次登录需输入动态验证码");
    } catch (e) {
      fail(e);
    }
  };

  const disableTotp = async () => {
    const code = await ask({ title: "关闭二次验证", placeholder: "输入当前动态验证码", danger: true });
    if (!code) return;
    try {
      await totpDisable(code);
      await refresh();
      notify("已关闭二次验证");
    } catch (e) {
      fail(e);
    }
  };

  return (
    <div>
      <PageHeader title="账号安全" description={`${admin?.email} · ${admin?.role}`} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="修改密码">
          <div className="space-y-3">
            <input className={inputCls} type="password" placeholder="当前密码" autoComplete="current-password" value={pwd.old} onChange={(e) => setPwd({ ...pwd, old: e.target.value })} />
            <input className={inputCls} type="password" placeholder="新密码（至少 10 位，含字母和数字）" autoComplete="new-password" value={pwd.next} onChange={(e) => setPwd({ ...pwd, next: e.target.value })} />
            <input className={inputCls} type="password" placeholder="再次输入新密码" autoComplete="new-password" value={pwd.confirm} onChange={(e) => setPwd({ ...pwd, confirm: e.target.value })} />
            <button type="button" className={btnPrimary} disabled={!pwd.old || pwd.next.length < 10} onClick={savePassword}>
              修改密码
            </button>
          </div>
        </Card>
        <Card title="二次验证（TOTP）">
          {admin?.totpEnabled ? (
            <div className="space-y-3 text-sm">
              <p className="text-emerald-700">
                <i className="ri-shield-check-line mr-1"></i>已开启。登录时需输入身份验证器 App 中的 6 位动态码。
              </p>
              <button type="button" className={btnGhost} onClick={disableTotp}>
                关闭二次验证
              </button>
            </div>
          ) : setup ? (
            <div className="space-y-3 text-sm">
              <p className="text-foreground-600">用 Google Authenticator、Microsoft Authenticator 或腾讯身份验证器扫码，然后输入 App 中显示的 6 位数字。</p>
              <img src={setup.qr} alt="TOTP 二维码" className="h-48 w-48 rounded-lg border border-background-300" />
              <p className="font-mono text-xs text-foreground-500">无法扫码时手动输入：{setup.secret}</p>
              <div className="flex gap-2">
                <input className={inputCls} inputMode="numeric" placeholder="6 位动态码" value={setup.code} onChange={(e) => setSetup({ ...setup, code: e.target.value.replace(/\D/g, "").slice(0, 6) })} />
                <button type="button" className={btnPrimary} disabled={setup.code.length !== 6} onClick={enableTotp}>
                  开启
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-3 text-sm">
              <p className="text-amber-700">尚未开启。后台账号可以调整积分、退款和查看企业资料，强烈建议开启。</p>
              <button type="button" className={btnPrimary} onClick={startTotp}>
                开始设置
              </button>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
