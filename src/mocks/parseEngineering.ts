// M02 招标文件解析与对标清单 —— 工程类项目专属指标骨架
//
// 与后端 backend/app/engines/parse_dimension_schema_engineering.json 完全对齐：
// 禁止增删 key、id、label、section id/title、row label，仅允许写入 rows.content。
// 基于对「滨湖新区环卫基地工程施工」「濉溪县双堆集镇高标准农田建设项目」两份
// 真实工程招标文件的解读结果设计：评定分离、定性定量评审、三信封、资格门槛、
// 工程量清单/图纸、异常低价与畸高畸低算法、否决清单等工程标特有要素。

import type { ParseDimension } from "./parse";

export const parseDimensionsEngineering: ParseDimension[] = [
  {
    key: "basic",
    label: "基本信息",
    completed: false,
    items: [
      {
        id: "basic-tenderer",
        label: "招标人/代理信息",
        sections: [
          {
            id: "bt-1",
            title: "招标人与代理机构",
            rows: [
              { label: "招标人", content: "" },
              { label: "招标代理机构", content: "" },
              { label: "质疑澄清渠道", content: "" },
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
              { label: "项目名称", content: "" },
              { label: "招标编号", content: "" },
              { label: "建设地点", content: "" },
              { label: "建设规模与内容", content: "" },
              { label: "标段划分", content: "" },
              { label: "最高投标限价/预算上限", content: "" },
              { label: "资金来源", content: "" },
            ],
          },
          {
            id: "bp-2",
            title: "招标范围与承包模式",
            rows: [
              { label: "招标范围", content: "" },
              { label: "是否设计施工总承包(EPC)", content: "" },
              { label: "绿色建筑/智慧工地等级要求", content: "" },
            ],
          },
        ],
      },
      {
        id: "basic-method",
        label: "评标体制",
        sections: [
          {
            id: "bm-1",
            title: "评标方法",
            rows: [
              { label: "评标方法类型（综合评估法/定性定量评审法/经评审的最低投标价法）", content: "" },
              { label: "是否评定分离", content: "" },
              { label: "中标候选人推荐规则与人数", content: "" },
              { label: "是否采用AI类人评审模式", content: "" },
              { label: "开评标方式（是否电子标/大模型辅助评标）", content: "" },
            ],
          },
        ],
      },
      {
        id: "basic-time",
        label: "工期与质量目标",
        sections: [
          {
            id: "btm-1",
            title: "关键时间节点",
            rows: [
              { label: "投标截止/开标时间", content: "" },
              { label: "投标有效期", content: "" },
            ],
          },
          {
            id: "btm-2",
            title: "履约目标",
            rows: [
              { label: "计划工期/关键节点工期", content: "" },
              { label: "质量目标（合格/优良等）", content: "" },
              { label: "缺陷责任期/质保期", content: "" },
              { label: "违约金与索赔条款", content: "" },
            ],
          },
        ],
      },
    ],
  },
  {
    key: "qualification",
    label: "资格与门槛",
    completed: false,
    items: [
      {
        id: "qual-license",
        label: "资质与财务要求",
        sections: [
          {
            id: "ql-1",
            title: "资质条件",
            rows: [
              { label: "资质等级要求（可多项并列）", content: "" },
              { label: "安全生产许可证", content: "" },
              { label: "财务状况要求", content: "" },
            ],
          },
        ],
      },
      {
        id: "qual-performance",
        label: "业绩与信誉要求",
        sections: [
          {
            id: "qp-1",
            title: "业绩认定规则",
            rows: [
              { label: "类似项目业绩认定标准", content: "" },
              { label: "业绩认定排除清单（明确不认可的项目类型）", content: "" },
              { label: "联合体业绩认定规则", content: "" },
            ],
          },
          {
            id: "qp-2",
            title: "信誉要求",
            rows: [
              { label: "信用等级/信用平台查询要求", content: "" },
              { label: "获奖要求", content: "" },
              { label: "体系认证要求（质量/环境/职业健康安全）", content: "" },
            ],
          },
        ],
      },
      {
        id: "qual-personnel",
        label: "人员资格要求",
        sections: [
          {
            id: "qn-1",
            title: "关键岗位人员",
            rows: [
              { label: "项目经理资格与业绩要求", content: "" },
              { label: "技术/设计/施工负责人资格要求", content: "" },
              { label: "其他专职岗位配置（施工员/质检员/安全员/造价员/劳资专管员等，含人数）", content: "" },
            ],
          },
          {
            id: "qn-2",
            title: "证书与社保要求",
            rows: [
              { label: "岗位证书等级要求（如安全生产考核合格证A类/C类）", content: "" },
              { label: "社保连续缴纳要求", content: "" },
              { label: "在建项目人员占用核查要求", content: "" },
            ],
          },
        ],
      },
      {
        id: "qual-combo",
        label: "联合体与禁止/否决情形",
        sections: [
          {
            id: "qc-1",
            title: "联合体投标",
            rows: [
              { label: "联合体成员数量限制", content: "" },
              { label: "联合体分工与责任划分", content: "" },
            ],
          },
          {
            id: "qc-2",
            title: "禁止投标与否决情形",
            rows: [
              { label: "不得存在的禁止投标情形", content: "" },
              { label: "否决投标的其他情形（串通投标/弄虚作假清单）", content: "" },
            ],
          },
        ],
      },
      {
        id: "qual-review",
        label: "形式/资格/响应性评审",
        sections: [
          {
            id: "qr-1",
            title: "初步评审标准",
            rows: [
              { label: "形式评审标准", content: "" },
              { label: "资格评审标准", content: "" },
              { label: "响应性评审标准", content: "" },
            ],
          },
        ],
      },
    ],
  },
  {
    key: "evalMethod",
    label: "评标办法",
    completed: false,
    items: [
      {
        id: "eval-tech",
        label: "技术评审标准",
        sections: [
          {
            id: "et-1",
            title: "技术评审标准（完整原文）",
            rows: [{ label: "评分因素与标准", content: "" }],
          },
        ],
      },
      {
        id: "eval-business",
        label: "商务标评分评审标准",
        sections: [
          {
            id: "eb-1",
            title: "商务标评分评审标准（完整原文）",
            rows: [{ label: "评分因素与标准", content: "" }],
          },
        ],
      },
    ],
  },
  {
    key: "envelope",
    label: "商务/技术/报价评审",
    completed: false,
    items: [
      {
        id: "env-business",
        label: "商务评审",
        sections: [
          {
            id: "eb-1",
            title: "商务评分因素",
            rows: [
              { label: "评分因素与权重原文", content: "" },
              { label: "分档/赋分规则（A/B/C 或分值区间）", content: "" },
              { label: "证明材料要求（含反山寨社团等合法性核验条款）", content: "" },
            ],
          },
        ],
      },
      {
        id: "env-tech",
        label: "技术评审",
        sections: [
          {
            id: "et-1",
            title: "技术评分因素",
            rows: [
              { label: "评分因素原文（含括号内项目专属考题）", content: "" },
              { label: "分档/赋分规则", content: "" },
              { label: "AI类人评审说明", content: "" },
            ],
          },
          {
            id: "et-2",
            title: "工程重难点与危大工程",
            rows: [
              { label: "工程重难点清单（发包人要求/第七章原文）", content: "" },
              { label: "危险性较大分部分项工程清单", content: "" },
              { label: "业主重要提示与特殊要求", content: "" },
            ],
          },
        ],
      },
      {
        id: "env-price",
        label: "报价评审",
        sections: [
          {
            id: "ep-1",
            title: "报价规则与公式",
            rows: [
              { label: "评标基准价/有效评标价计算方法", content: "" },
              { label: "投标报价偏差率计算公式", content: "" },
              { label: "报价得分计算公式", content: "" },
              { label: "异常低价识别公式与参数", content: "" },
              { label: "异常低价说明不得作为依据的排除清单", content: "" },
            ],
          },
        ],
      },
      {
        id: "env-calc",
        label: "得分计算与统计规则",
        sections: [
          {
            id: "ec-1",
            title: "畸高畸低/统计剔除规则",
            rows: [
              { label: "评委打分纵向/横向偏差率剔除算法原文", content: "" },
              { label: "综合评价等级组合规则（好/较好/一般）", content: "" },
            ],
          },
        ],
      },
    ],
  },
  {
    key: "quantity",
    label: "清单、图纸与技术标准",
    completed: false,
    items: [
      {
        id: "qty-boq",
        label: "工程量清单规则",
        sections: [
          {
            id: "qb-1",
            title: "计价与清单规则",
            rows: [
              { label: "暂列金额", content: "" },
              { label: "暂估价", content: "" },
              { label: "安全生产费/不可竞争费比例", content: "" },
              { label: "缺漏/偏差容差（如3%）", content: "" },
              { label: "清单编码名称特征单位数量不得改动条款", content: "" },
            ],
          },
        ],
      },
      {
        id: "qty-drawing",
        label: "图纸",
        sections: [
          {
            id: "qd-1",
            title: "图纸另册",
            rows: [
              { label: "图纸章节位置与图号图名", content: "" },
              { label: "图纸目录（图号 / 图名 / 专业 / 比例 / 页码）", content: "" },
              { label: "设计说明与施工要点", content: "" },
              { label: "主要工程内容与结构形式", content: "" },
              { label: "关键尺寸、材料与图面注记", content: "" },
              { label: "图纸与技术标准冲突时的处理原则", content: "" },
              { label: "解读范围说明（读了哪些页、哪些页未送视觉）", content: "" },
            ],
          },
        ],
      },
      {
        id: "qty-techstd",
        label: "发包人要求/技术标准",
        sections: [
          {
            id: "qt-1",
            title: "技术标准和要求",
            rows: [
              { label: "技术规范标准清单", content: "" },
              { label: "验收标准", content: "" },
              { label: "现场条件与踏勘说明", content: "" },
            ],
          },
        ],
      },
    ],
  },
  {
    key: "bidReq",
    label: "投标文件格式与提交",
    completed: false,
    items: [
      {
        id: "req-submit",
        label: "投标文件递交",
        sections: [
          {
            id: "rq-1",
            title: "递交要求",
            rows: [
              { label: "递交方式及截止时间", content: "" },
              { label: "密封与标识要求", content: "" },
            ],
          },
        ],
      },
      {
        id: "req-compose",
        label: "投标文件组成（三信封）",
        sections: [
          {
            id: "rq-2",
            title: "商务/技术/报价文件组成",
            rows: [
              { label: "三份文件各自组成内容", content: "" },
              { label: "信息隔离要求（如商务文件不得出现报价）", content: "" },
            ],
          },
        ],
      },
      {
        id: "req-seal",
        label: "响应文件盖章",
        sections: [
          {
            id: "rq-3",
            title: "盖章与签署要求",
            rows: [{ label: "盖章要求", content: "" }],
          },
        ],
      },
      {
        id: "req-encrypt",
        label: "电子标书加密、上传",
        sections: [
          {
            id: "rq-4",
            title: "加密与上传要求",
            rows: [{ label: "加密上传要求", content: "" }],
          },
        ],
      },
      {
        id: "req-format",
        label: "格式与页数限制",
        sections: [
          {
            id: "rq-5",
            title: "格式要求",
            rows: [
              { label: "页数/字体/装订要求", content: "" },
              { label: "暗标要求", content: "" },
            ],
          },
        ],
      },
      {
        id: "req-invalid",
        label: "响应无效情形",
        sections: [
          {
            id: "rq-6",
            title: "无效情形",
            rows: [{ label: "响应无效/否决情形", content: "" }],
          },
        ],
      },
    ],
  },
  {
    key: "process",
    label: "开评标与定标流程",
    completed: false,
    items: [
      {
        id: "pro-open",
        label: "开标流程",
        sections: [
          {
            id: "po-1",
            title: "开标流程",
            rows: [{ label: "开标程序", content: "" }],
          },
        ],
      },
      {
        id: "pro-review",
        label: "评标程序",
        sections: [
          {
            id: "pr-1",
            title: "评标程序",
            rows: [
              { label: "评标流程", content: "" },
              { label: "澄清补正规则", content: "" },
            ],
          },
        ],
      },
      {
        id: "pro-award",
        label: "定标规则",
        sections: [
          {
            id: "pa-1",
            title: "定标规则",
            rows: [{ label: "中标候选人排序与定标规则", content: "" }],
          },
        ],
      },
    ],
  },
];
