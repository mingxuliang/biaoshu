import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { Project, ProjectType } from "@/mocks/projects";
import { useAuth } from "@/context/AuthContext";
import {
  createProject as apiCreateProject,
  deleteProjectApi,
  getProjectApi,
  listProjects,
  setProjectMembers,
  updateProjectApi,
  uploadTenderDocument,
} from "@/lib/api";

export interface NewProjectInput {
  name: string;
  code: string;
  type: ProjectType;
  budget?: string;
  deadline?: string;
  owner?: string;
  tenderFile?: File;
  memberIds?: string[];
}

interface ProjectContextValue {
  projects: Project[];
  loading: boolean;
  addProject: (input: NewProjectInput) => Promise<Project>;
  updateProject: (id: string, patch: Partial<Project>, extra?: { tenderFile?: File; memberIds?: string[] }) => Promise<Project | undefined>;
  deleteProject: (id: string) => Promise<void>;
  getProject: (id: string | undefined) => Project | undefined;
}

const ProjectContext = createContext<ProjectContextValue | null>(null);

export function ProjectProvider({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) {
      setProjects([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    listProjects(token)
      .then((list) => {
        if (!cancelled) setProjects(list);
      })
      .catch(() => {
        if (!cancelled) setProjects([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const addProject = useCallback(
    async (input: NewProjectInput): Promise<Project> => {
      if (!token) throw new Error("未登录，无法创建项目");
      let created = await apiCreateProject(token, {
        name: input.name,
        code: input.code,
        type: input.type,
        budget: input.budget,
        deadline: input.deadline,
        owner: input.owner,
      });
      if (input.memberIds && input.memberIds.length > 0) {
        const team = await setProjectMembers(token, created.id, input.memberIds);
        created = { ...created, team };
      }
      if (input.tenderFile) {
        await uploadTenderDocument(created.id, input.tenderFile);
        created = await getProjectApi(token, created.id);
      }
      setProjects((prev) => [created, ...prev]);
      return created;
    },
    [token],
  );

  const getProject = useCallback(
    (id: string | undefined) => projects.find((p) => p.id === id),
    [projects],
  );

  const updateProject = useCallback(
    async (
      id: string,
      patch: Partial<Project>,
      extra?: { tenderFile?: File; memberIds?: string[] },
    ): Promise<Project | undefined> => {
      if (!token) throw new Error("未登录，无法更新项目");
      let updated = await updateProjectApi(token, id, patch);
      if (extra?.memberIds) {
        const team = await setProjectMembers(token, id, extra.memberIds);
        updated = { ...updated, team };
      }
      if (extra?.tenderFile) {
        await uploadTenderDocument(id, extra.tenderFile);
        updated = await getProjectApi(token, id);
      }
      setProjects((prev) => prev.map((p) => (p.id === id ? updated : p)));
      return updated;
    },
    [token],
  );

  const deleteProject = useCallback(
    async (id: string): Promise<void> => {
      if (!token) throw new Error("未登录，无法删除项目");
      await deleteProjectApi(token, id);
      setProjects((prev) => prev.filter((p) => p.id !== id));
    },
    [token],
  );

  return (
    <ProjectContext.Provider
      value={{ projects, loading, addProject, updateProject, deleteProject, getProject }}
    >
      {children}
    </ProjectContext.Provider>
  );
}

export function useProjects() {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error("useProjects 必须在 ProjectProvider 内使用");
  return ctx;
}
