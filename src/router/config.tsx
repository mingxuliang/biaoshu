import type { RouteObject } from "react-router-dom";
import { Navigate } from "react-router-dom";
import NotFound from "../pages/NotFound";
import ConsoleLayout from "../pages/console/components/ConsoleLayout";
import RequireAuth from "./RequireAuth";
import ProjectsPage from "../pages/console/projects/page";
import ProjectDetailPage from "../pages/console/projects/detail";
import WriterPage from "../pages/console/writer/page";
import TeamPage from "../pages/console/team/page";
import ParsePage from "../pages/console/parse/page";
import QualificationsPage from "../pages/console/qualifications/page";
import KnowledgePage from "../pages/console/knowledge/page";
import AuditPage from "../pages/console/audit/page";
import ReviewPage from "../pages/console/review/page";
import ExportPage from "../pages/console/export/page";
import RulesPage from "../pages/console/rules/page";
import AuditLogPage from "../pages/console/auditlog/page";
import LoginPage from "../pages/login/page";

const routes: RouteObject[] = [
  {
    path: "/",
    element: <Navigate to="/console/projects" replace />,
  },
  {
    path: "/login",
    element: <LoginPage />,
  },
  {
    path: "/console",
    element: (
      <RequireAuth>
        <ConsoleLayout />
      </RequireAuth>
    ),
    children: [
      {
        index: true,
        element: <Navigate to="/console/projects" replace />,
      },
      {
        path: "projects",
        element: <ProjectsPage />,
      },
      {
        path: "projects/:id",
        element: <ProjectDetailPage />,
      },
      {
        path: "writer",
        element: <WriterPage />,
      },
      {
        path: "parse",
        element: <ParsePage />,
      },
      {
        path: "qualifications",
        element: <QualificationsPage />,
      },
      {
        path: "knowledge",
        element: <KnowledgePage />,
      },
      {
        path: "audit",
        element: <AuditPage />,
      },
      {
        path: "review",
        element: <ReviewPage />,
      },
      {
        path: "export",
        element: <ExportPage />,
      },
      {
        path: "rules",
        element: <RulesPage />,
      },
      {
        path: "team",
        element: <TeamPage />,
      },
      {
        path: "auditlog",
        element: <AuditLogPage />,
      },
    ],
  },
  {
    path: "*",
    element: <NotFound />,
  },
];

export default routes;