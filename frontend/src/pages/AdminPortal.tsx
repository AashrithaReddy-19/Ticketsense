import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { IconAlert, IconChart, IconKnowledge, IconLayers, IconPlug, IconQueue, IconSettings, IconShield, IconSparkle } from "../components/icons";

const modules = [
  { capability: "ticket:read_all", to: "/tickets", title: "Tickets & queues", detail: "Assignment, escalation, reopened, SLA-risk and failed-processing work.", icon: IconQueue },
  { capability: "user:manage", to: "/admin/engineers", title: "Engineers", detail: "Accounts, departments, skills, availability, capacity and workload.", icon: IconSettings },
  { capability: "review:manage", to: "/review", title: "AI review", detail: "Review drafts, grounding warnings and low-confidence decisions.", icon: IconAlert },
  { capability: "incident:manage", to: "/incidents", title: "Incidents", detail: "Investigate tenant-scoped ticket clusters and emerging incidents.", icon: IconAlert },
  { capability: "knowledge:manage", to: "/knowledge", title: "Knowledge", detail: "Govern approved, versioned and publishable support evidence.", icon: IconKnowledge },
  { capability: "playbook:manage", to: "/admin/playbooks", title: "Playbooks", detail: "Versioned resolution playbooks for recurring issues, gated by the policy engine.", icon: IconLayers },
  { capability: "safe_action:execute", to: "/admin/safe-actions", title: "Safe actions", detail: "Allowlisted, audited actions with dry-run, confirmation, and risk-based approval.", icon: IconSparkle },
  { capability: "prevention:manage", to: "/admin/prevention", title: "Predictive prevention", detail: "Evidence-backed recommendations from real tenant trends — never a confirmed cause.", icon: IconChart },
  { capability: "feature:read", to: "/admin/ai-governance", title: "V2 AI governance", detail: "Feature rollout, emergency kill switches, immutable model versions and measured provider usage.", icon: IconShield },
  { capability: "evaluation:read", to: "/admin/evaluation-lab", title: "Evaluation lab", detail: "Leakage-safe dataset registry and reproducible classification evaluation runs — real metrics, never sample data.", icon: IconChart },
  { capability: "analytics:all", to: "/analytics", title: "Analytics", detail: "Live operational, confidence, workflow and workload metrics.", icon: IconChart },
  { capability: "audit:read", to: "/audit", title: "Audit & compliance", detail: "Search immutable security and workflow events.", icon: IconShield },
  { capability: "integration:manage", to: "/integrations", title: "Settings & integrations", detail: "Inspect connector status without exposing stored configuration.", icon: IconPlug },
];

export default function AdminPortal() {
  const { user, hasPermission } = useAuth();
  const visible = modules.filter(module => hasPermission(module.capability));
  return <div className="content">
    <div className="welcome"><div><p className="eyebrow">Capability-scoped administration</p><h1>Admin overview</h1><p>{user?.full_name}, manage only the modules granted to this account.</p></div><div className="live"><span />Tenant isolation active</div></div>
    <section className="admin-module-grid" aria-label="Admin modules">
      {visible.map(({ capability, to, title, detail, icon: Icon }) => <Link className="panel admin-module-card" to={to} key={capability}>
        <div className="incident-icon"><Icon size={18} /></div><div><h2>{title}</h2><p>{detail}</p><small>{capability}</small></div>
      </Link>)}
    </section>
  </div>;
}
