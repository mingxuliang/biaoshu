export type DocType = "招标文件" | "技术标" | "商务标" | "资格文件" | "评标报告";

export interface ProjectDoc {
  id: string;
  name: string;
  type: DocType;
  size: string;
  updated: string;
  status: "已完成" | "修订中";
}

export const projectDocs: ProjectDoc[] = [
  { id: "d-01", name: "招标文件-3号线机电安装.pdf", type: "招标文件", size: "18.6 MB", updated: "07-18", status: "已完成" },
  { id: "d-02", name: "技术标-总体方案V3.2.docx", type: "技术标", size: "6.2 MB", updated: "08-10", status: "已完成" },
  { id: "d-03", name: "商务标-报价明细表V2.1.xlsx", type: "商务标", size: "1.8 MB", updated: "08-12", status: "修订中" },
  { id: "d-04", name: "资格文件-企业资质证明.pdf", type: "资格文件", size: "9.4 MB", updated: "08-05", status: "已完成" },
  { id: "d-05", name: "AI评标预演报告-3号线.pdf", type: "评标报告", size: "3.1 MB", updated: "08-11", status: "已完成" },
];

export type StageStatus = "已完成" | "进行中" | "待开始";

export interface TimelineStage {
  id: string;
  label: string;
  date: string;
  status: StageStatus;
  desc: string;
}

export const timelineStages: TimelineStage[] = [
  { id: "s-01", label: "上传并解析招标文件", date: "07-18", status: "已完成", desc: "AI 自动提取 42 项评分点与 15 项废标条款" },
  { id: "s-02", label: "AI 生成标书初稿", date: "07-22", status: "已完成", desc: "8 个章节 6 小时完成初稿，整体通过率预测 91%" },
  { id: "s-03", label: "人工修订与合规校验", date: "08-02", status: "已完成", desc: "完成两轮人工修订，AI 合规校验零风险项" },
  { id: "s-04", label: "AI 评标预演", date: "08-11", status: "进行中", desc: "3 名虚拟专家打分完成，综合得分 91.5 分，排名第 1" },
  { id: "s-05", label: "递交标书", date: "08-22", status: "待开始", desc: "电子标书加密上传与纸质标书寄送" },
  { id: "s-06", label: "开标与结果公示", date: "08-28", status: "待开始", desc: "开标评标与结果公示跟踪" },
];