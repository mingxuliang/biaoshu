import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { ADMIN_TOKEN_KEY, ADMIN_UNAUTHORIZED, adminLogin, adminMe, type AdminRole, type AdminUser } from "./api";

interface AdminAuthValue {
  admin: AdminUser | null;
  loading: boolean;
  login: (email: string, password: string, totp: string) => Promise<void>;
  logout: () => void;
  setToken: (token: string) => void;
  refresh: () => Promise<void>;
}

const AdminAuthContext = createContext<AdminAuthValue | null>(null);

export function AdminAuthProvider({ children }: { children: ReactNode }) {
  const [admin, setAdmin] = useState<AdminUser | null>(null);
  const [loading, setLoading] = useState(() => !!localStorage.getItem(ADMIN_TOKEN_KEY));

  const logout = useCallback(() => {
    localStorage.removeItem(ADMIN_TOKEN_KEY);
    setAdmin(null);
  }, []);

  const refresh = useCallback(async () => {
    if (!localStorage.getItem(ADMIN_TOKEN_KEY)) return;
    try {
      setAdmin(await adminMe());
    } catch {
      logout();
    }
  }, [logout]);

  useEffect(() => {
    refresh().finally(() => setLoading(false));
  }, [refresh]);

  useEffect(() => {
    window.addEventListener(ADMIN_UNAUTHORIZED, logout);
    return () => window.removeEventListener(ADMIN_UNAUTHORIZED, logout);
  }, [logout]);

  const login = useCallback(async (email: string, password: string, totp: string) => {
    const result = await adminLogin(email, password, totp);
    localStorage.setItem(ADMIN_TOKEN_KEY, result.token);
    setAdmin(result.admin);
  }, []);

  const setToken = useCallback((token: string) => localStorage.setItem(ADMIN_TOKEN_KEY, token), []);

  return <AdminAuthContext.Provider value={{ admin, loading, login, logout, setToken, refresh }}>{children}</AdminAuthContext.Provider>;
}

export function useAdminAuth() {
  const ctx = useContext(AdminAuthContext);
  if (!ctx) throw new Error("useAdminAuth 必须在 AdminAuthProvider 内使用");
  return ctx;
}

/** 与后端 require_roles 一致：超级管理员拥有全部权限。 */
export function useCan() {
  const { admin } = useAdminAuth();
  const role: AdminRole | undefined = admin?.role;
  return {
    isSuper: role === "超级管理员",
    ops: role === "超级管理员" || role === "运营",
    finance: role === "超级管理员" || role === "财务",
  };
}
