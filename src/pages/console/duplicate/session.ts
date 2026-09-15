import type { DuplicateCheckReport } from "@/lib/api";

const KEY = "zhbiao_duplicate_report";

export function saveDuplicateReport(report: DuplicateCheckReport): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(report));
  } catch {
    // quota / private mode：结果仍展示在当前页，刷新后需重新上传
  }
}

export function loadDuplicateReport(): DuplicateCheckReport | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    return JSON.parse(raw) as DuplicateCheckReport;
  } catch {
    return null;
  }
}

export function clearDuplicateReport(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}

export interface DuplicateUploadState {
  fileA: File;
  fileB: File;
}
