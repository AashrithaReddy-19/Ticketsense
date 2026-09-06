import { useEffect, useState } from "react";
import { api, type ConnectorView } from "../api/client";
import { Badge, Empty, ErrorState, Loading } from "../components/States";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Dialog";
import { useToast } from "../components/ui/Toast";

export default function AdminConnectors() {
  const toast = useToast();
  const [connectors, setConnectors] = useState<ConnectorView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [configureTarget, setConfigureTarget] = useState<ConnectorView | null>(null);
  const [reference, setReference] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load() {
    setLoading(true); setError("");
    try { setConnectors((await api.connectors()).items); }
    catch (e) { setError(e instanceof Error ? e.message : "The connector lab is not available for this account or tenant."); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  async function saveConfiguration() {
    if (!configureTarget) return;
    setBusyId(configureTarget.id);
    try {
      await api.configureConnector(configureTarget.id, reference);
      toast("Connector configuration saved — not yet verified.", "success");
      setConfigureTarget(null); setReference("");
      await load();
    } catch (e) { toast(e instanceof Error ? e.message : "Unable to save the configuration", "danger"); }
    finally { setBusyId(null); }
  }

  async function verify(connector: ConnectorView) {
    setBusyId(connector.id);
    try {
      const result = await api.verifyConnector(connector.id);
      toast(result.status === "verified" ? "Connector verified — a real test message was sent." : `Verification failed: ${result.last_error}`, result.status === "verified" ? "success" : "danger");
      await load();
    } catch (e) { toast(e instanceof Error ? e.message : "Unable to verify the connector", "danger"); }
    finally { setBusyId(null); }
  }

  if (loading) return <div className="content"><Loading label="Loading connectors…" /></div>;
  if (error && connectors.length === 0) return <div className="content"><ErrorState message={error} onRetry={load} /></div>;

  return <div className="content">
    <div className="page-title">
      <div><p className="eyebrow">TicketSense V2 integrations</p><h1>External connectors</h1>
        <p>A connector is only ever marked verified after a real outbound call succeeds. Only Slack has a real implementation today — every other provider honestly reports itself as not yet implemented rather than pretending to work.</p></div>
      <div className="live"><span />No sample metrics</div>
    </div>
    {connectors.length === 0 ? <Empty label="No connectors registered for this tenant." /> : <div className="panel eval-lab-table">
      <div className="list-head governance-row"><span>Connector</span><span>Status</span><span>Last error</span><span></span></div>
      {connectors.map(connector => <article className="list-row governance-row" key={connector.id}>
        <div><b>{connector.name}</b><small>{connector.provider}</small>{connector.config_reference && <small>{connector.config_reference}</small>}</div>
        <Badge value={connector.enabled ? "enabled" : connector.status} />
        <small>{connector.last_error || "—"}</small>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <Button size="sm" variant="outline" onClick={() => { setConfigureTarget(connector); setReference(connector.config_reference || ""); }}>Configure</Button>
          <Button size="sm" variant="primary" loading={busyId === connector.id} disabled={!connector.config_reference} onClick={() => verify(connector)}>Verify</Button>
        </div>
      </article>)}
    </div>}

    <Modal open={!!configureTarget} onClose={() => setConfigureTarget(null)} title={`Configure ${configureTarget?.name ?? ""}`} description="Reference where the credential lives — never paste a raw secret here. Use env:VAR_NAME, secret-manager:path, file:path, or none:reason." footer={<><Button variant="outline" onClick={() => setConfigureTarget(null)}>Cancel</Button><Button variant="primary" disabled={reference.trim().length < 4} loading={!!busyId} onClick={saveConfiguration}>Save</Button></>}>
      <label className="ui-field"><span>Config reference</span><input value={reference} onChange={e => setReference(e.target.value)} placeholder="env:SLACK_WEBHOOK_URL" /></label>
    </Modal>
  </div>;
}
