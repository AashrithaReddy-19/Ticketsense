import { useEffect, useState } from "react";
import { api, type SafeActionDefinition, type SafeActionExecution } from "../api/client";
import { Badge, Empty, ErrorState, Loading } from "../components/States";

export default function AdminSafeActions() {
  const [actions, setActions] = useState<SafeActionDefinition[]>([]);
  const [executions, setExecutions] = useState<SafeActionExecution[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true); setError("");
    try {
      const [a, e] = await Promise.all([api.safeActions(), api.safeActionExecutions()]);
      setActions(a); setExecutions(e);
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to load safe actions"); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  return (
    <div className="content">
      <div className="page-title"><div><h1>Safe actions</h1><p>Allowlisted, typed, tenant-scoped actions with dry-run preview, confirmation, idempotency, and a full audit trail.</p></div></div>
      {loading ? <Loading skeleton /> : error ? <ErrorState message={error} onRetry={load} /> : (
        <>
          <section className="metric-section">
            <h2>Available actions</h2>
            {actions.length ? (
              <div className="panel ticket-list">
                <div className="list-head admin-engineer-row"><span>Action</span><span>Category</span><span>Risk</span><span>Approval</span><span>Status</span></div>
                {actions.map(action => (
                  <article className="list-row admin-engineer-row" key={action.action_key}>
                    <div><b>{action.display_name}</b><small>{action.description}</small></div>
                    <span>{action.category}</span>
                    <Badge value={action.risk_level} />
                    <span>{action.risk_level === "high" ? "Requires a second approver" : "Self-confirmed"}</span>
                    <span>{action.enabled ? <Badge value="active" /> : <Badge value="inactive" />}{action.connector === "sandbox" && <small> (sandbox)</small>}</span>
                  </article>
                ))}
              </div>
            ) : <Empty label="No safe actions are available to this account." />}
          </section>
          <section className="metric-section">
            <h2>Recent executions</h2>
            {executions.length ? (
              <div className="panel ticket-list">
                <div className="list-head admin-engineer-row"><span>Action</span><span>Status</span><span>Result</span><span>When</span><span>Ticket</span></div>
                {executions.map(execution => (
                  <article className="list-row admin-engineer-row" key={execution.id}>
                    <span>{execution.action_key}</span>
                    <Badge value={execution.status} />
                    <span>{execution.result ? (execution.result.sandbox ? `${execution.result.summary} (sandbox)` : execution.result.summary) : execution.error_summary || "—"}</span>
                    <span>{new Date(execution.created_at).toLocaleString()}</span>
                    <span>{execution.ticket_id ? execution.ticket_id.slice(0, 8) : "—"}</span>
                  </article>
                ))}
              </div>
            ) : <Empty label="No safe actions have been executed yet." />}
          </section>
        </>
      )}
    </div>
  );
}
