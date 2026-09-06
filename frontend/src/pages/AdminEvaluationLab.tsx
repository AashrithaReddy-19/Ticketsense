import { useEffect, useState } from "react";
import { api, type Dataset, type DatasetVersion, type EvaluationExample, type EvaluationRun, type EvaluationRunDetail } from "../api/client";
import { Badge, Empty, ErrorState, Loading } from "../components/States";
import { Button } from "../components/ui/Button";
import { Tabs, TabPanel } from "../components/ui/Tabs";
import { useToast } from "../components/ui/Toast";

const TARGETS = ["department", "priority", "sentiment"] as const;

export default function AdminEvaluationLab() {
  const toast = useToast();
  const [tab, setTab] = useState("datasets");
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedRun, setSelectedRun] = useState<string | null>(null);

  async function load() {
    setLoading(true); setError("");
    try {
      const [datasetResult, runResult] = await Promise.allSettled([api.datasets(), api.evaluationRuns()]);
      if (datasetResult.status === "fulfilled") setDatasets(datasetResult.value.items);
      if (runResult.status === "fulfilled") setRuns(runResult.value.items);
      if (datasetResult.status === "rejected" && runResult.status === "rejected") {
        throw new Error("The evaluation lab is not available for this account or tenant.");
      }
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to load the evaluation lab"); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  if (loading) return <div className="content"><Loading label="Loading evaluation lab…" /></div>;
  if (error && !datasets.length && !runs.length) return <div className="content"><ErrorState message={error} onRetry={load} /></div>;

  return <div className="content">
    <div className="page-title">
      <div><p className="eyebrow">TicketSense V2 evaluation lab</p><h1>Evaluation lab</h1>
        <p>Reproducible dataset registry and classification evaluation runs against the deployed classifier artifacts. Every metric shown here is computed from real predictions — nothing is a sample or placeholder.</p></div>
      <div className="live"><span />No sample metrics</div>
    </div>
    <Tabs idPrefix="eval-lab" active={tab} onChange={setTab} tabs={[{ key: "datasets", label: "Datasets" }, { key: "runs", label: "Evaluation runs" }]} />
    <TabPanel id="eval-lab" tabKey="datasets" active={tab}>
      <DatasetsPanel datasets={datasets} onChanged={load} toast={toast} />
    </TabPanel>
    <TabPanel id="eval-lab" tabKey="runs" active={tab}>
      {selectedRun
        ? <RunDetailPanel runId={selectedRun} onBack={() => setSelectedRun(null)} />
        : <RunsPanel datasets={datasets} runs={runs} onChanged={load} onSelect={setSelectedRun} toast={toast} />}
    </TabPanel>
  </div>;
}

function DatasetsPanel({ datasets, onChanged, toast }: { datasets: Dataset[]; onChanged: () => void; toast: (message: string, tone?: "success" | "danger") => void }) {
  const [key, setKey] = useState(""); const [name, setName] = useState(""); const [kind, setKind] = useState<"ticket_labels" | "retrieval_judgments">("ticket_labels");
  const [description, setDescription] = useState(""); const [creating, setCreating] = useState(false);
  const [importTarget, setImportTarget] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null); const [sourceFormat, setSourceFormat] = useState("csv"); const [importing, setImporting] = useState(false);
  const [versionsByDataset, setVersionsByDataset] = useState<Record<string, DatasetVersion[]>>({});

  async function createDataset() {
    if (!key || !name || !description) { toast("Key, name and description are required.", "danger"); return; }
    setCreating(true);
    try { await api.createDataset({ key, name, kind, description }); toast("Dataset registered.", "success"); setKey(""); setName(""); setDescription(""); onChanged(); }
    catch (e) { toast(e instanceof Error ? e.message : "Unable to create dataset", "danger"); }
    finally { setCreating(false); }
  }

  async function loadVersions(datasetId: string) {
    try { const result = await api.datasetVersions(datasetId); setVersionsByDataset(prev => ({ ...prev, [datasetId]: result.items })); }
    catch (e) { toast(e instanceof Error ? e.message : "Unable to load dataset versions", "danger"); }
  }

  async function runImport(datasetId: string) {
    if (!file) { toast("Choose a CSV/JSON/JSONL file first.", "danger"); return; }
    setImporting(true);
    try {
      const form = new FormData();
      form.append("file", file); form.append("source_format", sourceFormat);
      const result = await api.importDataset(datasetId, form);
      toast(`Imported version ${result.version.version_number}: ${result.version.row_count} rows accepted.`, "success");
      setFile(null); setImportTarget(null);
      await loadVersions(datasetId);
    } catch (e) { toast(e instanceof Error ? e.message : "Import failed", "danger"); }
    finally { setImporting(false); }
  }

  return <div className="panel" style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
    <form onSubmit={e => { e.preventDefault(); createDataset(); }} style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "flex-end" }}>
      <label>Key<input value={key} onChange={e => setKey(e.target.value)} placeholder="q1_ticket_labels" /></label>
      <label>Name<input value={name} onChange={e => setName(e.target.value)} placeholder="Q1 ticket labels" /></label>
      <label>Kind<select value={kind} onChange={e => setKind(e.target.value as typeof kind)}><option value="ticket_labels">Ticket labels</option><option value="retrieval_judgments">Retrieval judgments</option></select></label>
      <label>Description<input value={description} onChange={e => setDescription(e.target.value)} placeholder="Source and purpose" /></label>
      <Button type="submit" variant="primary" loading={creating}>Register dataset</Button>
    </form>
    {datasets.length === 0 ? <Empty label="No datasets are registered for this tenant yet." /> : datasets.map(dataset => <article className="panel" key={dataset.id} style={{ padding: "0.75rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div><b>{dataset.name}</b> <Badge value={dataset.kind} /> <small>{dataset.key}</small></div>
        <Button size="sm" variant="outline" onClick={() => { loadVersions(dataset.id); setImportTarget(importTarget === dataset.id ? null : dataset.id); }}>
          {importTarget === dataset.id ? "Close" : "Import / view versions"}
        </Button>
      </div>
      <small>{dataset.description}</small>
      {importTarget === dataset.id && <div style={{ marginTop: "0.75rem" }}>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
          <input type="file" accept=".csv,.json,.jsonl" onChange={e => setFile(e.target.files?.[0] ?? null)} />
          <select value={sourceFormat} onChange={e => setSourceFormat(e.target.value)}><option value="csv">CSV</option><option value="json">JSON</option><option value="jsonl">JSONL</option></select>
          <Button size="sm" variant="primary" loading={importing} onClick={() => runImport(dataset.id)}>Import</Button>
        </div>
        {(versionsByDataset[dataset.id]?.length ?? 0) === 0
          ? <Empty label="No versions imported yet." />
          : <div className="eval-lab-table" style={{ marginTop: "0.5rem" }}>
              <div className="list-head eval-version-row"><span>Version</span><span>Rows</span><span>Duplicates</span><span>Corruption</span><span>Leakage check</span><span>Status</span></div>
              {versionsByDataset[dataset.id].map(version => <article className="list-row eval-version-row" key={version.id}>
                <span>v{version.version_number}</span><span>{version.row_count} rows</span>
                <span>dup {(version.duplicate_rate * 100).toFixed(1)}%</span>
                <span>corrupt {(version.corruption_rate * 100).toFixed(1)}%</span>
                <span>{version.near_duplicate_check_skipped ? "leakage check skipped (>2000 rows)" : `${version.near_duplicate_cross_split_count} cross-split near-dupes`}</span>
                <Badge value={version.status} />
              </article>)}
            </div>}
      </div>}
    </article>)}
  </div>;
}

function RunsPanel({ datasets, runs, onChanged, onSelect, toast }: { datasets: Dataset[]; runs: EvaluationRun[]; onChanged: () => void; onSelect: (id: string) => void; toast: (message: string, tone?: "success" | "danger") => void }) {
  const [datasetId, setDatasetId] = useState(""); const [versions, setVersions] = useState<DatasetVersion[]>([]);
  const [versionId, setVersionId] = useState(""); const [target, setTarget] = useState<typeof TARGETS[number]>("department");
  const [creating, setCreating] = useState(false);

  async function pickDataset(id: string) {
    setDatasetId(id); setVersionId("");
    if (!id) { setVersions([]); return; }
    try { const result = await api.datasetVersions(id); setVersions(result.items.filter(v => v.status === "ready")); }
    catch { setVersions([]); }
  }

  async function createRun() {
    if (!versionId) { toast("Choose a ready dataset version first.", "danger"); return; }
    setCreating(true);
    try {
      const run = await api.createEvaluationRun({ dataset_version_id: versionId, target });
      toast(run.status === "completed" ? `Run completed: ${run.row_count_considered} rows evaluated.` : `Run status: ${run.status.replaceAll("_", " ")}.`, run.status === "completed" ? "success" : "danger");
      onChanged();
    } catch (e) { toast(e instanceof Error ? e.message : "Unable to create evaluation run", "danger"); }
    finally { setCreating(false); }
  }

  return <div className="panel" style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
    <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "flex-end" }}>
      <label>Dataset<select value={datasetId} onChange={e => pickDataset(e.target.value)}>
        <option value="">Choose dataset…</option>
        {datasets.filter(d => d.kind === "ticket_labels").map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
      </select></label>
      <label>Version<select value={versionId} onChange={e => setVersionId(e.target.value)} disabled={!versions.length}>
        <option value="">Choose ready version…</option>
        {versions.map(v => <option key={v.id} value={v.id}>v{v.version_number} ({v.row_count} rows)</option>)}
      </select></label>
      <label>Target<select value={target} onChange={e => setTarget(e.target.value as typeof target)}>{TARGETS.map(t => <option key={t} value={t}>{t}</option>)}</select></label>
      <Button variant="primary" loading={creating} onClick={createRun}>Run evaluation</Button>
    </div>
    {runs.length === 0 ? <Empty label="No evaluation runs yet." /> : <div className="panel governance-table">
      <div className="list-head governance-row"><span>Target</span><span>Status</span><span>Rows</span><span>Created</span></div>
      {runs.map(run => <article className="list-row governance-row" key={run.id} style={{ cursor: "pointer" }} onClick={() => onSelect(run.id)}>
        <b>{run.target}</b><Badge value={run.status} /><span>{run.row_count_considered} considered · {run.row_count_excluded} excluded</span><small>{new Date(run.created_at).toLocaleString()}</small>
      </article>)}
    </div>}
  </div>;
}

function RunDetailPanel({ runId, onBack }: { runId: string; onBack: () => void }) {
  const [detail, setDetail] = useState<EvaluationRunDetail | null>(null);
  const [errors, setErrors] = useState<EvaluationExample[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [detailResult, errorResult] = await Promise.allSettled([api.evaluationRunDetail(runId), api.evaluationRunExamples(runId, true)]);
        if (detailResult.status === "fulfilled") setDetail(detailResult.value);
        if (errorResult.status === "fulfilled") setErrors(errorResult.value.items);
      } finally { setLoading(false); }
    })();
  }, [runId]);

  if (loading) return <Loading label="Loading run detail…" />;
  if (!detail) return <ErrorState message="Unable to load this evaluation run." onRetry={onBack} />;

  return <div className="panel" style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
    <Button size="sm" variant="outline" onClick={onBack}>Back to runs</Button>
    <div><b>{detail.target}</b> evaluation — <Badge value={detail.status} /> — {detail.row_count_considered} rows considered, {detail.row_count_excluded} excluded</div>
    <small>Model artifact hash: {detail.model_artifact_hash ?? "unavailable"} · Git commit: {detail.git_commit ?? "unavailable"}</small>
    {detail.status !== "completed"
      ? <Empty label={`This run reported ${detail.status.replaceAll("_", " ")} — no metrics were computed. Reasons: ${JSON.stringify(detail.exclusion_reasons)}`} />
      : <>
        <div>
          <h3>Overall metrics</h3>
          <div className="list-head eval-metric-row"><span>Metric</span><span>Value</span></div>
          {Object.entries(detail.overall_metrics).map(([name, value]) => <div className="list-row eval-metric-row" key={name}><span>{name.replaceAll("_", " ")}</span><span>{(value * 100).toFixed(2)}%</span></div>)}
        </div>
        <div>
          <h3>Per-class metrics</h3>
          <div className="list-head eval-class-row"><span>Class</span><span>Precision</span><span>Recall</span><span>F1</span><span>Support</span></div>
          {Object.entries(detail.per_class_metrics).map(([label, values]) => <div className="list-row eval-class-row" key={label}>
            <span>{label}</span><span>{((values.precision ?? 0) * 100).toFixed(1)}%</span><span>{((values.recall ?? 0) * 100).toFixed(1)}%</span><span>{((values.f1 ?? 0) * 100).toFixed(1)}%</span><span>{values.support}</span>
          </div>)}
        </div>
        {detail.confusion_matrix && <div>
          <h3>Confusion matrix</h3>
          <table className="confusion-matrix" aria-label="Confusion matrix: rows are true labels, columns are predicted labels">
            <thead><tr><th scope="col">True \ Predicted</th>{detail.confusion_matrix.labels.map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead>
            <tbody>{detail.confusion_matrix.matrix.map((row, i) => <tr key={detail.confusion_matrix!.labels[i]}><th scope="row">{detail.confusion_matrix!.labels[i]}</th>{row.map((value, j) => <td key={j}>{value}</td>)}</tr>)}</tbody>
          </table>
        </div>}
        <div>
          <h3>Error slice (misclassifications, PII-redacted)</h3>
          {errors.length === 0 ? <Empty label="No misclassifications in this run." /> : <div className="list-head eval-error-row"><span>Text</span><span>True</span><span>Predicted</span></div>}
          {errors.map(example => <div className="list-row eval-error-row" key={example.id}><span>{example.redacted_text}</span><span>{example.true_label}</span><span>{example.predicted_label}</span></div>)}
        </div>
      </>}
  </div>;
}
