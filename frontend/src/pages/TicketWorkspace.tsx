import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type Analysis, type AttachmentMeta, type Evidence, type GroundedDraft, type Ticket } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Badge, ErrorState, Loading } from "../components/States";
import { IconAlert, IconArrowLeft, IconCheckCircle, IconPaperclip, IconRefresh } from "../components/icons";
import { Button } from "../components/ui/Button";
import { CitationValidationBadge, ExtractionStatusBadge } from "../components/ui/Badges";
import { EvidenceCard } from "../components/ui/Card";
import { ConfirmDialog } from "../components/ui/Dialog";
import { Tabs, TabPanel } from "../components/ui/Tabs";
import { Timeline } from "../components/ui/Utility";
import { useToast } from "../components/ui/Toast";
import { buildPipelineStages, ExplainPipeline, PipelineView } from "../components/ui/Pipeline";

type Similar = { id: string; subject: string; status: string; similarity: number };
type Trace = { action: string; detail: Record<string, unknown>; timestamp: string };
type ActionName = "accept" | "escalate" | "reject" | "reopen";
type PendingAction = { name: ActionName; label: string; description: string; variant: "primary" | "destructive" } | null;

export default function TicketWorkspace() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { hasPermission } = useAuth();
  const internal = hasPermission("ai:view_summary");
  const canTransition = hasPermission("ticket:transition");
  const canMutate = hasPermission("ticket:transition") || hasPermission("ticket:review");

  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [analysis, setAnalysis] = useState<Analysis>({});
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [similar, setSimilar] = useState<Similar[]>([]);
  const [trace, setTrace] = useState<Trace[]>([]);
  const [draft, setDraft] = useState<GroundedDraft | null>(null);
  const [attachment, setAttachment] = useState<AttachmentMeta | null>(null);
  const [tab, setTab] = useState("overview");
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState<PendingAction>(null);
  const [reason, setReason] = useState("");
  const cards = useRef<Record<string, HTMLElement | null>>({});

  async function load() {
    setLoading(true); setError("");
    try {
      const t = await api.ticket(id);
      setTicket(t);
      const at = await api.attachment(id).catch(() => null);
      setAttachment(at);
      if (internal) {
        const [a, e, s, tr, dr] = await Promise.all([
          api.analysis(id), api.evidence(id), api.similar(id), api.trace(id),
          api.groundedDraft(id).catch(() => null),
        ]);
        setAnalysis(a); setEvidence(e); setSimilar(s); setTrace(tr); setDraft(dr);
      }
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to load ticket"); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [id, internal]); // eslint-disable-line react-hooks/exhaustive-deps

  async function runAction(name: ActionName) {
    setActing(true); setError("");
    try {
      const updated = await api.ticketAction(id, { action: name, response: internal ? ticket?.ai_draft_reply || undefined : undefined, reason: reason.trim() || undefined });
      setTicket(updated);
      toast(`Ticket ${name === "accept" ? "approved and resolved" : name} successfully.`, "success");
      if (internal) setTrace(await api.trace(id));
    } catch (e) { toast(e instanceof Error ? e.message : "Action failed", "danger"); }
    finally { setActing(false); setPending(null); setReason(""); }
  }

  async function generate() {
    setActing(true); setError("");
    try { setDraft(await api.generateGroundedDraft(id)); toast("Grounded draft generated.", "success"); }
    catch (e) { toast(e instanceof Error ? e.message : "Generation unavailable", "danger"); }
    finally { setActing(false); }
  }

  async function process() {
    setActing(true); setError("");
    try { setAttachment(await api.processAttachment(id)); toast("Attachment processed.", "success"); }
    catch (e) { toast(e instanceof Error ? e.message : "Extraction failed", "danger"); }
    finally { setActing(false); }
  }

  function locate(cid: string) {
    const el = cards.current[cid];
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    el?.classList.add("citation-focus");
    el?.focus();
    setTimeout(() => el?.classList.remove("citation-focus"), 1500);
  }

  if (loading) return <div className="content"><Loading label={internal ? "Loading ticket workspace…" : "Loading your ticket…"} /></div>;
  if (error && !ticket) return <div className="content"><ErrorState message={error} onRetry={load} /></div>;
  if (!ticket) return null;

  const tabs = internal
    ? [{ key: "overview", label: "Overview" }, { key: "analysis", label: "Analysis" }, { key: "evidence", label: "Evidence" }, { key: "similar", label: "Similar tickets" }, { key: "trace", label: "Trace" }, { key: "pipeline", label: "Pipeline" }]
    : [{ key: "overview", label: "Overview" }];

  const actionDefs: Record<string, PendingAction> = {
    accept: { name: "accept", label: "Approve & resolve", description: "This marks the ticket resolved and shares the current response with the customer.", variant: "primary" },
    escalate: { name: "escalate", label: "Escalate", description: "This routes the ticket to expert escalation handling.", variant: "destructive" },
    reject: { name: "reject", label: "Reject recommendation", description: "This rejects the current recommendation and escalates the ticket for further review.", variant: "destructive" },
    reopen: { name: "reopen", label: "Reopen ticket", description: "This reopens a resolved ticket so it can be worked again.", variant: "primary" },
  };

  return (
    <div className="content workspace">
      <button className="back" onClick={() => nav(-1)}><IconArrowLeft size={14} />Back to tickets</button>
      {error && <div className="error-box" role="alert">{error}</div>}

      <div className="workspace-head">
        <div><small>Ticket {ticket.id}</small><h1>{ticket.subject}</h1><p>Created {new Date(ticket.created_at).toLocaleString()}{ticket.updated_at ? ` · Updated ${new Date(ticket.updated_at).toLocaleString()}` : ""}</p></div>
        <div><Badge value={ticket.priority} /><Badge value={ticket.status} /></div>
      </div>

      <div className="workspace-grid">
        <aside className="panel ticket-meta">
          <h3>Ticket information</h3>
          <Meta label="Status" value={ticket.status} />
          <Meta label="Priority" value={ticket.priority || "—"} />
          <Meta label="Sentiment" value={ticket.sentiment || "—"} />
          <Meta label="Department" value={ticket.department_id || "Not assigned"} />
          {internal && <>
            <Meta label="Category" value={String(analysis.category || "Unclassified")} />
            <Meta label="SLA risk" value={`${analysis.sla_risk || 0}%`} />
            <Meta label="Confidence" value={`${Math.round((ticket.confidence_score || 0) * 100)}%`} />
          </>}
        </aside>

        <section className="panel workspace-center">
          <Tabs tabs={tabs} active={tab} onChange={setTab} idPrefix="workspace" />

          <TabPanel id="workspace" tabKey="overview" active={tab}>
            <h3>Customer request</h3>
            <p className="description">{ticket.description}</p>
            {!internal && <>
              <CustomerAttachment attachment={attachment} />
              {ticket.ai_draft_reply && <section className="customer-response"><h3>Support response</h3><p>{ticket.ai_draft_reply}</p></section>}
              <section className="customer-timeline">
                <h3>Ticket progress</h3>
                <Timeline steps={customerTimeline(ticket)} />
              </section>
            </>}
            {internal && <>
              <AttachmentPanel attachment={attachment} canProcess={canMutate} busy={acting} process={process} />
              <div className="draft-heading">
                <h3>Evidence-grounded AI draft</h3>
                {canMutate && <Button variant="outline" size="sm" icon={<IconRefresh size={14} />} loading={acting} onClick={generate}>{draft ? "Retry generation" : "Generate draft"}</Button>}
              </div>
              {!draft ? <p className="empty-note">No grounded draft has been generated.</p> : (
                <div className="draft-evidence-layout">
                  <div className="draft-panel">
                    <Status draft={draft} />
                    {draft.draft_text && <div className="recommendation draft-copy">{renderDraft(draft.draft_text, locate)}</div>}
                    {internal && draft.validation.validation_errors && draft.validation.validation_errors.length > 0 && (
                      <div className="validation-warnings">
                        <b>Validation warnings (internal only)</b>
                        <ul>{draft.validation.validation_errors.map((msg, i) => <li key={i}>{msg}</li>)}</ul>
                      </div>
                    )}
                  </div>
                  <div className="evidence-panel">
                    <h3>Approved knowledge-base evidence</h3>
                    {draft.evidence.length === 0 ? <p className="empty-note">No evidence found.</p> : draft.evidence.map(x => (
                      <EvidenceCard
                        key={x.citation_id}
                        cardRef={el => { cards.current[x.citation_id] = el; }}
                        citationId={x.citation_id}
                        title={x.title}
                        version={x.article_version}
                        department={x.department}
                        snippet={x.chunk_text}
                        similarity={x.similarity}
                      />
                    ))}
                  </div>
                </div>
              )}
            </>}
          </TabPanel>

          <TabPanel id="workspace" tabKey="analysis" active={tab}>
            <h3>AI analysis</h3>
            <Meta label="Decision" value={String(analysis.decision || "—").replaceAll("_", " ")} />
            <Meta label="Reason" value={String(analysis.decision_reason || "—")} />
          </TabPanel>

          <TabPanel id="workspace" tabKey="evidence" active={tab}>
            {evidence.length ? evidence.map(x => (
              <article className="evidence-card" key={x.title}><div><b>{x.title}</b><span>{x.excerpt}</span></div><strong>{Math.round(x.score * 100)}%</strong></article>
            )) : <p className="empty-note">No evidence was retrieved.</p>}
          </TabPanel>

          <TabPanel id="workspace" tabKey="similar" active={tab}>
            {similar.length ? similar.map(x => (
              <div className="similar-card" key={x.id}><div><b>{x.subject}</b><span>{x.status}</span></div><strong>{Math.round(x.similarity * 100)}%</strong></div>
            )) : <p className="empty-note">No similar tickets found.</p>}
          </TabPanel>

          <TabPanel id="workspace" tabKey="trace" active={tab}>
            {trace.length ? trace.map(x => (
              <div className="trace-item" key={`${x.action}-${x.timestamp}`}><i /><div><b>{x.action.replaceAll("_", " ")}</b><span>{new Date(x.timestamp).toLocaleString()}</span></div></div>
            )) : <p className="empty-note">No trace events found.</p>}
          </TabPanel>

          <TabPanel id="workspace" tabKey="pipeline" active={tab}>
            <h3>AI processing pipeline</h3>
            <p className="empty-note">Every stage's status is read directly from this ticket's real data — nothing here is simulated.</p>
            <PipelineView stages={buildPipelineStages({ ticket, attachment, analysis, draft, traceCount: trace.length, canMutate, canTransition })} />
            <ExplainPipeline />
          </TabPanel>
        </section>

        {internal ? (
          <aside className="panel ai-panel">
            <h2>✦ AI Intelligence</h2>
            <div className="confidence-large"><b>{Math.round((ticket.confidence_score || 0) * 100)}%</b><span>confidence</span></div>
            <p>{String(analysis.decision_reason || "Awaiting backend decision.")}</p>
            {canTransition && ticket.status !== "resolved" && (
              <div className="action-stack">
                <Button variant="primary" disabled={acting} onClick={() => setPending(actionDefs.accept)}><IconCheckCircle size={15} />Approve & resolve</Button>
                <Button variant="outline" disabled={acting} onClick={() => setPending(actionDefs.escalate)}>Escalate</Button>
                <Button variant="outline" disabled={acting} onClick={() => setPending(actionDefs.reject)}>Reject recommendation</Button>
              </div>
            )}
          </aside>
        ) : (
          <aside className="panel ai-panel">
            <h2>Ticket progress</h2>
            <p>Your support team is reviewing this request. Internal analysis, confidence and staff notes remain protected.</p>
            {ticket.status === "resolved" && <Button variant="primary" disabled={acting} onClick={() => setPending(actionDefs.reopen)} icon={<IconRefresh size={15} />}>Reopen ticket</Button>}
          </aside>
        )}
      </div>

      <ConfirmDialog
        open={!!pending}
        onClose={() => { setPending(null); setReason(""); }}
        onConfirm={() => pending && runAction(pending.name)}
        title={pending?.label || ""}
        description={pending?.description || ""}
        confirmLabel={pending?.label || "Confirm"}
        variant={pending?.variant}
        busy={acting}
        requireReason={pending?.name === "escalate" || pending?.name === "reject"}
        reason={reason}
        onReasonChange={setReason}
      />
    </div>
  );
}

export function customerTimeline(ticket: Ticket) {
  const order = ["open", "in_review", "escalated", "resolved", "closed"];
  const current = Math.max(0, order.indexOf(ticket.status));
  const labels = ["Submitted", "In review", "Escalated", "Resolved", "Closed"];
  return labels.map((label, index) => ({
    key: order[index], label,
    done: index < current || (index === current && ["resolved", "closed"].includes(ticket.status)),
    active: index === current && !["resolved", "closed"].includes(ticket.status),
    timestamp: index === 0 ? ticket.created_at : index === current ? ticket.updated_at : undefined,
  }));
}

export function CustomerAttachment({ attachment }: { attachment: AttachmentMeta | null }) {
  if (!attachment) return null;
  const safeState = attachment.extraction_status === "failed" ? "Processing unavailable" : attachment.extraction_status === "ready" ? "Processed" : "Processing";
  return <section className="customer-attachment" aria-labelledby="customer-attachment-title">
    <h3 id="customer-attachment-title"><IconPaperclip size={15} /> Attachment</h3>
    <Meta label="File" value={attachment.original_filename} />
    <Meta label="Type and size" value={`${attachment.detected_mime_type} · ${(attachment.file_size_bytes / 1024).toFixed(1)} KB`} />
    <Meta label="Status" value={safeState} />
  </section>;
}

export function AttachmentPanel({ attachment, canProcess, busy, process }: { attachment: AttachmentMeta | null; canProcess: boolean; busy: boolean; process: () => void }) {
  if (!attachment) return <section className="attachment-panel"><h3><IconPaperclip size={15} /> Attachment</h3><p className="empty-note">No attachment.</p></section>;
  return (
    <section className="attachment-panel">
      <div className="draft-heading">
        <h3><IconPaperclip size={15} /> User attachment</h3>
        {canProcess && attachment.extraction_status !== "processing" && (
          <Button variant="outline" size="sm" loading={busy} onClick={process}>{attachment.extraction_status === "failed" ? "Retry extraction" : "Process attachment"}</Button>
        )}
      </div>
      <Meta label="File" value={`${attachment.original_filename} · ${(attachment.file_size_bytes / 1024).toFixed(1)} KB`} />
      <div className="meta"><span>Extraction</span><b><ExtractionStatusBadge value={attachment.extraction_status} /> {attachment.extraction_method || "Not available"}</b></div>
      <Meta label="OCR confidence" value={attachment.ocr_confidence_available && attachment.ocr_confidence != null ? `${(attachment.ocr_confidence * 100).toFixed(1)}%` : "Not available"} />
      {attachment.page_count != null && <Meta label="Page count" value={String(attachment.page_count)} />}
      {attachment.truncated && <div className="error-box"><IconAlert size={14} />Extracted text was truncated.</div>}
      {attachment.warnings && attachment.warnings.length > 0 && <div className="error-box"><IconAlert size={14} />{attachment.warnings.join(", ")}</div>}
      {attachment.sanitized_text ? <pre className="attachment-text">{attachment.sanitized_text}</pre> : null}
    </section>
  );
}

export function Status({ draft }: { draft: GroundedDraft }) {
  if (draft.insufficient_evidence) return <div className="error-box"><IconAlert size={14} />Insufficient evidence: engineer investigation is required.</div>;
  if (draft.citation_validation_status === "invalid") return <div className="error-box"><IconAlert size={14} />Citation validation failed. This draft is unavailable for approval.</div>;
  if (draft.generation_error) return <div className="error-box"><IconAlert size={14} />Generation unavailable.</div>;
  return <div className="success-box"><span><IconCheckCircle size={14} /> Draft ready</span><CitationValidationBadge value={draft.citation_validation_status} /></div>;
}

export function renderDraft(text: string, locate: (id: string) => void) {
  return <>{text.split(/(\[KB-\d{3}\])/g).map((p, i) => /^\[KB-\d{3}\]$/.test(p)
    ? <button className="citation-link" key={i} onClick={() => locate(p.slice(1, -1))}>{p}</button>
    : p)}</>;
}

function Meta({ label, value }: { label: string; value: string }) {
  return <div className="meta"><span>{label}</span><b>{value}</b></div>;
}
