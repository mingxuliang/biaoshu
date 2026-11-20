export type RolePerm =
  | "project_edit"
  | "writer"
  | "export"
  | "members"
  | "settings"
  | "qual_edit"
  | "review"
  | "billing"
  | "org";

const ROLE_PERMS: Record<string, RolePerm[]> = {
  管理员: ["project_edit", "writer", "export", "members", "settings", "qual_edit", "review", "billing", "org"],
  项目经理: ["project_edit", "writer", "export", "members", "qual_edit", "review"],
  撰写专家: ["writer", "export", "review"],
  评标专家: ["export", "review"],
  成员: ["export"],
};

// 传登录用户时优先用后端解析好的 perms（含自定义角色）；只传角色名时按内置角色
type PermSubject = string | { role?: string | null; perms?: string[] | null } | undefined | null;

function permsOf(subject: PermSubject): string[] {
  let role: string | null | undefined;
  if (typeof subject === "string") {
    role = subject;
  } else if (subject) {
    if (Array.isArray(subject.perms) && subject.perms.length > 0) return subject.perms;
    role = subject.role;
  }
  return ROLE_PERMS[role || "成员"] || ROLE_PERMS["成员"];
}

export function hasPerm(subject: PermSubject, perm: RolePerm): boolean {
  return permsOf(subject).includes(perm);
}

export function hasAnyPerm(subject: PermSubject, perms: RolePerm[]): boolean {
  const own = permsOf(subject);
  return perms.some((perm) => own.includes(perm));
}
