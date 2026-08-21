// M03 企业资质与证照库（演示数据）

export interface Qualification {
  id: string;
  kind: "cert" | "people" | "achievement" | "equipment" | "credit";
  name: string;
  level: string;
  number: string;
  validUntil: string;
  status: "有效" | "将到期" | "已过期";
  warnDays?: number;
  owner?: string;
  attachments?: string[];
  detail: string;
  updatedAt: string;
}

export const qualifications: Qualification[] = [
  { id: "q1", kind: "cert", name: "营业执照", level: "—", number: "91330100MA27Y2Q3XR", validUntil: "长期", status: "有效", detail: "注册资本 6800 万元，经营范围含市政工程施工", updatedAt: "2026-06-12" },
  { id: "q2", kind: "cert", name: "市政公用工程施工总承包一级", level: "一级", number: "D233016488", validUntil: "2026-11-20", status: "将到期", warnDays: 25, detail: "主项市政公用工程一级资质", updatedAt: "2026-05-30" },
  { id: "q3", kind: "cert", name: "安全生产许可证", level: "—", number: "(浙)JZ安许证字[2022]030188", validUntil: "2027-03-18", status: "有效", detail: "建筑施工企业安全生产许可", updatedAt: "2026-03-18" },
  { id: "q4", kind: "cert", name: "ISO9001 质量管理体系认证", level: "—", number: "CN20/31245", validUntil: "2026-09-30", status: "有效", detail: "覆盖市政工程施工范围", updatedAt: "2025-10-01" },
  { id: "q5", kind: "people", name: "王建军", level: "一级建造师（市政）", number: "浙1332018********", validUntil: "长期", status: "有效", owner: "项目经理", detail: "注册单位为本企业，社保满 6 个月", updatedAt: "2026-07-02" },
  { id: "q6", kind: "people", name: "李卫东", level: "安全员（C证）", number: "浙建安C（2021）******", validUntil: "2026-12-31", status: "有效", owner: "安全员", detail: "注册单位为本企业", updatedAt: "2026-06-15" },
  { id: "q7", kind: "achievement", name: "城东快速路改造工程（EPC）", level: "1.2 亿元", number: "HC-2023-088", validUntil: "长期", status: "有效", attachments: ["合同", "中标通知书", "竣工验收", "官网截图"], detail: "2023 年完工，市政一级公路，含桥梁两座", updatedAt: "2026-05-20" },
  { id: "q8", kind: "achievement", name: "经开区雨污分流管网工程", level: "8600 万元", number: "JK-2021-042", validUntil: "长期", status: "有效", attachments: ["合同", "中标通知书", "竣工验收"], detail: "2021 年完工，管网总长 42 公里", updatedAt: "2026-04-11" },
  { id: "q9", kind: "equipment", name: "盾构机", level: "Φ6.28m", number: "EQ-001", validUntil: "长期", status: "有效", owner: "自有", detail: "土压平衡式盾构机，购置于 2021 年", updatedAt: "2026-02-08" },
  { id: "q10", kind: "credit", name: "信用中国查询记录", level: "无失信记录", number: "CR-2026-07", validUntil: "2026-10-14", status: "有效", detail: "2026-07-14 查询，无行政处罚与失信记录", updatedAt: "2026-07-14" },
];

export const qualificationTabs = [
  { key: "all", label: "全部", icon: "ri-apps-2-line" },
  { key: "cert", label: "企业证照", icon: "ri-vip-crown-line" },
  { key: "people", label: "人员证书", icon: "ri-id-card-line" },
  { key: "achievement", label: "业绩", icon: "ri-trophy-line" },
  { key: "equipment", label: "设备机具", icon: "ri-truck-line" },
  { key: "credit", label: "信用材料", icon: "ri-shield-star-line" },
];