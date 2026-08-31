import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { api, type Notification } from "../api/client";
import { useAuth } from "../auth/AuthContext";

const labels: Record<string, string> = {
  customer: "Customer", support_agent: "Support Agent", reviewer: "Senior Reviewer",
  knowledge_manager: "Knowledge Manager", team_lead: "Team Lead",
  system_admin: "System Administrator", auditor: "Compliance Auditor",
  manager: "Manager", enterprise_admin: "Enterprise Admin", ai_admin: "AI Administrator",
  security_admin: "Security Administrator", end_user: "Customer",
  department_engineer: "Support Agent", admin: "Enterprise Admin",
};

const navByRole: Record<string, Array<[string, string, string]>> = {
  customer: [["/dashboard", "◫", "Overview"], ["/tickets", "⌁", "My Tickets"], ["/knowledge", "▤", "Knowledge"], ["/notifications", "◉", "Notifications"]],
  support_agent: [["/agent", "◫", "Command Center"], ["/queue", "⌁", "My Queue"], ["/ai", "✦", "AI Intelligence"], ["/knowledge", "▤", "Knowledge"], ["/escalations", "△", "Escalations"]],
  reviewer: [["/review", "⌁", "Review Queue"], ["/knowledge", "▤", "Knowledge"], ["/notifications", "◉", "Notifications"]],
  knowledge_manager: [["/knowledge", "▤", "Documents"], ["/queue", "⌁", "Approval Queue"], ["/reports", "△", "Knowledge Gaps"]],
  team_lead: [["/operations", "◫", "Team Operations"], ["/reports", "▥", "SLA Analytics"], ["/incidents", "△", "Incidents"], ["/knowledge", "▤", "Knowledge Gaps"]],
  system_admin: [["/admin", "◫", "Administration"], ["/integrations", "⚙", "Integrations"], ["/audit", "▤", "Audit Logs"], ["/settings", "⚙", "Settings"]],
  auditor: [["/audit", "▤", "Audit Logs"], ["/notifications", "◉", "Compliance Events"]],
  ai_admin: [["/dashboard", "✦", "AI Overview"], ["/ai", "▥", "Agent Performance"], ["/reports", "▤", "Evaluations"], ["/settings", "⚙", "Configuration"]],
};

const aliases: Record<string, string> = {
  end_user: "customer", department_engineer: "support_agent", manager: "team_lead",
  enterprise_admin: "system_admin", security_admin: "auditor", admin: "system_admin",
};

export function navigationForRole(role: string) {
  return navByRole[aliases[role] || role] || navByRole.customer;
}

export default function Shell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [notes, setNotes] = useState<Notification[]>([]);
  const [showNotes, setShowNotes] = useState(false);
  const role = aliases[user?.role || ""] || user?.role || "customer";
  const nav = navigationForRole(role);

  useEffect(() => { api.notifications().then(setNotes).catch(() => setNotes([])); }, []);
  function search(e: FormEvent) { e.preventDefault(); if (q.trim()) navigate(`/tickets?q=${encodeURIComponent(q.trim())}`); }
  async function read(note: Notification) {
    if (!note.is_read) {
      await api.markNotificationRead(note.id);
      setNotes(items => items.map(item => item.id === note.id ? { ...item, is_read: true } : item));
    }
  }

  return <div className="shell"><aside>
    <div className="brand"><div className="brandmark">T</div><div>Ticket<span>Sense</span><small>AI SUPPORT INTELLIGENCE</small></div></div>
    <div className="tenant"><i>T</i><div><b>Enterprise workspace</b><small>Tenant-isolated environment</small></div></div>
    <nav>{nav.map(([to, icon, label]) => <NavLink to={to} className={({ isActive }) => isActive ? "active" : ""} key={to}><span className="nav-icon">{icon}</span>{label}</NavLink>)}</nav>
    <div className="aside-bottom"><div className="ai-status"><span /><div><b>AI systems connected</b><small>Backend health monitored</small></div></div>
      <div className="profile"><div className="avatar">{(user?.full_name || labels[role] || "U").split(" ").map(part => part[0]).slice(0, 2).join("")}</div><div><b>{user?.full_name || labels[role]}</b><small>{labels[user?.role || ""] || user?.role}</small></div><button onClick={logout} title="Sign out">↪</button></div>
    </div>
  </aside><main><header>
    <form className="search" onSubmit={search}><span>⌕</span><input value={q} onChange={e => setQ(e.target.value)} placeholder="Search real tickets..." /><kbd>Enter</kbd></form>
    <div className="header-actions"><span className="role-label">{labels[user?.role || ""] || user?.role}</span><button className="icon-button" onClick={() => setShowNotes(!showNotes)} aria-label="Notifications">◉{notes.some(note => !note.is_read) && <i />}</button><button className="primary" onClick={() => navigate("/tickets/new")}>＋ New ticket</button>
      {showNotes && <div className="notification-popover"><b>Notifications</b>{notes.length ? notes.slice(0, 5).map(note => <button key={note.id} className={note.is_read ? "read" : ""} onClick={() => read(note)}><strong>{note.title}</strong><span>{note.message}</span></button>) : <p>No notifications.</p>}<NavLink to="/notifications" onClick={() => setShowNotes(false)}>View all</NavLink></div>}
    </div>
  </header>{children}</main></div>;
}
