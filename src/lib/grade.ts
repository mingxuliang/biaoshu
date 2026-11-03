// AI 预审报告去分数化：统一的 A/B/C/D 等级展示样式，供各页面组件引用，
// 避免各处零散写死颜色判断。等级本身由后端按问题严重度直接推出，前端只负责展示。

export type Grade = "A" | "B" | "C" | "D";

/** 等级说明文案：优（仅建议或无问题）/良（有扣分项）/中（有降档项）/差（有废标项）。 */
export const GRADE_LABEL: Record<Grade, string> = {
  A: "优",
  B: "良",
  C: "中",
  D: "差",
};

/** 徽章样式（背景/文字/边框），风格与现有 severity/status 徽章保持一致。 */
export const GRADE_BADGE_CLASS: Record<Grade, string> = {
  A: "bg-primary-50 text-primary-600 border-primary-200",
  B: "bg-primary-50 text-primary-600 border-primary-200",
  C: "bg-secondary-100 text-secondary-600 border-secondary-200",
  D: "bg-accent-50 text-accent-600 border-accent-200",
};

/** 纯文字颜色（不需要完整徽章底色时使用，如分数环/大字号场景）。 */
export const GRADE_TEXT_CLASS: Record<Grade, string> = {
  A: "text-primary-600",
  B: "text-primary-600",
  C: "text-secondary-600",
  D: "text-accent-600",
};

export function isGrade(value: unknown): value is Grade {
  return value === "A" || value === "B" || value === "C" || value === "D";
}

/** 风险灯样式：红/橙/绿，与后端 light 字段一一对应。 */
export const LIGHT_LABEL: Record<"绿" | "橙" | "红", string> = {
  绿: "低风险",
  橙: "中风险",
  红: "高风险",
};

export const LIGHT_TEXT_CLASS: Record<"绿" | "橙" | "红", string> = {
  绿: "text-primary-600",
  橙: "text-secondary-600",
  红: "text-accent-600",
};

/**
 * 与后端 orchestrator.py 的风险灯规则保持一致（纯计数，无算术）：
 * 有废标→红；无废标但有降档/扣分→橙；否则→绿。仅用于前端根据历史轮次的
 * waste/risk 计数派生展示用风险灯，不作为任何决策依据。
 */
export function lightFromCounts(waste: number, risk: number): "绿" | "橙" | "红" {
  if (waste > 0) return "红";
  if (risk > 0) return "橙";
  return "绿";
}
