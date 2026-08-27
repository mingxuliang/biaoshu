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

export const members: Member[] = [];
