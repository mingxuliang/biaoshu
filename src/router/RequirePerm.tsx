import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { hasAnyPerm, type RolePerm } from "@/lib/permissions";

export default function RequirePerm({
  anyOf,
  children,
}: {
  anyOf: RolePerm[];
  children: ReactNode;
}) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex min-h-[40vh] w-full items-center justify-center">
        <span className="h-8 w-8 animate-spin rounded-full border-2 border-primary-200 border-t-primary-500" />
      </div>
    );
  }

  if (!user || !hasAnyPerm(user.role, anyOf)) {
    return <Navigate to="/console/projects" replace />;
  }

  return <>{children}</>;
}
