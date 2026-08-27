import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { globalSearch, type SearchResult } from "@/lib/api";
import ProfileModal from "./ProfileModal";

interface TopbarProps {
  title: string;
  onMenuOpen: () => void;
}

const emptySearch: SearchResult = { projects: [], members: [], documents: [] };

export default function Topbar({ title, onMenuOpen }: TopbarProps) {
  const navigate = useNavigate();
  const { user, token, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [noticeOpen, setNoticeOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<SearchResult>(emptySearch);
  const menuRef = useRef<HTMLDivElement>(null);
  const noticeRef = useRef<HTMLDivElement>(null);
  const helpRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (menuRef.current && !menuRef.current.contains(target)) setMenuOpen(false);
      if (noticeRef.current && !noticeRef.current.contains(target)) setNoticeOpen(false);
      if (helpRef.current && !helpRef.current.contains(target)) setHelpOpen(false);
      if (searchRef.current && !searchRef.current.contains(target)) setSearchOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    const q = query.trim();
    if (!token || !q) {
      setResults(emptySearch);
      setSearching(false);
      return;
    }
    setSearching(true);
    const handle = window.setTimeout(() => {
      globalSearch(token, q)
        .then((data) => setResults(data))
        .catch(() => setResults(emptySearch))
        .finally(() => setSearching(false));
    }, 280);
    return () => window.clearTimeout(handle);
  }, [query, token]);

  const handleLogout = () => {
    setMenuOpen(false);
    logout();
    navigate("/login");
  };

  const avatarText = (user?.name || "用").trim().charAt(0) || "用";
  const hasHits =
    results.projects.length + results.members.length + results.documents.length > 0;

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
        <div className="relative hidden md:block" ref={searchRef}>
          <i className="ri-search-line absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-foreground-500"></i>
          <input
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSearchOpen(true);
            }}
            onFocus={() => setSearchOpen(true)}
            placeholder="搜索项目 / 文档 / 成员…"
            className="h-8 w-56 rounded-lg border border-background-300 bg-background-50 pl-8 pr-3 text-sm text-foreground-900 placeholder:text-foreground-500 outline-none transition-all focus:border-primary-400 focus:ring-2 focus:ring-primary-400/20"
          />
          {searchOpen && query.trim() && (
            <div className="absolute right-0 top-[calc(100%+8px)] z-40 w-80 overflow-hidden rounded-xl border border-background-300 bg-background-100 shadow-lg">
              {searching && !hasHits ? (
                <p className="px-4 py-6 text-center text-xs text-foreground-500">搜索中…</p>
              ) : !hasHits ? (
                <p className="px-4 py-6 text-center text-xs text-foreground-500">没有匹配的项目、文档或成员</p>
              ) : (
                <div className="max-h-80 overflow-y-auto py-1.5">
                  {results.projects.length > 0 && (
                    <div>
                      <div className="px-3 py-1.5 font-label text-[10px] text-foreground-500">项目</div>
                      {results.projects.map((p) => (
                        <button
                          key={p.id}
                          type="button"
                          onClick={() => {
                            setSearchOpen(false);
                            setQuery("");
                            navigate(`/console/projects/${p.id}`);
                          }}
                          className="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left hover:bg-background-200"
                        >
                          <i className="ri-folder-2-line text-sm text-foreground-500"></i>
                          <span className="min-w-0">
                            <span className="block truncate text-sm text-foreground-900">{p.name}</span>
                            <span className="block text-[11px] text-foreground-500">{p.code}</span>
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                  {results.documents.length > 0 && (
                    <div>
                      <div className="px-3 py-1.5 font-label text-[10px] text-foreground-500">文档</div>
                      {results.documents.map((d) => (
                        <button
                          key={`${d.kind}-${d.id}`}
                          type="button"
                          onClick={() => {
                            setSearchOpen(false);
                            setQuery("");
                            navigate(d.href);
                          }}
                          className="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left hover:bg-background-200"
                        >
                          <i className="ri-file-text-line text-sm text-foreground-500"></i>
                          <span className="min-w-0">
                            <span className="block truncate text-sm text-foreground-900">{d.title}</span>
                            <span className="block text-[11px] text-foreground-500">{d.kind}</span>
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                  {results.members.length > 0 && (
                    <div>
                      <div className="px-3 py-1.5 font-label text-[10px] text-foreground-500">成员</div>
                      {results.members.map((m) => (
                        <button
                          key={m.id}
                          type="button"
                          onClick={() => {
                            setSearchOpen(false);
                            setQuery("");
                            navigate("/console/team");
                          }}
                          className="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left hover:bg-background-200"
                        >
                          <i className="ri-user-line text-sm text-foreground-500"></i>
                          <span className="min-w-0">
                            <span className="block truncate text-sm text-foreground-900">{m.name}</span>
                            <span className="block text-[11px] text-foreground-500">
                              {m.role} · {m.email}
                            </span>
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="relative" ref={noticeRef}>
          <button
            type="button"
            onClick={() => {
              setNoticeOpen((v) => !v);
              setHelpOpen(false);
            }}
            className="relative flex h-8 w-8 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-colors hover:bg-background-200"
            aria-label="通知"
          >
            <i className="ri-notification-3-line text-lg"></i>
          </button>
          {noticeOpen && (
            <div className="absolute right-0 top-[calc(100%+8px)] w-72 rounded-xl border border-background-300 bg-background-100 p-4 shadow-lg">
              <div className="text-sm font-medium text-foreground-900">通知</div>
              <p className="mt-2 text-xs leading-5 text-foreground-600">
                暂无站内推送。导出阻断、预审完成等结果请在对应模块查看；操作留痕见「审计日志」。
              </p>
            </div>
          )}
        </div>

        <div className="relative" ref={helpRef}>
          <button
            type="button"
            onClick={() => {
              setHelpOpen((v) => !v);
              setNoticeOpen(false);
            }}
            className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-colors hover:bg-background-200"
            aria-label="帮助"
          >
            <i className="ri-question-line text-lg"></i>
          </button>
          {helpOpen && (
            <div className="absolute right-0 top-[calc(100%+8px)] w-72 rounded-xl border border-background-300 bg-background-100 p-4 shadow-lg">
              <div className="text-sm font-medium text-foreground-900">使用说明</div>
              <p className="mt-2 text-xs leading-5 text-foreground-600">
                项目中心管理投标项目；招标解析生成评标尺子；撰写工作台生成章节；预审与修改闭环处理废标项后导出。
              </p>
              <button
                type="button"
                onClick={() => {
                  setHelpOpen(false);
                  navigate("/console/auditlog");
                }}
                className="mt-3 cursor-pointer text-xs font-medium text-primary-600 hover:underline"
              >
                查看操作审计
              </button>
            </div>
          )}
        </div>

        <div className="mx-1 hidden h-5 w-px bg-background-300 sm:block" />

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
                  onClick={() => {
                    setMenuOpen(false);
                    setProfileOpen(true);
                  }}
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
