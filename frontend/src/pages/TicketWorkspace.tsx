import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type Analysis, type AttachmentMeta, type CounterfactualExplanationView, type DraftComparison, type EngineerSummary, type Evidence, type GroundedDraft, type PipelineTrace, type ResolutionPassportView, type ResponseDraft, type TechnicalEntity, type Ticket, type TicketEvent, type TicketExplanation, type TicketMessage } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Badge, ErrorState, Loading, SyncIndicator } from "../components/States";
import { IconAlert, IconArrowLeft, IconCheckCircle, IconPaperclip, IconRefresh } from "../components/icons";
import { Button } from "../components/ui/Button";
import { CitationValidationBadge, ExtractionStatusBadge } from "../components/ui/Badges";
import { EvidenceCard } from "../components/ui/Card";
import { Modal } from "../components/ui/Dialog";
import { Tabs, TabPanel } from "../components/ui/Tabs";
import { Timeline } from "../components/ui/Utility";
import { useToast } from "../components/ui/Toast";
import { buildPipelineStages, ExplainPipeline, PipelineView } from "../components/ui/Pipeline";
import { useAutoRefresh } from "../lib/useAutoRefresh";
import SafeActionPanel from "../components/SafeActionPanel";

type Similar = { id: string; subject: string; status: string; similarity: number };
type Trace = { action: string; detail: Record<string, unknown>; timestamp: string };

export default function TicketWorkspace() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { hasPermission, user } = useAuth();
  const internal = hasPermission("ai:view_summary");
  const canTransition = hasPermission("ticket:transition");
  const canMutate = hasPermission("ticket:transition") || hasPermission("ticket:review");
  const canReview = hasPermission("ticket:review");
  const canAssign = hasPermission("ticket:assign");
  const canEngineer = hasPermission("ticket:transition") && !canReview;

  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [analysis, setAnalysis] = useState<Analysis>({});
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [similar, setSimilar] = useState<Similar[]>([]);
  const [trace, setTrace] = useState<Trace[]>([]);
  const [draft, setDraft] = useState<GroundedDraft | null>(null);
  const [attachment, setAttachment] = useState<AttachmentMeta | null>(null);
  const [responseDrafts, setResponseDrafts] = useState<ResponseDraft[]>([]);
  const [draftComparison, setDraftComparison] = useState<DraftComparison | null>(null);
  const [pipelineTrace, setPipelineTrace] = useState<PipelineTrace | null>(null);
  const [technicalEntities, setTechnicalEntities] = useState<TechnicalEntity[]>([]);
  const [explanation, setExplanation] = useState<TicketExplanation | null>(null);
  const [comparisonFrom, setComparisonFrom] = useState("");
  const [comparisonTo, setComparisonTo] = useState("");
  const [events, setEvents] = useState<TicketEvent[]>([]);
  const [passport, setPassport] = useState<ResolutionPassportView | null>(null);
  const [counterfactual, setCounterfactual] = useState<CounterfactualExplanationView | null>(null);
  const [messages, setMessages] = useState<TicketMessage[]>([]);
  const [messageBody, setMessageBody] = useState("");
  const [internalNote, setInternalNote] = useState(false);
  const [engineers, setEngineers] = useState<EngineerSummary[]>([]);
  const [selectedEngineer, setSelectedEngineer] = useState("");
  const [responseContent, setResponseContent] = useState("");
  const [touchedResponse, setTouchedResponse] = useState(false);
  const [touchedAssignment, setTouchedAssignment] = useState(false);
  const [reviewAction, setReviewAction] = useState<"approve"|"modify_and_approve"|"request_changes"|"reject"|"escalate"|null>(null);
  const [tab, setTab] = useState("overview");
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState("");
  const [reason, setReason] = useState("");
  const cards = useRef<Record<string, HTMLElement | null>>({});

  async function load(opts: { silent?: boolean } = {}) {
    if (!opts.silent) { setLoading(true); setError(""); }
    try {
      const t = await api.ticket(id);
      setTicket(t);
      setPassport(t.final_response ? await api.resolutionPassport?.(id).catch(() => null) ?? null : null);
      setCounterfactual(await api.counterfactualExplanation?.(id).catch(() => null) ?? null);
      if (canAssign && t.department_id) {
        const available = await api.departmentEngineers(t.department_id).catch(() => []);
        setEngineers(available);
        if (!touchedAssignment) setSelectedEngineer(t.assignee_id || "");
      }
      const at = await api.attachment(id).catch(() => null);
      setAttachment(at);
      setEvents(await api.timeline(id).catch(() => []));
      setMessages(await api.messages?.(id).catch(() => []) || []);
      if (internal) {
        const [a, e, s, tr, dr, versions, persistedTrace, entities, why] = await Promise.all([
          api.analysis(id), api.evidence(id), api.similar(id), api.trace(id),
          api.groundedDraft(id).catch(() => null), api.drafts(id).catch(() => []),
          api.pipelineTrace(id).catch(() => null), api.technicalEntities(id).catch(() => []), api.ticketExplanation(id).catch(() => null),
        ]);
        setAnalysis(a); setEvidence(e); setSimilar(s); setTrace(tr); setDraft(dr); setResponseDrafts(versions);
        setPipelineTrace(persistedTrace); setTechnicalEntities(entities); setExplanation(why);
        setDraftComparison(await api.draftComparison(id).catch(() => null));
        if (versions.length >= 2) { setComparisonFrom(String(versions[1].version_number)); setComparisonTo(String(versions[0].version_number)); }
        if (!touchedResponse) setResponseContent(versions[0]?.content || dr?.draft_text || t.ai_draft_reply || "");
      }
    } catch (e) { if (!opts.silent) setError(e instanceof Error ? e.message : "Unable to load ticket"); else throw e; }
    finally { if (!opts.silent) setLoading(false); }
  }

  function updateResponseContent(value: string) { setResponseContent(value); setTouchedResponse(true); }
  function updateSelectedEngineer(value: string) { setSelectedEngineer(value); setTouchedAssignment(true); }

  async function startWork() { setActing(true); try { await api.startWork(id); await load(); toast("Work started.","success"); } catch(e){toast(e instanceof Error?e.message:"Unable to start work","danger")} finally{setActing(false)} }
  async function saveResponse() { setActing(true); try { await api.createResponseDraft(id,{content:responseContent,based_on_draft_id:responseDrafts[0]?.id}); setTouchedResponse(false); await load(); toast("Response saved as a new version.","success"); } catch(e){toast(e instanceof Error?e.message:"Unable to save response","danger")} finally{setActing(false)} }
  async function submitResponse() { setActing(true); try { await api.submitForReview(id); await load(); toast("Response submitted for senior review.","success"); } catch(e){toast(e instanceof Error?e.message:"Unable to submit response","danger")} finally{setActing(false)} }
  async function assignEngineer() { if(!selectedEngineer)return; setActing(true); try { await api.assignTicket(id,selectedEngineer,"Assigned from the ticket workspace."); setTouchedAssignment(false); await load(); toast("Engineer assignment synchronized.","success"); } catch(e){toast(e instanceof Error?e.message:"Unable to assign engineer","danger")} finally{setActing(false)} }
  async function compareVersions() { if(!comparisonFrom||!comparisonTo)return; setActing(true); try { setDraftComparison(await api.draftComparison(id,Number(comparisonFrom),Number(comparisonTo))); } catch(e){toast(e instanceof Error?e.message:"Unable to compare versions","danger")} finally{setActing(false)} }
  async function reviewResponse() { if(!reviewAction)return; setActing(true); try { await api.reviewResponse(id,{action:reviewAction,response_content:reviewAction==="modify_and_approve"?responseContent:undefined,review_comment:reason,customer_visible_note:reviewAction==="escalate"?"Your ticket has been escalated to a specialist.":undefined}); setReviewAction(null); setReason(""); setTouchedResponse(false); await load(); toast("Review decision synchronized.","success"); } catch(e){toast(e instanceof Error?e.message:"Review failed","danger")} finally{setActing(false)} }
  async function sendMessage() { if(!messageBody.trim())return; setActing(true); try { await api.createMessage(id,{body:messageBody,visibility:internalNote?"internal":"public"});setMessageBody("");await load({silent:true});toast(internalNote?"Internal note saved.":"Message sent.","success")} catch(e){toast(e instanceof Error?e.message:"Unable to send message","danger")} finally{setActing(false)} }
  async function confirmResolution(outcome:"solved"|"needs_help") { setActing(true); try { await api.confirmResolution(id,outcome,outcome==="needs_help"?"The proposed solution did not resolve the issue.":undefined);await load();toast(outcome==="solved"?"Resolution confirmed.":"Ticket reopened and routed to an Engineer.","success")} catch(e){toast(e instanceof Error?e.message:"Unable to save confirmation","danger")} finally{setActing(false)} }
  useEffect(() => { load(); }, [id, internal]); // eslint-disable-line react-hooks/exhaustive-deps
  const { status: syncStatus, lastSyncedAt, retryNow } = useAutoRefresh(() => load({ silent: true }), undefined, !loading && !!ticket);

  async function generate() {
    setActing(true); setError("");
    try { setDraft(await api.generateGroundedDraft(id)); await load(); toast("Grounded draft generated.", "success"); }
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
    ? [{ key: "overview", label: "Overview" }, { key: "analysis", label: "Analysis" }, { key: "technical", label: "Technical information" }, { key: "explain", label: "Why this decision?" }, { key: "evidence", label: "Evidence" }, { key: "similar", label: "Similar tickets" }, { key: "trace", label: "Trace" }, { key: "pipeline", label: "Pipeline" }]
    : [{ key: "overview", label: "Overview" }];

  return (
    <div className="content workspace">
      <button className="back" onClick={() => nav(-1)}><IconArrowLeft size={14} />Back to tickets</button>
      {error && <div className="error-box" role="alert">{error}</div>}

      <div className="workspace-head">
        <div><small>Ticket {ticket.id}</small><h1>{ticket.subject}</h1><p>Created {new Date(ticket.created_at).toLocaleString()}{ticket.updated_at ? ` · Updated ${new Date(ticket.updated_at).toLocaleString()}` : ""}</p></div>
        <div><SyncIndicator status={syncStatus} lastSyncedAt={lastSyncedAt} onRetry={retryNow} /><Badge value={ticket.priority} /><Badge value={ticket.status} /></div>
      </div>

      <div className="workspace-grid">
        <aside className="panel ticket-meta">
          <h3>Ticket information</h3>
          <Meta label="Status" value={ticket.status} />
          <Meta label="Priority" value={ticket.priority || "—"} />
          <Meta label="Sentiment" value={ticket.sentiment || "—"} />
          <Meta label="Department" value={ticket.department_name || "Not assigned"} />
          {ticket.assignee_id && <Meta label="Assigned engineer" value={ticket.assignee_id===user?.id?"You":"Assigned support engineer"} />}
          {canAssign && ticket.department_id && !["resolved","closed"].includes(ticket.status) && <div className="assignment-control"><label className="ui-field"><span>Assign engineer</span><select value={selectedEngineer} onChange={event=>updateSelectedEngineer(event.target.value)}><option value="">Select an active engineer</option>{engineers.map(engineer=><option key={engineer.id} value={engineer.id}>{engineer.full_name} ({engineer.active_tickets ?? 0} active)</option>)}</select></label><Button size="sm" variant="outline" disabled={!selectedEngineer} loading={acting} onClick={assignEngineer}>Save assignment</Button></div>}
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
            <section className="ticket-conversation" aria-labelledby="conversation-heading">
              <div className="draft-heading"><div><h3 id="conversation-heading">Conversation</h3><p>Public replies are shared with the customer. Internal notes remain staff-only.</p></div></div>
              <div className="message-thread">{messages.length?messages.map(message=><article className={`ticket-message ${message.visibility}`} key={message.id}><div><b>{message.author_name}</b><Badge value={message.visibility}/></div><p className="preserve-lines">{message.body}</p><small>{new Date(message.created_at).toLocaleString()}{message.machine_translated?" · machine translated":""}</small></article>):<p className="empty-note">No messages yet.</p>}</div>
              <label className="ui-field"><span>{internalNote?"Internal note":"Public reply"}</span><textarea rows={3} value={messageBody} onChange={event=>setMessageBody(event.target.value)} placeholder={internalNote?"Visible only to authorized staff":"Write a message about this ticket"}/></label>
              <div className="form-actions">{internal&&<label className="message-visibility"><input type="checkbox" checked={internalNote} onChange={event=>setInternalNote(event.target.checked)}/> Private internal note</label>}<Button size="sm" variant="primary" disabled={!messageBody.trim()} loading={acting} onClick={sendMessage}>Send</Button></div>
            </section>
            {!internal && <>
              <CustomerAttachment attachment={attachment} />
              {ticket.final_response && <section className="customer-response"><h3>{ticket.resolution_type==="ai"?"Verified AI resolution":"Support response"}</h3><p className="preserve-lines">{ticket.final_response}</p>{ticket.final_responder_name&&<small>Provided by {ticket.final_responder_name}</small>}{ticket.resolved_at&&<small>Resolved {new Date(ticket.resolved_at).toLocaleString()}</small>}
                {passport && <div className="resolution-passport" aria-label="Resolution passport"><b>Resolution passport</b><Badge value={passport.integrity_verified?"integrity verified":"integrity unverified"}/>{(passport.public_citations?.length??0)>0&&<small>Cited sources: {passport.public_citations!.map(c=>c.citation_id).filter(Boolean).join(", ")}</small>}<small>Confirmation: {(passport.confirmation_state||"pending").replaceAll("_"," ")}</small></div>}
                {["resolved","resolved_by_ai","resolved_by_engineer"].includes(ticket.status)&&<div className="resolution-confirm"><b>Did this solve your issue?</b><div className="form-actions"><Button size="sm" variant="primary" loading={acting} onClick={()=>confirmResolution("solved")}>Yes, close ticket</Button><Button size="sm" variant="outline" loading={acting} onClick={()=>confirmResolution("needs_help")}>I still need help</Button></div></div>}</section>}
              {ticket.status==="escalated"&&<div className="info-box">{ticket.public_status_message||"Your ticket has been escalated to a specialist."}</div>}
              <section className="customer-timeline">
                <h3>Ticket progress</h3>
                <Timeline steps={events.length?events.map((event,index)=>({key:event.id,label:(event.comment||event.event_type).replaceAll("_"," "),done:index<events.length-1,active:index===events.length-1,timestamp:event.created_at})):customerTimeline(ticket)} />
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
              {canEngineer && <section className="response-editor">
                <div className="draft-heading"><div><h3>Engineer response</h3><p>Saved versions remain internal until senior approval.</p></div>{responseDrafts[0]&&<Badge value={responseDrafts[0].status}/>}</div>
                {responseDrafts[0]?.citation_validation_status==="invalid"&&<div className="error-box" role="alert"><IconAlert size={14}/>This response version is blocked by citation or grounding validation. Correct it and save a new version before review.</div>}
                {responseDrafts[0]?.validation?.grounding?.overall_status==="Partially Grounded"&&<div className="validation-warnings" role="status">Grounding is partial. Investigation and reviewer attention are mandatory.</div>}
                {ticket.status==="assigned"&&<Button variant="primary" onClick={startWork} loading={acting}>Start work</Button>}
                {["in_progress","changes_requested"].includes(ticket.status)&&<><label className="ui-field"><span>Response draft</span><textarea rows={10} value={responseContent} onChange={e=>updateResponseContent(e.target.value)} /></label><div className="form-actions"><Button variant="outline" onClick={saveResponse} loading={acting}>Save new version</Button>{responseDrafts[0]?.status==="engineer_edited"&&<Button variant="primary" onClick={submitResponse} loading={acting}>Submit for review</Button>}</div></>}
              </section>}
              {responseDrafts.length>0&&<section className="draft-history"><h3>Response version history</h3>{responseDrafts.map(version=><article key={version.id}><b>Version {version.version_number}</b><Badge value={version.status}/><small>{version.author_type} · {new Date(version.created_at).toLocaleString()}</small></article>)}</section>}
              {draftComparison&&<section className="version-comparison"><div className="draft-heading"><div><h3>Response comparison</h3><p>Version {draftComparison.from_version} ({draftComparison.from_author_type}) to version {draftComparison.to_version} ({draftComparison.to_author_type})</p></div><Badge value={`${draftComparison.edit_percentage}% edited`}/></div><div className="comparison-controls"><label className="ui-field"><span>Earlier version</span><select value={comparisonFrom} onChange={event=>setComparisonFrom(event.target.value)}>{responseDrafts.slice().reverse().map(version=><option key={version.id} value={version.version_number}>Version {version.version_number} · {version.author_type}</option>)}</select></label><label className="ui-field"><span>Later version</span><select value={comparisonTo} onChange={event=>setComparisonTo(event.target.value)}>{responseDrafts.slice().reverse().map(version=><option key={version.id} value={version.version_number}>Version {version.version_number} · {version.author_type}</option>)}</select></label><Button size="sm" variant="outline" loading={acting} onClick={compareVersions}>Compare</Button></div><div className="comparison-summary"><span><b>+{draftComparison.added_word_count}</b> words added</span><span><b>-{draftComparison.removed_word_count}</b> words removed</span><span><b>{draftComparison.citations_added.length + draftComparison.citations_removed.length}</b> citation changes</span></div>{draftComparison.changes.length===0?<p className="empty-note">The response text is unchanged.</p>:draftComparison.changes.map((change,index)=><div className="comparison-change" key={`${change.operation}-${index}`}><Badge value={change.operation}/>{change.before&&<p><del>{change.before}</del></p>}{change.after&&<p><ins>{change.after}</ins></p>}</div>)}</section>}
            </>}
          </TabPanel>

          <TabPanel id="workspace" tabKey="analysis" active={tab}>
            <h3>AI analysis</h3>
            <Meta label="Decision" value={String(analysis.decision || "—").replaceAll("_", " ")} />
            <Meta label="Reason" value={String(analysis.decision_reason || "—")} />
          </TabPanel>

          <TabPanel id="workspace" tabKey="technical" active={tab}>
            <h3>Technical Information</h3>
            <p className="empty-note">Deterministically extracted values are predictions for staff verification.</p>
            {technicalEntities.length?<div className="entity-grid">{technicalEntities.map(entity=><article className="entity-card" key={entity.id}><div><b>{entity.entity_type.replaceAll("_"," ")}</b><Badge value={entity.validation_status}/></div><strong>{entity.normalized_value}</strong><small>{entity.source} · {Math.round(entity.confidence*100)}% rule confidence</small></article>)}</div>:<p className="empty-note">No technical entities recorded. Generate a grounded draft to run Release B processing.</p>}
          </TabPanel>

          <TabPanel id="workspace" tabKey="explain" active={tab}>
            <h3>Why did TicketSense make this decision?</h3>
            {!explanation?<p className="empty-note">No persisted explanation is available.</p>:<div className="explain-grid"><Meta label="Predicted category" value={explanation.predicted_category||"Not available"}/><Meta label="Predicted priority" value={explanation.predicted_priority||"Not available"}/><Meta label="Routing reason" value={explanation.routing_reason||"Not available"}/><Meta label="Assignment reason" value={explanation.assignment_reason||"Not available"}/><Meta label="Top evidence similarity" value={explanation.top_retrieval_similarity==null?"Not available":`${Math.round(explanation.top_retrieval_similarity*100)}%`}/><Meta label="Retrieval score gap" value={explanation.retrieval_score_gap==null?"Not available":explanation.retrieval_score_gap.toFixed(3)}/><Meta label="Valid evidence sources" value={String(explanation.valid_evidence_count)}/><Meta label="Confidence band" value={explanation.confidence_band||"Not available"}/><Meta label="Grounding result" value={explanation.grounding_status||"Not available"}/><Meta label="Human-review decision" value={explanation.human_review_decision||"Not available"}/><div className="factor-list"><b>Positive factors</b>{explanation.positive_factors.length?explanation.positive_factors.map(item=><span key={item}>{item}</span>):<span>Not available</span>}</div><div className="factor-list"><b>Risk factors</b>{explanation.risk_factors.length?explanation.risk_factors.map(item=><span key={item}>{item}</span>):<span>None recorded</span>}</div><small className="explain-disclaimer">{explanation.disclaimer}</small></div>}
            {counterfactual && <div className="counterfactual-cards">
              <article className="panel"><h4>Why human review?</h4>{counterfactual.immutable_reasons?.length ? <ul>{counterfactual.immutable_reasons.map(reason=><li key={reason}>{reason}</li>)}</ul> : <p className="empty-note">No fixed policy restriction blocked this decision.</p>}</article>
              <article className="panel"><h4>What evidence is missing?</h4>{counterfactual.evidence_gaps?.length ? <ul>{counterfactual.evidence_gaps.map(gap=><li key={gap.code}>{gap.narrative}{gap.minimal_safe_change && <><br/><small>{gap.minimal_safe_change}</small></>}</li>)}</ul> : <p className="empty-note">No evidence or quality gate is currently missing.</p>}</article>
            </div>}
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
            <p className="empty-note">Persisted Release B execution data is shown when available; no latency is simulated.</p>
            {!pipelineTrace?.execution?<><p className="empty-note">No persisted execution exists yet.</p><PipelineView stages={buildPipelineStages({ ticket, attachment, analysis, draft, traceCount: trace.length, canMutate, canTransition })}/></>:<><div className="pipeline-execution-head"><Badge value={pipelineTrace.execution.status}/><span>{pipelineTrace.execution.pipeline_version}</span><span>{pipelineTrace.execution.total_duration_ms??"—"} ms total</span></div><div className="persisted-pipeline">{pipelineTrace.stages.map(stage=><details key={stage.id} className="pipeline-stage-row"><summary><b>{stage.sequence_number}. {stage.stage_name.replaceAll("_"," ")}</b><Badge value={stage.fallback_used?"fallback":stage.status}/><span>{stage.duration_ms} ms</span></summary><p>{stage.output_summary||"No safe output summary"}</p><small>{stage.provider_name||"rule"} · {stage.provider_version||"version unavailable"}{stage.safe_error_summary?` · ${stage.safe_error_summary}`:""}</small></details>)}</div>{pipelineTrace.claims.length>0&&<section className="claim-validation"><h3>Grounding validation</h3>{pipelineTrace.claims.map((claim,index)=><article key={index}><Badge value={claim.validation_status}/><p>{claim.claim_text}</p><small>{claim.reason}{claim.citation_id?` · ${claim.citation_id}`:""}</small></article>)}</section>}</>}
            <ExplainPipeline />
          </TabPanel>
        </section>

        {internal ? (
          <aside className="panel ai-panel">
            <h2>✦ AI Intelligence</h2>
            <div className="confidence-large"><b>{Math.round((ticket.confidence_score || 0) * 100)}%</b><span>confidence</span></div>
            <p>{String(analysis.decision_reason || "Awaiting backend decision.")}</p>
            {passport && <div className="resolution-passport" aria-label="Resolution passport">
              <b>Resolution passport</b>
              <Badge value={passport.integrity_valid?"integrity valid":"integrity invalid"}/>
              {passport.is_backfilled && <Badge value="backfilled"/>}
              <small>{passport.resolution_type==="ai"?"AI-resolved":"Engineer-resolved"} · {(passport.passed_gates?.length??0)} gates passed{(passport.failed_gates?.length??0)>0?`, ${passport.failed_gates!.length} failed`:""}</small>
              {passport.engineer_edit_ratio!=null && <small>Engineer edit ratio: {(passport.engineer_edit_ratio*100).toFixed(1)}%</small>}
            </div>}
            {canReview && ticket.status === "pending_review" && (
              <div className="action-stack">
                <Button variant="primary" disabled={acting} onClick={() => {setReviewAction("approve");setReason("")}}><IconCheckCircle size={15} />Approve</Button>
                <Button variant="outline" disabled={acting} onClick={() => {setReviewAction("modify_and_approve");setReason("")}}>Modify & approve</Button>
                <Button variant="outline" disabled={acting} onClick={() => {setReviewAction("request_changes");setReason("")}}>Request changes</Button>
                <Button variant="outline" disabled={acting} onClick={() => {setReviewAction("reject");setReason("")}}>Reject draft</Button>
                <Button variant="destructive" disabled={acting} onClick={() => {setReviewAction("escalate");setReason("")}}>Escalate</Button>
              </div>
            )}
            {hasPermission("safe_action:execute") && <SafeActionPanel ticketId={id} />}
          </aside>
        ) : (
          <aside className="panel ai-panel">
            <h2>Ticket progress</h2>
            <p>Your support team is reviewing this request. Internal analysis, confidence and staff notes remain protected.</p>
            {counterfactual?.requires_human_review && <div className="resolution-passport" aria-label="Why human review"><b>Why human review?</b><small>{counterfactual.narrative}</small></div>}
            {["resolved","resolved_by_ai","resolved_by_engineer"].includes(ticket.status) && ticket.final_response && <Button variant="primary" disabled={acting} onClick={() => confirmResolution("needs_help")} icon={<IconRefresh size={15} />}>I still need help</Button>}
          </aside>
        )}
      </div>

      <Modal open={!!reviewAction} onClose={()=>{setReviewAction(null);setReason("")}} title={(reviewAction||"").replaceAll("_"," ")} description="The decision and comment are saved to the shared ticket history." footer={<><Button variant="outline" onClick={()=>setReviewAction(null)}>Cancel</Button><Button variant={reviewAction==="reject"||reviewAction==="escalate"?"destructive":"primary"} disabled={reason.trim().length<3} loading={acting} onClick={reviewResponse}>Confirm decision</Button></>}>
        {reviewAction==="modify_and_approve"&&<label className="ui-field"><span>Modified response <em>required</em></span><textarea rows={10} value={responseContent} onChange={e=>updateResponseContent(e.target.value)} /></label>}
        <label className="ui-field"><span>Review comment <em>required</em></span><textarea rows={4} value={reason} onChange={e=>setReason(e.target.value)} /></label>
      </Modal>
    </div>
  );
}

export function customerTimeline(ticket: Ticket) {
  const normalized = ticket.status === "escalated" ? "pending_review" : ticket.status;
  const stages = [
    { key: "submitted", label: "Submitted", statuses: ["submitted", "needs_clarification", "ai_processing", "processing", "classified", "routed", "ai_processing_failed"] },
    { key: "assigned", label: "Assigned", statuses: ["awaiting_assignment", "assigned", "in_progress", "awaiting_customer", "reopened"] },
    { key: "pending_review", label: "Under review", statuses: ["pending_review", "changes_requested", "escalated"] },
    { key: "resolved", label: "Resolved", statuses: ["approved", "resolved", "resolved_by_ai", "resolved_by_engineer"] },
    { key: "closed", label: "Closed", statuses: ["closed"] },
  ];
  const current = Math.max(0, stages.findIndex(stage => stage.statuses.includes(normalized)));
  return stages.map((stage, index) => ({
    key: stage.key, label: stage.label,
    done: index < current || (index === current && ["resolved", "resolved_by_ai", "resolved_by_engineer", "closed"].includes(ticket.status)),
    active: index === current && !["resolved", "resolved_by_ai", "resolved_by_engineer", "closed"].includes(ticket.status),
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
  return <>{text.split(/(\[(?:KB|RT)-\d{3}\])/g).map((p, i) => /^\[(?:KB|RT)-\d{3}\]$/.test(p)
    ? <button className="citation-link" key={i} onClick={() => locate(p.slice(1, -1))}>{p}</button>
    : p)}</>;
}

function Meta({ label, value }: { label: string; value: string }) {
  return <div className="meta"><span>{label}</span><b>{value}</b></div>;
}
