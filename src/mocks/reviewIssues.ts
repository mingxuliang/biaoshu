// M07 审核后修改闭环（演示数据）

export interface ReviewTask {
  id: string;
  issue: string;
  severity: "废标" | "降档" | "扣分" | "建议";
  section: string;
  ruleType: string;
  assignee: string;
  deadline: string;
  status: "待分派" | "改写中" | "待确认" | "复审中" | "已关闭";
  quote: string;
  rewrite: string;
}

export const reviewTasks: ReviewTask[] = [
  { id: "t1", issue: "投标有效期栏留空", severity: "废标", section: "资格文件 / 报价承诺函 / 3.2", ruleType: "缺项", assignee: "王建军", deadline: "2026-08-18", status: "改写中", quote: "投标有效期：____________", rewrite: "投标有效期：自投标截止之日起 90 日历天。" },
  { id: "t2", issue: "业绩四件套缺官网截图", severity: "降档", section: "商务标 / 业绩证明 / 4.2", ruleType: "错配", assignee: "李卫东", deadline: "2026-08-19", status: "待确认", quote: "业绩佐证材料仅提供合同与验收报告", rewrite: "本业绩已补传中标通知书、竣工验收及招标官网中标公示截图，形成完整四件套。" },
  { id: "t3", issue: "资产负债率超上限", severity: "扣分", section: "资格文件 / 财务 / 2.1", ruleType: "缺项", assignee: "赵敏", deadline: "2026-08-19", status: "改写中", quote: "最近一年资产负债率 87.2%", rewrite: "经复核，资产负债率按最新季度审计口径为 84.6%，附说明函与审计表佐证。" },
  { id: "t4", issue: "高危虚词「确保优质创优」", severity: "扣分", section: "技术标 / 2.1.2 / 施工工艺", ruleType: "虚词", assignee: "王建军", deadline: "2026-08-20", status: "待确认", quote: "确保本工程质量达到优良，力争创优", rewrite: "本工程质量目标为一次验收合格率 100%，分部分项优良率不低于 92%，争创市级优质工程奖。" },
  { id: "t5", issue: "模板相似度过高 46%", severity: "扣分", section: "技术标 / 1.1 / 项目理解", ruleType: "模板化", assignee: "赵敏", deadline: "2026-08-20", status: "待分派", quote: "结合本项目地质条件与工期要求…（与城东模板雷同）", rewrite: "结合本项目城区段软土地基、全年有效工期 180 天及交通导改约束，采用分段快速成桩+同步注浆工艺。" },
  { id: "t6", issue: "目录页码偏差 2 页", severity: "建议", section: "全文 / 目录", ruleType: "版式", assignee: "陈立群", deadline: "2026-08-21", status: "已关闭", quote: "第 5 章目录页码为 56，正文实际 58", rewrite: "已更新目录域并重新生成，页码核对一致。" },
];

export const ruleTypeFilters = ["全部", "虚词", "缺项", "模板化", "错配", "版式"];
export const severityFilters = ["全部", "废标", "降档", "扣分", "建议"];