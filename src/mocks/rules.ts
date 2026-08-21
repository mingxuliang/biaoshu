// M10 预审规则配置（演示数据）

export interface WeightTemplate {
  id: string;
  name: string;
  completeness: number;
  relevance: number;
  compliance: number;
  feasibility: number;
  standardization: number;
  scope: string;
  active: boolean;
}

export interface WordRule {
  id: string;
  category: string;
  word: string;
  pattern: string;
  rewrite: string;
  enabled: boolean;
}

export interface ThresholdRule {
  id: string;
  name: string;
  safe: number;
  risk: number;
  projectType: string;
}

export const weightTemplates: WeightTemplate[] = [
  { id: "w1", name: "青天默认五维", completeness: 30, relevance: 25, compliance: 20, feasibility: 15, standardization: 10, scope: "全局默认", active: true },
  { id: "w2", name: "政采服务类", completeness: 28, relevance: 26, compliance: 22, feasibility: 14, standardization: 10, scope: "按项目类型", active: false },
  { id: "w3", name: "EPC 总承包", completeness: 32, relevance: 24, compliance: 18, feasibility: 16, standardization: 10, scope: "按项目类型", active: false },
];

export const wordRules: WordRule[] = [
  { id: "wd1", category: "空话承诺", word: "确保…优良/创优", pattern: "确保|力争|务必|一定", rewrite: "一次验收合格率≥99%、优良率≥92%", enabled: true },
  { id: "wd2", category: "套话表态", word: "高度重视", pattern: "高度重视|全力以赴|保质保量", rewrite: "本项目投入管理人员 8 名、专职质检员 2 名", enabled: true },
  { id: "wd3", category: "虚泛描述", word: "先进的技术", pattern: "先进的技术|一流水平|领先地位", rewrite: "采用 XXX 工艺/设备（具体参数）", enabled: true },
  { id: "wd4", category: "过度承诺", word: "绝对安全", pattern: "绝对|百分之百|零事故", rewrite: "年事故率≤0.3‰、通过双重预防体系", enabled: true },
  { id: "wd5", category: "时间模糊", word: "尽快完成", pattern: "尽快|及时|按期", rewrite: "总工期 180 日历天、关键节点 2026-11-30", enabled: false },
];

export const thresholdRules: ThresholdRule[] = [
  { id: "th1", name: "全文查重", safe: 30, risk: 42, projectType: "全部" },
  { id: "th2", name: "重难点章节查重", safe: 20, risk: 40, projectType: "全部" },
  { id: "th3", name: "技术标虚词密度", safe: 25, risk: 35, projectType: "EPC 总承包" },
];

export const rulePackages = [
  { id: "rp1", name: "扬尘六个 100% 细则包", region: "华东", status: "启用", items: ["围挡率 100%", "洒水降尘 100%", "出入口冲洗 100%"] },
  { id: "rp2", name: "临边洞口防护细则包", region: "全国", status: "启用", items: ["临边防护高度 1.2m", "洞口盖板固定", "安全网兜底"] },
];