import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { Project, ProjectType, TenderUpload } from "@/mocks/projects";
import { useAuth } from "@/context/AuthContext";
import {
  createProject as apiCreateProject,
  deleteProjectApi,
  listProjects,
  updateProjectApi,
} from "@/lib/api";

export interface NewProjectInput {
  name: string;
  code: string;
  type: ProjectType;
  budget?: string;
  deadline?: string;
  owner?: string;
  tenderDoc?: TenderUpload;
}

interface ProjectContextValue {
  projects: Project[];
  loading: boolean;
  addProject: (input: NewProjectInput) => Promise<Project>;
  updateProject: (id: string, patch: Partial<Project>) => Promise<Project | undefined>;
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
      const created = await apiCreateProject(token, {
        name: input.name,
        code: input.code,
        type: input.type,
        budget: input.budget,
        deadline: input.deadline,
        owner: input.owner,
        tenderDoc: input.tenderDoc,
      });
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
    async (id: string, patch: Partial<Project>): Promise<Project | undefined> => {
      if (!token) throw new Error("未登录，无法更新项目");
      const updated = await updateProjectApi(token, id, patch);
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
