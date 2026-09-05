import { useEffect, useState, type ComponentType, type FormEvent, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { api, type Notification } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Avatar } from "./ui/Avatar";
import { IconAlert, IconBell, IconChart, IconChevronRight, IconDashboard, IconKnowledge, IconLayers, IconLogout, IconMenu, IconPlug, IconPlus, IconQueue, IconSearch, IconSettings, IconShield, IconSparkle } from "./icons";
import { Drawer } from "./ui/Dialog";
import { IconButton } from "./ui/Button";
import { Breadcrumbs } from "./ui/Utility";

type IconType = ComponentType<{ size?: number }>;

const labels: Record<string, string> = {
  customer: "Customer", support_agent: "Support Agent", reviewer: "Senior Reviewer",
  knowledge_manager: "Knowledge Manager", team_lead: "Team Lead",
  system_admin: "System Administrator", auditor: "Compliance Auditor",
  manager: "Manager", enterprise_admin: "Enterprise Admin", ai_admin: "AI Administrator",
  security_admin: "Security Administrator", end_user: "Customer",
  department_engineer: "Support Agent", admin: "Enterprise Admin",
};

const navByRole: Record<string, Array<[string, IconType, string]>> = {
  customer: [["/dashboard", IconDashboard, "Overview"], ["/tickets", IconQueue, "My Tickets"], ["/knowledge", IconKnowledge, "Knowledge"], ["/notifications", IconBell, "Notifications"]],
  support_agent: [["/agent", IconDashboard, "Command Center"], ["/queue", IconQueue, "My Queue"], ["/ai", IconSparkle, "AI Intelligence"], ["/pipeline", IconLayers, "AI Pipeline"], ["/knowledge", IconKnowledge, "Knowledge"], ["/escalations", IconAlert, "Escalations"]],
  reviewer: [["/review", IconQueue, "Review Queue"], ["/analytics", IconChart, "Analytics"], ["/pipeline", IconLayers, "AI Pipeline"], ["/knowledge", IconKnowledge, "Knowledge"], ["/notifications", IconBell, "Notifications"]],
  knowledge_manager: [["/knowledge", IconKnowledge, "Documents"], ["/queue", IconQueue, "Approval Queue"], ["/pipeline", IconLayers, "AI Pipeline"], ["/reports", IconAlert, "Knowledge Gaps"]],
  team_lead: [["/operations", IconDashboard, "Team Operations"], ["/analytics", IconChart, "Analytics"], ["/reports", IconChart, "SLA Analytics"], ["/pipeline", IconLayers, "AI Pipeline"], ["/incidents", IconAlert, "Incidents"], ["/knowledge", IconKnowledge, "Knowledge Gaps"]],
  system_admin: [["/admin", IconDashboard, "Administration"], ["/analytics", IconChart, "Analytics"], ["/integrations", IconPlug, "Integrations"], ["/pipeline", IconLayers, "AI Pipeline"], ["/audit", IconShield, "Audit Logs"], ["/settings", IconSettings, "Settings"]],
  auditor: [["/audit", IconShield, "Audit Logs"], ["/pipeline", IconLayers, "AI Pipeline"], ["/notifications", IconBell, "Compliance Events"]],
  ai_admin: [["/dashboard", IconSparkle, "AI Overview"], ["/ai", IconChart, "Agent Performance"], ["/reports", IconKnowledge, "Evaluations"], ["/settings", IconSettings, "Configuration"]],
};

const aliases: Record<string, string> = {
  end_user: "customer", department_engineer: "support_agent", manager: "team_lead",
  enterprise_admin: "system_admin", security_admin: "auditor", admin: "system_admin",
};

const sectionLabels: Record<string, string> = {
  dashboard: "Overview", portal: "Overview", agent: "Command Center", queue: "Queue", review: "Review Queue",
  operations: "Team Operations", admin: "Administration", tickets: "Tickets", knowledge: "Knowledge",
  incidents: "Incidents", notifications: "Notifications", ai: "AI Intelligence", reports: "Reports", analytics: "Analytics",
  audit: "Audit Logs", integrations: "Integrations", settings: "Settings", escalations: "Escalations", pipeline: "AI Pipeline",
};

export function navigationForRole(role: string) {
  return navByRole[aliases[role] || role] || navByRole.customer;
}

function navigationForUser(user: { role:string; public_role?:string; permissions:string[] } | null) {
  if (!user) return navByRole.customer;
  const canonical = aliases[user.role] || user.role;
  const experience = user.public_role || (canonical === "customer" ? "customer" : canonical === "support_agent" ? "engineer" : "admin");
  if (experience === "customer") return [["/customer", IconDashboard, "Overview"], ["/tickets", IconQueue, "My Tickets"], ["/knowledge", IconKnowledge, "Knowledge Base"], ["/notifications", IconBell, "Notifications"]] as Array<[string,IconType,string]>;
  if (experience === "engineer") return [["/engineer", IconDashboard, "Command Centre"], ["/queue", IconQueue, "My Queue"], ["/tickets", IconQueue, "Department Queue"], ["/knowledge", IconKnowledge, "Knowledge"], ["/analytics", IconChart, "Analytics"]] as Array<[string,IconType,string]>;
  const granted = new Set(user.permissions);
  const admin: Array<[string,IconType,string,string?]> = [
    ["/admin", IconDashboard, "Overview"], ["/tickets", IconQueue, "Tickets", "ticket:read_all"],
    ["/admin/engineers", IconSettings, "Engineers", "user:manage"], ["/review", IconAlert, "AI Review", "review:manage"],
    ["/incidents", IconAlert, "Incidents", "incident:manage"], ["/knowledge", IconKnowledge, "Knowledge", "knowledge:manage"],
    ["/admin/playbooks", IconLayers, "Playbooks", "playbook:manage"],
    ["/analytics", IconChart, "Analytics", "analytics:all"], ["/audit", IconShield, "Audit", "audit:read"],
    ["/settings", IconPlug, "Settings", "integration:manage"],
  ];
  return admin.filter(([, , , permission]) => !permission || granted.has(permission)).map(([to, icon, label]) => [to, icon, label] as [string,IconType,string]);
}

function useBreadcrumbs() {
  const location = useLocation();
  const segments = location.pathname.split("/").filter(Boolean);
  if (segments.length === 0) return [{ label: "Overview" }];
  const items = [{ label: sectionLabels[segments[0]] || segments[0], to: segments.length > 1 ? `/${segments[0]}` : undefined }];
  if (segments[0] === "tickets" && segments[1] === "new") items.push({ label: "New ticket", to: undefined });
  else if (segments[0] === "tickets" && segments[1]) items.push({ label: `Ticket ${segments[1].slice(0, 8)}`, to: undefined });
  return items;
}

function NavList({ nav, onNavigate }: { nav: Array<[string, IconType, string]>; onNavigate?: () => void }) {
  return (
    <nav aria-label="Primary">
      {nav.map(([to, Icon, label]) => (
        <NavLink to={to} className={({ isActive }) => (isActive ? "active" : "")} key={to} onClick={onNavigate}>
          <span className="nav-icon"><Icon size={17} /></span>
          <span className="nav-label">{label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

export default function Shell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [q, setQ] = useState("");
  const [notes, setNotes] = useState<Notification[]>([]);
  const [showNotes, setShowNotes] = useState(false);
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("ts_sidebar_collapsed") === "1");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const role = aliases[user?.role || ""] || user?.role || "customer";
  const experience = user?.public_role || (role === "customer" ? "customer" : role === "support_agent" ? "engineer" : "admin");
  const nav = navigationForUser(user);
  const crumbs = useBreadcrumbs();

  useEffect(() => { api.notifications().then(setNotes).catch(() => setNotes([])); }, []);
  useEffect(() => { setDrawerOpen(false); }, [location.pathname]);
  useEffect(() => { localStorage.setItem("ts_sidebar_collapsed", collapsed ? "1" : "0"); }, [collapsed]);

  function search(e: FormEvent) { e.preventDefault(); if (q.trim()) navigate(`/tickets?q=${encodeURIComponent(q.trim())}`); }
  async function read(note: Notification) {
    if (!note.is_read) {
      await api.markNotificationRead(note.id);
      setNotes(items => items.map(item => item.id === note.id ? { ...item, is_read: true } : item));
    }
  }

  return (
    <div className={`shell ${collapsed ? "sidebar-collapsed" : ""}`}>
      <aside aria-label="Sidebar navigation">
        <div className="brand">
          <div className="brandmark">T</div>
          <div><span>Ticket<em>Sense</em></span><small>AI SUPPORT INTELLIGENCE</small></div>
        </div>
        <div className="tenant"><i>T</i><div><b>Enterprise workspace</b><small>Tenant-isolated environment</small></div></div>
        <NavList nav={nav} />
        <div className="aside-bottom">
          <div className="ai-status"><span /><div><b>AI systems connected</b><small>Backend health monitored</small></div></div>
          <div className="profile">
            <Avatar name={user?.full_name || labels[role]} size={34} />
            <div><b>{user?.full_name || labels[role]}</b><small>{experience === "engineer" ? "Engineer" : experience === "admin" ? "Admin" : "Customer"}</small></div>
            <button onClick={logout} title="Sign out" aria-label="Sign out"><IconLogout size={17} /></button>
          </div>
          <button className="collapse-toggle" onClick={() => setCollapsed(v => !v)} aria-pressed={collapsed} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
            <IconChevronRight size={15} />
          </button>
        </div>
      </aside>

      <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} label="Navigation menu">
        <div className="brand"><div className="brandmark">T</div><div><span>Ticket<em>Sense</em></span></div></div>
        <NavList nav={nav} onNavigate={() => setDrawerOpen(false)} />
        <div className="aside-bottom">
          <div className="profile">
            <Avatar name={user?.full_name || labels[role]} size={34} />
            <div><b>{user?.full_name || labels[role]}</b><small>{experience === "engineer" ? "Engineer" : experience === "admin" ? "Admin" : "Customer"}</small></div>
            <button onClick={logout} title="Sign out" aria-label="Sign out"><IconLogout size={17} /></button>
          </div>
        </div>
      </Drawer>

      <main>
        <header>
          <div className="header-left">
            <IconButton label="Open navigation menu" className="menu-toggle" onClick={() => setDrawerOpen(true)}><IconMenu size={19} /></IconButton>
            <div>
              <Breadcrumbs items={[{ label: "TicketSense", to: "/dashboard" }, ...crumbs]} />
            </div>
          </div>
          <form className="search" onSubmit={search} role="search">
            <IconSearch size={15} aria-hidden="true" />
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search real tickets…" aria-label="Search tickets" />
            <kbd>Enter</kbd>
          </form>
          <div className="header-actions">
            <span className="role-label">{experience === "engineer" ? "Engineer" : experience === "admin" ? "Admin" : "Customer"}</span>
            <IconButton label="Notifications" onClick={() => setShowNotes(!showNotes)} active={showNotes} aria-expanded={showNotes} aria-haspopup="true">
              <IconBell size={17} />
              {notes.some(note => !note.is_read) && <i aria-hidden="true" />}
            </IconButton>
            {experience === "customer" && <button className="primary" onClick={() => navigate("/tickets/new")}><IconPlus size={15} />New ticket</button>}
            {showNotes && (
              <div className="notification-popover" role="dialog" aria-label="Notifications">
                <b>Notifications</b>
                {notes.length ? notes.slice(0, 5).map(note => (
                  <button key={note.id} className={note.is_read ? "read" : ""} onClick={() => read(note)}>
                    <strong>{note.title}</strong><span>{note.message}</span>
                  </button>
                )) : <p>No notifications.</p>}
                <NavLink to="/notifications" onClick={() => setShowNotes(false)}>View all</NavLink>
              </div>
            )}
          </div>
        </header>
        <div id="main-content" tabIndex={-1}>{children}</div>
      </main>
    </div>
  );
}
