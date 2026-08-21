import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import {
  apiGetMe,
  apiLogin,
  apiRegister,
  apiUpdateProfile,
  type AuthUser,
} from "@/lib/api";

export type UserProfile = AuthUser;

const TOKEN_KEY = "zhbiao_token";

interface AuthContextValue {
  user: UserProfile | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<UserProfile>;
  register: (input: { name: string; email: string; password: string }) => Promise<UserProfile>;
  logout: () => void;
  updateUser: (patch: Partial<UserProfile> & { password?: string }) => Promise<UserProfile>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState<boolean>(() => !!localStorage.getItem(TOKEN_KEY));

  useEffect(() => {
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    apiGetMe(token)
      .then((me) => {
        if (!cancelled) setUser(me);
      })
      .catch(() => {
        if (!cancelled) {
          setUser(null);
          setToken(null);
          localStorage.removeItem(TOKEN_KEY);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const login = useCallback(async (email: string, password: string): Promise<UserProfile> => {
    const result = await apiLogin(email, password);
    localStorage.setItem(TOKEN_KEY, result.token);
    setToken(result.token);
    setUser(result.user);
    return result.user;
  }, []);

  const register = useCallback(
    async (input: { name: string; email: string; password: string }): Promise<UserProfile> => {
      const result = await apiRegister(input);
      localStorage.setItem(TOKEN_KEY, result.token);
      setToken(result.token);
      setUser(result.user);
      return result.user;
    },
    [],
  );

  const logout = useCallback(() => {
    setUser(null);
    setToken(null);
    localStorage.removeItem(TOKEN_KEY);
  }, []);

  const updateUser = useCallback(
    async (patch: Partial<UserProfile> & { password?: string }): Promise<UserProfile> => {
      if (!token) throw new Error("未登录，无法更新个人信息");
      const next = await apiUpdateProfile(token, patch);
      setUser(next);
      return next;
    },
    [token],
  );

  return (
    <AuthContext.Provider value={{ user, token, loading, login, register, logout, updateUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return ctx;
}
