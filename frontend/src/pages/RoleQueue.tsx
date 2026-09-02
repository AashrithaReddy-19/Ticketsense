import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type QueueTicket } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Badge, Empty, Loading } from "../components/States";
import { IconAlert } from "../components/icons";
import { Button } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/Dialog";
import { FilterBar, SearchInput } from "../components/ui/Utility";

const DECISIONS = ["approve", "modify", "reject", "return"] as const;
type Decision = (typeof DECISIONS)[number];

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
  const [pending, setPending] = useState<{ id: string; decision: Decision } | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true); setError("");
    try { setItems((await api.queue(queue)).items); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to load queue"); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [queue, user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function accept(id: string) {
    try { await api.acceptTicket(id); setQueue("assigned"); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to accept ticket"); }
  }

  async function confirmDecision() {
    if (!pending) return;
    if (reason.trim().length < 3) return;
    setBusy(true);
    try { await api.reviewTicket(pending.id, { decision: pending.decision, reason: reason.trim() }); await load(); setPending(null); setReason(""); }
    catch (e) { setError(e instanceof Error ? e.message : "Review failed"); }
    finally { setBusy(false); }
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
      <div className="page-title"><div><h1>{title}</h1><p>Live tenant and department scoped tickets.</p></div></div>
      <div className="tabs" role="tablist">
        {tabs.map(([key, label]) => <button key={key} role="tab" aria-selected={queue === key} className={queue === key ? "active" : ""} onClick={() => setQueue(key)}>{label}</button>)}
      </div>

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
                      {DECISIONS.map(d => <button key={d} onClick={() => { setPending({ id: t.id, decision: d }); setReason(""); }}>{d}</button>)}
                    </div>
                  )}
                </div>
              </article>
            ))}
          </div>
        </>
      ) : <Empty label={items.length ? "No tickets match these filters." : "No tickets in this authorized queue."} />}

      <ConfirmDialog
        open={!!pending}
        onClose={() => { setPending(null); setReason(""); }}
        onConfirm={confirmDecision}
        title={pending ? `${pending.decision.charAt(0).toUpperCase()}${pending.decision.slice(1)} this ticket` : ""}
        description="A review reason is required and is recorded on the ticket's history."
        confirmLabel="Submit decision"
        variant={pending?.decision === "reject" ? "destructive" : "primary"}
        busy={busy}
        requireReason
        reason={reason}
        onReasonChange={setReason}
      />
    </div>
  );
}
