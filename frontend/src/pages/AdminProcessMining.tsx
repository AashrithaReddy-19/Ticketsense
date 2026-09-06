import { useEffect, useState } from "react";
import { api, type ProcessMiningRunView } from "../api/client";
import { Badge, Empty, ErrorState, Loading } from "../components/States";
import { Button } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

export default function AdminProcessMining() {
  const toast = useToast();
  const [runs, setRuns] = useState<ProcessMiningRunView[]>([]);
  const [detail, setDetail] = useState<ProcessMiningRunView | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true); setError("");
    try {
      const result = await api.processMiningRuns();
      setRuns(result.items);
      if (result.items.length > 0) setDetail(await api.processMiningRunDetail(result.items[0].id));
    } catch (e) { setError(e instanceof Error ? e.message : "The process mining lab is not available for this account or tenant."); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  async function runAnalysis() {
    setRunning(true);
    try {
      const run = await api.runProcessMining();
      setDetail(run);
      toast(run.status === "completed" ? `Analysis complete — ${run.ticket_count_considered} ticket(s), ${run.variants.length} variant(s).` : `Not enough data yet: ${run.insufficiency_reason}`, run.status === "completed" ? "success" : "danger");
      await load();
    } catch (e) { toast(e instanceof Error ? e.message : "Unable to run process mining", "danger"); }
    finally { setRunning(false); }
  }

  if (loading) return <div className="content"><Loading label="Loading process mining lab…" /></div>;
  if (error && runs.length === 0) return <div className="content"><ErrorState message={error} onRetry={load} /></div>;

  return <div className="content">
    <div className="page-title">
      <div><p className="eyebrow">TicketSense V2 operations</p><h1>Process mining</h1>
        <p>Real variant discovery and bottleneck timing computed only from the immutable ticket event log — never predicted or simulated. A tenant with too little history gets an honest insufficient-data result.</p></div>
      <div className="live"><span />No sample metrics</div>
    </div>
    <div className="panel" style={{ marginBottom: "1rem" }}>
      <Button variant="primary" loading={running} onClick={runAnalysis}>Run analysis</Button>
    </div>
    {!detail ? <Empty label="No process mining runs yet — run the analysis to see real results." /> : <>
      <div className="panel" style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginBottom: "1rem" }}>
        <div><Badge value={detail.status} /> <small>{new Date(detail.started_at).toLocaleString()}</small></div>
        {detail.status === "insufficient_data" ? <p>{detail.insufficiency_reason}</p> : <div className="eval-lab-table">
          <div className="list-head eval-metric-row"><span>Metric</span><span>Value</span></div>
          <div className="list-row eval-metric-row"><span>Tickets considered</span><span>{detail.ticket_count_considered}</span></div>
          <div className="list-row eval-metric-row"><span>Events considered</span><span>{detail.event_count_considered}</span></div>
          <div className="list-row eval-metric-row"><span>Distinct variants</span><span>{detail.variants.length}</span></div>
        </div>}
      </div>

      {detail.variants.length > 0 && <div className="panel" style={{ marginBottom: "1rem" }}>
        <h3>Process variants</h3>
        <div className="eval-lab-table">
          <div className="list-head dependency-edge-row"><span>Sequence</span><span>Tickets</span><span>Share</span></div>
          {detail.variants.map((variant, i) => <div className="list-row dependency-edge-row" key={i}>
            <span>{variant.sequence.join(" → ")}</span>
            <span>{variant.ticket_count}</span>
            <span>{(variant.percentage * 100).toFixed(1)}%</span>
          </div>)}
        </div>
      </div>}

      {detail.bottlenecks.length > 0 && <div className="panel">
        <h3>Bottlenecks (slowest transitions first)</h3>
        <div className="eval-lab-table">
          <div className="list-head dependency-edge-row"><span>Transition</span><span>Mean / median / p90</span><span>Sample size</span></div>
          {detail.bottlenecks.map((b, i) => <div className="list-row dependency-edge-row" key={i}>
            <span>{b.from_event_type} → {b.to_event_type}</span>
            <span>{formatDuration(b.mean_seconds)} / {formatDuration(b.median_seconds)} / {formatDuration(b.p90_seconds)}</span>
            <span>{b.sample_size}</span>
          </div>)}
        </div>
      </div>}
    </>}
    {runs.length > 1 && <div className="panel" style={{ marginTop: "1rem" }}>
      <h3>Run history</h3>
      <div className="eval-lab-table">
        <div className="list-head eval-metric-row"><span>Started</span><span>Status</span></div>
        {runs.map(run => <div className="list-row eval-metric-row" key={run.id}><span>{new Date(run.started_at).toLocaleString()}</span><span><Badge value={run.status} /></span></div>)}
      </div>
    </div>}
  </div>;
}
