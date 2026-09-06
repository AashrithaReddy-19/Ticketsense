import { useEffect, useState } from "react";
import { api, type OcrBenchmarkCaseView, type OcrBenchmarkDatasetView, type OcrBenchmarkRunView, type OcrEngineStatus } from "../api/client";
import { Badge, Empty, ErrorState, Loading } from "../components/States";
import { Button } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";

const ENGINES = ["tesseract", "easyocr", "paddleocr"] as const;

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve((reader.result as string).split(",").pop() || "");
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export default function AdminOcrBenchmarkLab() {
  const toast = useToast();
  const [engines, setEngines] = useState<Record<string, OcrEngineStatus>>({});
  const [datasets, setDatasets] = useState<OcrBenchmarkDatasetView[]>([]);
  const [selected, setSelected] = useState<OcrBenchmarkDatasetView | null>(null);
  const [cases, setCases] = useState<OcrBenchmarkCaseView[]>([]);
  const [runs, setRuns] = useState<OcrBenchmarkRunView[]>([]);
  const [runDetail, setRunDetail] = useState<OcrBenchmarkRunView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [newKey, setNewKey] = useState(""); const [newName, setNewName] = useState("");
  const [file, setFile] = useState<File | null>(null); const [groundTruth, setGroundTruth] = useState("");
  const [engine, setEngine] = useState<string>("tesseract");
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true); setError("");
    try {
      const [engineResult, datasetResult] = await Promise.all([api.ocrEngines(), api.ocrDatasets()]);
      setEngines(engineResult.engines);
      setDatasets(datasetResult.items);
    } catch (e) { setError(e instanceof Error ? e.message : "The OCR benchmark lab is not available for this account or tenant."); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  async function selectDataset(dataset: OcrBenchmarkDatasetView) {
    setSelected(dataset); setRunDetail(null);
    const [caseResult, runResult] = await Promise.all([api.ocrCases(dataset.id), api.ocrRuns(dataset.id)]);
    setCases(caseResult.items); setRuns(runResult.items);
  }

  async function createDataset() {
    setBusy(true);
    try {
      const dataset = await api.createOcrDataset({ key: newKey, name: newName });
      toast("Dataset registered.", "success");
      setNewKey(""); setNewName("");
      await load();
      await selectDataset(dataset);
    } catch (e) { toast(e instanceof Error ? e.message : "Unable to create the dataset", "danger"); }
    finally { setBusy(false); }
  }

  async function addCase() {
    if (!selected || !file) return;
    setBusy(true);
    try {
      await api.createOcrCase(selected.id, { image_base64: await fileToBase64(file), ground_truth_text: groundTruth });
      toast("Ground-truth case added.", "success");
      setFile(null); setGroundTruth("");
      await load();
      await selectDataset(selected);
    } catch (e) { toast(e instanceof Error ? e.message : "Unable to add the case", "danger"); }
    finally { setBusy(false); }
  }

  async function triggerRun() {
    if (!selected) return;
    setBusy(true);
    try {
      const run = await api.createOcrRun({ dataset_id: selected.id, engine });
      toast(run.status === "completed" ? `Run complete — mean CER ${((run.mean_character_error_rate ?? 0) * 100).toFixed(1)}%.` : `Run finished as "${run.status.replaceAll("_", " ")}".`, run.status === "completed" ? "success" : "danger");
      await selectDataset(selected);
      setRunDetail(await api.ocrRunDetail(run.id));
    } catch (e) { toast(e instanceof Error ? e.message : "Unable to start the benchmark run", "danger"); }
    finally { setBusy(false); }
  }

  if (loading) return <div className="content"><Loading label="Loading OCR benchmark lab…" /></div>;
  if (error && datasets.length === 0) return <div className="content"><ErrorState message={error} onRetry={load} /></div>;

  return <div className="content">
    <div className="page-title">
      <div><p className="eyebrow">TicketSense V2 multimodal diagnostics</p><h1>OCR benchmark lab</h1>
        <p>Curated, synthetic ground-truth screenshots and logs only — never a real customer attachment. Every character/word error rate is computed from a real engine call; an engine that isn't installed here reports itself unavailable rather than a fabricated score.</p></div>
      <div className="live"><span />No sample metrics</div>
    </div>

    <div className="panel" style={{ marginBottom: "1rem" }}>
      <h3>Engine availability</h3>
      <div className="eval-lab-table">
        <div className="list-head eval-metric-row"><span>Engine</span><span>Status</span></div>
        {ENGINES.map(name => <div className="list-row eval-metric-row" key={name}>
          <span>{name}</span>
          <span><Badge value={engines[name]?.available ? "available" : "not configured"} />{!engines[name]?.available && <small> {engines[name]?.reason}</small>}</span>
        </div>)}
      </div>
    </div>

    <div className="panel" style={{ marginBottom: "1rem", display: "flex", gap: "1rem", alignItems: "flex-end", flexWrap: "wrap" }}>
      <label className="ui-field"><span>Dataset key</span><input value={newKey} onChange={e => setNewKey(e.target.value)} placeholder="error-screenshots" /></label>
      <label className="ui-field"><span>Dataset name</span><input value={newName} onChange={e => setNewName(e.target.value)} placeholder="Error dialog screenshots" /></label>
      <Button variant="primary" loading={busy} disabled={!newKey || !newName} onClick={createDataset}>Register dataset</Button>
    </div>

    {datasets.length === 0 ? <Empty label="No OCR benchmark datasets registered yet." /> : <div className="panel" style={{ marginBottom: "1rem" }}>
      <div className="eval-lab-table">
        <div className="list-head eval-metric-row"><span>Dataset</span><span>Cases</span></div>
        {datasets.map(dataset => <button key={dataset.id} className="list-row eval-metric-row" style={{ width: "100%", textAlign: "left", background: selected?.id === dataset.id ? "var(--surface-hover, rgba(0,0,0,0.04))" : "transparent", border: "none", cursor: "pointer" }} onClick={() => selectDataset(dataset)}>
          <span><b>{dataset.name}</b> <small>{dataset.key}</small></span><span>{dataset.case_count}</span>
        </button>)}
      </div>
    </div>}

    {selected && <>
      <div className="panel" style={{ marginBottom: "1rem" }}>
        <h3>Add ground-truth case to “{selected.name}”</h3>
        <div style={{ display: "flex", gap: "1rem", alignItems: "flex-end", flexWrap: "wrap" }}>
          <label className="ui-field"><span>Image</span><input type="file" accept="image/*" onChange={e => setFile(e.target.files?.[0] ?? null)} /></label>
          <label className="ui-field" style={{ flex: 1, minWidth: "200px" }}><span>Ground-truth text</span><textarea rows={2} value={groundTruth} onChange={e => setGroundTruth(e.target.value)} /></label>
          <Button variant="outline" loading={busy} disabled={!file || !groundTruth} onClick={addCase}>Add case</Button>
        </div>
        {cases.length > 0 && <p><small>{cases.length} case(s) registered.</small></p>}
      </div>

      <div className="panel" style={{ marginBottom: "1rem", display: "flex", gap: "1rem", alignItems: "center" }}>
        <label className="ui-field"><span>Engine</span><select value={engine} onChange={e => setEngine(e.target.value)}>{ENGINES.map(name => <option key={name} value={name}>{name}</option>)}</select></label>
        <Button variant="primary" loading={busy} onClick={triggerRun}>Run benchmark</Button>
      </div>

      {runs.length > 0 && <div className="panel" style={{ marginBottom: "1rem" }}>
        <h3>Runs</h3>
        <div className="eval-lab-table">
          <div className="list-head eval-metric-row"><span>Engine / status</span><span>Mean CER / WER</span></div>
          {runs.map(run => <button key={run.id} className="list-row eval-metric-row" style={{ width: "100%", textAlign: "left", border: "none", background: "transparent", cursor: "pointer" }} onClick={async () => setRunDetail(await api.ocrRunDetail(run.id))}>
            <span>{run.engine} <Badge value={run.status} /></span>
            <span>{run.mean_character_error_rate == null ? run.unavailable_reason ?? "unavailable" : `${(run.mean_character_error_rate * 100).toFixed(1)}% / ${((run.mean_word_error_rate ?? 0) * 100).toFixed(1)}%`}</span>
          </button>)}
        </div>
      </div>}

      {runDetail?.results && <div className="panel">
        <h3>Run detail — {runDetail.engine}</h3>
        <div className="eval-lab-table">
          <div className="list-head dependency-edge-row"><span>Extracted text</span><span>CER / WER</span><span>Latency</span></div>
          {runDetail.results.map(result => <div className="list-row dependency-edge-row" key={result.id}>
            <span>{result.extracted_text || <em>(empty)</em>}</span>
            <span>{(result.character_error_rate * 100).toFixed(1)}% / {(result.word_error_rate * 100).toFixed(1)}%</span>
            <span>{result.latency_ms.toFixed(0)}ms</span>
          </div>)}
        </div>
      </div>}
    </>}
  </div>;
}
