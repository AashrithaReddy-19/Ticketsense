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

function Planned({ title }: { title: string }) {
  return <div className="content"><div className="page-title"><div><h1>{title}</h1><p>This protected module is planned and currently in progress.</p></div></div></div>;
}

export function Protected() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Loading label="Restoring secure session..." />;
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  return <Shell><Routes>
    <Route path="/dashboard" element={<Dashboard />} />
    <Route path="/portal" element={<RoleRoute roles={["customer"]}><Dashboard /></RoleRoute>} />
    <Route path="/agent" element={<RoleRoute roles={["support_agent"]}><RoleQueue /></RoleRoute>} />
    <Route path="/review" element={<RoleRoute roles={["reviewer"]}><RoleQueue /></RoleRoute>} />
    <Route path="/operations" element={<RoleRoute roles={["team_lead"]}><RoleQueue /></RoleRoute>} />
    <Route path="/admin" element={<RoleRoute roles={["system_admin"]}><Planned title="Administration console" /></RoleRoute>} />
    <Route path="/tickets" element={<Tickets />} />
    <Route path="/queue" element={<Tickets />} />
    <Route path="/escalations" element={<Tickets escalated />} />
    <Route path="/tickets/new" element={<NewTicket />} />
    <Route path="/tickets/:id" element={<TicketWorkspace />} />
    <Route path="/knowledge" element={<Knowledge />} />
    <Route path="/incidents" element={<Incidents />} />
    <Route path="/notifications" element={<Notifications />} />
    <Route path="/ai" element={<RoleRoute roles={["support_agent", "team_lead", "system_admin"]}><AIMetrics /></RoleRoute>} />
    <Route path="/reports" element={<RoleRoute roles={["knowledge_manager", "team_lead", "system_admin"]}><AIMetrics /></RoleRoute>} />
    <Route path="/pipeline" element={<RoleRoute roles={["support_agent", "reviewer", "team_lead", "knowledge_manager", "system_admin", "auditor"]}><KnowledgePipeline /></RoleRoute>} />
    <Route path="/audit" element={<RoleRoute roles={["auditor", "system_admin"]}><Audit /></RoleRoute>} />
    <Route path="/integrations" element={<RoleRoute roles={["system_admin"]}><Integrations /></RoleRoute>} />
    <Route path="/settings" element={<RoleRoute roles={["system_admin"]}><Planned title="Settings" /></RoleRoute>} />
    <Route path="*" element={<Navigate to="/dashboard" replace />} />
  </Routes></Shell>;
}

export default function App() {
  return <BrowserRouter><ToastProvider><AuthProvider><a href="#main-content" className="ui-skip-link">Skip to content</a><Routes>
    <Route path="/login" element={<Login />} />
    <Route path="/*" element={<Protected />} />
  </Routes></AuthProvider></ToastProvider></BrowserRouter>;
}
