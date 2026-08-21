export type ChapterStatus = "待生成" | "生成中" | "已完成";

export interface ChapterNode {
  id: string;
  num: string;
  title: string;
  status: ChapterStatus;
  words: number;
  aiRounds: number;
  parentId: string | null;
  expanded: boolean;
}

/** 扁平章节列表 — 含父子关系 */
export const outlineNodes: ChapterNode[] = [
  // 第一章
  { id: "c-01", num: "一", title: "采购需求与商务要求", status: "已完成", words: 3200, aiRounds: 3, parentId: null, expanded: true },
  { id: "c-01-1", num: "（一）", title: "核心采购内容", status: "已完成", words: 1800, aiRounds: 2, parentId: "c-01", expanded: false },
  { id: "c-01-2", num: "（二）", title: "系统功能需求范围", status: "已完成", words: 1400, aiRounds: 1, parentId: "c-01", expanded: false },
  { id: "c-01-3", num: "（三）", title: "技术要求与标准参数", status: "已完成", words: 0, aiRounds: 0, parentId: "c-01", expanded: false },
  // 第二章
  { id: "c-02", num: "二", title: "组织与账号管理", status: "已完成", words: 2600, aiRounds: 2, parentId: null, expanded: true },
  { id: "c-02-1", num: "（一）", title: "组织管理", status: "已完成", words: 1200, aiRounds: 1, parentId: "c-02", expanded: false },
  { id: "c-02-2", num: "（二）", title: "账号管理", status: "已完成", words: 800, aiRounds: 1, parentId: "c-02", expanded: false },
  { id: "c-02-3", num: "（三）", title: "角色权限", status: "已完成", words: 600, aiRounds: 0, parentId: "c-02", expanded: false },
  // 第三章
  { id: "c-03", num: "三", title: "组织管理", status: "已完成", words: 1900, aiRounds: 2, parentId: null, expanded: true },
  { id: "c-03-1", num: "（一）", title: "组织管理", status: "已完成", words: 900, aiRounds: 1, parentId: "c-03", expanded: false },
  { id: "c-03-2", num: "（二）", title: "学员角色", status: "已完成", words: 600, aiRounds: 1, parentId: "c-03", expanded: false },
  { id: "c-03-3", num: "（三）", title: "临时人员管理", status: "已完成", words: 400, aiRounds: 0, parentId: "c-03", expanded: false },
  // 第四章
  { id: "c-04", num: "四", title: "学员角色", status: "已完成", words: 1500, aiRounds: 1, parentId: null, expanded: true },
  { id: "c-04-1", num: "（一）", title: "学员角色配置", status: "已完成", words: 800, aiRounds: 1, parentId: "c-04", expanded: false },
  { id: "c-04-2", num: "（二）", title: "权限分配", status: "已完成", words: 700, aiRounds: 0, parentId: "c-04", expanded: false },
  // 第五章
  { id: "c-05", num: "五", title: "临时人员管理", status: "已完成", words: 1200, aiRounds: 1, parentId: null, expanded: true },
  { id: "c-05-1", num: "（一）", title: "临时账号管理", status: "已完成", words: 600, aiRounds: 1, parentId: "c-05", expanded: false },
  { id: "c-05-2", num: "（二）", title: "权限模型管理", status: "已完成", words: 600, aiRounds: 0, parentId: "c-05", expanded: false },
  // 第六章
  { id: "c-06", num: "六", title: "数据与报表", status: "生成中", words: 800, aiRounds: 1, parentId: null, expanded: true },
  { id: "c-06-1", num: "（一）", title: "数据采集与接口", status: "生成中", words: 400, aiRounds: 1, parentId: "c-06", expanded: false },
  { id: "c-06-2", num: "（二）", title: "统计报表", status: "待生成", words: 0, aiRounds: 0, parentId: "c-06", expanded: false },
  // 第七章 — 待生成
  { id: "c-07", num: "七", title: "培训计划管理", status: "待生成", words: 0, aiRounds: 0, parentId: null, expanded: false },
  { id: "c-08", num: "八", title: "文件文档管理", status: "待生成", words: 0, aiRounds: 0, parentId: null, expanded: false },
  { id: "c-09", num: "九", title: "服务与运维", status: "待生成", words: 0, aiRounds: 0, parentId: null, expanded: false },
];

/** 兼容旧接口的 Chapter（扁平化提取，仅用于编辑器内部） */
export interface Chapter {
  id: string;
  num: string;
  title: string;
  status: ChapterStatus;
  words: number;
  aiRounds: number;
}

/** 从树节点提取为 Chapter */
export function nodeToChapter(node: ChapterNode): Chapter {
  return {
    id: node.id,
    num: node.num,
    title: node.title,
    status: node.status,
    words: node.words,
    aiRounds: node.aiRounds,
  };
}

/** 获取所有顶层节点 */
export function getTopLevelNodes(nodes: ChapterNode[]): ChapterNode[] {
  return nodes.filter((n) => n.parentId === null);
}

/** 获取某节点的直接子节点 */
export function getChildren(nodes: ChapterNode[], parentId: string): ChapterNode[] {
  return nodes.filter((n) => n.parentId === parentId);
}

/** 判断节点是否有子节点 */
export function hasChildren(nodes: ChapterNode[], parentId: string): boolean {
  return nodes.some((n) => n.parentId === parentId);
}

/** 在视图中应显示的节点（父节点已展开） */
export function getVisibleNodes(nodes: ChapterNode[]): ChapterNode[] {
  const result: ChapterNode[] = [];
  const roots = getTopLevelNodes(nodes);
  for (const root of roots) {
    result.push(root);
    if (root.expanded) {
      const children = getChildren(nodes, root.id);
      result.push(...children);
    }
  }
  return result;
}

/** 计算某个父节点下的完成进度 */
export function getGroupProgress(nodes: ChapterNode[], parentId: string | null): number {
  const targets = parentId === null
    ? getTopLevelNodes(nodes)
    : getChildren(nodes, parentId);
  if (targets.length === 0) return 0;
  const done = targets.filter((t) => t.status === "已完成").length;
  return Math.round((done / targets.length) * 100);
}

export const editorContents: Record<string, string> = {
  "c-01":
    "## 一、采购需求与商务要求\n\n我公司将提供一系列满足本项目需求的核心采购内容，以确保企业培训管理系统的高效建设与稳定运行。具体包含以下服务：\n\n1）提供一套满足5500名以上学员使用需求的企业培训管理平台软件，具备强大的功能和良好的性能，能够适应大规模用户的并发访问和使用。\n\n2）提供本地化部署服务，依据招标人提供的部署环境或自身方案建议进行配置，提供完整的部署架构，确保系统稳定运行，并具备可扩展部署能力，以满足未来用户、课程、记录和附件规模的增长需求。\n\n3）提供系统集成服务，完成与文件管理系统、企业微信、人事系统、访客系统等4个现有系统的接口对接或提供可落地集成方案，实现数据的流通和共享，减少人工重复维护。\n\n4）提供数据迁移/初始化服务，确保组织、人员、岗位、课程、计划、记录等初始化数据的准确转移和初始化，为系统的正常运行打好基础。\n\n5）提供业务流程配置服务，根据招标人的业务需求和管理模式，对系统的业务流程进行个性化配置，实现流程的自动化和规范化。\n\n6）提供统计报表配置服务，根据不同的维度和需求，配置多样化的统计报表，为企业的培训管理决策提供数据支持。",
  "c-01-1":
    "### （一）核心采购内容\n\n本项目核心采购内容为企业培训管理平台软件及其配套实施服务，主要包括以下模块：\n\n- **培训管理平台**：支持课程管理、学员管理、考试测评、证书管理、培训计划制定与跟踪等核心功能；\n\n- **本地化部署服务**：根据招标人提供的硬件环境和网络条件，完成系统的安装、配置和调优；\n\n- **系统集成服务**：实现与现有业务系统的数据互通，减少信息孤岛；\n\n- **数据迁移服务**：将历史培训数据完整、准确地迁移到新系统中。",
  "c-01-2":
    "### （二）系统功能需求范围\n\n系统功能需求涵盖培训业务的全生命周期管理，具体范围如下：\n\n1. **课程资源管理**：支持多种类型课程（视频、文档、直播、线下）的统一管理和分类存储；\n\n2. **学员学习管理**：支持学习计划制定、学习进度跟踪、学习提醒和督学机制；\n\n3. **考试测评管理**：支持题库管理、随机组卷、在线考试、成绩统计与分析；\n\n4. **证书与资质管理**：支持培训证书模板配置、自动发证、证书查询与验证；\n\n5. **数据统计分析**：提供培训覆盖率、完成率、满意度等多维度统计报表。",
  "c-02":
    "## 二、组织与账号管理\n\n系统提供完善的组织架构管理与账号管理体系，支持多级组织架构的灵活配置，满足不同规模企业的管理需求。",
  "c-03":
    "## 三、组织管理\n\n系统组织架构支持树形结构管理，可灵活配置部门层级关系，实现人员与组织的精准关联。",
  "c-04":
    "## 四、学员角色\n\n系统内置多种学员角色模板，同时支持自定义角色配置，满足差异化的权限管理需求。",
  "c-05":
    "## 五、临时人员管理\n\n针对项目制、外包等场景，系统提供临时人员账号管理功能，支持限时账号创建与自动回收机制。",
  "c-06":
    "## 六、数据与报表\n\n系统提供全面的数据采集与报表分析能力，支持自定义报表模板和多维度数据可视化展示。",
  "c-07": "",
  "c-08": "",
  "c-09": "",
};

export const aiGeneratedSample = `## 售后服务与质量保障

### 售后服务总体承诺

我方郑重承诺，为本项目提供「7 × 24 小时」全天候售后服务保障，服务期自项目最终验收合格之日起计算，免费质保期 36 个月，质保期内因产品质量或实施原因导致的故障，由我方免费维修或更换。

### 服务响应机制

- 一般故障：2 小时内响应，24 小时内解决；
- 重大故障：30 分钟内响应，工程师 2 小时到场处理；
- 紧急故障：立即响应，远程 + 现场双通道处置，直至系统恢复运行。

### 质量保障体系

本项目建立以 ISO 9001 质量管理体系为基础的全过程质量管控机制，覆盖设计、开发、测试、部署与运维全生命周期，严格执行三级评审与质量门禁制度，确保交付物质量稳定可控。

### 培训与知识转移

我方将在试运行阶段为业主方提供不少于 40 人次的系统培训，包含管理员培训、操作人员培训与运维人员培训三个层次，并交付完整的操作手册、运维手册与培训视频资料。

### 应急预案

针对机房断电、网络中断、设备宕机等典型故障场景，我方制定专项应急预案并每季度组织一次应急演练，确保突发事件发生时系统可快速恢复，最大限度降低对运营的影响。`;