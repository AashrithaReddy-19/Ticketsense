import { useEffect, useState } from "react";
import { api, type KnowledgeConflictView } from "../api/client";
import { Badge, Empty, ErrorState, Loading } from "../components/States";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Dialog";
import { useToast } from "../components/ui/Toast";

export default function AdminKnowledgeConflicts() {
  const toast = useToast();
  const [conflicts, setConflicts] = useState<KnowledgeConflictView[]>([]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState("");
  const [reviewTarget, setReviewTarget] = useState<KnowledgeConflictView | null>(null);
  const [reviewAction, setReviewAction] = useState<"resolved" | "dismissed">("resolved");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true); setError("");
    try { setConflicts((await api.knowledgeConflicts()).items); }
    catch (e) { setError(e instanceof Error ? e.message : "Knowledge conflict detection is not available for this account or tenant."); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  async function scan() {
    setScanning(true);
    try { const result = await api.scanKnowledgeConflicts(); toast(result.new_conflicts === 0 ? "Scan complete — no new conflicts found." : `Scan complete — ${result.new_conflicts} new conflict(s) found.`, result.new_conflicts > 0 ? "danger" : "success"); await load(); }
    catch (e) { toast(e instanceof Error ? e.message : "Unable to run the conflict scan", "danger"); }
    finally { setScanning(false); }
  }

  async function submitReview() {
    if (!reviewTarget) return;
    setBusy(true);
    try {
      await api.reviewKnowledgeConflict(reviewTarget.id, { review_state: reviewAction, resolution_note: note });
      toast(`Conflict marked ${reviewAction}.`, "success");
      setReviewTarget(null); setNote("");
      await load();
    } catch (e) { toast(e instanceof Error ? e.message : "Unable to update the conflict", "danger"); }
    finally { setBusy(false); }
  }

  if (loading) return <div className="content"><Loading label="Loading knowledge conflicts…" /></div>;
  if (error && conflicts.length === 0) return <div className="content"><ErrorState message={error} onRetry={load} /></div>;

  const openCount = conflicts.filter(c => c.review_state === "open").length;

  return <div className="content">
    <div className="page-title">
      <div><p className="eyebrow">TicketSense V2 knowledge platform</p><h1>Knowledge conflicts</h1>
        <p>Real signals computed from approved articles, citations and recorded outcomes. Articles are never auto-edited or deleted — every conflict is a human review task, and open high/critical conflicts block that evidence from auto-resolution.</p></div>
      <div className="live"><span />No sample metrics</div>
    </div>
    <div className="panel" style={{ marginBottom: "1rem", display: "flex", gap: "1rem", alignItems: "center" }}>
      <Button variant="primary" loading={scanning} onClick={scan}>Run conflict scan</Button>
      <small>{openCount} open of {conflicts.length} total</small>
    </div>
    {conflicts.length === 0 ? <Empty label="No knowledge conflicts detected yet." /> : <div className="panel governance-table">
      <div className="list-head governance-row"><span>Conflict</span><span>Severity</span><span>Status</span><span></span></div>
      {conflicts.map(conflict => <article className="list-row governance-row" key={conflict.id}>
        <div><b>{conflict.conflict_type.replaceAll("_", " ")}</b><small>{conflict.evidence_excerpt_a.slice(0, 140)}</small>{conflict.sample_size != null && <small>Sample size: {conflict.sample_size}</small>}</div>
        <Badge value={conflict.severity} />
        <Badge value={conflict.review_state} />
        {conflict.review_state === "open" ? <Button size="sm" variant="outline" onClick={() => { setReviewTarget(conflict); setReviewAction("resolved"); setNote(""); }}>Review</Button> : <small>{conflict.resolution_note}</small>}
      </article>)}
    </div>}

    <Modal open={!!reviewTarget} onClose={() => setReviewTarget(null)} title="Review knowledge conflict" description="Resolving or dismissing this conflict clears the auto-resolution block for this evidence. The article itself is never edited or deleted here." footer={<><Button variant="outline" onClick={() => setReviewTarget(null)}>Cancel</Button><Button variant="primary" disabled={note.trim().length < 3} loading={busy} onClick={submitReview}>Save decision</Button></>}>
      <label className="ui-field"><span>Decision</span><select value={reviewAction} onChange={e => setReviewAction(e.target.value as typeof reviewAction)}><option value="resolved">Resolved (article corrected outside this tool)</option><option value="dismissed">Dismissed (false positive)</option></select></label>
      <label className="ui-field"><span>Note <em>required</em></span><textarea rows={4} value={note} onChange={e => setNote(e.target.value)} /></label>
    </Modal>
  </div>;
}
