import { useEffect, useState } from "react";
import { api, type SafeActionDefinition, type SafeActionExecution, type SafeActionPreview } from "../api/client";
import { Badge, Empty, Loading } from "./States";
import { Button } from "./ui/Button";
import { useToast } from "./ui/Toast";

/** Engineer-facing safe-action panel embedded in the ticket workspace. Shows only
 * enabled actions the current user has the capability for; every action requires
 * an explicit preview before it can be executed, and every execute call carries a
 * fresh idempotency key so a duplicate click never runs the action twice. */
export default function SafeActionPanel({ ticketId }: { ticketId: string }) {
  const toast = useToast();
  const [actions, setActions] = useState<SafeActionDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [params, setParams] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<SafeActionPreview | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [lastExecution, setLastExecution] = useState<SafeActionExecution | null>(null);

  useEffect(() => { api.safeActions().then(setActions).catch(() => setActions([])).finally(() => setLoading(false)); }, []);

  function openAction(action: SafeActionDefinition) {
    setSelected(action.action_key);
    const initial: Record<string, string> = {};
    for (const field of Object.keys(action.parameter_schema)) initial[field] = field === "ticket_id" ? ticketId : "";
    setParams(initial);
    setPreview(null); setConfirm(false); setConsent(false); setLastExecution(null);
  }

  async function doPreview() {
    if (!selected) return;
    setBusy(true);
    try { setPreview(await api.previewSafeAction(selected, { parameters: params, ticket_id: ticketId })); }
    catch (err) { toast(err instanceof Error ? err.message : "Preview failed", "danger"); }
    finally { setBusy(false); }
  }

  async function doExecute() {
    if (!selected) return;
    setBusy(true);
    try {
      const execution = await api.executeSafeAction(selected, { parameters: params, ticket_id: ticketId, confirm, customer_consent: consent }, crypto.randomUUID());
      setLastExecution(execution);
      toast(execution.status === "pending_approval" ? "Sent for approval" : execution.status === "succeeded" ? "Action completed" : "Action did not succeed", execution.status === "failed" ? "danger" : "success");
    } catch (err) { toast(err instanceof Error ? err.message : "Execution failed", "danger"); }
    finally { setBusy(false); }
  }

  const action = actions.find(a => a.action_key === selected);

  if (loading) return <Loading skeleton />;
  return (
    <div className="safe-action-panel">
      {actions.length ? (
        <div className="safe-action-list">
          {actions.filter(a => a.enabled).map(a => (
            <button key={a.action_key} className={`safe-action-chip${selected === a.action_key ? " active" : ""}`} onClick={() => openAction(a)}>
              {a.display_name} <Badge value={a.risk_level} />
            </button>
          ))}
        </div>
      ) : <Empty label="No safe actions are available for this ticket." />}

      {action && (
        <div className="safe-action-detail">
          <p>{action.description}</p>
          {Object.keys(action.parameter_schema).filter(f => f !== "ticket_id").map(field => (
            <label className="ui-field" key={field}><span>{field}</span>
              <input value={params[field] || ""} onChange={e => setParams({ ...params, [field]: e.target.value })} />
            </label>
          ))}
          <div className="review-actions">
            <Button size="sm" variant="outline" loading={busy} onClick={doPreview}>Preview</Button>
          </div>
          {preview && (
            <div className="recommendation">
              <p><b>Will do:</b> {preview.would_do}</p>
              <p><b>Will not do:</b> {preview.would_not_do}</p>
              {preview.requires_confirmation && <label className="ui-field-inline"><input type="checkbox" checked={confirm} onChange={e => setConfirm(e.target.checked)} /> I confirm this action should run</label>}
              {preview.requires_customer_consent && <label className="ui-field-inline"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} /> Customer consent obtained</label>}
              <div className="review-actions">
                <Button size="sm" variant="primary" loading={busy}
                  disabled={(preview.requires_confirmation && !confirm) || (preview.requires_customer_consent && !consent)}
                  onClick={doExecute}>Execute</Button>
              </div>
            </div>
          )}
          {lastExecution && (
            <div className="recommendation">
              <Badge value={lastExecution.status} />
              {lastExecution.result && <p>{lastExecution.result.summary}{lastExecution.result.sandbox ? " (sandbox result)" : ""}</p>}
              {lastExecution.error_summary && <p>{lastExecution.error_summary}</p>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
