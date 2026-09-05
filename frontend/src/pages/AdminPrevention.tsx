import { useEffect, useState } from "react";
import { api, type PreventionRecommendation, type PreventionRecommendationDetail } from "../api/client";
import { Badge, Empty, ErrorState, Loading } from "../components/States";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Dialog";
import { useToast } from "../components/ui/Toast";

const STATUS_TABS: Array<[string, string]> = [["", "All"], ["new", "New"], ["under_investigation", "Investigating"], ["accepted", "Accepted"], ["converted", "Converted"], ["dismissed", "Dismissed"], ["rejected", "Rejected"]];
const TYPE_LABELS: Record<string, string> = {
  create_knowledge_article: "Create knowledge article", update_knowledge_article: "Update knowledge article",
  investigate_version: "Investigate version", publish_customer_announcement: "Publish announcement",
  conduct_training: "Conduct training", add_monitoring: "Add monitoring",
  review_capacity_allocation: "Review capacity", investigate_infrastructure: "Investigate infrastructure",
};

function RecommendationDetail({ recommendation, onChanged }: { recommendation: PreventionRecommendation; onChanged: () => void }) {
  const toast = useToast();
  const [detail, setDetail] = useState<PreventionRecommendationDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [dismissing, setDismissing] = useState(false);
  const [reason, setReason] = useState("");

  useEffect(() => { api.preventionRecommendation(recommendation.id).then(setDetail).catch(() => setDetail(null)); }, [recommendation.id]);

  async function act(action: "accept" | "investigate" | "convert" | "reject" | "dismiss") {
    setBusy(true);
    try {
      if (action === "accept") await api.acceptRecommendation(recommendation.id);
      else if (action === "investigate") await api.investigateRecommendation(recommendation.id);
      else if (action === "convert") { const result = await api.convertRecommendationToKnowledge(recommendation.id); toast(`Draft article ${result.knowledge_article_id.slice(0, 8)} created`, "success"); }
      else if (action === "reject") await api.rejectRecommendation(recommendation.id, reason);
      else if (action === "dismiss") await api.dismissRecommendation(recommendation.id, reason);
      toast(`Recommendation ${action === "convert" ? "converted" : action + "ed"}`, "success");
      setDismissing(false); setReason("");
      onChanged();
    } catch (err) { toast(err instanceof Error ? err.message : `Unable to ${action}`, "danger"); }
    finally { setBusy(false); }
  }

  const canReview = ["new", "under_investigation"].includes(recommendation.status);
  return (
    <div className="incident-detail">
      <p>{recommendation.description}</p>
      <p><b>Expected benefit:</b> {recommendation.expected_benefit}</p>
      {detail && (
        <>
          <p className="empty-note">Evidence ({detail.evidence.length} item{detail.evidence.length === 1 ? "" : "s"}):</p>
          <ul>{detail.evidence.slice(0, 5).map((e, i) => <li key={i}>{e.evidence_type}{e.reference_id ? ` — ${e.reference_id.slice(0, 8)}` : ""}</li>)}</ul>
          {detail.actions.length > 0 && (
            <>
              <p className="empty-note">Action history:</p>
              <ul>{detail.actions.map((a, i) => <li key={i}>{a.action_type}{a.reason ? `: ${a.reason}` : ""} — {new Date(a.created_at).toLocaleString()}</li>)}</ul>
            </>
          )}
        </>
      )}
      {canReview && (
        <div className="review-actions">
          {recommendation.status === "new" && <Button size="sm" variant="outline" loading={busy} onClick={() => act("investigate")}>Mark investigating</Button>}
          <Button size="sm" variant="primary" loading={busy} onClick={() => act("accept")}>Accept</Button>
          {["create_knowledge_article", "update_knowledge_article"].includes(recommendation.recommendation_type) &&
            <Button size="sm" variant="primary" loading={busy} onClick={() => act("convert")}>Convert to draft article</Button>}
          <Button size="sm" variant="outline" loading={busy} onClick={() => setDismissing(true)}>Dismiss</Button>
        </div>
      )}
      <Modal open={dismissing} onClose={() => setDismissing(false)} title="Dismiss this recommendation" footer={null}>
        <div className="admin-engineer-form">
          <label className="ui-field"><span>Reason</span><textarea required minLength={3} rows={3} value={reason} onChange={e => setReason(e.target.value)} /></label>
          <div className="form-actions"><Button type="button" variant="outline" onClick={() => setDismissing(false)}>Cancel</Button><Button type="button" variant="primary" loading={busy} disabled={reason.trim().length < 3} onClick={() => act("dismiss")}>Dismiss</Button></div>
        </div>
      </Modal>
    </div>
  );
}

export default function AdminPrevention() {
  const [statusFilter, setStatusFilter] = useState("");
  const [items, setItems] = useState<PreventionRecommendation[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState("");
  const toast = useToast();

  async function load() {
    setLoading(true);
    try { setItems(await api.preventionRecommendations({ status_filter: statusFilter })); setError(""); }
    catch (e) { setError(e instanceof Error ? e.message : "Request failed"); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [statusFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  async function scan() {
    setScanning(true);
    try { const found = await api.scanForPreventionRecommendations(); toast(`Scan complete — ${found.length} new recommendation(s)`, "success"); await load(); }
    catch (err) { toast(err instanceof Error ? err.message : "Scan failed", "danger"); }
    finally { setScanning(false); }
  }

  return (
    <div className="content">
      <div className="page-title">
        <div><h1>Predictive prevention</h1><p>Evidence-backed recommendations from real tenant-scoped trends — never a confirmed cause, always a labelled recommendation.</p></div>
        <Button variant="outline" loading={scanning} onClick={scan}>Scan now</Button>
      </div>
      <div className="tabs" role="tablist">
        {STATUS_TABS.map(([key, label]) => <button key={key} role="tab" aria-selected={statusFilter === key} className={statusFilter === key ? "active" : ""} onClick={() => setStatusFilter(key)}>{label}</button>)}
      </div>
      {loading ? <Loading skeleton /> : error ? <ErrorState message={error} onRetry={load} /> : items.length ? (
        <div className="knowledge-grid">
          {items.map(rec => (
            <article className="panel knowledge-card" key={rec.id}>
              <Badge value={rec.evidence_strength} /> <Badge value={rec.status} />
              <h3>{rec.title}</h3>
              <p>{TYPE_LABELS[rec.recommendation_type] || rec.recommendation_type}</p>
              <div className="incident-stats">
                <b>{rec.supporting_ticket_count}<small>Supporting</small></b>
                <b>{rec.window_days}d<small>Window</small></b>
                <b>{rec.category || "—"}<small>Category</small></b>
              </div>
              <Button size="sm" variant="ghost" onClick={() => setExpanded(expanded === rec.id ? null : rec.id)}>{expanded === rec.id ? "Hide details" : "View details"}</Button>
              {expanded === rec.id && <RecommendationDetail recommendation={rec} onChanged={load} />}
            </article>
          ))}
        </div>
      ) : <Empty label="No recommendations match this filter." />}
    </div>
  );
}
