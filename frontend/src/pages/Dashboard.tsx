import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Analytics, type Incident, type Ticket } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Badge, Empty, ErrorState, Loading } from "../components/States";
import { IconAlert, IconCheckCircle, IconLayers, IconPlus, IconTickets } from "../components/icons";
import { StatCard } from "../components/ui/Card";
import { Button } from "../components/ui/Button";

export default function Dashboard() {
  const { user, hasPermission } = useAuth();
  const internal = hasPermission("ai:view_summary") || hasPermission("analytics:department");
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [stats, setStats] = useState<Analytics | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true); setError("");
    try {
      const t = await api.tickets();
      setTickets(t);
      if (internal) {
        const results = await Promise.allSettled([api.analytics(), api.incidents()]);
        if (results[0].status === "fulfilled") setStats(results[0].value);
        if (results[1].status === "fulfilled") setIncidents(results[1].value);
      }
    } catch (e) { setError(e instanceof Error ? e.message : "Request failed"); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [internal]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <div className="content"><Loading label="Loading dashboard…" /></div>;
  if (error) return <div className="content"><ErrorState message={error} onRetry={load} /></div>;

  const open = tickets.filter(x => !["resolved", "closed"].includes(x.status)).length;
  const inReview = tickets.filter(x => x.status === "pending_review").length;
  const resolved = tickets.filter(x => x.status === "resolved" || x.status === "closed").length;

  return (
    <div className="content">
      <div className="welcome">
        <div>
          <p className="eyebrow">Live ticket data</p>
          <h1>{internal ? "Support command center" : `Welcome, ${user?.full_name || "Customer"}`}</h1>
          <p>{internal ? "Operational intelligence from the TicketSense backend." : "Create requests and track their status from one place."}</p>
        </div>
        <div className="welcome-actions">
          <div className="live"><span />Backend connected</div>
          {!internal && <Button variant="primary" icon={<IconPlus size={15} />} onClick={() => (window.location.href = "/tickets/new")}>Create ticket</Button>}
        </div>
      </div>

      <section className="metrics">
        <StatCard label={internal ? "Open tickets" : "My open tickets"} value={String(stats?.open_tickets ?? open)} sub={`${stats?.total_tickets ?? tickets.length} total`} icon={<IconTickets size={18} />} tone="violet" />
        {!internal && <StatCard label="In review" value={String(inReview)} sub="Awaiting a response" icon={<IconLayers size={18} />} tone="info" />}
        <StatCard label="Resolved" value={String(stats?.resolved_tickets ?? resolved)} sub="Completed requests" icon={<IconCheckCircle size={18} />} tone="success" />
        {internal && <>
          <StatCard label="Escalated" value={String(stats?.escalated_tickets || 0)} sub="Requires expert attention" icon={<IconAlert size={18} />} tone="danger" />
          <StatCard label="Avg. confidence" value={`${Math.round((stats?.average_confidence || 0) * 100)}%`} sub="Authorized internal metric" icon={<IconLayers size={18} />} tone="info" />
        </>}
      </section>

      <section className="grid">
        <div className="panel queue">
          <div className="panel-head">
            <div><h2>{internal ? "Priority queue" : "Recent tickets"}</h2><p>{internal ? "Authorized department tickets" : "Tickets created by your account"}</p></div>
            <Link to="/tickets">View all →</Link>
          </div>
          {tickets.length ? (
            <div className="real-table table-scroll">
              {tickets.slice(0, 8).map(t => (
                <Link to={`/tickets/${t.id}`} className="real-ticket-row" key={t.id}>
                  <div><b>{t.subject}</b><small>{t.id.slice(0, 8)}{internal && t.analysis.category ? ` · ${t.analysis.category}` : ""}</small></div>
                  <Badge value={t.priority} />
                  {internal && <strong>{Math.round((t.confidence_score || 0) * 100)}%</strong>}
                  <Badge value={t.status} />
                </Link>
              ))}
            </div>
          ) : <Empty label="No tickets yet. Create your first support request." action={!internal && <Link to="/tickets/new" className="ui-btn ui-btn-primary ui-btn-sm">Create a ticket</Link>} />}
        </div>
        {internal && (
          <div className="panel incident">
            <div className="panel-head"><div><h2>Emerging incidents</h2><p>Backend-detected clusters</p></div><Link to="/incidents">View incidents</Link></div>
            {incidents.length ? incidents.slice(0, 4).map(i => (
              <article key={i.id}>
                <div className="incident-icon"><IconAlert size={15} /></div>
                <div><Badge value={i.severity} /><h3>{i.title}</h3><p>{i.ticket_count} related tickets · {i.service}</p></div>
              </article>
            )) : <Empty label="No active incidents." />}
          </div>
        )}
      </section>
    </div>
  );
}
