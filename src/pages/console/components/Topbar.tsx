import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import ProfileModal from "./ProfileModal";

interface TopbarProps {
  title: string;
  onMenuOpen: () => void;
}

export default function Topbar({ title, onMenuOpen }: TopbarProps) {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleLogout = () => {
    setMenuOpen(false);
    logout();
    navigate("/login");
  };

  const avatarText = (user?.name || "用").trim().charAt(0) || "用";

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-background-300 bg-background-100 px-5">
      <button
        type="button"
        onClick={onMenuOpen}
        className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-colors hover:bg-background-200 lg:hidden"
        aria-label="打开菜单"
      >
        <i className="ri-menu-line text-lg"></i>
      </button>

      <div className="flex items-center gap-1.5 text-sm">
        <span className="font-heading text-foreground-500">智标云</span>
        <i className="ri-arrow-right-s-line text-foreground-400 text-xs"></i>
        <span className="font-label font-medium text-foreground-900">{title}</span>
      </div>

      <div className="ml-auto flex items-center gap-2">
        {/* Search */}
        <div className="relative hidden md:block">
          <i className="ri-search-line absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-foreground-500"></i>
          <input
            type="text"
            placeholder="搜索项目 / 文档 / 成员…"
            className="h-8 w-56 rounded-lg border border-background-300 bg-background-50 pl-8 pr-3 text-sm text-foreground-900 placeholder:text-foreground-500 outline-none transition-all focus:border-primary-400 focus:ring-2 focus:ring-primary-400/20"
          />
        </div>

        <button
          type="button"
          className="relative flex h-8 w-8 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-colors hover:bg-background-200"
          aria-label="通知"
        >
          <i className="ri-notification-3-line text-lg"></i>
          <span className="absolute right-1.5 top-1.5 flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full rounded-full bg-primary-400 opacity-60 animate-ping" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary-500" />
          </span>
        </button>
        <button
          type="button"
          className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-colors hover:bg-background-200"
          aria-label="帮助"
        >
          <i className="ri-question-line text-lg"></i>
        </button>

        <div className="mx-1 hidden h-5 w-px bg-background-300 sm:block" />

        {/* 用户菜单 */}
        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            className="flex cursor-pointer items-center gap-2 rounded-lg px-1.5 py-1 transition-colors hover:bg-background-200"
            aria-label="用户菜单"
          >
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-primary-400 to-primary-600 text-xs font-medium text-background-50 ring-2 ring-background-100">
              {avatarText}
            </span>
            <span className="hidden leading-tight text-left md:block">
              <span className="block text-[13px] font-medium text-foreground-900">
                {user?.name || "未登录"}
              </span>
              <span className="block text-[11px] text-foreground-500">{user?.position || "成员"}</span>
            </span>
            <i
              className={`ri-arrow-down-s-line hidden text-sm text-foreground-500 transition-transform duration-200 md:block ${
                menuOpen ? "rotate-180" : ""
              }`}
            ></i>
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-[calc(100%+8px)] w-60 animate-pop-in rounded-xl border border-background-300 bg-background-100 shadow-lg">
              <div className="border-b border-background-300 px-4 py-3">
                <div className="text-sm font-semibold text-foreground-900">{user?.name || "未登录"}</div>
                <div className="mt-0.5 truncate text-xs text-foreground-500">{user?.email || "—"}</div>
              </div>
              <div className="p-1.5">
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    setProfileOpen(true);
                  }}
                  className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-foreground-800 transition-colors hover:bg-background-200"
                >
                  <i className="ri-user-settings-line text-base text-foreground-500"></i>
                  个人信息
                </button>
                <button
                  type="button"
                  onClick={() => setMenuOpen(false)}
                  className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-foreground-800 transition-colors hover:bg-background-200"
                >
                  <i className="ri-lock-password-line text-base text-foreground-500"></i>
                  账号与安全
                </button>
              </div>
              <div className="h-px bg-background-300" />
              <div className="p-1.5">
                <button
                  type="button"
                  onClick={handleLogout}
                  className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-red-600 transition-colors hover:bg-red-50"
                >
                  <i className="ri-logout-box-r-line text-base"></i>
                  退出登录
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      <ProfileModal open={profileOpen} onClose={() => setProfileOpen(false)} />
    </header>
  );
}