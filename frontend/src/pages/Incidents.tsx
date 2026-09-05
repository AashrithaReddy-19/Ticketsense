import { useEffect, useState } from "react";
import { api, type Incident, type IncidentTicketSummary, type RootCauseHypothesis } from "../api/client";
import { Badge, Empty, ErrorState, Loading } from "../components/States";
import { IconRefresh } from "../components/icons";
import { Button } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";

const STATUS_TABS: Array<[string, string]> = [["", "All"], ["candidate", "Needs confirmation"], ["investigating", "Investigating"], ["resolved", "Resolved"], ["dismissed", "Dismissed"]];

function IncidentDetail({ incident, onChanged }: { incident: Incident; onChanged: () => void }) {
  const toast = useToast();
  const [tickets, setTickets] = useState<IncidentTicketSummary[] | null>(null);
  const [hypothesis, setHypothesis] = useState<RootCauseHypothesis | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.incidentTickets(incident.id).then(setTickets).catch(() => setTickets([]));
    api.incidentRootCause(incident.id).then(setHypothesis).catch(() => setHypothesis(null));
  }, [incident.id]);

  async function act(action: "confirm" | "dismiss" | "resolve" | "notify") {
    setBusy(true);
    try {
      if (action === "confirm") await api.confirmIncident(incident.id);
      else if (action === "dismiss") await api.dismissIncident(incident.id);
      else if (action === "resolve") await api.resolveIncident(incident.id);
      else { const result = await api.notifyIncidentCustomers(incident.id); toast(`Notified ${result.notified} customer(s)`, "success"); }
      if (action !== "notify") { toast(`Incident ${action}ed`, "success"); onChanged(); }
    } catch (err) { toast(err instanceof Error ? err.message : `Unable to ${action} this incident`, "danger"); }
    finally { setBusy(false); }
  }

  return (
    <div className="incident-detail">
      {incident.detection_reason && <p className="empty-note">{incident.detection_reason}</p>}
      {hypothesis && (
        <div className="recommendation">
          <b>Root-cause hypothesis</b> — <em>{hypothesis.disclaimer}</em>
          {hypothesis.likely_symptom && <p>Likely symptom: {hypothesis.likely_symptom}</p>}
          {hypothesis.recurring_error_codes.length > 0 && <p>Recurring codes: {hypothesis.recurring_error_codes.map(c => `${c.code} (${c.occurrences})`).join(", ")}</p>}
        </div>
      )}
      {tickets && (tickets.length ? (
        <ul>{tickets.map(t => <li key={t.id}>{t.subject} — <Badge value={t.status} /></li>)}</ul>
      ) : <p className="empty-note">No linked tickets.</p>)}
      <div className="review-actions">
        {incident.status === "candidate" && <>
          <Button size="sm" variant="primary" loading={busy} onClick={() => act("confirm")}>Confirm incident</Button>
          <Button size="sm" variant="outline" loading={busy} onClick={() => act("dismiss")}>Dismiss</Button>
        </>}
        {(incident.status === "investigating") && <>
          <Button size="sm" variant="outline" loading={busy} onClick={() => act("notify")}>Notify customers</Button>
          <Button size="sm" variant="primary" loading={busy} onClick={() => act("resolve")}>Mark resolved</Button>
        </>}
      </div>
    </div>
  );
}

export default function Incidents() {
  const [statusFilter, setStatusFilter] = useState("");
  const [items, setItems] = useState<Incident[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState("");
  const toast = useToast();

  async function load() {
    setLoading(true);
    try { setItems(await api.incidents(statusFilter)); setError(""); }
    catch (e) { setError(e instanceof Error ? e.message : "Request failed"); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [statusFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  async function scan() {
    setScanning(true);
    try { const found = await api.scanForIncidents(); toast(`Scan complete — ${found.length} candidate incident(s)`, "success"); await load(); }
    catch (err) { toast(err instanceof Error ? err.message : "Scan failed", "danger"); }
    finally { setScanning(false); }
  }

  return (
    <div className="content">
      <div className="page-title">
        <div><h1>Incidents</h1><p>Duplicate-ticket clusters, auto-detected and Admin-confirmable before being declared.</p></div>
        <div style={{ display: "flex", gap: 8 }}>
          <Button variant="outline" loading={scanning} onClick={scan}>Scan now</Button>
          <Button variant="outline" icon={<IconRefresh size={14} />} onClick={load}>Refresh</Button>
        </div>
      </div>
      <div className="tabs" role="tablist">
        {STATUS_TABS.map(([key, label]) => <button key={key} role="tab" aria-selected={statusFilter === key} className={statusFilter === key ? "active" : ""} onClick={() => setStatusFilter(key)}>{label}</button>)}
      </div>
      {loading ? <Loading skeleton /> : error ? <ErrorState message={error} onRetry={load} /> : items.length ? (
        <div className="knowledge-grid">
          {items.map(i => (
            <article className="panel knowledge-card" key={i.id}>
              <Badge value={i.severity} /> <Badge value={i.status} />
              <h3>{i.title}</h3>
              <p>{i.common_symptom || "No common symptom reported."}</p>
              <div className="incident-stats">
                <b>{i.ticket_count}<small>Tickets</small></b>
                <b>{i.growth_rate}%<small>Growth</small></b>
                <b>{i.service}<small>Service</small></b>
              </div>
              <Button size="sm" variant="ghost" onClick={() => setExpanded(expanded === i.id ? null : i.id)}>{expanded === i.id ? "Hide details" : "View details"}</Button>
              {expanded === i.id && <IncidentDetail incident={i} onChanged={load} />}
            </article>
          ))}
        </div>
      ) : <Empty label="No incidents match this filter." />}
    </div>
  );
}
