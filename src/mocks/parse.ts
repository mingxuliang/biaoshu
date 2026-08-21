// M02 招标文件解析与对标清单（演示数据）

export interface TenderDoc {
  id: string;
  name: string;
  type: "招标文件" | "答疑补遗" | "图纸清单";
  format: "Word" | "PDF";
  pages: number;
  version: number;
  status: "已解析" | "解析中" | "待解析" | "高风险";
  risk?: string;
  updatedAt: string;
}

export interface ScoreRule {
  id: string;
  dimension: string;
  weight: number;
  detail: string;
  subject: boolean;
  sectionPath: string;
  responseStatus: "未覆盖" | "部分" | "已覆盖";
  isEssential: boolean;
}

export interface MustRespond {
  id: string;
  clause: string;
  original: string;
  type: "星号条款" | "废标条款" | "实质性条款";
  status: "待响应" | "已响应";
}

// 解析内容板块
export interface ParseSection {
  id: string;
  title: string;
  rows: { label: string; content: string }[];
}

// 二级分析项目
export interface ParseSubItem {
  id: string;
  label: string;
  sections: ParseSection[];
}

// 一级解析维度
export interface ParseDimension {
  key: string;
  label: string;
  completed: boolean;
  items: ParseSubItem[];
}

export const parseDimensions: ParseDimension[] = [
  {
    key: "basic",
    label: "基本信息",
    completed: true,
    items: [
      {
        id: "basic-tenderer",
        label: "招标人/代理信息",
        sections: [
          {
            id: "bt-1",
            title: "招标人与代理机构",
            rows: [
              { label: "招标人", content: "贝恩医疗设备（广州）有限公司（采购人/招标人）\n注册地址：广州市黄埔区科学城创新大道168号贝恩医疗总部大楼" },
              { label: "招标代理机构", content: "广州鼎信招标代理有限公司\n项目负责人：王慧敏\n联系电话：020-8765 4321\n联系地址：广州市天河区珠江新城华夏路16号富力盈凯广场36层" },
            ],
          },
          {
            id: "bt-2",
            title: "联系与答疑",
            rows: [
              { label: "质疑澄清渠道", content: "答疑/澄清均在投标截止前7日以书面形式发出，投标人对招标文件有异议的应在截止前10日提出；\n联系邮箱：wanghm@dingxin-cp.com" },
            ],
          },
        ],
      },
      {
        id: "basic-project",
        label: "项目信息",
        sections: [
          {
            id: "bp-1",
            title: "项目概况",
            rows: [
              { label: "项目名称", content: "企业培训管理系统建设项目（软件开发与实施服务）" },
              { label: "招标编号", content: "BM-PX202605001" },
              { label: "建设地点", content: "广州市黄埔区科学城创新大道168号贝恩医疗总部大楼" },
              { label: "预算上限", content: "人民币480万元（含税）" },
              { label: "资金来源", content: "企业自筹，已落实" },
            ],
          },
          {
            id: "bp-2",
            title: "招标范围",
            rows: [
              { label: "招标范围", content: "企业培训管理系统软件的设计、开发、部署、培训、验收及三年运维服务。\n包括：在线学习平台（PC端、移动端APP、微信小程序）、考试与测评系统、培训计划与资源管理、学员档案与证书管理、数据分析与报表、系统集成（OA/企业微信/人事/访客）及三年运维。" },
            ],
          },
        ],
      },
      {
        id: "basic-time",
        label: "关键时间/内容",
        sections: [
          {
            id: "btm-1",
            title: "关键时间节点",
            rows: [
              { label: "时间安排", content: "获取招标文件：2026年05月20日 — 05月26日\n投标截止：2026年06月15日 09:30\n开标时间：2026年06月15日 10:00\n评标周期：5个工作日\n中标通知：评标结束后7日内\n合同签订：中标通知书发出后15日内" },
            ],
          },
          {
            id: "btm-2",
            title: "履约时间",
            rows: [
              { label: "工期与质保", content: "系统上线：合同签订后180日历天\n试运行期：不少于90日历天\n质保期：自验收合格之日起三年" },
            ],
          },
        ],
      },
      {
        id: "basic-other",
        label: "其他信息",
        sections: [
          {
            id: "bo-1",
            title: "其他补充要求",
            rows: [
              { label: "踏勘与答疑", content: "不组织集中现场踏勘，投标人可自行前往；答疑澄清以书面形式统一答复。\n投标保证金：人民币9万元，须在投标截止前到账。\n履约保证金：合同金额的5%，签订合同前提交。" },
              { label: "评标方式", content: "综合评分法，满分100分，暗标评审（技术标匿名）。" },
            ],
          },
        ],
      },
      {
        id: "basic-purchase",
        label: "采购要求",
        sections: [
          {
            id: "bpu-1",
            title: "采购与交付要求",
            rows: [
              { label: "采购方式", content: "公开招标（自行委托代理机构），不接受联合体投标。\n交付要求：验收测试通过后视为交付完成，须提供完整部署文档、操作手册、培训视频及源代码。" },
              { label: "验收标准", content: "满足第四章全部功能需求项（F-01至F-17），通过招标人组织的功能测试、性能测试、安全测试及第三方测评。" },
            ],
          },
        ],
      },
    ],
  },
  {
    key: "qualification",
    label: "资格要求",
    completed: true,
    items: [
      {
        id: "qual-applicant",
        label: "申请人资格要求",
        sections: [
          {
            id: "qa-1",
            title: "资质与业绩要求",
            rows: [
              { label: "资质条件", content: "须为境内依法注册的独立法人，注册资本不低于500万元（含）；\n须具备软件企业认定证书或高新技术企业证书；\n须通过ISO 9001质量管理体系与ISO 27001信息安全管理体系认证且在有效期内。" },
              { label: "业绩要求", content: "近三年（2023年1月1日至今）承担过至少2个单项合同额不低于200万元的企业培训管理系统或E-Learning平台建设项目，须提供合同复印件及验收证明。" },
              { label: "人员要求", content: "拟派项目经理须具备PMP或信息系统项目管理师（高级）资格，且近三年担任过至少1个同类项目项目经理。" },
            ],
          },
        ],
      },
      {
        id: "qual-capacity",
        label: "资格性审查",
        sections: [
          {
            id: "qc-1",
            title: "资格性审查要点",
            rows: [
              { label: "审查内容", content: "1. 营业执照、税务登记、组织机构代码证是否有效；\n2. 资质证书（软件企业/高新企业）是否在有效期内；\n3. ISO体系认证证书是否覆盖本项目范围；\n4. 业绩合同及验收证明是否真实、齐全；\n5. 项目经理资格证明及社保证明；\n6. 是否被列入失信被执行人、重大税收违法失信主体名单。" },
              { label: "审查结果判定", content: "资格性审查不通过的投标人不得进入符合性审查及后续评审，其投标文件按无效标处理。" },
            ],
          },
        ],
      },
      {
        id: "qual-conformity",
        label: "符合性审查",
        sections: [
          {
            id: "qcf-1",
            title: "符合性审查要点",
            rows: [
              { label: "审查内容", content: "1. 投标文件是否按招标文件要求的格式、份数、签署盖章提交；\n2. 投标有效期是否满足90日历天；\n3. 报价是否超过预算上限480万元；\n4. 是否实质性响应招标文件全部技术功能需求；\n5. 是否按要求提交投标保证金；\n6. 是否存在偏离招标文件实质性条款的情形。" },
              { label: "审查结果判定", content: "符合性审查不通过的按无效标处理，且不因投标人数不足而放宽审查标准。" },
            ],
          },
        ],
      },
    ],
  },
  {
    key: "review",
    label: "评审要求",
    completed: true,
    items: [
      {
        id: "review-tech",
        label: "技术",
        sections: [
          {
            id: "rt-1",
            title: "功能响应与需求满足度",
            rows: [
              { label: "评分细则", content: "对第四章全部功能项（F-01至F-17及4.2、4.3、4.4、4.6、4.7、4.8、4.9等）逐项响应，标注「满足/部分满足/不满足」，说明实现方式、交付周期及偏差；\n未列示的视为已包含在报价和交付范围内；\n重点审查培训管理（F-07至F-11）、视频防作弊（F-16）、手写签名（F-13）、二维码签到（F-12）、审计追踪（4.9）、多语言支持（4.4）等关键场景。", },
            ],
          },
          {
            id: "rt-2",
            title: "系统架构与本地化部署",
            rows: [
              { label: "评分细则", content: "提供完整部署架构（应用服务、数据库、文件存储、中间件、消息、接口、备份、安全边界）；\n明确软硬件建议、服务器规格、第三方授权费用；\n方案须支持5500+学员、100+管理员、300+岗位、800+课程、10年数据保存及高并发场景。" },
            ],
          },
          {
            id: "rt-3",
            title: "系统集成与接口方案",
            rows: [
              { label: "评分细则", content: "针对四类对接系统（文件管理系统/OA、企业微信、人事系统、访客系统），分别说明接口方式、字段范围、触发机制、失败重试、无接口替代流程；\n提供接口文档样例及数据映射表，明确联调计划与验收标准。" },
            ],
          },
        ],
      },
      {
        id: "review-service",
        label: "服务",
        sections: [
          {
            id: "rs-1",
            title: "实施与交付服务",
            rows: [
              { label: "评分细则", content: "提供完整实施计划（需求确认、设计开发、测试、部署、试运行、验收）；\n明确项目里程碑与资源投入；\n数据迁移方案须承诺迁移后数据完整率不低于99.5%，并提供迁移报告模板。" },
            ],
          },
          {
            id: "rs-2",
            title: "培训与上线服务",
            rows: [
              { label: "评分细则", content: "提供面向管理员、讲师、学员分层培训方案，含培训计划自动分配逻辑（4.2）；\n上线后提供不少于90日历天试运行及现场支持；\n提供操作手册、视频教程与知识库。" },
            ],
          },
        ],
      },
      {
        id: "review-after",
        label: "售后",
        sections: [
          {
            id: "ra-1",
            title: "质保与运维服务",
            rows: [
              { label: "评分细则", content: "质保期三年，质保期内免费修复缺陷、免费升级小版本；\n提供7×24小时技术支持热线，重大故障4小时到场、一般故障24小时内响应；\n提供季度巡检报告与年度运维总结。" },
            ],
          },
        ],
      },
    ],
  },
  {
    key: "business",
    label: "商务评分",
    completed: true,
    items: [
      {
        id: "business-credit",
        label: "资信",
        sections: [
          {
            id: "bc-1",
            title: "资信评分要点",
            rows: [
              { label: "评分细则", content: "企业信用等级（AAA级得满分，依次递减）；\n近年诉讼与行政处罚记录情况；\n银行资信证明及财务状况（近三年经审计财务报表，资产负债率不高于85%）。" },
            ],
          },
        ],
      },
      {
        id: "business-commerce",
        label: "商务",
        sections: [
          {
            id: "bc2-1",
            title: "商务条款响应",
            rows: [
              { label: "评分细则", content: "对付款方式（3:4:3比例）、质保期、履约保证金等商务条款的接受度；\n提出更优商务方案（如延长质保、提前付款节点、提供额外增值服务）可酌情加分；\n商务条款响应表须逐项勾选响应并说明。" },
            ],
          },
        ],
      },
      {
        id: "business-price",
        label: "报价",
        sections: [
          {
            id: "bp-1",
            title: "报价评分细则",
            rows: [
              { label: "评分细则", content: "报价合理性（15分）：以有效投标报价算术平均价为基准价，报价等于基准价得满分，每偏离±1%扣0.5分；\n成本控制措施（5分）：提供详细成本构成分析表（人力、软件授权、硬件、差旅、管理费等明细）；\n付款方式接受度（5分）：接受招标文件付款方式得满分。" },
            ],
          },
        ],
      },
    ],
  },
  {
    key: "reject",
    label: "废标项",
    completed: true,
    items: [
      {
        id: "reject-base",
        label: "废标项",
        sections: [
          {
            id: "rb-1",
            title: "废标条款清单",
            rows: [
              { label: "废标情形", content: "1. 投标报价超过预算上限（480万元）；\n2. 技术标出现可识别投标人身份的标记（名称、LOGO、水印、特殊标记）；\n3. 未按要求提供全部资格证明文件；\n4. 投标有效期少于90日历天；\n5. 未按招标文件要求签字盖章；\n6. 存在串标、围标、弄虚作假等违法违规行为。" },
            ],
          },
        ],
      },
      {
        id: "reject-forbidden",
        label: "不得存在的情形",
        sections: [
          {
            id: "rf-1",
            title: "投标人不得存在的情形",
            rows: [
              { label: "负面清单", content: "1. 与本项目招标人存在利害关系可能影响招标公正性；\n2. 单位负责人为同一人或存在控股、管理关系的不同单位同时投标；\n3. 被责令停业、财产被接管或冻结；\n4. 被列入失信被执行人、重大税收违法失信主体；\n5. 投标人在投标有效期内撤销投标。" },
            ],
          },
        ],
      },
      {
        id: "reject-invalid",
        label: "否决和无效投标情形",
        sections: [
          {
            id: "ri-1",
            title: "否决与无效投标情形",
            rows: [
              { label: "无效投标情形", content: "1. 未按要求密封、装订、签字盖章的；\n2. 逾期送达或未送达指定地点的；\n3. 电子标书无法正常解密或无法读取的；\n4. 技术方案存在重大偏离，不能满足技术需求书实质性要求的；\n5. 存在明显报价异常、明显低于成本价的（须作出书面说明，说明不合理的否决）。" },
            ],
          },
        ],
      },
    ],
  },
  {
    key: "bidReq",
    label: "招标文件要求",
    completed: true,
    items: [
      { id: "req-submit", label: "响应文件提交", sections: [{ id: "rq-1", title: "响应文件提交要求", rows: [{ label: "提交要求", content: "投标截止：2026年06月15日 09:30，逾时不再受理；\n提交地点：广州鼎信招标代理有限公司开标室；\n提交方式：纸质正本1份、副本5份+电子标书加密U盘，现场当面递交；\n密封要求：正、副本分别密封并标注项目名称、编号及「正本/副本」。" }] }] },
      { id: "req-compose", label: "响应文件编制", sections: [{ id: "rq-2", title: "响应文件编制要求", rows: [{ label: "编制要求", content: "按第一卷商务部分、第二卷技术部分、第三卷资格证明文件组织装订；\n封面使用统一模板，注明项目名称、招标编号、投标人名称并盖章；\n技术标按暗标要求，不得出现任何可识别投标人身份的标记。" }] }] },
      { id: "req-seal", label: "响应文件盖章", sections: [{ id: "rq-3", title: "盖章与签署要求", rows: [{ label: "盖章要求", content: "投标文件正本须加盖投标人公章；\n法定代表人签字处须由法定代表人或其授权代表签字并盖章；\n授权代表须附法定代表人授权书原件；\n骑缝章须覆盖全部页边，缺章或缺签名的按无效标处理。" }] }] },
      { id: "req-encrypt", label: "响应文件加密、上传", sections: [{ id: "rq-4", title: "加密与上传要求", rows: [{ label: "加密上传", content: "电子标书须加密后存入U盘随纸质文件一同提交；\n文件格式：docx与加密PDF双格式，PDF须与纸质版完全一致；\n开标现场由工作人员统一解密，无法解密或读取失败的按无效标处理。" }] }] },
      { id: "req-mustsubmit", label: "应标需提交文件", sections: [{ id: "rq-5", title: "应标需提交文件清单", rows: [{ label: "文件清单", content: "1. 投标函及投标函附录；\n2. 法定代表人身份证明及授权委托书；\n3. 开标一览表（报价表）；\n4. 分项报价表；\n5. 商务条款响应表；\n6. 技术方案书；\n7. 项目实施计划与团队配置表；\n8. 售后服务承诺书；\n9. 培训方案；\n10. 演示方案及视频；\n11. 资格证明文件全套；\n12. 投标保证金缴纳凭证。" }] }] },
      { id: "req-qualifyfiles", label: "资格证明文件", sections: [{ id: "rq-6", title: "资格证明文件", rows: [{ label: "资格证明", content: "营业执照副本、税务登记证、组织机构代码证（或三证合一）；\n软件企业/高新技术企业证书；\nISO 9001与ISO 27001认证证书；\n近三年经审计财务报表；\n类似业绩合同复印件及验收证明；\n项目经理资质证书及社保证明；\n信用中国查询截图。" }] }] },
      { id: "req-invalid", label: "响应无效情形", sections: [{ id: "rq-7", title: "响应无效情形", rows: [{ label: "无效情形", content: "1. 报价超预算上限；\n2. 技术标可识别投标人身份；\n3. 资格证明文件缺失或不满足要求；\n4. 未实质性响应技术功能需求；\n5. 投标有效期不足；\n6. 未按格式签署盖章；\n7. 未缴纳投标保证金。" }] }] },
      { id: "req-format", label: "响应文件格式与签署要求", sections: [{ id: "rq-8", title: "格式与签署要求", rows: [{ label: "格式要求", content: "A4打印、左侧装订、统一封面模板；\n正文宋体小四、行距1.5倍，各级标题用黑体规范排版；\n全文连续页码，目录自动生成并与正文页码一致；\n签字盖章齐全，法定代表人签字处不得代签或漏签。" }] }] },
      { id: "req-reviewprocess", label: "评审过程中的响应文件处理", sections: [{ id: "rq-9", title: "评审过程文件处理", rows: [{ label: "处理要求", content: "评标委员会可要求投标人对投标文件中含义不明确的内容作书面澄清或说明，不得改变实质性内容；\n澄清文件须加盖公章，作为投标文件的组成部分；\n评标过程严格保密，投标人不得干扰评审。" }] }] },
      { id: "req-structure", label: "投标文件组成和内容", sections: [{ id: "rq-10", title: "投标文件组成和内容", rows: [{ label: "组成内容", content: "商务标：投标函、授权书、开标一览表、分项报价表、商务条款响应表、资格证明文件；\n技术标：技术方案书、实施计划、团队配置、售后承诺、培训方案、演示方案；\n须按招标文件目录顺序编排并编制目录索引。" }] }] },
      { id: "req-formatrule", label: "格式要求", sections: [{ id: "rq-11", title: "格式要求", rows: [{ label: "格式要求", content: "全篇使用标准打印字体，禁止手写、涂改；\n报价表金额大小写须一致，不一致以大写为准；\n表格与图示清晰可辨，涉及签署处须盖章。" }] }] },
      { id: "req-delivery", label: "递交方式及时间", sections: [{ id: "rq-12", title: "递交方式及时间", rows: [{ label: "递交要求", content: "仅接受现场当面递交，不接受邮寄、快递、电子邮件或传真；\n递交时间以开标室现场签到为准，逾期不候；\n未按指定地点或方式递交的，按无效标处理。" }] }] },
      { id: "req-attachment", label: "已约定附件", sections: [{ id: "rq-13", title: "已约定附件", rows: [{ label: "附件清单", content: "附件一：投标函及投标函附录格式；\n附件二：开标一览表格式；\n附件三：分项报价表格式；\n附件四：商务条款响应表格式；\n附件五：法定代表人授权委托书格式；\n附件六：技术方案书框架及评分细则；\n附件七：售后服务承诺书模板；\n附件八：合同范本（不可偏离条款）。" }] }] },
    ],
  },
  {
    key: "rejectCheck",
    label: "应标提交文件",
    completed: true,
    items: [
      { id: "submit-must", label: "应标需提交文件", sections: [{ id: "sm-1", title: "应标需提交文件清单", rows: [{ label: "文件清单", content: "1. 投标函；\n2. 法定代表人身份证明与授权委托书；\n3. 开标一览表及分项报价表；\n4. 商务条款响应表；\n5. 技术方案书及演示材料；\n6. 实施计划与团队配置；\n7. 售后与培训方案；\n8. 资格证明文件全套；\n9. 投标保证金凭证；\n10. 其他招标文件要求提交的资料。" }] }] },
    ],
  },
  {
    key: "docReview",
    label: "招标文件审查",
    completed: true,
    items: [
      {
        id: "doc-risk",
        label: "条款风险",
        sections: [
          {
            id: "dr-1",
            title: "条款风险审查",
            rows: [
              { label: "风险条款", content: "1. 付款方式为3:4:3（合同签订30%、上线30%、验收40%），付款节点偏后，存在资金占用风险；\n2. 质保期三年且含免费小版本升级，运维成本需在报价中充分考虑；\n3. 验收标准要求通过第三方测评（等保2.0三级），需提前预留测评预算与时间；\n4. 违约金条款、知识产权归属条款需重点核对。" },
              { label: "应对建议", content: "在报价中充分计入质保期运维与等保测评成本；在技术方案中明确知识产权与数据归属边界；对付款节点可提出更优商务方案争取加分。" },
            ],
          },
        ],
      },
      {
        id: "doc-fair",
        label: "公平性审查风险",
        sections: [
          {
            id: "df-1",
            title: "公平性审查",
            rows: [
              { label: "公平性要点", content: "1. 评审标准是否客观、可量化，是否存在指向性描述；\n2. 资格条件是否具有排他性或限制充分竞争；\n3. 评分项设置是否与项目实际需求匹配、权重是否合理；\n4. 是否存在不合理的资质、业绩门槛设置。" },
              { label: "审查结论", content: "经核查，本项目评审办法为综合评分法，技术权重35%、商务报价25%，无明显指向性或排他性条款，评审程序合法合规。" },
            ],
          },
        ],
      },
    ],
  },
  {
    key: "process",
    label: "开标评定流程",
    completed: false,
    items: [
      { id: "pro-open", label: "开标流程", sections: [{ id: "po-1", title: "开标流程", rows: [{ label: "开标程序", content: "1. 签到、查验投标文件密封情况；\n2. 宣布开标纪律与注意事项；\n3. 当众拆封，宣读投标人名称、报价、工期等主要内容；\n4. 记录开标结果并由投标人代表签字确认；\n5. 开标结束进入评标环节。" }] }] },
      { id: "pro-unseal", label: "开启响应文件", sections: [{ id: "pu-1", title: "开启响应文件", rows: [{ label: "开启要求", content: "开标现场由工作人员在监督人员见证下统一解密电子标书并开启纸质响应文件；\n开启顺序按投标截止时间先后；\n开启后发现密封损坏或无法解密的，当场记录并按无效标处理。" }] }] },
      { id: "pro-panel", label: "磋商小组", sections: [{ id: "pp-1", title: "磋商小组组成", rows: [{ label: "小组构成", content: "磋商（评标）小组由5名成员组成：技术专家3名、商务专家2名；\n专家从专家库随机抽取，与投标人有利害关系的须回避；\n小组依法独立评审，任何单位和个人不得干预。" }] }] },
      { id: "pro-procedure", label: "评审程序", sections: [{ id: "ppr-1", title: "评审程序", rows: [{ label: "评审流程", content: "1. 资格审查（资格性审查）；\n2. 符合性审查；\n3. 商务标评审；\n4. 技术标评审（暗标）；\n5. 现场演示与答辩；\n6. 汇总评分、出具评标报告；\n7. 推荐中标候选人。" }] }] },
      { id: "pro-standard", label: "评分标准", sections: [{ id: "ps-1", title: "评分标准", rows: [{ label: "评分构成", content: "技术方案35分：系统架构、功能响应完整性、技术先进性；\n项目团队15分：项目经理资质、核心人员经验、团队稳定性；\n商务报价25分：报价合理性、性价比、付款方式；\n实施与售后15分：实施计划、培训方案、售后承诺；\n演示答辩10分：现场演示、答辩表现、问题响应能力。\n总分100分，按得分高低推荐中标候选人。" }] }] },
      { id: "pro-negotiate", label: "磋商", sections: [{ id: "pn-1", title: "磋商要求", rows: [{ label: "磋商规则", content: "针对响应文件不明确处，评标小组可与投标人进行澄清性磋商，但不得改变实质性条款；\n磋商过程全程记录并保密；\n磋商结果以书面形式确认，作为评审依据。" }] }] },
      { id: "pro-deal", label: "成交", sections: [{ id: "pd-1", title: "成交与定标", rows: [{ label: "定标规则", content: "按评审得分由高到低排序，得分最高者为第一中标候选人；\n综合得分相同时，报价低者优先；再相同时，技术得分高者优先；\n中标结果公示期不少于3个工作日，无异议后发出中标通知书。" }] }] },
      { id: "pro-contract", label: "合同授予和签订流程", sections: [{ id: "pc-1", title: "合同授予与签订", rows: [{ label: "流程要求", content: "中标通知书发出后15日内，招标人与中标人签订书面合同；\n签订前中标人须提交履约保证金（合同金额5%）；\n合同内容不得对招标文件和中标投标文件的实质性内容作修改；\n拒签合同的中标人将被取消中标资格并依法追责。" }] }] },
      { id: "pro-terminate", label: "合同解除和终止条件", sections: [{ id: "pt-1", title: "合同解除与终止", rows: [{ label: "解除终止情形", content: "1. 中标人无正当理由拒签合同或逾期不提交履约保证金的，招标人有权解除；\n2. 中标人严重违约、交付严重滞后或质量不达标的，招标人有权解除并索赔；\n3. 因不可抗力导致合同无法履行的，双方可协商解除；\n4. 出现法定或约定解除事由时，按合同条款执行。" }] }] },
    ],
  },
];

export const tenderDocs: TenderDoc[] = [
  { id: "td1", name: "CG-2026-1022_招标文件（正文）.docx", type: "招标文件", format: "Word", pages: 286, version: 1, status: "已解析", updatedAt: "2026-08-10" },
  { id: "td2", name: "CG-2026-1022_评标办法及评分细则.pdf", type: "招标文件", format: "PDF", pages: 18, version: 1, status: "已解析", updatedAt: "2026-08-10" },
  { id: "td3", name: "CG-2026-1022_图纸清单及工程量表.xlsx", type: "图纸清单", format: "PDF", pages: 42, version: 1, status: "已解析", updatedAt: "2026-08-11" },
  { id: "td4", name: "CG-2026-1022_答疑澄清（第1号）.docx", type: "答疑补遗", format: "Word", pages: 6, version: 2, status: "高风险", risk: "含图片扫描页", updatedAt: "2026-08-14" },
];

export const scoreRules: ScoreRule[] = [
  { id: "sr1", dimension: "技术方案", weight: 30, detail: "施工总体部署与项目理解，组织机构与资源配置合理性", subject: true, sectionPath: "1 → 1.1 → 1.1.1", responseStatus: "已覆盖", isEssential: false },
  { id: "sr2", dimension: "技术方案", weight: 20, detail: "重难点分析及针对性措施，关键工序施工工艺与技术保障", subject: true, sectionPath: "2 → 2.1 → 2.1.2", responseStatus: "部分", isEssential: false },
  { id: "sr3", dimension: "商务标", weight: 20, detail: "报价合理性、成本控制措施与报价组成完整性", subject: false, sectionPath: "3 → 3.1", responseStatus: "未覆盖", isEssential: true },
  { id: "sr4", dimension: "资格业绩", weight: 15, detail: "类似工程业绩、人员资质与履约能力证明", subject: false, sectionPath: "4 → 4.2", responseStatus: "已覆盖", isEssential: true },
  { id: "sr5", dimension: "进度工期", weight: 15, detail: "进度计划编制合理性、里程碑节点与保障措施", subject: true, sectionPath: "5 → 5.1 → 5.1.3", responseStatus: "部分", isEssential: false },
];

export const mustRespond: MustRespond[] = [
  { id: "mr1", clause: "投标人须具备市政公用工程施工总承包一级及以上资质", original: "第二章 投标人须知 1.4.1", type: "星号条款", status: "已响应" },
  { id: "mr2", clause: "拟派项目经理须持市政一级建造师注册证书，且不得在其他项目在建", original: "第二章 投标人须知 1.4.2", type: "废标条款", status: "已响应" },
  { id: "mr3", clause: "投标有效期自投标截止之日起 90 日历天", original: "第二章 投标人须知 3.3", type: "实质性条款", status: "待响应" },
  { id: "mr4", clause: "本项目为暗标评审，投标文件不得出现任何可识别投标人身份的标记", original: "第二章 投标人须知 5.2", type: "废标条款", status: "待响应" },
  { id: "mr5", clause: "须提交近三年经审计的财务报表，且资产负债率不高于 85%", original: "第三章 评标办法 2.1.2", type: "星号条款", status: "已响应" },
];