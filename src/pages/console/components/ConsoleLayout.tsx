import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import { ProjectProvider } from "@/context/ProjectContext";
import { ProductCatalogProvider } from "@/context/ProductCatalogContext";

function getTitle(pathname: string): string {
  if (pathname.startsWith("/console/projects")) {
    return pathname.includes("/projects/") ? "项目详情" : "项目中心";
  }
  if (pathname.startsWith("/console/writer")) return "撰写工作台";
  if (pathname.startsWith("/console/parse")) return "招标解析";
  if (pathname.startsWith("/console/qualifications")) return "资质证照库";
  if (pathname.match(/^\/console\/knowledge\/[^/]+$/)) return "知识文档切片";
  if (pathname.startsWith("/console/knowledge")) return "文档知识库";
  if (pathname.match(/^\/console\/products\/[^/]+$/)) return "产品库详情";
  if (pathname.startsWith("/console/products")) return "产品功能库";
  if (pathname.startsWith("/console/audit")) return "AI 预审中心";
  if (pathname.startsWith("/console/review")) return "修改闭环";
  if (pathname.startsWith("/console/export")) return "Word 导出";
  if (pathname.startsWith("/console/rules")) return "预审规则";
  if (pathname.startsWith("/console/models")) return "模型配置";
  if (pathname.startsWith("/console/team")) return "团队管理";
  if (pathname.startsWith("/console/auditlog")) return "审计日志";
  return "工作台";
}

export default function ConsoleLayout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  return (
    <div className="relative min-h-screen bg-background-50 text-foreground-950">
      <Sidebar mobileOpen={mobileOpen} onClose={() => setMobileOpen(false)} />

      <div className="relative lg:pl-[220px]">
        <Topbar title={getTitle(location.pathname)} onMenuOpen={() => setMobileOpen(true)} />
        <main className="min-h-[calc(100vh-3.5rem)] px-5 py-5">
          <ProjectProvider>
            <ProductCatalogProvider>
              <Outlet />
            </ProductCatalogProvider>
          </ProjectProvider>
        </main>
      </div>
    </div>
  );
}