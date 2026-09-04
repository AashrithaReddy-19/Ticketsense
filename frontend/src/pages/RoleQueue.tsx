import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type EngineerWorkload, type QueueTicket } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Badge, Empty, Loading, SyncIndicator } from "../components/States";
import { IconAlert } from "../components/icons";
import { Button } from "../components/ui/Button";
import { FilterBar, SearchInput } from "../components/ui/Utility";
import { useAutoRefresh } from "../lib/useAutoRefresh";

export default function RoleQueue() {
  const { user } = useAuth();
  const reviewer = user?.role === "reviewer";
  const lead = ["team_lead", "manager"].includes(user?.role || "");
  const tabs = reviewer
    ? [["review", "Awaiting review"]]
    : lead
      ? [["all", "Managed department"], ["escalated", "Escalated"]]
      : [["assigned", "Assigned to me"], ["department_triage", "Department triage"], ["all", "All authorized"], ["escalated", "Escalated"]];

  const [queue, setQueue] = useState(tabs[0][0]);
  const [items, setItems] = useState<QueueTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [priority, setPriority] = useState("");
  const [workloads, setWorkloads] = useState<EngineerWorkload[]>([]);

  async function load(opts: { silent?: boolean } = {}) {
    if (!opts.silent) { setLoading(true); setError(""); }
    try { setItems((await api.queue(queue)).items); if(lead)setWorkloads(await api.engineerWorkloads()); }
    catch (e) { if (!opts.silent) setError(e instanceof Error ? e.message : "Unable to load queue"); else throw e; }
    finally { if (!opts.silent) setLoading(false); }
  }
  useEffect(() => { load(); }, [queue, user?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const { status: syncStatus, lastSyncedAt, retryNow } = useAutoRefresh(() => load({ silent: true }), undefined, !loading && !error);

  async function accept(id: string) {
    try { await api.acceptTicket(id); setQueue("assigned"); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to accept ticket"); }
  }

  const filtered = useMemo(() => {
    let rows = items;
    if (q.trim()) { const needle = q.trim().toLowerCase(); rows = rows.filter(t => t.title.toLowerCase().includes(needle) || t.display_id.toLowerCase().includes(needle)); }
    if (priority) rows = rows.filter(t => t.priority === priority);
    return rows;
  }, [items, q, priority]);

  const title = reviewer ? "Reviewer queue" : lead ? "Team operations" : "Agent workspace";

  return (
    <div className="content">
      <div className="page-title"><div><h1>{title}</h1><p>Live tenant and department scoped tickets.</p></div><SyncIndicator status={syncStatus} lastSyncedAt={lastSyncedAt} onRetry={retryNow} /></div>
      <div className="tabs" role="tablist">
        {tabs.map(([key, label]) => <button key={key} role="tab" aria-selected={queue === key} className={queue === key ? "active" : ""} onClick={() => setQueue(key)}>{label}</button>)}
      </div>
      {lead && <section className="panel workload-panel"><div className="panel-head"><div><h2>Engineer workload</h2><p>Backend-calculated department capacity and ticket counts.</p></div></div>{workloads.length?<div className="table-scroll"><div className="list-head workload-row"><span>Engineer</span><span>Availability</span><span>Active / capacity</span><span>In progress</span><span>Review</span><span>Escalated</span></div>{workloads.map(row=><article className="list-row workload-row" key={row.id}><div><b>{row.name}</b><small>{row.specializations.join(", ")||row.department||"No specialization"}</small></div><Badge value={row.is_active&&row.is_available?"available":"unavailable"}/><span>{row.active_workload} / {row.capacity} ({row.capacity_percent}%)</span><span>{row.in_progress}</span><span>{row.under_review}</span><span>{row.escalated}</span></article>)}</div>:<Empty label="No engineers are configured for this department."/>}</section>}

      <FilterBar>
        <SearchInput value={q} onChange={setQ} placeholder="Search ticket title or ID" />
        <select value={priority} onChange={e => setPriority(e.target.value)} aria-label="Filter by priority">
          <option value="">All priorities</option>
          <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="urgent">Urgent</option>
        </select>
        {(q || priority) && <Button variant="ghost" size="sm" onClick={() => { setQ(""); setPriority(""); }}>Clear filters</Button>}
      </FilterBar>

      {error && <div className="error-box" role="alert">{error}</div>}
      {loading ? <Loading skeleton /> : filtered.length ? (
        <>
          <p className="result-count">{filtered.length} of {items.length} tickets</p>
          <div className="panel ticket-list queue-sticky table-scroll">
            <div className="list-head queue-row"><span>Ticket</span><span>Priority</span><span>Confidence</span><span>Status</span><span>Actions</span></div>
            {filtered.map(t => (
              <article className={`list-row queue-row ${t.priority === "urgent" ? "is-urgent" : ""}`} key={t.id}>
                <div>
                  <Link to={`/tickets/${t.id}`}><b>{t.priority === "urgent" && <IconAlert size={13} className="urgent-icon" />}{t.title}</b></Link>
                  <small>{t.display_id} · {new Date(t.created_at).toLocaleString()}</small>
                  <small>{t.review_reason || `${t.sla_state} · ${t.analysis_status}`}</small>
                </div>
                <Badge value={t.priority} />
                <span className="confidence-band">{t.confidence_band}</span>
                <Badge value={t.status} />
                <div className="queue-actions">
                  {!reviewer && !lead && queue === "department_triage" && <Button variant="outline" size="sm" onClick={() => accept(t.id)}>Accept</Button>}
                  {reviewer && (
                    <div className="review-actions">
                      <Link className="ui-btn ui-btn-primary ui-btn-sm" to={`/tickets/${t.id}`}>Open review</Link>
                    </div>
                  )}
                </div>
              </article>
            ))}
          </div>
        </>
      ) : <Empty label={items.length ? "No tickets match these filters." : "No tickets in this authorized queue."} />}

    </div>
  );
}
