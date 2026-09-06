import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import Shell from "./components/Shell";
import Dashboard from "./pages/Dashboard";
import Tickets from "./pages/Tickets";
import NewTicket from "./pages/NewTicket";
import TicketWorkspace from "./pages/TicketWorkspace";
import Knowledge from "./pages/Knowledge";
import Incidents from "./pages/Incidents";
import Notifications from "./pages/Notifications";
import Login from "./pages/Login";
import RoleQueue from "./pages/RoleQueue";
import { AIMetrics, Audit, Integrations } from "./pages/AdminData";
import KnowledgePipeline from "./pages/KnowledgePipeline";
import AdminEngineers from "./pages/AdminEngineers";
import AdminKnowledge from "./pages/AdminKnowledge";
import AdminPlaybooks from "./pages/AdminPlaybooks";
import AdminSafeActions from "./pages/AdminSafeActions";
import AdminPrevention from "./pages/AdminPrevention";
import AnalyticsDashboard from "./pages/AnalyticsDashboard";
import AdminPortal from "./pages/AdminPortal";
import AdminV2Governance from "./pages/AdminV2Governance";
import AdminEvaluationLab from "./pages/AdminEvaluationLab";
import { Loading } from "./components/States";
import { ToastProvider } from "./components/ui/Toast";
import "./tokens.css";
import "./components/ui/ui.css";
import "./styles.css";

const aliases: Record<string, string> = {
  manager: "team_lead",
  enterprise_admin: "system_admin",
  security_admin: "auditor",
  end_user: "customer",
  department_engineer: "support_agent",
  admin: "system_admin",
};

export function RoleRoute({ roles, children }: { roles: string[]; children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <Loading label="Checking permissions..." />;
  const role = aliases[user?.role || ""] || user?.role;
  if (!role || !roles.includes(role)) {
    return <div className="content"><div className="error-box"><h2>Access denied</h2><p>Your account does not have permission to open this module.</p></div></div>;
  }
  return <>{children}</>;
}

export function CapabilityRoute({ anyOf, children }: { anyOf: string[]; children: React.ReactNode }) {
  const { user, loading, hasPermission } = useAuth();
  if (loading) return <Loading label="Checking permissions..." />;
  if (!user || !anyOf.some(hasPermission)) return <div className="content"><div className="error-box"><h2>Access denied</h2><p>Your account does not have the required capability for this module.</p></div></div>;
  return <>{children}</>;
}

export function KnowledgeRoute() {
  const { hasPermission } = useAuth();
  return hasPermission("knowledge:manage") ? <AdminKnowledge /> : <Knowledge />;
}

function publicExperience(role: string, declared?: string) {
  if (declared) return declared;
  const canonical = aliases[role] || role;
  return canonical === "customer" ? "customer" : canonical === "support_agent" ? "engineer" : "admin";
}

export function Protected() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Loading label="Restoring secure session..." />;
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  return <Shell><Routes>
    <Route path="/dashboard" element={<Dashboard />} />
    <Route path="/customer" element={publicExperience(user.role, user.public_role) === "customer" ? <Dashboard /> : <Navigate to={`/${publicExperience(user.role, user.public_role)}`} replace />} />
    <Route path="/engineer" element={publicExperience(user.role, user.public_role) === "engineer" ? <RoleQueue /> : <Navigate to={`/${publicExperience(user.role, user.public_role)}`} replace />} />
    <Route path="/admin" element={publicExperience(user.role, user.public_role) === "admin" ? <AdminPortal /> : <Navigate to={`/${publicExperience(user.role, user.public_role)}`} replace />} />
    <Route path="/portal" element={<Navigate to="/customer" replace />} />
    <Route path="/agent" element={<Navigate to="/engineer" replace />} />
    <Route path="/operations" element={<Navigate to="/admin" replace />} />
    <Route path="/review" element={<CapabilityRoute anyOf={["review:manage"]}><RoleQueue /></CapabilityRoute>} />
    <Route path="/admin/engineers" element={<CapabilityRoute anyOf={["user:manage"]}><AdminEngineers /></CapabilityRoute>} />
    <Route path="/admin/playbooks" element={<CapabilityRoute anyOf={["playbook:manage"]}><AdminPlaybooks /></CapabilityRoute>} />
    <Route path="/admin/safe-actions" element={<CapabilityRoute anyOf={["safe_action:execute"]}><AdminSafeActions /></CapabilityRoute>} />
    <Route path="/admin/prevention" element={<CapabilityRoute anyOf={["prevention:manage"]}><AdminPrevention /></CapabilityRoute>} />
    <Route path="/admin/ai-governance" element={<CapabilityRoute anyOf={["feature:read", "model:read", "observability:read"]}><AdminV2Governance /></CapabilityRoute>} />
    <Route path="/admin/evaluation-lab" element={<CapabilityRoute anyOf={["evaluation:read", "dataset:read"]}><AdminEvaluationLab /></CapabilityRoute>} />
    <Route path="/analytics" element={<CapabilityRoute anyOf={["analytics:department", "analytics:all", "ticket:internal_ai"]}><AnalyticsDashboard /></CapabilityRoute>} />
    <Route path="/tickets" element={<Tickets />} />
    <Route path="/queue" element={<Tickets />} />
    <Route path="/escalations" element={<Tickets escalated />} />
    <Route path="/tickets/new" element={<NewTicket />} />
    <Route path="/tickets/:id" element={<TicketWorkspace />} />
    <Route path="/knowledge" element={<KnowledgeRoute />} />
    <Route path="/incidents" element={<Incidents />} />
    <Route path="/notifications" element={<Notifications />} />
    <Route path="/ai" element={<CapabilityRoute anyOf={["ticket:internal_ai", "ai:monitor"]}><AIMetrics /></CapabilityRoute>} />
    <Route path="/reports" element={<CapabilityRoute anyOf={["analytics:all", "knowledge:manage"]}><AIMetrics /></CapabilityRoute>} />
    <Route path="/pipeline" element={<CapabilityRoute anyOf={["ticket:internal_ai", "knowledge:manage", "audit:read"]}><KnowledgePipeline /></CapabilityRoute>} />
    <Route path="/audit" element={<CapabilityRoute anyOf={["audit:read"]}><Audit /></CapabilityRoute>} />
    <Route path="/integrations" element={<CapabilityRoute anyOf={["integration:manage"]}><Integrations /></CapabilityRoute>} />
    <Route path="/settings" element={<CapabilityRoute anyOf={["integration:manage", "policy:manage"]}><Integrations /></CapabilityRoute>} />
    <Route path="*" element={<Navigate to={`/${publicExperience(user.role, user.public_role)}`} replace />} />
  </Routes></Shell>;
}

export default function App() {
  return <BrowserRouter><ToastProvider><AuthProvider><a href="#main-content" className="ui-skip-link">Skip to content</a><Routes>
    <Route path="/login" element={<Login />} />
    <Route path="/*" element={<Protected />} />
  </Routes></AuthProvider></ToastProvider></BrowserRouter>;
}
