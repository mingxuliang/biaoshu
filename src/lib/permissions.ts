export type RolePerm =
  | "project_edit"
  | "writer"
  | "export"
  | "members"
  | "settings"
  | "qual_edit"
  | "review";

const ROLE_PERMS: Record<string, RolePerm[]> = {
  管理员: ["project_edit", "writer", "export", "members", "settings", "qual_edit", "review"],
  项目经理: ["project_edit", "writer", "export", "qual_edit", "review"],
  撰写专家: ["writer", "export", "review"],
  评标专家: ["export", "review"],
  成员: ["export"],
};

export function hasPerm(role: string | undefined | null, perm: RolePerm): boolean {
  const perms = ROLE_PERMS[role || "成员"] || ROLE_PERMS["成员"];
  return perms.includes(perm);
}

export function hasAnyPerm(role: string | undefined | null, perms: RolePerm[]): boolean {
  return perms.some((perm) => hasPerm(role, perm));
}
