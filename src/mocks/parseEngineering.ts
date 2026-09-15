// M02 招标文件解析与对标清单 —— 工程类项目专属指标骨架
//
// 与后端 backend/app/engines/parse_dimension_schema_engineering.json 完全对齐：
// 禁止增删 key、id、label、section id/title、row label，仅允许写入 rows.content。
// 一级/二级分类对齐专业解读报告 A 基础审核～G 开评定标；
// 工程量清单、图纸、专用合同条款、其他材料为产品保留的专用抽取槽，不删。

import type { ParseDimension } from "./parse";

export const parseDimensionsEngineering: ParseDimension[] = [
  {
    key: "basic",
    label: "基础审核",
    completed: false,
    items: [
      {
        id: "basic-project",
        label: "项目基本信息",
        sections: [
          {
            id: "bp-1",
            title: "项目基本信息",
            rows: [
              { label: "项目名称", content: "" },
              { label: "报建编号", content: "" },
              { label: "招标项目编号", content: "" },
              { label: "建设地点", content: "" },
              { label: "招标方式", content: "" },
              { label: "项目类型", content: "" },
              { label: "所属行业", content: "" },
              { label: "招标文件编制日期", content: "" },
            ],
          }
        ],
      },
      {
        id: "basic-tenderer",
        label: "招标人及代理机构",
        sections: [
          {
            id: "bt-1",
            title: "甲方及代理机构信息",
            rows: [
              { label: "招标人（名称/地址/联系人/电话/邮箱）", content: "" },
              { label: "招标代理机构（名称/地址/联系人/电话/邮箱）", content: "" },
              { label: "监督部门（名称/地址/电话）", content: "" },
              { label: "质疑澄清渠道", content: "" },
            ],
          }
        ],
      },
      {
        id: "basic-scale",
        label: "项目概况及建设规模",
        sections: [
          {
            id: "bs-1",
            title: "项目概况及建设规模",
            rows: [
              { label: "建设规模与内容", content: "" },
              { label: "标段范围", content: "" },
              { label: "主要工程内容", content: "" },
              { label: "概算金额", content: "" },
            ],
          }
        ],
      },
      {
        id: "basic-time",
        label: "关键时间节点",
        sections: [
          {
            id: "btm-1",
            title: "关键时间节点",
            rows: [
              { label: "招标文件获取时间", content: "" },
              { label: "投标截止时间", content: "" },
              { label: "开标时间", content: "" },
              { label: "投标有效期", content: "" },
              { label: "提问截止时间", content: "" },
              { label: "澄清答疑时间", content: "" },
            ],
          }
        ],
      },
      {
        id: "basic-duration",
        label: "工期与质量",
        sections: [
          {
            id: "bd-1",
            title: "工期要求",
            rows: [
              { label: "计划工期", content: "" },
              { label: "计划开工日期", content: "" },
              { label: "里程碑工期", content: "" },
              { label: "质量目标", content: "" },
              { label: "缺陷责任期/质保期", content: "" },
            ],
          }
        ],
      },
      {
        id: "basic-bond",
        label: "预算及保证金",
        sections: [
          {
            id: "bb-1",
            title: "预算及投标保证金",
            rows: [
              { label: "最高投标限价/预算上限", content: "" },
              { label: "投标保证金（金额与形式）", content: "" },
              { label: "履约保证金", content: "" },
            ],
          }
        ],
      },
      {
        id: "basic-fund",
        label: "资金来源",
        sections: [
          {
            id: "bf-1",
            title: "资金来源及落实情况",
            rows: [
              { label: "资金来源", content: "" },
              { label: "出资比例", content: "" },
              { label: "资金落实情况", content: "" },
            ],
          }
        ],
      }
    ],
  },
  {
    key: "qualification",
    label: "资格与合规",
    completed: false,
    items: [
      {
        id: "qual-license",
        label: "资格性审查要求",
        sections: [
          {
            id: "ql-1",
            title: "资格性审查要求",
            rows: [
              { label: "企业资质（可多项并列）", content: "" },
              { label: "营业执照", content: "" },
              { label: "安全生产许可证", content: "" },
              { label: "联合体投标要求", content: "" },
            ],
          }
        ],
      },
      {
        id: "qual-personnel",
        label: "项目管理人员资格",
        sections: [
          {
            id: "qn-1",
            title: "项目管理人员资格要求",
            rows: [
              { label: "项目经理资格与业绩要求", content: "" },
              { label: "技术负责人资格要求", content: "" },
              { label: "其他专职岗位配置（岗位/资格/经验/证书/人数）", content: "" },
              { label: "社保连续缴纳要求", content: "" },
              { label: "在建项目人员占用核查要求", content: "" },
            ],
          }
        ],
      },
      {
        id: "qual-performance",
        label: "企业业绩要求",
        sections: [
          {
            id: "qp-1",
            title: "企业业绩要求",
            rows: [
              { label: "类似项目业绩认定标准", content: "" },
              { label: "业绩时间窗口与证明文件", content: "" },
              { label: "类似工程定义", content: "" },
              { label: "业绩认定排除清单", content: "" },
            ],
          }
        ],
      },
      {
        id: "qual-finance",
        label: "财务要求",
        sections: [
          {
            id: "qf-1",
            title: "财务要求",
            rows: [
              { label: "营运资金要求", content: "" },
              { label: "营业收入要求", content: "" },
              { label: "财务审计报告要求", content: "" },
            ],
          }
        ],
      },
      {
        id: "qual-credit",
        label: "信誉要求",
        sections: [
          {
            id: "qcr-1",
            title: "信誉要求",
            rows: [
              { label: "信用平台查询要求", content: "" },
              { label: "诉讼、履约与失信情形", content: "" },
              { label: "行业黑名单/承诺函要求", content: "" },
            ],
          }
        ],
      },
      {
        id: "qual-equipment",
        label: "专用设备要求",
        sections: [
          {
            id: "qe-1",
            title: "专用设备要求",
            rows: [{ label: "专用设备清单（名称/规格/数量）", content: "" }],
          }
        ],
      },
      {
        id: "qual-review",
        label: "符合性审查标准",
        sections: [
          {
            id: "qr-1",
            title: "符合性审查标准",
            rows: [{ label: "符合性审查项目与标准", content: "" }],
          }
        ],
      }
    ],
  },
  {
    key: "evalMethod",
    label: "技术评分",
    completed: false,
    items: [
      {
        id: "eval-tech",
        label: "施工组织设计评分",
        sections: [
          {
            id: "et-1",
            title: "施工组织设计评分标准",
            rows: [
              { label: "评分因素与标准", content: "" },
              { label: "分档/赋分规则", content: "" },
              { label: "技术标编制要点（暗标）", content: "" },
              { label: "技术标评分门槛", content: "" },
            ],
          }
        ],
      }
    ],
  },
  {
    key: "envelope",
    label: "商务评分",
    completed: false,
    items: [
      {
        id: "eval-business",
        label: "企业与项目管理机构评分",
        sections: [
          {
            id: "eb-1",
            title: "企业与项目管理机构评分标准",
            rows: [
              { label: "评分因素与标准", content: "" },
              { label: "分档/赋分规则", content: "" },
            ],
          }
        ],
      },
      {
        id: "env-price",
        label: "投标报价评分",
        sections: [
          {
            id: "ep-1",
            title: "投标报价评分标准",
            rows: [
              { label: "评标基准价/有效评标价计算方法", content: "" },
              { label: "有效报价区间与K值", content: "" },
              { label: "投标报价偏差率计算公式", content: "" },
              { label: "报价得分计算公式", content: "" },
              { label: "异常低价识别公式与参数", content: "" },
            ],
          }
        ],
      },
      {
        id: "contract-tech",
        label: "专用合同条款（技术要求）",
        sections: [
          {
            id: "ct-1",
            title: "合同技术指标与加分项",
            rows: [
              { label: "工程专业（市政/房建/公路/水利等）", content: "" },
              { label: "进度计划确认与修订时限", content: "" },
              { label: "材料、工艺与验收标准", content: "" },
              { label: "质量检测与实测实量要求", content: "" },
              { label: "安全文明施工量化要求", content: "" },
              { label: "监理/发包人确认时限", content: "" },
              { label: "违约、索赔与工期奖罚", content: "" },
              { label: "其他技术加分相关条款", content: "" },
            ],
          },
          {
            id: "ct-2",
            title: "市政工程重点",
            rows: [
              { label: "管线迁改与保护", content: "" },
              { label: "交通组织与占道施工", content: "" },
              { label: "道路、桥梁与管网施工要求", content: "" },
              { label: "排水、绿化与移交标准", content: "" },
            ],
          },
          {
            id: "ct-3",
            title: "房建工程重点",
            rows: [
              { label: "结构形式与主要材料", content: "" },
              { label: "装修装饰与节能要求", content: "" },
              { label: "起重机械与危大工程", content: "" },
              { label: "样板引路与实测实量", content: "" },
            ],
          },
          {
            id: "ct-4",
            title: "其他专业工程重点",
            rows: [
              { label: "公路交通专项技术要求", content: "" },
              { label: "水利农田专项技术要求", content: "" },
              { label: "电力通信专项技术要求", content: "" },
            ],
          }
        ],
      }
    ],
  },
  {
    key: "reject",
    label: "废标风险",
    completed: false,
    items: [
      {
        id: "reject-open",
        label: "开标前阶段",
        sections: [
          {
            id: "rj-1",
            title: "开标前阶段废标风险",
            rows: [{ label: "废标风险点（风险点/描述/等级/条款号）", content: "" }],
          }
        ],
      },
      {
        id: "reject-qual",
        label: "资格性审查",
        sections: [
          {
            id: "rj-2",
            title: "资格性审查废标风险",
            rows: [{ label: "废标风险点（风险点/描述/等级/条款号）", content: "" }],
          }
        ],
      },
      {
        id: "reject-conform",
        label: "符合性审查",
        sections: [
          {
            id: "rj-3",
            title: "符合性审查废标风险",
            rows: [{ label: "废标风险点（风险点/描述/等级/条款号）", content: "" }],
          }
        ],
      },
      {
        id: "reject-eval",
        label: "评标与定标阶段",
        sections: [
          {
            id: "rj-4",
            title: "评标与定标阶段废标风险",
            rows: [{ label: "废标风险点（风险点/描述/等级/条款号）", content: "" }],
          }
        ],
      },
      {
        id: "reject-other",
        label: "其他高风险情形",
        sections: [
          {
            id: "rj-5",
            title: "其他高风险情形",
            rows: [{ label: "废标风险点（风险点/描述/等级/条款号）", content: "" }],
          }
        ],
      }
    ],
  },
  {
    key: "bidReq",
    label: "投标文件要求",
    completed: false,
    items: [
      {
        id: "req-compose",
        label: "投标文件组成",
        sections: [
          {
            id: "rq-2",
            title: "投标文件组成",
            rows: [{ label: "投标文件组成清单（文件名/格式/是否必须/备注）", content: "" }],
          }
        ],
      },
      {
        id: "req-format",
        label: "格式与暗标",
        sections: [
          {
            id: "rq-5",
            title: "投标文件格式要求",
            rows: [
              { label: "技术标暗标要求", content: "" },
              { label: "页数/字体/页边距", content: "" },
              { label: "盖章与签署要求", content: "" },
            ],
          }
        ],
      },
      {
        id: "req-encrypt",
        label: "电子投标要求",
        sections: [
          {
            id: "rq-4",
            title: "电子投标要求",
            rows: [
              { label: "加密与上传要求", content: "" },
              { label: "递交方式及截止时间", content: "" },
              { label: "解密要求", content: "" },
            ],
          }
        ],
      },
      {
        id: "req-submit",
        label: "纸质投标文件",
        sections: [
          {
            id: "rq-1",
            title: "纸质投标文件要求",
            rows: [{ label: "纸质投标文件要求", content: "" }],
          }
        ],
      },
      {
        id: "req-qualdocs",
        label: "资格审查资料清单",
        sections: [
          {
            id: "rq-7",
            title: "资格审查资料详细清单",
            rows: [{ label: "资格审查资料详细清单（资料类别/具体资料/是否必须/备注）", content: "" }],
          }
        ],
      }
    ],
  },
  {
    key: "process",
    label: "开评定标流程",
    completed: false,
    items: [
      {
        id: "pro-open",
        label: "开标流程",
        sections: [
          {
            id: "po-1",
            title: "开标流程",
            rows: [
              { label: "开标时间与地点", content: "" },
              { label: "开标程序", content: "" },
              { label: "解密时长与方式", content: "" },
            ],
          }
        ],
      },
      {
        id: "pro-review",
        label: "评标流程",
        sections: [
          {
            id: "pr-1",
            title: "评标流程",
            rows: [
              { label: "评标委员会组建", content: "" },
              { label: "评标方法类型", content: "" },
              { label: "评审程序", content: "" },
              { label: "评分权重构成", content: "" },
              { label: "技术标门槛与推荐原则", content: "" },
              { label: "是否评定分离", content: "" },
            ],
          }
        ],
      },
      {
        id: "pro-award",
        label: "合同授予",
        sections: [
          {
            id: "pa-1",
            title: "合同授予流程",
            rows: [
              { label: "中标候选人公示", content: "" },
              { label: "中标结果公示与通知", content: "" },
              { label: "履约保证金与合同签订", content: "" },
              { label: "投标保证金退还", content: "" },
            ],
          }
        ],
      },
      {
        id: "pro-dispute",
        label: "异议质疑与投诉",
        sections: [
          {
            id: "pd-1",
            title: "异议和质疑处理",
            rows: [
              { label: "招标文件异议", content: "" },
              { label: "开标异议", content: "" },
              { label: "评标结果异议", content: "" },
              { label: "投诉", content: "" },
            ],
          }
        ],
      },
      {
        id: "pro-clarify",
        label: "澄清补正",
        sections: [
          {
            id: "pc-1",
            title: "澄清和补正",
            rows: [{ label: "澄清补正规则", content: "" }],
          }
        ],
      },
      {
        id: "pro-terminate",
        label: "合同解除条件",
        sections: [
          {
            id: "pt-1",
            title: "合同解除条件",
            rows: [
              { label: "发包人解除合同", content: "" },
              { label: "承包人解除合同", content: "" },
            ],
          }
        ],
      }
    ],
  },
  {
    key: "quantity",
    label: "清单、图纸与其他",
    completed: false,
    items: [
      {
        id: "qty-boq",
        label: "工程量清单",
        sections: [
          {
            id: "qb-1",
            title: "分类分项工程量清单",
            rows: [
              { label: "项目名称", content: "" },
              { label: "计量单位", content: "" },
              { label: "工程数量", content: "" },
              { label: "备注", content: "" },
            ],
          }
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
              { label: "图纸文件", content: "" },
              { label: "设计说明", content: "" },
            ],
          }
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
          }
        ],
      },
      {
        id: "misc-other",
        label: "其他材料",
        sections: [
          {
            id: "mo-1",
            title: "其他文件提炼",
            rows: [
              { label: "文件摘要", content: "" },
              { label: "评分因素与标准", content: "" },
              { label: "否决/废标条款", content: "" },
              { label: "资格与门槛补充", content: "" },
              { label: "格式与递交要求", content: "" },
              { label: "技术指标与加分项", content: "" },
            ],
          }
        ],
      }
    ],
  }
];
