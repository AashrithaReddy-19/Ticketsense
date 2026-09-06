import { useEffect, useState } from "react";
import { api, type RedTeamRunListItem, type RedTeamRunSummary } from "../api/client";
import { Badge, Empty, ErrorState, Loading } from "../components/States";
import { Button } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";

export default function AdminRedTeamLab() {
  const toast = useToast();
  const [runs, setRuns] = useState<RedTeamRunListItem[]>([]);
  const [detail, setDetail] = useState<RedTeamRunSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true); setError("");
    try {
      const result = await api.redTeamRuns();
      setRuns(result.items);
      if (result.items.length > 0) setDetail(await api.redTeamRunDetail(result.items[0].id));
    } catch (e) { setError(e instanceof Error ? e.message : "The red-team lab is not available for this account or tenant."); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  async function runSuite() {
    setRunning(true);
    try {
      const summary = await api.runRedTeamSuite();
      setDetail(summary);
      toast(`Run complete: ${summary.applicable_cases - Math.round((summary.attack_success_rate ?? 0) * summary.applicable_cases)}/${summary.applicable_cases} defenses held.`, (summary.attack_success_rate ?? 0) > 0 ? "danger" : "success");
      await load();
    } catch (e) { toast(e instanceof Error ? e.message : "Unable to run the red-team suite", "danger"); }
    finally { setRunning(false); }
  }

  if (loading) return <div className="content"><Loading label="Loading red-team lab…" /></div>;
  if (error && runs.length === 0) return <div className="content"><ErrorState message={error} onRetry={load} /></div>;

  return <div className="content">
    <div className="page-title">
      <div><p className="eyebrow">TicketSense V2 red-team lab</p><h1>Adversarial safety lab</h1>
        <p>Every case here exercises a real defense mechanism with synthetic attack payloads only — never sent to a customer, never inserted into the production knowledge corpus.</p></div>
      <div className="live"><span />No sample metrics</div>
    </div>
    <div className="panel" style={{ marginBottom: "1rem" }}>
      <Button variant="primary" loading={running} onClick={runSuite}>Run red-team suite</Button>
    </div>
    {!detail ? <Empty label="No red-team runs yet — run the suite to see real results." /> : <>
      <div className="panel" style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
        <div><Badge value={detail.status} /> <small>Suite v{detail.suite_version} · {new Date(detail.started_at).toLocaleString()}</small></div>
        <div className="eval-lab-table">
          <div className="list-head eval-metric-row"><span>Metric</span><span>Value</span></div>
          <div className="list-row eval-metric-row"><span>Applicable cases</span><span>{detail.applicable_cases} ({detail.not_applicable_cases} not applicable)</span></div>
          <div className="list-row eval-metric-row"><span>Attack success rate</span><span>{detail.attack_success_rate == null ? "unavailable" : `${(detail.attack_success_rate * 100).toFixed(1)}%`}</span></div>
          <div className="list-row eval-metric-row"><span>Block rate</span><span>{detail.block_rate == null ? "unavailable" : `${(detail.block_rate * 100).toFixed(1)}%`}</span></div>
        </div>
      </div>
      <div className="panel" style={{ marginTop: "1rem" }}>
        <h3>By severity</h3>
        <div className="eval-lab-table">
          <div className="list-head eval-metric-row"><span>Severity</span><span>Failed / total</span></div>
          {Object.entries(detail.by_severity).map(([severity, stats]) => <div className="list-row eval-metric-row" key={severity}><span><Badge value={severity} /></span><span>{stats.failed} / {stats.total}</span></div>)}
        </div>
      </div>
      <div className="panel" style={{ marginTop: "1rem" }}>
        <h3>Case results</h3>
        <div className="eval-lab-table">
          <div className="list-head dependency-edge-row"><span>Case</span><span>Result</span><span>Status</span></div>
          {detail.results.map(result => <article className="list-row dependency-edge-row" key={result.case_key}>
            <div><b>{result.title}</b><small> {result.category.replaceAll("_", " ")} · {result.severity} {result.gate_responsible ? `· ${result.gate_responsible}` : ""}</small><small>{result.detail}</small></div>
            <span>expected {result.expected_result} → observed {result.observed_result}</span>
            <Badge value={!result.applicable ? "not applicable" : result.passed ? "held" : "gap found"} />
          </article>)}
        </div>
      </div>
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
