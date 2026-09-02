import { useEffect, useState } from "react";
import { api, type Incident } from "../api/client";
import { Badge, Empty, ErrorState, Loading } from "../components/States";
import { IconRefresh } from "../components/icons";
import { Button } from "../components/ui/Button";

export default function Incidents() {
  const [items, setItems] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    try { setItems(await api.incidents()); setError(""); }
    catch (e) { setError(e instanceof Error ? e.message : "Request failed"); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  return (
    <div className="content">
      <div className="page-title">
        <div><h1>Incidents</h1><p>Real emerging incident clusters for this tenant.</p></div>
        <Button variant="outline" icon={<IconRefresh size={14} />} onClick={load}>Refresh</Button>
      </div>
      {loading ? <Loading skeleton /> : error ? <ErrorState message={error} onRetry={load} /> : items.length ? (
        <div className="knowledge-grid">
          {items.map(i => (
            <article className="panel knowledge-card" key={i.id}>
              <Badge value={i.severity} />
              <h3>{i.title}</h3>
              <p>{i.common_symptom || "No common symptom reported."}</p>
              <div className="incident-stats">
                <b>{i.ticket_count}<small>Tickets</small></b>
                <b>{i.growth_rate}%<small>Growth</small></b>
                <b>{i.service}<small>Service</small></b>
              </div>
            </article>
          ))}
        </div>
      ) : <Empty label="No active incidents." />}
    </div>
  );
}
