// M08 Word 导出与交付（演示数据）

export interface ExportRecord {
  id: string;
  project: string;
  section: string;
  filename: string;
  mode: "明标" | "暗标";
  operator: string;
  checkStatus: "已通过" | "已阻断";
  checkNote?: string;
  fileSize: string;
  hash: string;
  exportedAt: string;
}

export const exportRecords: ExportRecord[] = [
  { id: "e1", project: "市智慧交通信号控制系统升级改造", section: "技术标", filename: "CG-2026-1022_技术标_明标_v2_20260815.docx", mode: "明标", operator: "陈立群", checkStatus: "已通过", fileSize: "8.6 MB", hash: "A3F2…91CE", exportedAt: "2026-08-15 14:32" },
  { id: "e2", project: "市智慧交通信号控制系统升级改造", section: "商务标", filename: "CG-2026-1022_商务标_明标_v2_20260815.docx", mode: "明标", operator: "赵敏", checkStatus: "已通过", fileSize: "5.1 MB", hash: "8B71…22FD", exportedAt: "2026-08-15 14:40" },
  { id: "e3", project: "市智慧交通信号控制系统升级改造", section: "资格文件", filename: "CG-2026-1022_资格文件_明标_v2_20260815.docx", mode: "明标", operator: "李卫东", checkStatus: "已阻断", checkNote: "存在 1 个未关闭废标项（投标有效期）", fileSize: "—", hash: "—", exportedAt: "2026-08-14 09:15" },
  { id: "e4", project: "高新区综合管廊一期工程", section: "技术标", filename: "GX-2026-031_技术标_暗标_v1_20260728.docx", mode: "暗标", operator: "王建军", checkStatus: "已通过", fileSize: "9.3 MB", hash: "C4D0…5A31", exportedAt: "2026-07-28 16:05" },
];

export const sections = ["技术标", "商务标", "资格文件", "合订本"];