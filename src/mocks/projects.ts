export type ProjectStatus = "撰写中" | "评标中" | "已提交" | "已中标" | "未中标";
export type ProjectType = "工程" | "政采" | "医疗" | "交通" | "IT" | "能源";

export interface TenderUpload {
  name: string;
  size: string;
  format: string;
  pages?: number;
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
}

export const projectTypes: ProjectType[] = ["工程", "政采", "医疗", "交通", "IT", "能源"];

export const projectStatuses: ProjectStatus[] = ["撰写中", "评标中", "已提交", "已中标", "未中标"];

export const projects: Project[] = [
  {
    id: "p-1001",
    code: "ZB-2026-0412",
    name: "城市轨道交通 3 号线智能化机电安装工程",
    type: "交通",
    owner: "陈立群",
    budget: "¥ 8,600 万",
    deadline: "2026-08-28",
    progress: 76,
    score: 91.5,
    status: "评标中",
    createdAt: "2026-06-18",
  },
  {
    id: "p-1002",
    code: "CG-2026-0877",
    name: "市政务数据中心云资源池扩容采购项目",
    type: "政采",
    owner: "林晓雯",
    budget: "¥ 2,450 万",
    deadline: "2026-08-22",
    progress: 92,
    score: 88.2,
    status: "已提交",
    createdAt: "2026-06-25",
  },
  {
    id: "p-1003",
    code: "GX-2026-1530",
    name: "三甲医院智慧医疗一体化信息平台建设",
    type: "医疗",
    owner: "王浩然",
    budget: "¥ 3,180 万",
    deadline: "2026-09-05",
    progress: 45,
    score: 84.6,
    status: "撰写中",
    createdAt: "2026-07-02",
  },
  {
    id: "p-1004",
    code: "YT-2026-0934",
    name: "河西综合管廊二期土建施工总承包工程",
    type: "工程",
    owner: "赵启铭",
    budget: "¥ 12,900 万",
    deadline: "2026-08-15",
    progress: 100,
    score: 93.1,
    status: "已中标",
    createdAt: "2026-05-20",
  },
  {
    id: "p-1005",
    code: "XX-2026-0219",
    name: "省级国资云安全态势感知平台建设项目",
    type: "IT",
    owner: "李思源",
    budget: "¥ 1,860 万",
    deadline: "2026-09-12",
    progress: 18,
    score: 0,
    status: "撰写中",
    createdAt: "2026-07-20",
  },
  {
    id: "p-1006",
    code: "NY-2026-0671",
    name: "光伏电站智能运维监控系统集成项目",
    type: "能源",
    owner: "陈立群",
    budget: "¥ 4,520 万",
    deadline: "2026-08-30",
    progress: 100,
    score: 79.8,
    status: "未中标",
    createdAt: "2026-04-15",
  },
  {
    id: "p-1007",
    code: "CG-2026-1022",
    name: "智慧园区一网统管综合服务平台建设",
    type: "政采",
    owner: "林晓雯",
    budget: "¥ 2,980 万",
    deadline: "2026-09-20",
    progress: 8,
    score: 0,
    status: "撰写中",
    createdAt: "2026-08-02",
  },
];