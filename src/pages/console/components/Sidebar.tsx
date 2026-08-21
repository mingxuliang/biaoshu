import { NavLink } from "react-router-dom";

const navGroups = [
  {
    label: "业务模块",
    items: [
      { to: "/console/projects", label: "项目中心", icon: "ri-folder-2-line" },
      { to: "/console/parse", label: "招标解析", icon: "ri-file-settings-line" },
      { to: "/console/writer", label: "撰写工作台", icon: "ri-edit-2-line" },
      { to: "/console/audit", label: "AI 预审中心", icon: "ri-shield-check-line" },
      { to: "/console/review", label: "修改闭环", icon: "ri-loop-left-line" },
      { to: "/console/export", label: "Word 导出", icon: "ri-download-2-line" },
    ],
  },
  {
    label: "资源模块",
    items: [
      { to: "/console/qualifications", label: "资质证照库", icon: "ri-vip-crown-2-line" },
      { to: "/console/knowledge", label: "文档知识库", icon: "ri-book-3-line" },
    ],
  },
  {
    label: "系统模块",
    items: [
      { to: "/console/rules", label: "预审规则", icon: "ri-tools-line" },
      { to: "/console/team", label: "团队管理", icon: "ri-team-line" },
      { to: "/console/auditlog", label: "审计日志", icon: "ri-file-history-line" },
    ],
  },
];

interface SidebarProps {
  mobileOpen: boolean;
  onClose: () => void;
}

export default function Sidebar({ mobileOpen, onClose }: SidebarProps) {
  return (
    <>
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-foreground-950/40 lg:hidden animate-fade-in"
          onClick={onClose}
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-[220px] flex-col border-r border-background-300 bg-background-100 transition-transform duration-300 lg:translate-x-0 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {/* Logo */}
        <div className="flex items-center gap-2.5 px-4 py-5 border-b border-background-300">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
            <i className="ri-sparkling-2-line text-lg"></i>
          </div>
          <div>
            <div className="font-heading text-[15px] font-bold tracking-wider text-foreground-950">
              智标云
            </div>
            <div className="font-label text-[10px] text-foreground-500">
              AI 标书系统
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto px-3 py-3">
          {navGroups.map((group) => (
            <div key={group.label}>
              <div className="font-label px-3 pb-2 pt-1 text-[11px] font-medium text-foreground-500">
                {group.label}
              </div>
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
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
                          isActive ? "bg-gradient-to-br from-primary-400 to-primary-600 text-background-50" : "text-foreground-500 group-hover:text-foreground-700"
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

        {/* AI usage */}
        <div className="mx-3 mb-3 rounded-lg border border-background-300 bg-background-50 p-3">
          <div className="flex items-center justify-between text-xs">
            <span className="font-label flex items-center gap-1.5 font-medium text-foreground-700">
              <i className="ri-cpu-line text-sm text-primary-500"></i>
              本月 AI 额度
            </span>
            <span className="font-heading text-gradient font-semibold">78%</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-background-200">
            <div className="h-full w-[78%] rounded-full bg-gradient-to-r from-primary-500 to-primary-400 animate-shimmer" />
          </div>
          <p className="font-label mt-1.5 text-[11px] text-foreground-500">
            已消耗 1.56M tokens
          </p>
        </div>

        {/* User */}
        <div className="border-t border-background-300 px-3 py-3">
          <button
            type="button"
            className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors hover:bg-background-200"
          >
            <span className="relative flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-primary-400 to-primary-600 text-xs font-medium text-background-50 ring-2 ring-background-100">
              陈
              <span className="absolute bottom-0 right-0 h-2 w-2 rounded-full border-2 border-background-100 bg-primary-400 animate-pulse" />
            </span>
            <span className="flex-1 min-w-0">
              <span className="font-label block truncate text-[13px] font-medium text-foreground-900">陈立群</span>
              <span className="font-label block text-[11px] text-foreground-500">管理员</span>
            </span>
            <i className="ri-arrow-down-s-line text-base text-foreground-500"></i>
          </button>
        </div>
      </aside>
    </>
  );
}