import { useEffect, useState } from "react";
import { api, type Analytics } from "../api/client";
import { Empty, ErrorState, Loading, SyncIndicator } from "../components/States";
import { useAutoRefresh } from "../lib/useAutoRefresh";

const STAGE_LABELS: Record<string, string> = {
  classification: "Classification", routing: "Routing", confidence_scoring: "Confidence scoring",
  total_intake_pipeline: "Total intake pipeline", evidence_retrieval_and_drafting: "Evidence retrieval + drafting",
  ocr_extraction: "OCR extraction",
};

const DECISION_ROWS: Array<[keyof Analytics, string]> = [
  ["ai_acceptance_rate", "AI response accepted as-is"],
  ["reviewer_modification_rate", "Modified and approved"],
  ["rejection_rate", "Rejected"],
  ["escalation_rate", "Escalated"],
];

function pct(value: number | null | undefined) { return value == null ? "—" : `${Math.round(value * 100)}%`; }

function Bar({ label, value, max, tone = "primary", detail }: { label: string; value: number; max: number; tone?: "primary" | "success" | "warning" | "danger"; detail: string }) {
  const width = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return (
    <div className="metric-bar-row">
      <span className="metric-bar-label">{label}</span>
      <div className="metric-bar-track"><div className={`metric-bar-fill metric-bar-${tone}`} style={{ width: `${width}%` }} /></div>
      <span className="metric-bar-value">{detail}</span>
    </div>
  );
}

export default function AnalyticsDashboard() {
  const [data, setData] = useState<Analytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load(opts: { silent?: boolean } = {}) {
    if (!opts.silent) { setLoading(true); setError(""); }
    try { setData(await api.analytics()); }
    catch (e) { if (!opts.silent) setError(e instanceof Error ? e.message : "Unable to load analytics"); else throw e; }
    finally { if (!opts.silent) setLoading(false); }
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const { status: syncStatus, lastSyncedAt, retryNow } = useAutoRefresh(() => load({ silent: true }), undefined, !loading && !error);

  if (loading) return <div className="content"><Loading label="Loading analytics…" /></div>;
  if (error) return <div className="content"><ErrorState message={error} onRetry={load} /></div>;
  if (!data) return null;

  const confidenceTotal = data.confidence_distribution.low + data.confidence_distribution.borderline + data.confidence_distribution.high;
  const decisionMax = Math.max(0.0001, ...DECISION_ROWS.map(([key]) => Number(data[key]) || 0));
  const latencyMax = Math.max(0.0001, ...data.pipeline_stage_latency.map(row => row.average_duration_ms || 0));

  return (
    <div className="content">
      <div className="page-title">
        <div><h1>Analytics</h1><p>Ticket volume, AI/human agreement and pipeline-stage latency computed by the backend.</p></div>
        <SyncIndicator status={syncStatus} lastSyncedAt={lastSyncedAt} onRetry={retryNow} />
      </div>

      <div className="stat-tile-row">
        <StatTile label="Total tickets" value={String(data.total_tickets)} />
        <StatTile label="Open" value={String(data.open_tickets)} />
        <StatTile label="Resolved" value={String(data.resolved_tickets)} />
        <StatTile label="Escalated" value={String(data.escalated_tickets)} />
        <StatTile label="Avg. confidence" value={pct(data.average_confidence)} />
        <StatTile label="Avg. response time" value={data.average_response_time_hours != null ? `${data.average_response_time_hours}h` : "—"} />
        <StatTile label="Avg. resolution time" value={data.average_resolution_time_hours != null ? `${data.average_resolution_time_hours}h` : "—"} />
      </div>

      <section className="panel metric-section">
        <h2>Confidence distribution</h2>
        <p className="empty-note">Every ticket's independently scored confidence, bucketed by the same thresholds the workflow gate uses.</p>
        {confidenceTotal === 0 ? <Empty label="No scored tickets yet." /> : <>
          <Bar label="High" value={data.confidence_distribution.high} max={confidenceTotal} tone="success" detail={`${data.confidence_distribution.high} (${Math.round(data.confidence_distribution.high / confidenceTotal * 100)}%)`} />
          <Bar label="Borderline" value={data.confidence_distribution.borderline} max={confidenceTotal} tone="warning" detail={`${data.confidence_distribution.borderline} (${Math.round(data.confidence_distribution.borderline / confidenceTotal * 100)}%)`} />
          <Bar label="Low" value={data.confidence_distribution.low} max={confidenceTotal} tone="danger" detail={`${data.confidence_distribution.low} (${Math.round(data.confidence_distribution.low / confidenceTotal * 100)}%)`} />
        </>}
      </section>

      <section className="panel metric-section">
        <h2>Reviewer decisions</h2>
        <p className="empty-note">Share of reviewed tickets ending in each outcome (of {Object.values(data.status_distribution).reduce((a, b) => a + b, 0)} tickets total).</p>
        {DECISION_ROWS.every(([key]) => data[key] == null) ? <Empty label="No reviewer decisions recorded yet." /> :
          DECISION_ROWS.map(([key, label]) => <Bar key={String(key)} label={label} value={Number(data[key]) || 0} max={decisionMax} detail={pct(data[key] as number | null)} />)}
      </section>

      <section className="panel metric-section">
        <h2>Pipeline-stage latency</h2>
        <p className="empty-note">Mean wall-clock duration per instrumented stage, from real timing recorded at request time.</p>
        {data.pipeline_stage_latency.length === 0 ? <Empty label="No pipeline timing recorded yet." /> :
          data.pipeline_stage_latency.map(row => (
            <Bar key={row.stage} label={STAGE_LABELS[row.stage] || row.stage} value={row.average_duration_ms || 0} max={latencyMax}
              detail={`${row.average_duration_ms ?? "—"}ms · n=${row.sample_count}${row.failure_count ? ` · ${row.failure_count} failed` : ""}`} />
          ))}
      </section>

      <section className="panel metric-section">
        <h2>Department performance</h2>
        {data.department_performance.length === 0 ? <Empty label="No departments configured." /> : (
          <div className="table-scroll">
            <div className="list-head dept-performance-row"><span>Department</span><span>Total</span><span>Resolved</span><span>Resolution rate</span><span>Avg. confidence</span></div>
            {data.department_performance.map(row => (
              <article className="list-row dept-performance-row" key={row.department_id}>
                <b>{row.department}</b>
                <span>{row.total_tickets}</span>
                <span>{row.resolved_tickets}</span>
                <span>{row.total_tickets ? `${Math.round(row.resolved_tickets / row.total_tickets * 100)}%` : "—"}</span>
                <span>{pct(row.average_confidence)}</span>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: string }) {
  return <div className="stat-tile"><span>{label}</span><b>{value}</b></div>;
}
