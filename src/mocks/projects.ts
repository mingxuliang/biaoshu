export type ProjectStatus = "撰写中" | "评标中" | "已提交" | "已中标" | "未中标";
export type ProjectType = "工程" | "政采" | "医疗" | "交通" | "IT" | "能源";

export interface TenderUpload {
  name: string;
  size: string;
  format: string;
  pages?: number;
}

export interface ProjectTeamMember {
  id: string;
  name: string;
  email: string;
  role: string;
}

export interface Project {
  id: string;
  code: string;
  name: string;
  type: ProjectType;
  owner: string;
  budget: string;
  deadline: string;
  progress: number;
  score: number;
  status: ProjectStatus;
  createdAt: string;
  tenderDoc?: TenderUpload;
  team?: ProjectTeamMember[];
}

export const projectTypes: ProjectType[] = ["工程", "政采", "医疗", "交通", "IT", "能源"];

export const projectStatuses: ProjectStatus[] = ["撰写中", "评标中", "已提交", "已中标", "未中标"];

export const projects: Project[] = [];
