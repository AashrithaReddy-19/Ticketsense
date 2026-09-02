import { describe, expect, it } from "vitest";
import { buildPipelineStages } from "./Pipeline";
import type { AttachmentMeta, GroundedDraft, Ticket } from "../../api/client";

const baseTicket: Ticket = {
  id: "t1", subject: "VPN issue", description: "Cannot connect", status: "in_review",
  priority: "high", sentiment: "negative", department_id: "dept-1", confidence_score: 0.5,
  created_at: "2026-09-01T10:00:00Z", analysis: { category: "Networking", sla_risk: 20, decision_reason: "x" },
};

function stage(key: string, args: Parameters<typeof buildPipelineStages>[0]) {
  return buildPipelineStages(args).find(s => s.key === key)!;
}

describe("buildPipelineStages — real-data-only status derivation", () => {
  it("marks attachment processing not_applicable when no attachment was submitted", () => {
    const s = stage("attachment", { ticket: baseTicket, attachment: null, analysis: {}, draft: null, traceCount: 0, canMutate: false, canTransition: false });
    expect(s.status).toBe("not_applicable");
  });

  it("marks retrieval/draft/validation pending before any draft has been generated — never fakes completion", () => {
    const args = { ticket: baseTicket, attachment: null, analysis: {}, draft: null, traceCount: 0, canMutate: false, canTransition: false };
    expect(stage("retrieval", args).status).toBe("pending");
    expect(stage("draft", args).status).toBe("pending");
    expect(stage("validation", args).status).toBe("pending");
  });

  it("marks validation failed when the backend reports invalid citations, not completed", () => {
    const draft: GroundedDraft = {
      ticket_id: "t1", draft_text: "text [KB-999]", citations: [], evidence: [],
      provider: "deterministic-development", model: "evidence-template-v1",
      generation_status: "failed_validation", citation_validation_status: "invalid",
      validation: { valid: false, invalid_citation_ids: ["KB-999"], validation_errors: ["Unknown citation: KB-999"] },
      generation_error: null, insufficient_evidence: false, attempt_count: 1,
    };
    const s = stage("validation", { ticket: baseTicket, attachment: null, analysis: {}, draft, traceCount: 0, canMutate: false, canTransition: false });
    expect(s.status).toBe("failed");
    expect(s.details.find(d => d.label === "Invalid citation IDs")?.value).toBe("KB-999");
  });

  it("marks validation completed only when citations are actually valid", () => {
    const draft: GroundedDraft = {
      ticket_id: "t1", draft_text: "text [KB-001]", citations: [], evidence: [],
      provider: "deterministic-development", model: "evidence-template-v1",
      generation_status: "ready", citation_validation_status: "valid",
      validation: { valid: true, valid_citation_ids: ["KB-001"], validation_errors: [] },
      generation_error: null, insufficient_evidence: false, attempt_count: 1,
    };
    expect(stage("validation", { ticket: baseTicket, attachment: null, analysis: {}, draft, traceCount: 0, canMutate: false, canTransition: false }).status).toBe("completed");
  });

  it("reports attachment extraction failure honestly", () => {
    const attachment: AttachmentMeta = {
      id: "a1", ticket_id: "t1", original_filename: "bad.pdf", detected_mime_type: "application/pdf",
      file_extension: ".pdf", file_size_bytes: 10, status: "failed", extraction_status: "failed",
      created_at: "2026-09-01T10:00:00Z",
    };
    const s = stage("attachment", { ticket: baseTicket, attachment, analysis: {}, draft: null, traceCount: 0, canMutate: false, canTransition: false });
    expect(s.status).toBe("failed");
  });

  it("routing is pending (manual triage) when the ticket has no department, not silently completed", () => {
    const s = stage("routing", { ticket: { ...baseTicket, department_id: null }, attachment: null, analysis: {}, draft: null, traceCount: 0, canMutate: false, canTransition: false });
    expect(s.status).toBe("pending");
  });
});
