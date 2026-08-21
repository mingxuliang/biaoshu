// M11 操作审计（演示数据）

export interface AuditLog {
  id: string;
  time: string;
  user: string;
  action: string;
  target: string;
  version: string;
  detail: string;
}

export const auditLogs: AuditLog[] = [
  { id: "a1", time: "2026-08-15 14:32:08", user: "陈立群", action: "导出", target: "技术标（CG-2026-1022）", version: "v2", detail: "明标导出，校验通过，哈希 A3F2…91CE" },
  { id: "a2", time: "2026-08-15 14:20:44", user: "王建军", action: "改写接受", target: "技术标 / 2.1.2 / 施工工艺", version: "v3", detail: "接受 AI 改写：虚词→量化（问题 T4）" },
  { id: "a3", time: "2026-08-15 11:05:17", user: "赵敏", action: "AI 改写", target: "资格文件 / 财务 / 2.1", version: "v1", detail: "生成对照稿，待编写人确认（问题 T3）" },
  { id: "a4", time: "2026-08-14 09:15:30", user: "李卫东", action: "导出", target: "资格文件（CG-2026-1022）", version: "v1", detail: "导出被阻断：存在未关闭废标项" },
  { id: "a5", time: "2026-08-14 08:46:12", user: "陈立群", action: "发起预审", target: "CG-2026-1022（第 2 轮）", version: "—", detail: "全量预审，风险灯：橙" },
  { id: "a6", time: "2026-08-13 17:30:55", user: "王建军", action: "引用知识", target: "知识库 / 深基坑支护方案", version: "—", detail: "插入章节 2.1.2，防串稿扫描通过" },
  { id: "a7", time: "2026-08-13 15:12:40", user: "陈立群", action: "确认对标", target: "CG-2026-1022 对标清单", version: "v1", detail: "锁定 5 条评分规则、5 条必响应条款" },
  { id: "a8", time: "2026-08-12 10:08:22", user: "赵敏", action: "解析", target: "答疑澄清（第1号）", version: "v2", detail: "增量解析，变更条款已高亮" },
];