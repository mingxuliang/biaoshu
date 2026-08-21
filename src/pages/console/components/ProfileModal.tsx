import { useEffect, useState } from "react";
import Modal from "./Modal";
import Toast from "./Toast";
import { useAuth } from "@/context/AuthContext";

interface ProfileModalProps {
  open: boolean;
  onClose: () => void;
}

export default function ProfileModal({ open, onClose }: ProfileModalProps) {
  const { user, updateUser } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [company, setCompany] = useState("");
  const [position, setPosition] = useState("");
  const [password, setPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [toast, setToast] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (open && user) {
      setName(user.name);
      setEmail(user.email);
      setPhone(user.phone);
      setCompany(user.company);
      setPosition(user.position);
      setPassword("");
      setError("");
    }
  }, [open, user]);

  const handleSave = async () => {
    if (!name.trim() || !email.trim()) return;
    setSaving(true);
    setError("");
    try {
      await updateUser({
        name: name.trim(),
        email: email.trim(),
        phone: phone.trim(),
        company: company.trim(),
        position: position.trim(),
        ...(password.trim() ? { password: password.trim() } : {}),
      });
      setToast(true);
      setTimeout(() => {
        setToast(false);
        onClose();
      }, 900);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败，请稍后重试");
    } finally {
      setSaving(false);
    }
  };

  const inputCls =
    "h-10 w-full rounded-lg border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 placeholder:text-foreground-500 outline-none transition-all focus:border-primary-400 focus:ring-2 focus:ring-primary-400/20";

  return (
    <>
      <Modal
        open={open}
        title="个人信息"
        subtitle="维护你的账号资料与安全设置，保存后立即生效"
        onClose={onClose}
      >
        <div className="space-y-4">
          {/* 头像预览 */}
          <div className="flex items-center gap-4">
            <span className="flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-primary-400 to-primary-600 text-lg font-semibold text-background-50 ring-2 ring-background-100">
              {name.trim() ? name.trim().charAt(0) : "用"}
            </span>
            <div className="leading-tight">
              <div className="text-sm font-semibold text-foreground-900">{name || "未命名"}</div>
              <div className="mt-0.5 flex items-center gap-1.5 text-xs text-foreground-500">
                <i className="ri-vip-crown-2-line text-primary-500"></i>
                {user?.role || "管理员"}
              </div>
            </div>
          </div>

          <div className="h-px bg-background-300" />

          {error && (
            <div className="flex items-center gap-2 rounded-lg border border-secondary-300 bg-secondary-50 px-3 py-2 text-xs text-secondary-800">
              <i className="ri-error-warning-line text-sm"></i>
              {error}
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="font-label mb-1.5 block text-[13px] font-medium text-foreground-800">
                姓名
              </label>
              <input type="text" name="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="请输入姓名" className={inputCls} />
            </div>
            <div>
              <label className="font-label mb-1.5 block text-[13px] font-medium text-foreground-800">
                邮箱
              </label>
              <input type="email" name="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" className={inputCls} />
            </div>
            <div>
              <label className="font-label mb-1.5 block text-[13px] font-medium text-foreground-800">
                手机号
              </label>
              <input type="tel" name="phone" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="请输入手机号" className={inputCls} />
            </div>
            <div>
              <label className="font-label mb-1.5 block text-[13px] font-medium text-foreground-800">
                所在公司
              </label>
              <input type="text" name="company" value={company} onChange={(e) => setCompany(e.target.value)} placeholder="请输入公司名称" className={inputCls} />
            </div>
            <div>
              <label className="font-label mb-1.5 block text-[13px] font-medium text-foreground-800">
                职位
              </label>
              <input type="text" name="position" value={position} onChange={(e) => setPosition(e.target.value)} placeholder="请输入职位" className={inputCls} />
            </div>
            <div>
              <label className="font-label mb-1.5 block text-[13px] font-medium text-foreground-800">
                登录密码
              </label>
              <div className="relative">
                <input
                  type={showPwd ? "text" : "password"}
                  name="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="留空则不修改密码"
                  className={`${inputCls} pr-9`}
                />
                <button
                  type="button"
                  onClick={() => setShowPwd((v) => !v)}
                  className="absolute right-2.5 top-1/2 flex h-6 w-6 -translate-y-1/2 cursor-pointer items-center justify-center text-foreground-500 transition-colors hover:text-foreground-800"
                  aria-label={showPwd ? "隐藏密码" : "显示密码"}
                >
                  <i className={`${showPwd ? "ri-eye-off-line" : "ri-eye-line"} text-base`}></i>
                </button>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="cursor-pointer rounded-lg border border-background-300 bg-background-100 px-4 py-2 text-sm whitespace-nowrap text-foreground-700 transition-colors hover:bg-background-200"
            >
              取消
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="cursor-pointer rounded-lg bg-primary-500 px-5 py-2 text-sm whitespace-nowrap font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:opacity-70"
            >
              {saving ? "保存中…" : "保存修改"}
            </button>
          </div>
        </div>
      </Modal>
      <Toast message="个人信息已保存" visible={toast} />
    </>
  );
}