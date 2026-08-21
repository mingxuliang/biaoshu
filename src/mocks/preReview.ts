// M06 AI 预审中心（演示数据）

export interface PreReviewLevel {
  key: string;
  name: string;
  desc: string;
  score: number;
  full: number;
  issues: number;
  status: "通过" | "风险" | "未达标";
}

export interface PreReviewIssue {
  id: string;
  level: string;
  severity: "废标" | "降档" | "扣分" | "建议";
  location: string;
  excerpt: string;
  rule: string;
  tenderQuote: string;
  suggestion: string;
}

export const preReviewLevels: PreReviewLevel[] = [
  { key: "L1", name: "一票否决扫描", desc: "星号条款、废标条款、资质证件、暗标残留", score: 96, full: 100, issues: 1, status: "通过" },
  { key: "L2", name: "商务客观核验", desc: "业绩匹配度、人员证书、财务一致性、信用材料", score: 88, full: 100, issues: 3, status: "风险" },
  { key: "L3", name: "技术标五维打分", desc: "完整性/针对性/合规性/可落地性/规范性", score: 82.5, full: 100, issues: 6, status: "通过" },
  { key: "L4", name: "虚词与模板查重", desc: "虚词密度、高危句式、相似度比对", score: 79, full: 100, issues: 4, status: "风险" },
  { key: "L5", name: "版式终审", desc: "标题层级、目录页码、图表编号、空白页", score: 91, full: 100, issues: 2, status: "通过" },
];

export const preReviewIssues: PreReviewIssue[] = [
  { id: "pi1", level: "L1", severity: "废标", location: "资格文件 / 报价承诺函 / 3.2", excerpt: "投标有效期栏留空，未填写 90 日历天", rule: "F02.03 实质性条款须明确响应", tenderQuote: "投标函及投标有效期：自投标截止之日起 90 日历天，未按要求填写投标有效期的，投标将被否决。", suggestion: "补填投标有效期 90 日历天并加盖公章" },
  { id: "pi2", level: "L2", severity: "降档", location: "商务标 / 业绩证明 / 4.2", excerpt: "城东快速路业绩缺少「官网截图」佐证，四件套不全", rule: "F03.05 业绩四件套齐全才计分", tenderQuote: "投标人须提供中标通知书、合同、竣工验收证明及招标官网中标公示截图（四件套齐全），缺少任一项该项业绩不予计分。", suggestion: "补充官网公示截图，或声明扣分接受" },
  { id: "pi3", level: "L2", severity: "扣分", location: "资格文件 / 财务 / 2.1", excerpt: "近三年财务报表资产负债率 87.2%，超 85% 上限", rule: "F02.04 财务要求核对", tenderQuote: "投标人最近三年资产负债率不高于 85%，否则资格审查不予通过。", suggestion: "核对最新年度报表或附说明函" },
  { id: "pi4", level: "L4", severity: "扣分", location: "技术标 / 2.1.2 / 施工工艺", excerpt: "“确保本工程质量达到优良，力争创优” 属高危虚词句", rule: "F10.02 虚词表-空话承诺", tenderQuote: "本工程质量目标为一次验收合格率 100%，杜绝“确保优质、力争创优”等无量化表述。", suggestion: "改为量化指标：一次验收合格率≥99%、创市级优质工程" },
  { id: "pi5", level: "L4", severity: "扣分", location: "技术标 / 1.1 / 项目理解", excerpt: "段落与「城东快速路改造工程」模板相似度 46%", rule: "F06.05 查重阈值全文≤30%", tenderQuote: "投标文件内容须结合本项目实际情况编制，全文与既有模板相似度不得超过 30%。", suggestion: "注入本项目地点、工期、地质特征重写" },
  { id: "pi6", level: "L5", severity: "建议", location: "全文 / 目录", excerpt: "第 5 章标题页码与正文不符（偏差 2 页）", rule: "F06.06 版式终审", tenderQuote: "目录自动生成且页码须与正文一致，否则按未实质性响应评审。", suggestion: "更新目录域代码后重新生成" },
];

export const dimensionBreakdown = [
  { name: "完整性", weight: 30, score: 88 },
  { name: "针对性", weight: 25, score: 80 },
  { name: "合规性", weight: 20, score: 86 },
  { name: "可落地性", weight: 15, score: 78 },
  { name: "规范性", weight: 10, score: 84 },
];