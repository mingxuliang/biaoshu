// M08 闭环修改 · 投标书 Word 正文（演示数据）
// 每个 section 对应投标书一个章节，paragraph 内的 problem 句会被高亮并锚定到预审问题。

export interface BidProblem {
  issueId: string;
  highlight: string; // 投标书原文中需要高亮的句段
}

export interface BidParagraph {
  id: string;
  text: string;
  problem?: BidProblem;
}

export interface BidSection {
  id: string; // 锚点 id
  heading: string;
  level: 1 | 2 | 3;
  paragraphs: BidParagraph[];
}

export interface BidVersion {
  id: string;
  label: string;
  time: string;
  author: string;
  note: string;
  wordCount: number;
}

export const bidDocument: BidSection[] = [
  {
    id: "sec-cover",
    heading: "第一部分 资格文件",
    level: 1,
    paragraphs: [
      { id: "cover-p1", text: "投标人（盖章）：智标云建设集团有限公司" },
      { id: "cover-p2", text: "法定代表人或授权代表（签字）：____________" },
      { id: "cover-p3", text: "投标日期：2026 年 8 月 17 日" },
    ],
  },
  {
    id: "sec-finance",
    heading: "2.1 财务状况说明",
    level: 2,
    paragraphs: [
      {
        id: "fin-p1",
        text: "本企业近三年财务状况良好，资产负债率保持稳定，现金流充足，具备本项目履约所需的资金保障能力。",
        problem: { issueId: "pi3", highlight: "资产负债率保持稳定" },
      },
      { id: "fin-p2", text: "我方随附经审计的近三年财务报表（资产负债表、利润表、现金流量表）及审计报告，供评标委员会核验。" },
      { id: "fin-p3", text: "经复核，我方最近一年资产负债率为 84.6%，符合招标文件不高于 85% 的上限要求，附说明函与最新季度审计表佐证。" },
    ],
  },
  {
    id: "sec-letter",
    heading: "3.2 报价承诺函（含投标有效期）",
    level: 2,
    paragraphs: [
      {
        id: "let-p1",
        text: "我方承诺自投标截止之日起投标有效期为 90 日历天，并在有效期内不撤回投标文件、不改变报价及承诺条件。",
        problem: { issueId: "pi1", highlight: "90 日历天" },
      },
      { id: "let-p2", text: "本报价包含完成招标文件规定全部工作所需的全部费用，报价在有效期内保持固定不变，不因市场价格波动而调整。" },
    ],
  },
  {
    id: "sec-perf",
    heading: "4.2 同类业绩证明",
    level: 2,
    paragraphs: [
      {
        id: "perf-p1",
        text: "本企业近三年承担过不少于一项单项合同额 5000 万元以上的同类市政工程，业绩佐证材料包括中标通知书、合同、竣工验收证明及招标官网中标公示截图，形成完整四件套。",
        problem: { issueId: "pi2", highlight: "同类市政工程" },
      },
      { id: "perf-p2", text: "城东快速路改造工程项目为本企业 2024 年 6 月承接，合同金额 6,320 万元，已于 2025 年 4 月竣工验收合格。" },
    ],
  },
  {
    id: "sec-tech-1",
    heading: "第二部分 技术标",
    level: 1,
    paragraphs: [
      { id: "tech-cover", text: "本部分针对本项目需求编制，涵盖项目理解、总体方案、实施计划与质量保障等全部评审维度。" },
    ],
  },
  {
    id: "sec-understand",
    heading: "1.1 项目理解与需求分析",
    level: 2,
    paragraphs: [
      {
        id: "und-p1",
        text: "结合本项目城区段软土地基、全年有效工期 180 天及交通导改约束，我方采用分段快速成桩结合同步注浆工艺，确保关键线路按期推进。",
        problem: { issueId: "pi5", highlight: "分段快速成桩结合同步注浆工艺" },
      },
      { id: "und-p2", text: "本项目核心需求可归纳为：数据融合、智能决策、安全合规三大要点，我方将据此组织方案设计。" },
    ],
  },
  {
    id: "sec-tech",
    heading: "2.1.2 施工工艺与质量目标",
    level: 2,
    paragraphs: [
      {
        id: "tech-p1",
        text: "本工程质量目标为一次验收合格率 100%，分部分项优良率不低于 92%，杜绝空话套话，以可量化指标响应招标要求。",
        problem: { issueId: "pi4", highlight: "杜绝空话套话" },
      },
      { id: "tech-p2", text: "通过样板引路、过程三检与工序交接检制度，实现质量目标全过程受控。" },
    ],
  },
  {
    id: "sec-outline",
    heading: "目录",
    level: 1,
    paragraphs: [
      {
        id: "toc-p1",
        text: "第 5 章 商务报价与成本分析 ………………… 56\n第 6 章 售后服务与质量保障 …………… 68",
        problem: { issueId: "pi6", highlight: "56" },
      },
      { id: "toc-p2", text: "目录由域代码自动生成，页码与正文一致。" },
    ],
  },
];

export const bidVersions: BidVersion[] = [
  { id: "v3", label: "V3", time: "2026-08-17 13:20", author: "王建军", note: "预审后第二轮修改：补齐业绩四件套与财务说明", wordCount: 12840 },
  { id: "v2", label: "V2", time: "2026-08-15 18:05", author: "王建军", note: "预审后第一轮修改：补充投标有效期承诺", wordCount: 12110 },
  { id: "v1", label: "V1", time: "2026-08-12 10:00", author: "AI 撰写引擎", note: "AI 初稿，基于招标解析与大纲生成", wordCount: 10860 },
];

export const bidVersionsNext = (): BidVersion[] => {
  const now = new Date();
  const time = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")} ${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  return [{ id: "v-new", label: "草稿", time, author: "陈立群", note: "当前编辑中的最新版本", wordCount: 0 }, ...bidVersions];
};