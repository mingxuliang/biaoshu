// 项目二级详情页 · 全部文档目录（演示数据）
// 按四大类分组：招标文件 / 招标解析 / 投标文件技术标 / 商务标文件

export type DocGroupKey = "tender" | "analysis" | "technical" | "commercial";

export interface GroupDoc {
  id: string;
  name: string;
  ext: "Word" | "PDF" | "Excel";
  size: string;
  updated: string;
  pages?: number;
  status: string;
  desc: string;
  content: string[];
}

export interface DocGroup {
  key: DocGroupKey;
  label: string;
  icon: string;
  desc: string;
  docs: GroupDoc[];
}

export const docGroupMeta: Record<DocGroupKey, { icon: string; color: string; bar: string }> = {
  tender: { icon: "ri-file-list-3-line", color: "bg-primary-50 text-primary-500", bar: "from-primary-500 to-primary-400" },
  analysis: { icon: "ri-file-settings-line", color: "bg-accent-50 text-accent-500", bar: "from-accent-500 to-accent-400" },
  technical: { icon: "ri-file-text-line", color: "bg-secondary-50 text-secondary-600", bar: "from-secondary-400 to-secondary-300" },
  commercial: { icon: "ri-calculator-line", color: "bg-primary-50 text-primary-600", bar: "from-primary-400 to-primary-300" },
};

export const projectDocGroups: DocGroup[] = [
  {
    key: "tender",
    label: "招标文件",
    icon: "ri-file-list-3-line",
    desc: "采购人发布的全套招标文件，AI 已完成解析并提取评分点与废标条款",
    docs: [
      {
        id: "g-t1",
        name: "CG-2026-1022_招标文件（正文）.docx",
        ext: "Word",
        size: "12.8 MB",
        updated: "08-10",
        pages: 286,
        status: "已解析",
        desc: "招标文件正文，含投标人须知、合同条款、技术需求书与评分办法。",
        content: [
          "第一章 招标公告：本项目建设内容、资金来源、投标人资格要求与获取招标文件的方式。",
          "第二章 投标人须知：投标有效期（90日历天）、密封装订要求、澄清答疑规则与废标情形。",
          "第三章 评标办法：综合评分法，技术权重35%、商务报价25%、资格业绩15%、进度工期15%、演示答辩10%。",
          "第四章 技术需求书：涵盖系统架构、功能模块、接口与本地化部署等全部硬性需求项。",
        ],
      },
      {
        id: "g-t2",
        name: "CG-2026-1022_评标办法及评分细则.pdf",
        ext: "PDF",
        size: "2.4 MB",
        updated: "08-10",
        pages: 18,
        status: "已解析",
        desc: "评标委员会评审依据，逐项列明各评分维度的分值、权重与评分标准。",
        content: [
          "技术方案（30分）：总体部署、项目理解、组织机构与资源配置合理性。",
          "技术方案（20分）：重难点分析及针对性措施、关键工序施工工艺与技术保障。",
          "商务报价（20分）：报价合理性、成本控制措施与报价组成完整性。",
          "资格业绩（15分）：类似工程业绩、人员资质与履约能力证明。",
        ],
      },
      {
        id: "g-t3",
        name: "CG-2026-1022_图纸清单及工程量表.xlsx",
        ext: "Excel",
        size: "8.6 MB",
        updated: "08-11",
        pages: 42,
        status: "已解析",
        desc: "工程量清单与图纸索引，供技术标编制工程量与造价测算参考。",
        content: [
          "图纸清单索引：各专业图纸目录、图号与比例尺对照。",
          "工程量清单：分部工程数量、计量单位与综合单价列示。",
          "造价说明：暂估价、暂列金额与甲供材料范围说明。",
        ],
      },
      {
        id: "g-t4",
        name: "CG-2026-1022_答疑澄清（第1号）.docx",
        ext: "Word",
        size: "0.6 MB",
        updated: "08-14",
        pages: 6,
        status: "已解析",
        desc: "对投标人疑问的统一澄清答复，含对若干条款的补充说明。",
        content: [
          "澄清一：明确本工程投标保证金为人民币9万元，须在投标截止前到账。",
          "澄清二：补充说明暗标评审规则，技术标不得出现可识别投标人身份的标记。",
          "澄清三：对图纸清单中部分计量单位的换算口径作出统一解释。",
        ],
      },
    ],
  },
  {
    key: "analysis",
    label: "招标解析",
    icon: "ri-file-settings-line",
    desc: "AI 对招标文件的深度解析报告，提炼评审要点、风险条款与应标策略",
    docs: [
      {
        id: "g-a1",
        name: "AI 招标解析报告_基本信息与资格要求.pdf",
        ext: "PDF",
        size: "1.2 MB",
        updated: "08-12",
        pages: 24,
        status: "已完成",
        desc: "解析招标人信息、项目概况、资质与业绩门槛，并给出资格性审查对照清单。",
        content: [
          "招标人/代理机构：贝恩医疗设备（广州）有限公司，代理为广州鼎信招标代理有限公司。",
          "项目概况：企业培训管理系统建设项目，预算上限480万元，资金来源已落实。",
          "资格要求：注册资本≥500万、软件企业/高新证书、ISO 9001与27001认证在有效期内。",
          "业绩要求：近三年至少2个单项合同额≥200万元的同类培训系统项目。",
        ],
      },
      {
        id: "g-a2",
        name: "AI 招标解析报告_评审要求与废标项.pdf",
        ext: "PDF",
        size: "1.1 MB",
        updated: "08-12",
        pages: 20,
        status: "已完成",
        desc: "逐项拆解技术/服务/售后评审细则与全部废标条款，标注响应状态。",
        content: [
          "技术评审：功能响应、系统架构、系统集成三大维度共35分。",
          "服务评审：实施交付、培训上线、售后运维三大维度共15分。",
          "废标条款：报价超预算、技术标可识别身份、资格证明缺失等6项高风险情形。",
          "风险提示：质保期三年且含免费小版本升级，运维成本需充分计入报价。",
        ],
      },
      {
        id: "g-a3",
        name: "对标清单_评分点与响应状态.xlsx",
        ext: "Excel",
        size: "0.8 MB",
        updated: "08-13",
        pages: 16,
        status: "已完成",
        desc: "42 项评分点与响应覆盖状态清单，支撑技术标与商务标的针对性编制。",
        content: [
          "技术方案：共8个评分点，其中4个已覆盖、3个部分覆盖、1个未覆盖。",
          "商务报价：报价合理性、成本控制、付款方式接受度共3个评分点。",
          "资格业绩：类似业绩、人员资质、财务状况共3个评分点。",
          "建议：优先补齐「未覆盖」评分点，争取技术标满分区间。",
        ],
      },
    ],
  },
  {
    key: "technical",
    label: "投标文件技术标",
    icon: "ri-file-text-line",
    desc: "AI 撰写并人工修订的技术方案书，含总体方案、实施计划与质量保障",
    docs: [
      {
        id: "g-c1",
        name: "技术标_总体方案V3.2.docx",
        ext: "Word",
        size: "6.2 MB",
        updated: "08-10",
        pages: 96,
        status: "已完成",
        desc: "技术标正文主体，涵盖项目理解、总体架构、分项实施与质量保障。",
        content: [
          "第一章 项目理解与需求分析：结合软土地基与180天有效工期的针对性理解。",
          "第二章 总体技术方案：系统架构、数据融合、智能决策与安全合规四大板块。",
          "第三章 实施计划：里程碑节点、资源配置与关键线路保障措施。",
          "第四章 质量保障：一次验收合格率100%、优良率不低于92%的可量化目标。",
        ],
      },
      {
        id: "g-c2",
        name: "技术标_施工组织与进度计划.docx",
        ext: "Word",
        size: "3.5 MB",
        updated: "08-09",
        pages: 48,
        status: "已完成",
        desc: "施工组织设计、进度计划横道图与网络图，含关键工序工艺说明。",
        content: [
          "施工总体部署：分段快速成桩结合同步注浆工艺，确保关键线路按期推进。",
          "进度计划：采用横道图与网络图双形式，标注各里程碑节点与关键路径。",
          "资源配置：投入主要机械与劳动力计划表，含高峰与低谷期配置。",
          "季节性施工：雨季、高温季专项施工保障措施。",
        ],
      },
      {
        id: "g-c3",
        name: "技术标_售后服务承诺书.docx",
        ext: "Word",
        size: "1.8 MB",
        updated: "08-11",
        pages: 12,
        status: "已完成",
        desc: "质保期36个月、7×24小时响应机制与应急预案说明。",
        content: [
          "服务承诺：免费质保期36个月，质保期内免费修复缺陷与升级小版本。",
          "响应机制：重大故障30分钟响应、2小时到场；一般故障24小时内解决。",
          "应急预案：针对断电、断网、宕机等场景制定专项预案并每季度演练。",
          "培训转移：不少于40人次的分层培训与完整操作手册交付。",
        ],
      },
    ],
  },
  {
    key: "commercial",
    label: "商务标文件",
    icon: "ri-calculator-line",
    desc: "报价明细、商务条款响应与资格证明文件，支撑商务评分与合规审查",
    docs: [
      {
        id: "g-b1",
        name: "商务标_报价明细表V2.1.xlsx",
        ext: "Excel",
        size: "1.8 MB",
        updated: "08-12",
        pages: 14,
        status: "修订中",
        desc: "分项报价、成本构成与付款方式响应表，含开标一览表。",
        content: [
          "开标一览表：投标总价与主要分项报价汇总。",
          "分项报价表：人力、软件授权、硬件、差旅、管理费等成本明细。",
          "成本控制措施：阐述成本构成与合理性，支撑报价评分项。",
          "付款方式响应：接受招标文件3:4:3付款比例。",
        ],
      },
      {
        id: "g-b2",
        name: "商务标_商务条款响应表.docx",
        ext: "Word",
        size: "0.9 MB",
        updated: "08-12",
        pages: 10,
        status: "已完成",
        desc: "对质保期、履约保证金、付款节点等商务条款的逐项响应。",
        content: [
          "质保期：承诺36个月，优于招标要求。",
          "履约保证金：同意合同金额5%的履约保证金要求。",
          "投标有效期：承诺90日历天，符合招标文件要求。",
          "知识产权：明确项目成果与数据归属边界。",
        ],
      },
      {
        id: "g-b3",
        name: "商务标_资格证明文件.pdf",
        ext: "PDF",
        size: "9.4 MB",
        updated: "08-05",
        pages: 68,
        status: "已完成",
        desc: "企业资质证书、ISO体系认证、近三年财务报表与同类业绩证明。",
        content: [
          "企业资质：营业执照、软件企业/高新技术企业证书。",
          "体系认证：ISO 9001质量管理与ISO 27001信息安全管理体系认证。",
          "财务报表：近三年经审计财务报表，资产负债率84.6%符合要求。",
          "同类业绩：2项单项合同额≥200万元的同类项目合同及验收证明。",
        ],
      },
    ],
  },
];