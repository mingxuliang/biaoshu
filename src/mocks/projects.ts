export type ProjectStatus = "撰写中" | "评标中" | "已提交" | "已中标" | "未中标";
export type ProjectType = "工程" | "政采" | "医疗" | "交通" | "IT" | "能源";
// 决定招标解析用哪套指标骨架。标书类别只认用户在新建/编辑时的选择：
// 软件服务类不抽图纸和施工清单；工程类按施工类招标书解析。
// 「产品标」「工程标」只是历史别名，读取时分别视为软件服务类、工程类。
export type ProjectCategory = "软件服务类" | "工程类";

export function normalizeCategory(category?: string | null): ProjectCategory {
  return category === "工程类" || category === "工程标" ? "工程类" : "软件服务类";
}

export function isEngineeringCategory(category?: string | null): boolean {
  return category === "工程类" || category === "工程标";
}

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
  specialty?: string;
  workType?: string;
  owner: string;
  budget: string;
  deadline: string;
  progress: number;
  light?: "绿" | "橙" | "红" | null; // 最新一轮预审的风险灯，代替原来的数字得分
  status: ProjectStatus;
  createdAt: string;
  tenderDoc?: TenderUpload;
  team?: ProjectTeamMember[];
}

export const projectTypes: ProjectType[] = ["工程", "政采", "医疗", "交通", "IT", "能源"];

export const projectCategories: ProjectCategory[] = ["软件服务类", "工程类"];

export type WriterTrack = "software" | "engineering" | "water";

export const writerTracks: { id: WriterTrack; label: string; hint: string }[] = [
  { id: "software", label: "软件服务标", hint: "招标解析不抽图纸和工程量清单。撰写走产品功能应答，对话改写不套水利规则。" },
  { id: "engineering", label: "工程标通用", hint: "施工类招标解析。撰写按施工组织设计，专业不含水利，对话改写不套水利度汛规则。" },
  { id: "water", label: "工程标水利", hint: "施工类招标解析。撰写按水利施组账和目录，对话改写会按区段、座数和规范编号校核。" },
];

export function writerTrackOf(category?: string | null, specialty?: string | null): WriterTrack {
  if (!isEngineeringCategory(category)) return "software";
  if ((specialty || "").trim() === "水利") return "water";
  return "engineering";
}

export const projectStatuses: ProjectStatus[] = ["撰写中", "评标中", "已提交", "已中标", "未中标"];

export const projects: Project[] = [];
