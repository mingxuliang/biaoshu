export type MemberRole = "管理员" | "项目经理" | "撰写专家" | "评标专家";
export type MemberStatus = "在线" | "忙碌" | "离线";

export interface Member {
  id: string;
  name: string;
  role: MemberRole;
  email: string;
  phone: string;
  status: MemberStatus;
  lastActive: string;
  projectCount: number;
  joinedAt: string;
}

export const memberRoles: MemberRole[] = ["管理员", "项目经理", "撰写专家", "评标专家"];

export const members: Member[] = [
  {
    id: "m-01",
    name: "陈立群",
    role: "管理员",
    email: "chenliqun@zby.ai",
    phone: "138 **** 0216",
    status: "在线",
    lastActive: "刚刚",
    projectCount: 12,
    joinedAt: "2025-03-12",
  },
  {
    id: "m-02",
    name: "林晓雯",
    role: "项目经理",
    email: "linxiaowen@zby.ai",
    phone: "136 **** 8832",
    status: "忙碌",
    lastActive: "10 分钟前",
    projectCount: 8,
    joinedAt: "2025-05-06",
  },
  {
    id: "m-03",
    name: "王浩然",
    role: "撰写专家",
    email: "wanghaoran@zby.ai",
    phone: "139 **** 4570",
    status: "在线",
    lastActive: "2 分钟前",
    projectCount: 6,
    joinedAt: "2025-07-21",
  },
  {
    id: "m-04",
    name: "赵启铭",
    role: "撰写专家",
    email: "zhaoqiming@zby.ai",
    phone: "137 **** 9021",
    status: "离线",
    lastActive: "昨天 18:40",
    projectCount: 9,
    joinedAt: "2025-04-19",
  },
  {
    id: "m-05",
    name: "李思源",
    role: "评标专家",
    email: "lisiyuan@zby.ai",
    phone: "135 **** 1190",
    status: "在线",
    lastActive: "5 分钟前",
    projectCount: 5,
    joinedAt: "2025-09-02",
  },
  {
    id: "m-06",
    name: "沈慧敏",
    role: "评标专家",
    email: "shenhuimin@zby.ai",
    phone: "133 **** 6723",
    status: "忙碌",
    lastActive: "1 小时前",
    projectCount: 4,
    joinedAt: "2025-11-15",
  },
  {
    id: "m-07",
    name: "冯铁军",
    role: "项目经理",
    email: "fengtiejun@zby.ai",
    phone: "158 **** 3345",
    status: "离线",
    lastActive: "昨天 09:12",
    projectCount: 7,
    joinedAt: "2025-06-28",
  },
];

export interface PermissionItem {
  name: string;
  granted: boolean;
}

export interface RolePermission {
  role: MemberRole;
  desc: string;
  permissions: PermissionItem[];
}

const permissionsName = [
  "项目创建与编辑",
  "AI 标书撰写",
  "报告导出",
  "成员与权限管理",
  "系统设置",
];

export const rolePermissions: RolePermission[] = [
  {
    role: "管理员",
    desc: "全部功能与成员管理权限",
    permissions: permissionsName.map((name) => ({ name, granted: true })),
  },
  {
    role: "项目经理",
    desc: "负责项目全流程统筹与提交",
    permissions: [
      { name: "项目创建与编辑", granted: true },
      { name: "AI 标书撰写", granted: true },
      { name: "报告导出", granted: true },
      { name: "成员与权限管理", granted: false },
      { name: "系统设置", granted: false },
    ],
  },
  {
    role: "撰写专家",
    desc: "专注标书内容撰写与修订",
    permissions: [
      { name: "项目创建与编辑", granted: false },
      { name: "AI 标书撰写", granted: true },
      { name: "报告导出", granted: true },
      { name: "成员与权限管理", granted: false },
      { name: "系统设置", granted: false },
    ],
  },
  {
    role: "评标专家",
    desc: "参与标书质量评审与合规复核",
    permissions: [
      { name: "项目创建与编辑", granted: false },
      { name: "AI 标书撰写", granted: false },
      { name: "报告导出", granted: true },
      { name: "成员与权限管理", granted: false },
      { name: "系统设置", granted: false },
    ],
  },
];