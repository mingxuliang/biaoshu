import { NavLink } from "react-router-dom";

export interface SidebarNavItem {
  to: string;
  label: string;
  icon: string;
  /** 只在路径完全相同时高亮（用于首页 "/"） */
  end?: boolean;
}

export interface SidebarNavGroup {
  label: string;
  items: SidebarNavItem[];
}

interface AppSidebarProps {
  groups: SidebarNavGroup[];
  brandTitle?: string;
  brandSubtitle: string;
  brandIcon?: string;
  user: { name: string; subtitle: string; to?: string };
  footer?: React.ReactNode;
  mobileOpen: boolean;
  onClose: () => void;
}

/** 企业工作台与平台后台共用的侧边栏外观；菜单内容和权限过滤由调用方决定。 */
export default function AppSidebar({
  groups,
  brandTitle = "慧投标",
  brandSubtitle,
  brandIcon = "ri-sparkling-2-line",
  user,
  footer,
  mobileOpen,
  onClose,
}: AppSidebarProps) {
  const avatarText = (user.name || "用").trim().charAt(0) || "用";
  const userCard = (
    <>
      <span className="relative flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-primary-400 to-primary-600 text-xs font-medium text-background-50 ring-2 ring-background-100">
        {avatarText}
      </span>
      <span className="flex-1 min-w-0">
        <span className="font-label block truncate text-[13px] font-medium text-foreground-900">{user.name || "未登录"}</span>
        <span className="font-label block truncate text-[11px] text-foreground-500">{user.subtitle}</span>
      </span>
    </>
  );

  return (
    <>
      {mobileOpen && <div className="fixed inset-0 z-40 bg-foreground-950/40 lg:hidden animate-fade-in" onClick={onClose} />}
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-[220px] flex-col border-r border-background-300 bg-background-100 transition-transform duration-300 lg:translate-x-0 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center gap-2.5 px-4 py-5 border-b border-background-300">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
            <i className={`${brandIcon} text-lg`}></i>
          </div>
          <div>
            <div className="font-heading text-[15px] font-bold tracking-wider text-foreground-950">{brandTitle}</div>
            <div className="font-label max-w-[140px] truncate text-[10px] text-foreground-500" title={brandSubtitle}>
              {brandSubtitle}
            </div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-3">
          {groups
            .filter((g) => g.items.length > 0)
            .map((group) => (
              <div key={group.label}>
                <div className="font-label px-3 pb-2 pt-1 text-[11px] font-medium text-foreground-500">{group.label}</div>
                {group.items.map((item) => (
                  <NavLink
                    key={`${item.to}-${item.label}`}
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      `group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all duration-150 ${
                        isActive
                          ? "bg-primary-50/80 text-primary-500 font-medium"
                          : "text-foreground-600 hover:bg-background-200 hover:text-foreground-900"
                      }`
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <span
                          className={`absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-primary-500 transition-opacity ${
                            isActive ? "opacity-100" : "opacity-0"
                          }`}
                        />
                        <span
                          className={`flex h-7 w-7 items-center justify-center rounded-md transition-colors ${
                            isActive
                              ? "bg-gradient-to-br from-primary-400 to-primary-600 text-background-50"
                              : "text-foreground-500 group-hover:text-foreground-700"
                          }`}
                        >
                          <i className={`${item.icon} text-base`}></i>
                        </span>
                        <span className="font-label flex-1">{item.label}</span>
                      </>
                    )}
                  </NavLink>
                ))}
              </div>
            ))}
        </nav>

        <div className="border-t border-background-300 px-3 py-3">
          {user.to ? (
            <NavLink to={user.to} className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 transition-colors hover:bg-background-200">
              {userCard}
            </NavLink>
          ) : (
            <div className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2">{userCard}</div>
          )}
          {footer}
        </div>
      </aside>
    </>
  );
}
