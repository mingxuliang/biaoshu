// M05 标书撰写工作台 · 四步式推进（演示数据）

// 第一步：大模型配置
export interface ModelOption {
  id: string;
  name: string;
  provider: string;
  desc: string;
  ctx: string;
  speed: string;
  tag?: string;
}

export const modelOptions: ModelOption[] = [
  { id: "bidllm", name: "BidLLM-标书专用", provider: "自研", desc: "专为招投标场景深度训练，懂评分标准、懂暗标规则、懂格式规范", ctx: "512K", speed: "快", tag: "自研" },
  { id: "deepseek", name: "DeepSeek-V4-Pro", provider: "深度求索", desc: "长文档结构化输出稳定，对标评分点逐项展开能力强，成本均衡", ctx: "256K", speed: "快", tag: "推荐" },
  { id: "kimi", name: "Kimi 3", provider: "月之暗面", desc: "长上下文理解与行业知识扎实，中文标书写作措辞专业", ctx: "256K", speed: "中" },
  { id: "qwen", name: "通义千问 Qwen-Max", provider: "阿里云", desc: "工程与规范条文检索能力强，企业文档写作稳健", ctx: "128K", speed: "中" },
  { id: "glm", name: "智谱 GLM-4-Plus", provider: "智谱AI", desc: "中文标书写作能力突出，行业知识扎实", ctx: "128K", speed: "中" },
  { id: "doubao", name: "豆包-Doubao-Pro", provider: "字节跳动", desc: "生成速度快，适合批量章节续写", ctx: "256K", speed: "快" },
  { id: "minimax", name: "MiniMax-M2", provider: "MiniMax", desc: "长文表达流畅，逻辑结构化清晰，性价比高", ctx: "200K", speed: "快" },
  { id: "siliconflow", name: "硅基流动 SiliconFlow", provider: "硅基流动", desc: "聚合多模型池，稳定 API 与低延迟推理", ctx: "128K", speed: "快" },
];

// 第一步：页数设置（滑块刻度）
export const pageSliderTicks = [0, 40, 80, 120, 160, 200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000];

export interface PageConfig {
  total: number; // 目标总页数
  cover: number;
  body: number;
  appendix: number;
}

export const defaultPage: PageConfig = {
  total: 200,
  cover: 6,
  body: 140,
  appendix: 30,
};

// 第一步：排版规则配置
export interface LayoutConfig {
  margins: { top: number; bottom: number; left: number; right: number }; // cm
  fontSize: string; // 正文字号
  lineSpacing: string; // 正文行间距
}

export const defaultLayout: LayoutConfig = {
  margins: { top: 2, bottom: 2, left: 2, right: 2 },
  fontSize: "小四",
  lineSpacing: "1.5倍行距",
};

export const layoutFontSizes = ["小三", "小四", "四号", "三号"];
export const layoutLineSpacings = ["1.5倍行距", "2倍行距", "固定值28磅", "固定值30磅"];

// 第一步：配图设置
export interface ImageConfig {
  normal: string; // 普通配图方式
  arch: string; // 架构图方式
  aiStyle: string; // AI 生图风格
}

export const defaultImage: ImageConfig = {
  normal: "互联网搜图",
  arch: "图库配图",
  aiStyle: "专业商务风",
};

export const normalImageOptions = ["互联网搜图", "图库配图", "AI生图"];
export const archImageOptions = ["图库配图", "AI生成架构图"];
export const aiImageStyles = ["专业商务风", "简约扁平风", "科技渐变风", "写实摄影风"];

// 第一步：撰写风格配置
export interface StyleConfig {
  tone: string; // 行文基调
  length: string; // 篇幅档位
  firmName: string; // 企业署名（暗标/去标识）
  strictness: string; // 格式规范
}

export const defaultStyle: StyleConfig = {
  tone: "专业务实 · 突出量化指标",
  length: "详细版（对标评分点逐项展开）",
  firmName: "我方投标企业（自动去标识）",
  strictness: "严格遵循招标文件格式要求",
};

// 第二步：解析来源
export type InterpretSource = "reuse" | "upload";

// 第三步：目录章节 + 编写思路
export interface TocChapter {
  id: string;
  num: string;
  title: string;
  idea: string; // 当前编写思路
  aiIdea: string; // AI 优化建议
  optimized: boolean;
  weight?: number; // 关联评分点权重
}

export const defaultToc: TocChapter[] = [
  {
    id: "toc-01",
    num: "1",
    title: "项目理解与需求分析",
    idea: "结合招标文件第一章与采购需求，阐述对本项目的理解、建设目标与需求梳理，回应「项目理解」评分点。",
    aiIdea: "围绕招标人企业培训业务痛点与 17 项功能需求（F-01~F-17），分层梳理建设背景、目标、范围，量化 5500+ 学员、800+ 课程规模，用「理解-目标-落地」三段式呼应评分点。",
    optimized: true,
    weight: 10,
  },
  {
    id: "toc-02",
    num: "2",
    title: "总体技术方案",
    idea: "概述系统总体架构、技术选型与设计原则，形成全案骨架。",
    aiIdea: "提出「一个平台、双层中台、三层闭环」总体思路，明确微服务 + 本地化部署架构，标注云边协同、高可用与安全边界，紧扣架构评分项。",
    optimized: false,
    weight: 20,
  },
  {
    id: "toc-03",
    num: "2.1",
    title: "系统架构设计",
    idea: "描述应用、数据、中间件与部署架构分层设计。",
    aiIdea: "给出四层架构图式描述（感知-服务-数据-应用），补充 5500+ 并发、10 年数据保存的容量设计，与 F-15 性能需求对齐。",
    optimized: false,
    weight: 12,
  },
  {
    id: "toc-04",
    num: "2.2",
    title: "关键技术路线",
    idea: "说明数字孪生、时序分析、智能诊断等关键技术路线。",
    aiIdea: "逐条列出数字孪生建模、视频防作弊（F-16）、手写签名（F-13）、二维码签到（F-12）等关键技术实现路径，标注成熟度与落地案例。",
    optimized: false,
    weight: 8,
  },
  {
    id: "toc-05",
    num: "3",
    title: "实施方案与进度计划",
    idea: "编制实施阶段、里程碑与资源投入计划。",
    aiIdea: "拆解为需求确认-开发-测试-部署-试运行-验收六阶段，180 日历天 + 90 天试运行，输出甘特式里程碑表，覆盖实施与交付评分项。",
    optimized: false,
    weight: 15,
  },
  {
    id: "toc-06",
    num: "4",
    title: "商务报价与成本分析",
    idea: "编制报价构成、成本分析与付款方式响应。",
    aiIdea: "按人力/授权/硬件/差旅/管理费列成本明细，报价对标 480 万控制价与 3:4:3 付款节点，提供成本控制措施与性价比论证。",
    optimized: false,
    weight: 25,
  },
  {
    id: "toc-07",
    num: "5",
    title: "售后服务与质量保障",
    idea: "编写质保、响应机制、培训与应急预案。",
    aiIdea: "覆盖 36 个月质保、7×24 响应、重大故障 4 小时到场、季度巡检，结合售后承诺与质量体系评分项逐条响应。",
    optimized: false,
    weight: 10,
  },
  {
    id: "toc-08",
    num: "6",
    title: "企业资质与业绩证明",
    idea: "汇总企业资质、人员证书与类似业绩。",
    aiIdea: "整理软件/高新企业证书、ISO 双体系、PMP 项目经理，引用 ≥200 万同类业绩（近三年 ≥2 个），附合同与验收证明编号。",
    optimized: false,
    weight: 0,
  },
];

// 第三步：AI 优化提示样例
export const aiOptimizeTips = [
  "已对标 9 大解析维度，自动绑定章节与评分点权重",
  "重难点章节（技术方案/报价）已补充量化描述",
  "已按「明暗标」规则生成章节标题命名规范",
];