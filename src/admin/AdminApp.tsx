import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AdminAuthProvider, useAdminAuth, useCan } from "./auth";
import { UiProvider } from "./ui";
import AdminLayout from "./Layout";
import AdminLoginPage from "./LoginPage";
import DashboardPage from "./pages/DashboardPage";
import TenantsPage from "./pages/TenantsPage";
import TenantDetailPage from "./pages/TenantDetailPage";
import CreditsPage from "./pages/CreditsPage";
import UsersFeesPage from "./pages/UsersFeesPage";
import PricingPage from "./pages/PricingPage";
import OrdersPage from "./pages/OrdersPage";
import InvoicesPage from "./pages/InvoicesPage";
import LlmPage from "./pages/LlmPage";
import { AnnouncementsPage, AuditPage, StoragePage, SystemPage } from "./pages/SystemPages";
import StandardsPage from "./pages/StandardsPage";
import { AccountPage, AdminsPage } from "./pages/AccountPages";

function Gate() {
  const { admin, loading } = useAdminAuth();
  const { isSuper } = useCan();
  if (loading) return <div className="flex min-h-screen items-center justify-center text-sm text-foreground-500">加载中…</div>;
  if (!admin) return <AdminLoginPage />;
  return (
    <Routes>
      <Route element={<AdminLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="tenants" element={<TenantsPage />} />
        <Route path="tenants/:id" element={<TenantDetailPage />} />
        <Route path="credits" element={<CreditsPage />} />
        <Route path="users" element={<UsersFeesPage />} />
        <Route path="pricing" element={<PricingPage />} />
        <Route path="orders" element={<OrdersPage />} />
        <Route path="invoices" element={<InvoicesPage />} />
        <Route path="llm" element={<LlmPage />} />
        <Route path="storage" element={<StoragePage />} />
        <Route path="system" element={<SystemPage />} />
        <Route path="standards" element={<StandardsPage />} />
        <Route path="announcements" element={<AnnouncementsPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="admins" element={isSuper ? <AdminsPage /> : <Navigate to="/" replace />} />
        <Route path="account" element={<AccountPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

export default function AdminApp() {
  return (
    <BrowserRouter basename="/admin">
      <AdminAuthProvider>
        <UiProvider>
          <Gate />
        </UiProvider>
      </AdminAuthProvider>
    </BrowserRouter>
  );
}
