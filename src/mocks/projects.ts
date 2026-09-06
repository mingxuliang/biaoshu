export type ProjectStatus = "撰写中" | "评标中" | "已提交" | "已中标" | "未中标";
export type ProjectType = "工程" | "政采" | "医疗" | "交通" | "IT" | "能源";
// 决定招标解析用哪套指标骨架、AI 预审走哪套引擎参数：软件服务类沿用现有字段体系，
// 工程类按施工类招标书特点（评定分离、三信封、清单图纸、异常低价等）单独解析。
export type ProjectCategory = "软件服务类" | "工程类";

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
  category: ProjectCategory;
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

export const projectCategories: ProjectCategory[] = ["软件服务类", "工程类"];

export const projectStatuses: ProjectStatus[] = ["撰写中", "评标中", "已提交", "已中标", "未中标"];

export const projects: Project[] = [];
