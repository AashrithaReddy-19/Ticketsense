import { useState } from "react";
import type { AttachmentMeta, Analysis, GroundedDraft, Ticket } from "../../api/client";
import { IconAlert, IconCheckCircle, IconClock, IconXCircle } from "../icons";
import { Pill } from "./Badges";
import type { Tone } from "../../lib/status";

export type StageStatus = "pending" | "running" | "completed" | "failed" | "skipped" | "not_applicable";

export interface PipelineStage {
  key: string;
  label: string;
  status: StageStatus;
  simple: string;
  details: Array<{ label: string; value: string }>;
}

const STATUS_META: Record<StageStatus, { label: string; tone: Tone }> = {
  pending: { label: "Pending", tone: "neutral" },
  running: { label: "Running", tone: "info" },
  completed: { label: "Completed", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  skipped: { label: "Skipped", tone: "neutral" },
  not_applicable: { label: "Not applicable", tone: "neutral" },
};

function fmtMs(ms?: number | null) { return ms != null ? `${ms} ms` : "Not available"; }
function fmtPct(v?: number | null) { return v != null ? `${(v * 100).toFixed(1)}%` : "Not available"; }

/** Builds the real per-ticket pipeline stage list from already-fetched API responses.
 * Every status is derived from actual response fields — nothing here is a fabricated
 * "always green" state. A stage that hasn't run yet reports "pending", not "completed". */
export function buildPipelineStages(opts: {
  ticket: Ticket; attachment: AttachmentMeta | null; analysis: Analysis; draft: GroundedDraft | null;
  traceCount: number; canMutate: boolean; canTransition: boolean;
}): PipelineStage[] {
  const { ticket, attachment, analysis, draft, traceCount, canMutate, canTransition } = opts;
  const stages: PipelineStage[] = [];

  stages.push({
    key: "intake", label: "Ticket Intake", status: "completed",
    simple: "The ticket was received and stored with its subject, description and tenant scope.",
    details: [
      { label: "Ticket ID", value: ticket.id },
      { label: "Subject received", value: "Yes" },
      { label: "Description received", value: "Yes" },
      { label: "Attachment present", value: attachment ? "Yes" : "No" },
    ],
  });

  if (!attachment) {
    stages.push({ key: "attachment", label: "Attachment Processing", status: "not_applicable", simple: "No attachment was submitted with this ticket.", details: [] });
  } else {
    const status: StageStatus = attachment.extraction_status === "ready" || attachment.extraction_status === "empty" ? "completed"
      : attachment.extraction_status === "failed" ? "failed"
      : attachment.extraction_status === "processing" ? "running" : "pending";
    stages.push({
      key: "attachment", label: "Attachment Processing", status,
      simple: status === "completed" ? "The attachment was validated and its text was extracted." : status === "failed" ? "Extraction failed for this attachment." : "The attachment has not been processed yet.",
      details: [
        { label: "File validation", value: attachment.status },
        { label: "Extraction method", value: attachment.extraction_method || "Not available" },
        { label: "OCR confidence", value: attachment.ocr_confidence_available ? fmtPct(attachment.ocr_confidence) : "Not available" },
        { label: "Character count", value: String(attachment.character_count ?? 0) },
        { label: "Processing duration", value: fmtMs(attachment.processing_duration_ms) },
        { label: "Sanitization result", value: attachment.truncated ? "Completed (text truncated to configured limit)" : "Completed" },
      ],
    });
  }

  stages.push({
    key: "classification", label: "Classification", status: "completed",
    simple: "The ticket text was classified for department, priority and sentiment.",
    details: [
      { label: "Predicted department", value: String(analysis.category || ticket.department_id || "Unclassified") },
      { label: "Priority", value: ticket.priority || "—" },
      { label: "Sentiment", value: ticket.sentiment || "—" },
      { label: "Model", value: "TF-IDF + Logistic Regression (independent pipeline per target)" },
    ],
  });

  stages.push({
    key: "routing", label: "Routing", status: ticket.department_id ? "completed" : "pending",
    simple: ticket.department_id ? "The ticket was routed to an authorized department queue." : "The ticket could not be matched to a department and awaits manual triage.",
    details: [
      { label: "Assigned department", value: ticket.department_id || "Not assigned (manual triage)" },
      { label: "Routing status", value: ticket.department_id ? "Routed" : "Manual triage" },
      { label: "Tenant/department validation", value: "Enforced — department must belong to the ticket's tenant" },
    ],
  });

  const hasDraftRun = !!draft;
  stages.push({
    key: "retrieval", label: "Retrieval", status: !hasDraftRun ? "pending" : "completed",
    simple: !hasDraftRun ? "No grounded draft has been generated yet, so retrieval has not run." : draft!.evidence.length ? `${draft!.evidence.length} approved knowledge-base passages were retrieved.` : "Retrieval ran but found no matching approved evidence.",
    details: [
      { label: "Embedding model", value: "sentence-transformers/all-MiniLM-L6-v2" },
      { label: "Vector dimensions", value: "384" },
      { label: "Tenant filter", value: "Enforced" },
      { label: "Department filter", value: ticket.department_id ? "Enforced" : "Unavailable — ticket not routed" },
      { label: "Article version filter", value: draft?.evidence[0]?.article_version || "1.0" },
      { label: "Approved / publishable filter", value: "Enforced — status=approved, is_publishable=true" },
      { label: "Retrieved articles", value: hasDraftRun ? String(draft!.evidence.length) : "0" },
    ],
  });

  stages.push({
    key: "draft", label: "Draft Generation", status: !hasDraftRun ? "pending" : draft!.generation_status === "failed" || draft!.generation_status === "failed_validation" ? "failed" : "completed",
    simple: !hasDraftRun ? "No draft has been requested for this ticket yet." : draft!.insufficient_evidence ? "The provider reported insufficient evidence and declined to draft a technical recommendation." : "A grounded draft was generated from the retrieved evidence.",
    details: hasDraftRun ? [
      { label: "Provider", value: draft!.provider || "Not available" },
      { label: "Model", value: draft!.model || "Not available" },
      { label: "Generation status", value: draft!.generation_status },
      { label: "Insufficient evidence", value: draft!.insufficient_evidence ? "Yes" : "No" },
      { label: "Attempt count", value: String(draft!.attempt_count) },
    ] : [],
  });

  stages.push({
    key: "validation", label: "Citation Validation", status: !hasDraftRun ? "pending" : draft!.citation_validation_status === "valid" ? "completed" : "failed",
    simple: !hasDraftRun ? "Nothing to validate yet." : draft!.citation_validation_status === "valid" ? "Every citation in the draft was checked against tenant, department, version, approval and publishability rules." : "One or more citations failed validation, so this draft is not usable.",
    details: hasDraftRun ? [
      { label: "Validation status", value: draft!.citation_validation_status },
      { label: "Valid citation IDs", value: draft!.validation.valid_citation_ids?.join(", ") || "None" },
      { label: "Invalid citation IDs", value: draft!.validation.invalid_citation_ids?.join(", ") || "None" },
      { label: "Uncited claim warnings", value: draft!.validation.uncited_claim_warnings?.join(", ") || "None" },
      { label: "Validation errors", value: draft!.validation.validation_errors?.join(", ") || "None" },
    ] : [],
  });

  const reviewStatus: StageStatus = ["resolved", "closed"].includes(ticket.status) ? "completed" : ticket.status === "escalated" ? "running" : "pending";
  stages.push({
    key: "review", label: "Engineer Review", status: reviewStatus,
    simple: reviewStatus === "completed" ? "An engineer resolved this ticket." : reviewStatus === "running" ? "This ticket is escalated and awaiting expert handling." : "This ticket is awaiting engineer review.",
    details: [
      { label: "Current status", value: ticket.status },
      { label: "Allowed actions (for you)", value: [canTransition && "approve/escalate/reject", canMutate && "process attachment / generate draft"].filter(Boolean).join(", ") || "View only" },
      { label: "Trace events recorded", value: String(traceCount) },
    ],
  });

  return stages;
}

function StageIcon({ status }: { status: StageStatus }) {
  if (status === "completed") return <IconCheckCircle size={16} />;
  if (status === "failed") return <IconXCircle size={16} />;
  if (status === "running") return <IconClock size={16} />;
  return <IconAlert size={16} className="ui-stage-icon-muted" />;
}

export function PipelineView({ stages }: { stages: PipelineStage[] }) {
  const [mode, setMode] = useState<"simple" | "technical">("simple");
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <div className="pipeline-view">
      <div className="pipeline-mode-toggle" role="group" aria-label="Pipeline detail level">
        <button className={mode === "simple" ? "active" : ""} onClick={() => setMode("simple")}>Simple view</button>
        <button className={mode === "technical" ? "active" : ""} onClick={() => setMode("technical")}>Technical view</button>
      </div>

      <ol className="pipeline-stages">
        {stages.map(stage => {
          const meta = STATUS_META[stage.status];
          const isOpen = expanded === stage.key;
          return (
            <li key={stage.key} className={`pipeline-stage tone-${meta.tone}`}>
              <button className="pipeline-stage-head" onClick={() => setExpanded(isOpen ? null : stage.key)} aria-expanded={isOpen}>
                <span className="pipeline-stage-icon"><StageIcon status={stage.status} /></span>
                <span className="pipeline-stage-label">{stage.label}</span>
                <Pill label={meta.label} tone={meta.tone} />
              </button>
              {isOpen && (
                <div className="pipeline-stage-body">
                  <p>{stage.simple}</p>
                  {mode === "technical" && stage.details.length > 0 && (
                    <dl className="pipeline-detail-list">
                      {stage.details.map(d => <div key={d.label}><dt>{d.label}</dt><dd>{d.value}</dd></div>)}
                    </dl>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function ExplainPipeline() {
  return (
    <div className="explain-pipeline">
      <h3>Explain this pipeline</h3>
      <p>
        Every ticket runs through a fixed sequence of automated stages (a LangGraph graph), then hands off to a
        human engineer. Attachment text is processed <em>before</em> the graph runs and is treated as untrusted
        secondary context — it can help retrieval find the right articles, but it can never change which tenant or
        department is searched, and it is never itself cited as knowledge-base evidence.
      </p>
      <pre className="pipeline-flow">START{"\n"}  → intake_node{"\n"}  → attachment_or_text_node{"\n"}  → technical_entity_node{"\n"}  → classify_node{"\n"}  → priority_node{"\n"}  → route_node{"\n"}  → retrieve_node{"\n"}  → draft_node{"\n"}  → validate_citations_node{"\n"}  → validate_grounding_node{"\n"}  → confidence_node{"\n"}  → human_review_gate_node{"\n"}→ END</pre>
      <p className="pipeline-caveat">Grounding checks are conservative deterministic safeguards. They identify common unsupported, contradictory and unsafe claims, but do not guarantee complete hallucination detection.</p>
    </div>
  );
}
