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
  {
    id: "deepseek-v4-pro",
    name: "DeepSeek 4 Pro",
    provider: "深度求索",
    desc: "长上下文推理模型，用于目录生成、章节正文与对话改写",
    ctx: "1M",
    speed: "中",
    tag: "推荐",
  },
  {
    id: "deepseek-v4-flash",
    name: "DeepSeek V4 Flash",
    provider: "深度求索",
    desc: "高吞吐撰写模型，适合快速生成目录与章节正文",
    ctx: "1M",
    speed: "快",
    tag: "已接入",
  },
  {
    id: "doubao",
    name: "豆包",
    provider: "火山引擎 · 方舟",
    desc: "豆包大模型，用于目录生成、章节正文与对话改写",
    ctx: "256K",
    speed: "快",
    tag: "已接入",
  },
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
  body: 164,
  appendix: 30,
};

// 第一步：排版规则配置
export interface LayoutConfig {
  margins: { top: number; bottom: number; left: number; right: number }; // cm
  fontSize: string; // 正文字号
  lineSpacing: string; // 正文行间距
  bodyFont?: string;
  bodySizePt?: number;
  headingFont?: string;
  headingSizePt?: number;
  headingBold?: boolean;
  indentPt?: number;
  indentChars?: number;
  hangingIndentPt?: number;
  leftIndentPt?: number;
  lineSpacingMul?: number | null;
  lineSpacingExactPt?: number | null;
  lineSpacingAtLeastPt?: number | null;
  fromTender?: boolean;
  preset?: string;
  bodyLatinFont?: string;
  justify?: boolean;
  paragraphBefore?: number;
  paragraphAfter?: number;
  headings?: Partial<Record<"h1" | "h2" | "h3" | "h4", LayoutHeading>>;
  header?: string;
  headerFont?: string;
  headerSizePt?: number;
  headerBorder?: boolean;
  headerDistanceCm?: number;
  footerFont?: string;
  footerSizePt?: number;
  footerDistanceCm?: number;
  differentFirstPage?: boolean;
  pageNumber?: "none" | "simple" | "full";
  orientation?: "portrait" | "landscape";
  cover?: {
    enabled?: boolean;
    title?: string;
    subtitle?: string;
    company?: string;
    date?: string;
    titleFont?: string;
    titleSizePt?: number;
    subtitleFont?: string;
    subtitleSizePt?: number;
    infoFont?: string;
    infoSizePt?: number;
    infoSpaceAfter?: number;
  };
  toc?: { enabled?: boolean; levels?: number };
  table?: { headerFill?: string; fontSizePt?: number; headerBold?: boolean; borderColor?: string; borderSizePt?: number };
  caption?: { font?: string; sizePt?: number; spaceAfter?: number };
}

export interface LayoutHeading {
  font?: string;
  sizePt?: number;
  bold?: boolean;
  align?: "left" | "center" | "right" | "justify";
  spaceBefore?: number;
  spaceAfter?: number;
  color?: string;
}

export const layoutFontFamilies = [
  "宋体",
  "仿宋",
  "仿宋_GB2312",
  "黑体",
  "楷体",
  "楷体_GB2312",
  "方正小标宋简体",
  "华文中宋",
  "微软雅黑",
  "等线",
  "Times New Roman",
  "Arial",
  "Calibri",
  "Cambria",
  "Courier New",
];

/** 与《自然资源…技术投标书_配图优化版V4-1》一致，也是撰写默认版式。 */
export const defaultLayout: LayoutConfig = {
  preset: "技术标标准",
  margins: { top: 3.7, bottom: 3.5, left: 2.8, right: 2.6 },
  fontSize: "小四",
  bodyFont: "仿宋",
  bodyLatinFont: "Times New Roman",
  bodySizePt: 12,
  lineSpacing: "1.5倍行距",
  lineSpacingMul: 1.5,
  indentChars: 2,
  indentPt: 24,
  justify: false,
  headingFont: "黑体",
  headings: {
    h1: { font: "黑体", sizePt: 18, bold: true, align: "left", spaceBefore: 0, spaceAfter: 0 },
    h2: { font: "黑体", sizePt: 15, bold: true, align: "left", spaceBefore: 0, spaceAfter: 0 },
    h3: { font: "黑体", sizePt: 13, bold: true, align: "left", spaceBefore: 0, spaceAfter: 0 },
    h4: { font: "黑体", sizePt: 12, bold: true, align: "left", spaceBefore: 0, spaceAfter: 0 },
  },
  pageNumber: "full",
  header: "{project}  技术投标书",
  headerFont: "仿宋",
  headerSizePt: 9,
  headerBorder: true,
  headerDistanceCm: 1.5,
  footerFont: "仿宋",
  footerSizePt: 10.5,
  footerDistanceCm: 2.0,
  differentFirstPage: true,
  cover: {
    enabled: false,
    title: "{project}",
    subtitle: "技 术 投 标 书",
    company: "投标单位：（投标人名称）",
    date: "编制日期：",
    titleFont: "方正小标宋简体",
    titleSizePt: 32,
    subtitleFont: "黑体",
    subtitleSizePt: 44,
    infoFont: "仿宋",
    infoSizePt: 16,
    infoSpaceAfter: 12,
  },
  caption: { font: "黑体", sizePt: 10.5, spaceAfter: 10 },
  table: { headerFill: "E8E8E8", fontSizePt: 10.5, headerBold: true, borderColor: "808080", borderSizePt: 0.5 },
};

export const layoutFontSizes = [
  "初号",
  "小初",
  "一号",
  "小一",
  "二号",
  "小二",
  "三号",
  "小三",
  "四号",
  "小四",
  "五号",
  "小五",
  "六号",
  "小六",
  "七号",
  "八号",
];
export const layoutLineSpacings = [
  "单倍行距",
  "1.15倍行距",
  "1.5倍行距",
  "2倍行距",
  "固定值28磅",
  "固定值30磅",
  "最小值28磅",
];
export const layoutFontNamePt: Record<string, number> = {
  初号: 42,
  小初: 36,
  一号: 26,
  小一: 24,
  二号: 22,
  小二: 18,
  三号: 16,
  小三: 15,
  四号: 14,
  小四: 12,
  五号: 10.5,
  小五: 9,
  六号: 7.5,
  小六: 6.5,
  七号: 5.5,
  八号: 5,
};

const FONT_STACK: Record<string, string> = {
  宋体: '"宋体", SimSun, serif',
  仿宋: '"仿宋", FangSong, serif',
  仿宋_GB2312: '"仿宋_GB2312", "仿宋", FangSong, serif',
  黑体: '"黑体", SimHei, sans-serif',
  楷体: '"楷体", KaiTi, serif',
  楷体_GB2312: '"楷体_GB2312", "楷体", KaiTi, serif',
  方正小标宋简体: '"方正小标宋简体", "黑体", SimHei, serif',
  华文中宋: '"华文中宋", "宋体", SimSun, serif',
  微软雅黑: '"微软雅黑", "Microsoft YaHei", sans-serif',
  等线: '"等线", DengXian, "微软雅黑", sans-serif',
  "Times New Roman": '"Times New Roman", Times, serif',
  Arial: "Arial, Helvetica, sans-serif",
  Calibri: "Calibri, Candara, sans-serif",
  Cambria: "Cambria, Georgia, serif",
  "Courier New": '"Courier New", Courier, monospace',
};

export function writerBodyFontStack(name?: string): string {
  const n = (name || "宋体").trim();
  return FONT_STACK[n] || `"${n}", serif`;
}

function headingLevel(
  layout: Partial<LayoutConfig> | null | undefined,
  key: "h1" | "h2" | "h3" | "h4",
  bodyPt: number,
  bodyFont: string,
): { font: string; size: string; weight: string } {
  const spec = layout?.headings?.[key];
  const offset = key === "h1" ? 6 : key === "h2" ? 3 : key === "h3" ? 1.5 : 0;
  const fontName = spec?.font || layout?.headingFont || (key === "h3" || key === "h4" ? bodyFont : "黑体");
  let pt = spec?.sizePt;
  if (pt == null && layout?.headingSizePt != null) {
    pt = key === "h1" ? layout.headingSizePt + 2 : key === "h2" ? layout.headingSizePt : Math.max(layout.headingSizePt - 2, bodyPt);
  }
  if (pt == null) pt = bodyPt + offset;
  return {
    font: writerBodyFontStack(fontName),
    size: `${pt}pt`,
    weight: spec?.bold === false ? "400" : "700",
  };
}

export function writerLayoutCssVars(
  layout?: Partial<LayoutConfig> | null,
  applyIndent = false,
  body?: { font?: string; sizeName?: string },
): Record<string, string> {
  const bodyFont = body?.font || layout?.bodyFont || "宋体";
  const namedPt = body?.sizeName ? layoutFontNamePt[body.sizeName] : undefined;
  const bodyPt = namedPt ?? layout?.bodySizePt ?? layoutFontNamePt[layout?.fontSize || ""] ?? 12;
  const h1 = headingLevel(layout, "h1", bodyPt, bodyFont);
  const h2 = headingLevel(layout, "h2", bodyPt, bodyFont);
  const h3 = headingLevel(layout, "h3", bodyPt, bodyFont);
  const h4 = headingLevel(layout, "h4", bodyPt, bodyFont);
  let indent = "0";
  if (applyIndent) {
    if (layout?.hangingIndentPt) indent = `-${layout.hangingIndentPt}pt`;
    else if (layout?.indentPt) indent = `${layout.indentPt}pt`;
    else if (layout?.indentChars) indent = `${layout.indentChars}em`;
    else indent = "2em";
  }
  const lineHeight = layout?.lineSpacingExactPt
    ? "normal"
    : layout?.lineSpacingAtLeastPt
      ? "normal"
      : layout?.lineSpacingMul
        ? String(layout.lineSpacingMul)
        : layout?.lineSpacing === "2倍行距"
          ? "2"
          : layout?.lineSpacing === "单倍行距"
            ? "1"
            : layout?.lineSpacing === "1.15倍行距"
              ? "1.15"
              : "1.75";
  return {
    "--writer-body-font": writerBodyFontStack(bodyFont),
    "--writer-body-size": `${bodyPt}pt`,
    "--writer-heading-font": h2.font,
    "--writer-heading-size": h2.size,
    "--writer-heading-weight": h2.weight,
    "--writer-h1-font": h1.font,
    "--writer-h1-size": h1.size,
    "--writer-h1-weight": h1.weight,
    "--writer-h2-font": h2.font,
    "--writer-h2-size": h2.size,
    "--writer-h2-weight": h2.weight,
    "--writer-h3-font": h3.font,
    "--writer-h3-size": h3.size,
    "--writer-h3-weight": h3.weight,
    "--writer-h4-font": h4.font,
    "--writer-h4-size": h4.size,
    "--writer-h4-weight": h4.weight,
    "--writer-indent": indent,
    "--writer-line-height": lineHeight,
    "--writer-left-indent": layout?.leftIndentPt ? `${layout.leftIndentPt}pt` : "0",
  };
}

// 第一步：配图设置
export interface ImageConfig {
  normal: string; // 普通配图方式
  arch: string; // 架构图方式
  aiStyle: string; // AI 生图风格
}

export const defaultImage: ImageConfig = {
  normal: "AI生图",
  arch: "AI生成架构图",
  aiStyle: "专业商务风",
};

export const normalImageOptions = ["AI生图", "本机上传"];
export const archImageOptions = ["AI生成架构图", "本机上传"];
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