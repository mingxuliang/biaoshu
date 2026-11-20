import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import AppSidebar, { type SidebarNavGroup } from "@/components/shell/AppSidebar";
import { useAdminAuth, useCan } from "./auth";
import AdminTopbar from "./Topbar";

const NAV: { label: string; items: { to: string; label: string; icon: string; superOnly?: boolean }[] }[] = [
  {
    label: "运营",
    items: [
      { to: "/", label: "概览", icon: "ri-dashboard-3-line" },
      { to: "/tenants", label: "企业管理", icon: "ri-building-2-line" },
    ],
  },
  {
    label: "计费与财务",
    items: [
      { to: "/credits", label: "企业费用", icon: "ri-coins-line" },
      { to: "/users", label: "全员费用", icon: "ri-user-follow-line" },
      { to: "/pricing", label: "扣费规则与套餐", icon: "ri-price-tag-3-line" },
      { to: "/orders", label: "订单与对公转账", icon: "ri-bank-card-line" },
      { to: "/invoices", label: "发票", icon: "ri-bill-line" },
    ],
  },
  {
    label: "平台",
    items: [
      { to: "/llm", label: "大模型接入", icon: "ri-robot-2-line" },
      { to: "/storage", label: "对象存储", icon: "ri-hard-drive-3-line" },
      { to: "/system", label: "系统环境", icon: "ri-server-line" },
      { to: "/standards", label: "规范库", icon: "ri-book-2-line" },
      { to: "/announcements", label: "公告", icon: "ri-megaphone-line" },
      { to: "/audit", label: "平台审计", icon: "ri-file-shield-2-line" },
      { to: "/admins", label: "后台账号", icon: "ri-admin-line", superOnly: true },
    ],
  },
];

const TITLES: [RegExp, string][] = [
  [/^\/tenants\/[^/]+/, "企业详情"],
  [/^\/tenants/, "企业管理"],
  [/^\/credits/, "企业费用"],
  [/^\/users/, "全员费用"],
  [/^\/pricing/, "扣费规则与套餐"],
  [/^\/orders/, "订单与对公转账"],
  [/^\/invoices/, "发票"],
  [/^\/llm/, "大模型接入"],
  [/^\/storage/, "对象存储"],
  [/^\/system/, "系统环境"],
  [/^\/standards/, "规范库"],
  [/^\/announcements/, "公告"],
  [/^\/audit/, "平台审计"],
  [/^\/admins/, "后台账号"],
  [/^\/account/, "账号与安全"],
];

function getTitle(pathname: string): string {
  return TITLES.find(([re]) => re.test(pathname))?.[1] || "概览";
}

export default function AdminLayout() {
  const { admin } = useAdminAuth();
  const { isSuper } = useCan();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  const groups: SidebarNavGroup[] = NAV.map((g) => ({
    label: g.label,
    items: g.items.filter((i) => !i.superOnly || isSuper).map((i) => ({ ...i, end: i.to === "/" })),
  }));

  return (
    <div className="relative min-h-screen bg-background-50 text-foreground-950">
      <AppSidebar
        groups={groups}
        brandSubtitle="平台管理后台"
        brandIcon="ri-shield-star-line"
        user={{ name: admin?.name || admin?.email || "", subtitle: admin?.role || "", to: "/account" }}
        mobileOpen={mobileOpen}
        onClose={() => setMobileOpen(false)}
      />
      <div className="relative lg:pl-[220px]">
        <AdminTopbar title={getTitle(location.pathname)} onMenuOpen={() => setMobileOpen(true)} />
        <main className="min-h-[calc(100vh-3.5rem)] px-5 py-5">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
