import { useEffect, useState, type FormEvent } from "react";
import { api, type KnowledgeArticleSummary, type KnowledgeGaps, type KnowledgeHealth } from "../api/client";
import { Badge, Empty, ErrorState, Loading } from "../components/States";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Dialog";
import { useToast } from "../components/ui/Toast";

type Tab = "articles" | "gaps" | "health";
const STATUS_TABS: Array<[string, string]> = [["", "All"], ["pending_review", "Pending review"], ["published", "Published"], ["rejected", "Rejected"], ["draft", "Draft"]];

function ArticlesPanel() {
  const toast = useToast();
  const [statusFilter, setStatusFilter] = useState("pending_review");
  const [articles, setArticles] = useState<KnowledgeArticleSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<KnowledgeArticleSummary | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [form, setForm] = useState({ title: "", body: "" });

  async function load() {
    setLoading(true); setError("");
    try { setArticles(await api.knowledgeArticles(statusFilter)); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to load knowledge articles"); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [statusFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  async function create(e: FormEvent) {
    e.preventDefault();
    try { await api.generateKnowledgeArticle(form); setOpen(false); setForm({ title: "", body: "" }); toast("Draft article created — pending review", "success"); await load(); }
    catch (err) { toast(err instanceof Error ? err.message : "Unable to create the article", "danger"); }
  }

  async function approve(article: KnowledgeArticleSummary) {
    setBusy(article.id);
    try { await api.approveKnowledgeArticle(article.id); toast("Published to the retrieval knowledge base", "success"); await load(); }
    catch (err) { toast(err instanceof Error ? err.message : "Unable to approve this article", "danger"); }
    finally { setBusy(null); }
  }

  async function reject() {
    if (!rejecting) return;
    setBusy(rejecting.id);
    try { await api.rejectKnowledgeArticle(rejecting.id, rejectReason); toast("Article rejected", "success"); setRejecting(null); setRejectReason(""); await load(); }
    catch (err) { toast(err instanceof Error ? err.message : "Unable to reject this article", "danger"); }
    finally { setBusy(null); }
  }

  return (
    <>
      <div className="tabs" role="tablist" aria-label="Article status filter">
        {STATUS_TABS.map(([key, label]) => <button key={key} role="tab" aria-selected={statusFilter === key} className={statusFilter === key ? "active" : ""} onClick={() => setStatusFilter(key)}>{label}</button>)}
      </div>
      <div className="filter-bar">
        <span className="empty-note">Draft-from-resolution articles appear here automatically when a human resolves a ticket with no cited evidence.</span>
        <Button variant="primary" size="sm" onClick={() => setOpen(true)}>New article</Button>
      </div>
      {loading ? <Loading skeleton /> : error ? <ErrorState message={error} onRetry={load} /> : articles.length ? (
        <div className="panel ticket-list">
          <div className="list-head admin-engineer-row"><span>Title</span><span>Status</span><span>Source</span><span>Version</span><span>Actions</span></div>
          {articles.map(article => (
            <article className="list-row admin-engineer-row" key={article.id}>
              <div><b>{article.title}</b>{article.rejected_reason && <small>Rejected: {article.rejected_reason}</small>}</div>
              <Badge value={article.status} />
              <span>{article.source_signal === "no_cited_evidence_at_resolution" ? "Auto-drafted (knowledge gap)" : article.source_signal === "manual" ? "Manually authored" : "—"}</span>
              <span>{article.version}{article.published_knowledge_base_id ? " · embedded" : ""}</span>
              <div className="review-actions">
                {article.status === "pending_review" && <>
                  <Button size="sm" variant="primary" loading={busy === article.id} onClick={() => approve(article)}>Approve &amp; publish</Button>
                  <Button size="sm" variant="outline" onClick={() => setRejecting(article)}>Reject</Button>
                </>}
              </div>
            </article>
          ))}
        </div>
      ) : <Empty label="No articles match this filter." />}
      <Modal open={open} onClose={() => setOpen(false)} title="Author a knowledge article" footer={null}>
        <form onSubmit={create} className="admin-engineer-form">
          <label className="ui-field"><span>Title</span><input required minLength={4} value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} /></label>
          <label className="ui-field"><span>Body</span><textarea required minLength={20} rows={6} value={form.body} onChange={e => setForm({ ...form, body: e.target.value })} /></label>
          <small>Saved as a pending-review draft — it is never published or embedded until an Admin explicitly approves it.</small>
          <div className="form-actions"><Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" variant="primary">Save draft</Button></div>
        </form>
      </Modal>
      <Modal open={!!rejecting} onClose={() => setRejecting(null)} title="Reject this article" footer={null}>
        <div className="admin-engineer-form">
          <label className="ui-field"><span>Reason</span><textarea required minLength={3} rows={3} value={rejectReason} onChange={e => setRejectReason(e.target.value)} /></label>
          <div className="form-actions"><Button type="button" variant="outline" onClick={() => setRejecting(null)}>Cancel</Button><Button type="button" variant="primary" loading={busy === rejecting?.id} onClick={reject} disabled={rejectReason.trim().length < 3}>Reject</Button></div>
        </div>
      </Modal>
    </>
  );
}

function GapsPanel() {
  const [gaps, setGaps] = useState<KnowledgeGaps | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => { api.knowledgeGaps().then(setGaps).catch(e => setError(e instanceof Error ? e.message : "Unable to load knowledge gaps")).finally(() => setLoading(false)); }, []);
  if (loading) return <Loading skeleton />;
  if (error) return <ErrorState message={error} />;
  if (!gaps) return null;
  const hasData = gaps.weak_evidence_by_category.length > 0 || gaps.heavy_edit_by_category.length > 0;
  return hasData ? (
    <>
      <section className="metric-section">
        <h2>Weak or missing evidence</h2>
        <p className="empty-note">Categories where the resolution-policy gate actually failed for lack of approved, relevant evidence in the last {gaps.window_days} days.</p>
        {gaps.weak_evidence_by_category.map(row => (
          <div className="metric-bar-row" key={row.category}>
            <span className="metric-bar-label">{row.category}</span>
            <div className="metric-bar-track"><div className="metric-bar-fill metric-bar-danger" style={{ width: `${Math.min(100, row.count * 10)}%` }} /></div>
            <span className="metric-bar-value">{row.count} ticket{row.count === 1 ? "" : "s"}</span>
          </div>
        ))}
      </section>
      <section className="metric-section">
        <h2>Heavy reviewer edits</h2>
        <p className="empty-note">Categories where a reviewer's final text diverged substantially (&gt;50% character-level change) from the AI draft — a sign the source evidence didn't really fit.</p>
        {gaps.heavy_edit_by_category.map(row => (
          <div className="metric-bar-row" key={row.category}>
            <span className="metric-bar-label">{row.category}</span>
            <div className="metric-bar-track"><div className="metric-bar-fill metric-bar-warning" style={{ width: `${Math.min(100, (row.average_edit_ratio ?? 0) * 100)}%` }} /></div>
            <span className="metric-bar-value">{row.count} · avg {(row.average_edit_ratio ?? 0) * 100 | 0}% changed</span>
          </div>
        ))}
      </section>
    </>
  ) : <Empty label="No knowledge-gap signals in this window — every recent resolution had adequate approved evidence." />;
}

function HealthPanel() {
  const [health, setHealth] = useState<KnowledgeHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => { api.knowledgeHealth().then(setHealth).catch(e => setError(e instanceof Error ? e.message : "Unable to load knowledge health")).finally(() => setLoading(false)); }, []);
  if (loading) return <Loading skeleton />;
  if (error) return <ErrorState message={error} />;
  if (!health) return null;
  return health.articles.length ? (
    <div className="panel ticket-list">
      <div className="list-head admin-engineer-row"><span>Article</span><span>Version</span><span>Age</span><span>Status</span><span /></div>
      {health.articles.map(article => (
        <article className="list-row admin-engineer-row" key={article.id}>
          <b>{article.title}</b><span>{article.version}</span><span>{article.age_days ?? "—"} days</span>
          <Badge value={article.stale ? "stale" : "current"} /><span />
        </article>
      ))}
    </div>
  ) : <Empty label="No published knowledge articles yet." />;
}

export default function AdminKnowledge() {
  const [tab, setTab] = useState<Tab>("articles");
  return (
    <div className="content">
      <div className="page-title"><div><h1>Knowledge management</h1><p>Review, approve, and monitor the approved evidence corpus that AI resolutions cite.</p></div></div>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "articles"} className={tab === "articles" ? "active" : ""} onClick={() => setTab("articles")}>Articles</button>
        <button role="tab" aria-selected={tab === "gaps"} className={tab === "gaps" ? "active" : ""} onClick={() => setTab("gaps")}>Knowledge gaps</button>
        <button role="tab" aria-selected={tab === "health"} className={tab === "health" ? "active" : ""} onClick={() => setTab("health")}>Knowledge health</button>
      </div>
      {tab === "articles" && <ArticlesPanel />}
      {tab === "gaps" && <GapsPanel />}
      {tab === "health" && <HealthPanel />}
    </div>
  );
}
