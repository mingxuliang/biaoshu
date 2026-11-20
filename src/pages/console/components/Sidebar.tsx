import AppSidebar, { type SidebarNavGroup } from "@/components/shell/AppSidebar";
import { useAuth } from "@/context/AuthContext";
import { isPersonal } from "@/lib/api";
import { hideWriter } from "@/lib/flags";
import { hasAnyPerm, type RolePerm } from "@/lib/permissions";

type NavItem = { to: string; label: string; icon: string; anyOf?: RolePerm[]; orgOnly?: boolean; personalOnly?: boolean };

const navGroups: {
  label: string;
  personalLabel?: string;
  items: NavItem[];
}[] = [
  {
    label: "业务模块",
    items: [
      { to: "/console/projects", label: "项目中心", icon: "ri-folder-2-line" },
      { to: "/console/parse", label: "招标解析", icon: "ri-file-settings-line", anyOf: ["project_edit", "writer"] },
      { to: "/console/writer", label: "撰写工作台", icon: "ri-edit-2-line", anyOf: ["writer"] },
      { to: "/console/audit", label: "AI 预审中心", icon: "ri-shield-check-line", anyOf: ["review"] },
      { to: "/console/duplicate", label: "查重分析", icon: "ri-file-copy-2-line", anyOf: ["review"] },
      { to: "/console/review", label: "修改闭环", icon: "ri-loop-left-line", anyOf: ["writer"] },
      { to: "/console/export", label: "Word 导出", icon: "ri-download-2-line", anyOf: ["export"] },
    ],
  },
  {
    label: "资源模块",
    items: [
      {
        to: "/console/qualifications",
        label: "资质证照库",
        icon: "ri-vip-crown-2-line",
        anyOf: ["project_edit", "writer", "review", "qual_edit"],
      },
      { to: "/console/knowledge", label: "文档知识库", icon: "ri-book-3-line" },
      {
        to: "/console/products",
        label: "产品功能库",
        icon: "ri-box-3-line",
        anyOf: ["project_edit", "writer", "review", "qual_edit"],
      },
    ],
  },
  {
    label: "系统模块",
    items: [
      { to: "/console/rules", label: "预审规则", icon: "ri-tools-line", anyOf: ["settings"] },
      { to: "/console/models", label: "模型配置", icon: "ri-cpu-line", anyOf: ["settings"] },
      { to: "/console/team", label: "团队管理", icon: "ri-team-line", anyOf: ["members"], orgOnly: true },
      { to: "/console/auditlog", label: "审计日志", icon: "ri-file-history-line", anyOf: ["settings"] },
    ],
  },
  {
    label: "企业管理",
    personalLabel: "我的账号",
    items: [
      { to: "/console/org", label: "企业与组织", icon: "ri-building-2-line", anyOf: ["org"], orgOnly: true },
      { to: "/console/org", label: "升级为企业", icon: "ri-building-2-line", anyOf: ["org"], personalOnly: true },
      { to: "/console/billing", label: "费用中心", icon: "ri-wallet-3-line" },
    ],
  },
];

interface SidebarProps {
  mobileOpen: boolean;
  onClose: () => void;
}

export default function Sidebar({ mobileOpen, onClose }: SidebarProps) {
  const { user } = useAuth();
  const personal = isPersonal(user);
  const groups: SidebarNavGroup[] = navGroups.map((group) => ({
    label: personal && group.personalLabel ? group.personalLabel : group.label,
    items: group.items.filter((item) => {
      if (hideWriter && item.to === "/console/writer") return false;
      if (item.personalOnly && !personal) return false;
      if (item.orgOnly && personal) return false;
      return !item.anyOf || hasAnyPerm(user, item.anyOf);
    }),
  }));

  return (
    <AppSidebar
      groups={groups}
      brandSubtitle={user?.tenant?.name || "AI 标书系统"}
      user={{ name: user?.name || "", subtitle: user?.role || "" }}
      mobileOpen={mobileOpen}
      onClose={onClose}
    />
  );
}
