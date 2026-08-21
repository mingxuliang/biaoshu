// 第三步：目录生成 — 树形目录 + 编写思路（演示数据）
// 知识库引用（KnowledgeRef）已改为真实后端接入，类型定义迁移至 @/lib/api。

export interface LinkedRule {
  ruleId: string;
  dimension: string;
  detail: string;
  weight: number;
  source: string; // 如 "第二章 1.4.1"
}

export interface PlanNode {
  id: string;
  num: string;
  title: string;
  idea: string; // 当前编写思路
  aiIdea: string; // AI 优化建议
  optimized: boolean;
  weight: number; // 关联评分点权重
  parentId: string | null;
  expanded: boolean;
  linkedRules: LinkedRule[]; // 关联的招标解析规则
}

/** 目录树初始数据 */
export const planNodes: PlanNode[] = [
  {
    id: "p-01",
    num: "1",
    title: "项目理解与需求分析",
    idea: "结合招标文件第一章与采购需求，阐述对本项目的理解、建设目标与需求梳理，回应「项目理解」评分点。",
    aiIdea: "围绕招标人企业培训业务痛点与 17 项功能需求（F-01~F-17），分层梳理建设背景、目标、范围，量化 5500+ 学员、800+ 课程规模，用「理解-目标-落地」三段式呼应评分点。",
    optimized: true,
    weight: 10,
    parentId: null,
    expanded: true,
    linkedRules: [
      { ruleId: "sr1", dimension: "技术方案", detail: "施工总体部署与项目理解，组织机构与资源配置合理性", weight: 30, source: "第三章 评标办法 3.1" },
      { ruleId: "basic-1", dimension: "基本信息", detail: "项目概况、建设背景与需求梳理", weight: 5, source: "第一章 1.1" },
    ],
  },
  {
    id: "p-02",
    num: "2",
    title: "总体技术方案",
    idea: "概述系统总体架构、技术选型与设计原则，形成全案骨架。",
    aiIdea: "提出「一个平台、双层中台、三层闭环」总体思路，明确微服务 + 本地化部署架构，标注云边协同、高可用与安全边界，紧扣架构评分项。",
    optimized: false,
    weight: 20,
    parentId: null,
    expanded: true,
    linkedRules: [
      { ruleId: "sr1", dimension: "技术方案", detail: "系统架构与本地化部署方案完整性", weight: 20, source: "第三章 评标办法 3.2" },
      { ruleId: "sr2", dimension: "技术方案", detail: "重难点分析及针对性措施，关键工序施工工艺与技术保障", weight: 15, source: "第三章 评标办法 3.3" },
    ],
  },
  {
    id: "p-02-1",
    num: "2.1",
    title: "系统架构设计",
    idea: "描述应用、数据、中间件与部署架构分层设计。",
    aiIdea: "给出四层架构图式描述（感知-服务-数据-应用），补充 5500+ 并发、10 年数据保存的容量设计，与 F-15 性能需求对齐。",
    optimized: false,
    weight: 12,
    parentId: "p-02",
    expanded: false,
    linkedRules: [
      { ruleId: "sr1", dimension: "技术方案", detail: "系统架构分层设计与容量规划", weight: 10, source: "第三章 评标办法 3.2.1" },
      { ruleId: "review-tech-1", dimension: "评审要求", detail: "部署架构（应用服务、数据库、文件存储、中间件、消息、接口、备份、安全边界）", weight: 8, source: "第三章 3.2.2" },
    ],
  },
  {
    id: "p-02-2",
    num: "2.2",
    title: "关键技术路线",
    idea: "说明数字孪生、时序分析、智能诊断等关键技术路线。",
    aiIdea: "逐条列出数字孪生建模、视频防作弊（F-16）、手写签名（F-13）、二维码签到（F-12）等关键技术实现路径，标注成熟度与落地案例。",
    optimized: false,
    weight: 8,
    parentId: "p-02",
    expanded: false,
    linkedRules: [
      { ruleId: "sr2", dimension: "技术方案", detail: "关键技术路线与实现路径", weight: 8, source: "第三章 评标办法 3.3.1" },
      { ruleId: "review-tech-2", dimension: "评审要求", detail: "系统集成与接口方案（四类对接系统接口方式、字段范围、触发机制）", weight: 6, source: "第三章 3.3.2" },
    ],
  },
  {
    id: "p-03",
    num: "3",
    title: "实施方案与进度计划",
    idea: "编制实施阶段、里程碑与资源投入计划。",
    aiIdea: "拆解为需求确认-开发-测试-部署-试运行-验收六阶段，180 日历天 + 90 天试运行，输出甘特式里程碑表，覆盖实施与交付评分项。",
    optimized: false,
    weight: 15,
    parentId: null,
    expanded: true,
    linkedRules: [
      { ruleId: "sr5", dimension: "进度工期", detail: "进度计划编制合理性、里程碑节点与保障措施", weight: 15, source: "第三章 评标办法 3.5" },
      { ruleId: "review-service-1", dimension: "评审要求", detail: "实施与交付服务（完整实施计划、里程碑与资源投入）", weight: 10, source: "第三章 3.4.1" },
    ],
  },
  {
    id: "p-04",
    num: "4",
    title: "商务报价与成本分析",
    idea: "编制报价构成、成本分析与付款方式响应。",
    aiIdea: "按人力/授权/硬件/差旅/管理费列成本明细，报价对标 480 万控制价与 3:4:3 付款节点，提供成本控制措施与性价比论证。",
    optimized: false,
    weight: 25,
    parentId: null,
    expanded: false,
    linkedRules: [
      { ruleId: "sr3", dimension: "商务标", detail: "报价合理性、成本控制措施与报价组成完整性", weight: 20, source: "第三章 评标办法 3.6" },
      { ruleId: "business-commerce-1", dimension: "商务评分", detail: "商务条款响应（付款方式、质保期、履约保证金接受度）", weight: 10, source: "第三章 3.6.1" },
      { ruleId: "business-price-1", dimension: "商务评分", detail: "报价评分细则（基准价偏离扣分、成本构成分析）", weight: 15, source: "第三章 3.6.2" },
    ],
  },
  {
    id: "p-05",
    num: "5",
    title: "售后服务与质量保障",
    idea: "编写质保、响应机制、培训与应急预案。",
    aiIdea: "覆盖 36 个月质保、7×24 响应、重大故障 4 小时到场、季度巡检，结合售后承诺与质量体系评分项逐条响应。",
    optimized: false,
    weight: 10,
    parentId: null,
    expanded: false,
    linkedRules: [
      { ruleId: "review-after-1", dimension: "评审要求", detail: "质保与运维服务（三年质保、7×24响应、重大故障4小时到场）", weight: 10, source: "第三章 评标办法 3.4.3" },
      { ruleId: "review-service-2", dimension: "评审要求", detail: "培训与上线服务（分层培训方案、试运行不少于90天）", weight: 8, source: "第三章 3.4.2" },
    ],
  },
  {
    id: "p-06",
    num: "6",
    title: "企业资质与业绩证明",
    idea: "汇总企业资质、人员证书与类似业绩。",
    aiIdea: "整理软件/高新企业证书、ISO 双体系、PMP 项目经理，引用 ≥200 万同类业绩（近三年 ≥2 个），附合同与验收证明编号。",
    optimized: false,
    weight: 0,
    parentId: null,
    expanded: false,
    linkedRules: [
      { ruleId: "sr4", dimension: "资格业绩", detail: "类似工程业绩、人员资质与履约能力证明", weight: 15, source: "第三章 评标办法 2.1" },
      { ruleId: "qual-applicant-1", dimension: "资格要求", detail: "资质与业绩要求（软件企业/高新企业证书、ISO认证、≥200万业绩）", weight: 10, source: "第二章 1.4.1" },
    ],
  },
];

/** 项目概述数据 */
export interface ProjectOverview {
  name: string;
  code: string;
  budget: string;
  location: string;
  tenderer: string;
  agency: string;
  period: string;
  warranty: string;
  scope: string;
  keyDates: { label: string; date: string }[];
}

export const projectOverview: ProjectOverview = {
  name: "企业培训管理系统建设项目（软件开发与实施服务）",
  code: "BM-PX202605001",
  budget: "人民币480万元（含税）",
  location: "广州市黄埔区科学城创新大道168号贝恩医疗总部大楼",
  tenderer: "贝恩医疗设备（广州）有限公司",
  agency: "广州鼎信招标代理有限公司",
  period: "系统上线：合同签订后180日历天 · 试运行：不少于90日历天 · 质保：三年",
  warranty: "自验收合格之日起三年，含免费小版本升级",
  scope: "企业培训管理系统软件的设计、开发、部署、培训、验收及三年运维服务。包括：在线学习平台（PC端、移动端APP、微信小程序）、考试与测评系统、培训计划与资源管理、学员档案与证书管理、数据分析与报表、系统集成（OA/企业微信/人事/访客）及三年运维。",
  keyDates: [
    { label: "获取招标文件", date: "2026年05月20日 — 05月26日" },
    { label: "投标截止", date: "2026年06月15日 09:30" },
    { label: "开标时间", date: "2026年06月15日 10:00" },
    { label: "评标周期", date: "5个工作日" },
    { label: "中标通知", date: "评标结束后7日内" },
    { label: "合同签订", date: "中标通知书发出后15日内" },
  ],
};
