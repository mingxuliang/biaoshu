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
  if (pathname.startsWith("/console/duplicate/result")) return "查重结果";
  if (pathname.startsWith("/console/duplicate")) return "查重分析";
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

  const lockViewport = location.pathname.startsWith("/console/review");

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!lockViewport) return;
    const html = document.documentElement;
    const prevHtml = html.style.overflow;
    const prevBody = document.body.style.overflow;
    html.style.overflow = "hidden";
    document.body.style.overflow = "hidden";
    return () => {
      html.style.overflow = prevHtml;
      document.body.style.overflow = prevBody;
    };
  }, [lockViewport]);

  return (
    <div className={`relative bg-background-50 text-foreground-950 ${lockViewport ? "h-screen overflow-hidden" : "min-h-screen"}`}>
      <Sidebar mobileOpen={mobileOpen} onClose={() => setMobileOpen(false)} />

      <div className={`relative lg:pl-[220px] ${lockViewport ? "h-full" : ""}`}>
        <Topbar title={getTitle(location.pathname)} onMenuOpen={() => setMobileOpen(true)} />
        <main
          className={
            lockViewport
              ? "flex h-[calc(100vh-3.5rem)] flex-col overflow-hidden px-5 py-5"
              : "min-h-[calc(100vh-3.5rem)] px-5 py-5"
          }
        >
          <ProjectProvider>
            <ProductCatalogProvider>
              {lockViewport ? (
                <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                  <Outlet />
                </div>
              ) : (
                <Outlet />
              )}
            </ProductCatalogProvider>
          </ProjectProvider>
        </main>
      </div>
    </div>
  );
}