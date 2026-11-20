import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import {
  apiGetMe,
  apiLogin,
  apiRegister,
  apiTenantSignup,
  apiUpdateProfile,
  TOKEN_EVENT,
  UNAUTHORIZED_EVENT,
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
  signupTenant: (input: Parameters<typeof apiTenantSignup>[0]) => Promise<UserProfile>;
  logout: () => void;
  /** 重新拉取当前用户（例如个人升级为企业后） */
  refreshUser: () => Promise<UserProfile | null>;
  updateUser: (patch: Partial<UserProfile> & { password?: string; currentPassword?: string }) => Promise<UserProfile>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState<boolean>(() => !!localStorage.getItem(TOKEN_KEY));
  const seenUser = useRef(false);

  useEffect(() => {
    const onToken = (event: Event) => {
      const next = (event as CustomEvent<string>).detail;
      if (next) setToken(next);
    };
    const onUnauthorized = () => {
      seenUser.current = false;
      setUser(null);
      setToken(null);
      localStorage.removeItem(TOKEN_KEY);
    };
    window.addEventListener(TOKEN_EVENT, onToken);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => {
      window.removeEventListener(TOKEN_EVENT, onToken);
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    };
  }, []);

  useEffect(() => {
    if (!token) {
      seenUser.current = false;
      setUser(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    if (!seenUser.current) setLoading(true);
    apiGetMe(token)
      .then((me) => {
        if (!cancelled) {
          seenUser.current = true;
          setUser(me);
        }
      })
      .catch(() => {
        if (!cancelled) {
          seenUser.current = false;
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

  const signupTenant = useCallback(async (input: Parameters<typeof apiTenantSignup>[0]): Promise<UserProfile> => {
    const result = await apiTenantSignup(input);
    localStorage.setItem(TOKEN_KEY, result.token);
    setToken(result.token);
    setUser(result.user);
    return result.user;
  }, []);

  const logout = useCallback(() => {
    setUser(null);
    setToken(null);
    localStorage.removeItem(TOKEN_KEY);
  }, []);

  const refreshUser = useCallback(async (): Promise<UserProfile | null> => {
    if (!token) return null;
    const me = await apiGetMe(token);
    setUser(me);
    return me;
  }, [token]);

  const updateUser = useCallback(
    async (patch: Partial<UserProfile> & { password?: string; currentPassword?: string }): Promise<UserProfile> => {
      if (!token) throw new Error("未登录，无法更新个人信息");
      const next = await apiUpdateProfile(token, patch);
      if (next.token) {
        localStorage.setItem(TOKEN_KEY, next.token);
        setToken(next.token);
      }
      setUser(next);
      return next;
    },
    [token],
  );

  return (
    <AuthContext.Provider value={{ user, token, loading, login, register, signupTenant, logout, refreshUser, updateUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return ctx;
}
