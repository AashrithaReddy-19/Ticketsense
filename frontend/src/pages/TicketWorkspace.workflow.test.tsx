import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type Ticket } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ToastProvider } from "../components/ui/Toast";
import TicketWorkspace from "./TicketWorkspace";

vi.mock("../auth/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("../lib/useAutoRefresh", () => ({ useAutoRefresh: () => ({ status: "idle", lastSyncedAt: null, retryNow: vi.fn() }) }));
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    api: {
      ticket: vi.fn(), attachment: vi.fn(), timeline: vi.fn(), analysis: vi.fn(), evidence: vi.fn(),
      similar: vi.fn(), trace: vi.fn(), groundedDraft: vi.fn(), drafts: vi.fn(), draftComparison: vi.fn(), pipelineTrace: vi.fn(), technicalEntities: vi.fn(), ticketExplanation: vi.fn(), departmentEngineers: vi.fn(),
      startWork: vi.fn(), createResponseDraft: vi.fn(), submitForReview: vi.fn(), reviewResponse: vi.fn(),
      assignTicket: vi.fn(), reopenTicket: vi.fn(), processAttachment: vi.fn(), generateGroundedDraft: vi.fn(),
      ticketAction: vi.fn(), safeActions: vi.fn(), resolutionPassport: vi.fn(),
    },
  };
});

function baseTicket(overrides: Partial<Ticket> = {}): Ticket {
  return {
    id: "t1", subject: "VPN broken", description: "Cannot connect to VPN.", status: "in_progress",
    priority: "high", sentiment: "negative", department_id: "d1", department_name: "Networking",
    assignee_id: "engineer-1", confidence_score: 0.7, ai_draft_reply: null, final_response: null,
    created_at: "2026-09-01T10:00:00Z", updated_at: "2026-09-01T10:05:00Z", analysis: {},
    ...overrides,
  };
}

function mockCommonInternalCalls() {
  vi.mocked(api.attachment).mockResolvedValue(null as never);
  vi.mocked(api.timeline).mockResolvedValue([]);
  vi.mocked(api.analysis).mockResolvedValue({});
  vi.mocked(api.evidence).mockResolvedValue([]);
  vi.mocked(api.similar).mockResolvedValue([]);
  vi.mocked(api.trace).mockResolvedValue([]);
  vi.mocked(api.groundedDraft).mockResolvedValue(null as never);
  vi.mocked(api.draftComparison).mockRejectedValue(new Error("No comparison available"));
  vi.mocked(api.pipelineTrace).mockResolvedValue({execution:null,stages:[],claims:[]});
  vi.mocked(api.technicalEntities).mockResolvedValue([]);
  vi.mocked(api.ticketExplanation).mockResolvedValue(null as never);
  vi.mocked(api.safeActions).mockResolvedValue([]);
  vi.mocked(api.resolutionPassport).mockResolvedValue(null as never);
}

function renderWorkspace() {
  render(<ToastProvider><MemoryRouter initialEntries={["/tickets/t1"]}><Routes><Route path="/tickets/:id" element={<TicketWorkspace />} /></Routes></MemoryRouter></ToastProvider>);
}

afterEach(() => cleanup());

describe("engineer response workflow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useAuth).mockReturnValue({
      user: { id: "engineer-1", email: "agent@demo.com", full_name: "Agent", role: "support_agent", department_id: "d1", tenant_id: "tenant", permissions: ["ticket:transition", "ai:view_summary"] },
      loading: false, login: vi.fn(), logout: vi.fn(),
      hasPermission: (p: string) => ["ticket:transition", "ai:view_summary"].includes(p),
    });
  });

  it("saves an edited draft as a new version and submits it for review", async () => {
    mockCommonInternalCalls();
    vi.mocked(api.ticket).mockResolvedValue(baseTicket());
    vi.mocked(api.drafts).mockResolvedValue([{ id: "d1", ticket_id: "t1", version_number: 1, content: "Original draft text", author_type: "engineer", citations: [], status: "engineer_edited", created_at: "2026-09-01T10:00:00Z", updated_at: "2026-09-01T10:00:00Z" }]);
    vi.mocked(api.createResponseDraft).mockResolvedValue({ id: "d2", ticket_id: "t1", version_number: 2, content: "Edited draft text", author_type: "engineer", citations: [], status: "engineer_edited", created_at: "2026-09-01T10:01:00Z", updated_at: "2026-09-01T10:01:00Z" });
    vi.mocked(api.submitForReview).mockResolvedValue({ ticket_id: "t1", status: "pending_review", draft: { id: "d2", ticket_id: "t1", version_number: 2, content: "Edited draft text", author_type: "engineer", citations: [], status: "submitted_for_review", created_at: "2026-09-01T10:01:00Z", updated_at: "2026-09-01T10:01:00Z" } });

    renderWorkspace();
    const editor = await screen.findByLabelText("Response draft");
    fireEvent.change(editor, { target: { value: "Edited draft text" } });
    fireEvent.click(screen.getByRole("button", { name: /save new version/i }));

    await waitFor(() => expect(api.createResponseDraft).toHaveBeenCalledWith("t1", expect.objectContaining({ content: "Edited draft text" })));

    fireEvent.click(await screen.findByRole("button", { name: /submit for review/i }));
    await waitFor(() => expect(api.submitForReview).toHaveBeenCalledWith("t1"));
  });

  it("shows a resolution passport summary for a resolved ticket", async () => {
    mockCommonInternalCalls();
    vi.mocked(api.ticket).mockResolvedValue(baseTicket({ status: "resolved_by_ai", resolution_type: "ai", final_response: "Reset your VPN client cache." }));
    vi.mocked(api.drafts).mockResolvedValue([]);
    vi.mocked(api.resolutionPassport).mockResolvedValue({
      ticket_id: "t1", resolution_type: "ai",
      passed_gates: Array.from({ length: 19 }, (_, i) => `gate_${i}`), failed_gates: [],
      overall_confidence: 0.95, applicable_threshold: 0.85,
      integrity_hash: "abc", integrity_valid: true, is_backfilled: false,
    });

    renderWorkspace();
    expect(await screen.findByText("Resolution passport")).toBeTruthy();
    expect(screen.getByText("integrity valid")).toBeTruthy();
    expect(screen.getByText(/19 gates passed/)).toBeTruthy();
    expect(api.resolutionPassport).toHaveBeenCalledWith("t1");
  });

  it("shows actual additions and removals between selected immutable versions", async () => {
    mockCommonInternalCalls();
    vi.mocked(api.ticket).mockResolvedValue(baseTicket());
    vi.mocked(api.drafts).mockResolvedValue([
      { id: "d2", ticket_id: "t1", version_number: 2, content: "Reset credentials and reconnect safely", author_type: "engineer", citations: [], status: "engineer_edited", created_at: "2026-09-01T10:01:00Z", updated_at: "2026-09-01T10:01:00Z" },
      { id: "d1", ticket_id: "t1", version_number: 1, content: "Reset credentials", author_type: "ai", citations: [], status: "superseded", created_at: "2026-09-01T10:00:00Z", updated_at: "2026-09-01T10:00:00Z" },
    ]);
    vi.mocked(api.draftComparison).mockResolvedValue({ from_version: 1, to_version: 2, from_author_type: "ai", to_author_type: "engineer", edit_percentage: 42.86, added_word_count: 3, removed_word_count: 0, changes: [{ operation: "insert", before: "", after: "and reconnect safely" }], citations_added: [], citations_removed: [] });

    renderWorkspace();

    expect(await screen.findByRole("heading", { name: /response comparison/i })).toBeTruthy();
    expect(screen.getByText("+3")).toBeTruthy();
    expect(screen.getByText("and reconnect safely")).toBeTruthy();
    expect(api.draftComparison).toHaveBeenCalledWith("t1");
  });

  it("renders persisted Release B entities, explanation, and pipeline stages", async () => {
    mockCommonInternalCalls();
    vi.mocked(api.ticket).mockResolvedValue(baseTicket());
    vi.mocked(api.drafts).mockResolvedValue([]);
    vi.mocked(api.technicalEntities).mockResolvedValue([{id:"e1",entity_type:"error_code",raw_value:"VPN-809",normalized_value:"VPN-809",source:"description",extraction_method:"technical-entities-rules-1.0",confidence:.98,validation_status:"extracted",created_at:"2026-09-01T10:00:00Z"}]);
    vi.mocked(api.ticketExplanation).mockResolvedValue({predicted_department:"Networking",candidate_department_probabilities:null,predicted_category:"network",predicted_priority:"high",important_keywords:null,technical_entities:[{type:"error_code",value:"VPN-809"}],routing_reason:"VPN evidence matched Networking",assignment_reason:"VPN specialization and lowest workload",top_retrieval_similarity:.87,retrieval_score_gap:.12,valid_evidence_count:2,citation_coverage:1,confidence_score:.82,low_threshold:.55,high_threshold:.8,confidence_band:"high",positive_factors:["Approved evidence was retrieved"],risk_factors:[],grounding_status:"Grounded",human_review_decision:"normal_controlled_review",disclaimer:"Predictions are decision support."});
    vi.mocked(api.pipelineTrace).mockResolvedValue({execution:{id:"x1",pipeline_version:"release-b-1.0",trigger_type:"draft_generation",status:"completed",started_at:"2026-09-01T10:00:00Z",completed_at:"2026-09-01T10:00:01Z",total_duration_ms:120,failure_stage:null,fallback_used:false,correlation_id:"c1"},stages:[{id:"s1",stage_name:"technical_entity",sequence_number:3,status:"completed",output_summary:"Updated: technical_entities",provider_name:"deterministic",provider_version:"release-b-1.0",confidence:null,started_at:"2026-09-01T10:00:00Z",completed_at:"2026-09-01T10:00:00Z",duration_ms:2,error_category:null,safe_error_summary:null,fallback_used:false}],claims:[]});

    renderWorkspace();
    fireEvent.click(await screen.findByRole("tab",{name:/technical information/i}));
    expect(await screen.findByText("VPN-809")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab",{name:/why this decision/i}));
    expect(screen.getByText("VPN specialization and lowest workload")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab",{name:/pipeline/i}));
    expect(screen.getByText("release-b-1.0")).toBeTruthy();
    expect(screen.getByText(/technical entity/i)).toBeTruthy();
  });

  it("renders the persisted pipeline empty and failed states", async () => {
    mockCommonInternalCalls();
    vi.mocked(api.ticket).mockResolvedValue(baseTicket());
    vi.mocked(api.drafts).mockResolvedValue([]);
    vi.mocked(api.pipelineTrace).mockResolvedValue({execution:{id:"x-failed",pipeline_version:"release-b-1.0",trigger_type:"draft_generation",status:"failed",started_at:"2026-09-01T10:00:00Z",completed_at:"2026-09-01T10:00:01Z",total_duration_ms:4,failure_stage:"retrieve",fallback_used:false,correlation_id:"c-failed"},stages:[{id:"s-failed",stage_name:"retrieve",sequence_number:7,status:"failed",output_summary:"Stage failed",provider_name:"deterministic",provider_version:"release-b-1.0",confidence:null,started_at:"2026-09-01T10:00:00Z",completed_at:"2026-09-01T10:00:01Z",duration_ms:4,error_category:"TimeoutError",safe_error_summary:"Stage could not complete",fallback_used:false}],claims:[]});
    renderWorkspace();
    fireEvent.click(await screen.findByRole("tab",{name:/pipeline/i}));
    expect(screen.getByText("Stage could not complete",{exact:false})).toBeTruthy();
    expect(screen.getAllByText(/generation failed/i).length).toBeGreaterThan(0);
  });

  it("renders a truthful empty trace before any execution", async () => {
    mockCommonInternalCalls();
    vi.mocked(api.ticket).mockResolvedValue(baseTicket());
    vi.mocked(api.drafts).mockResolvedValue([]);
    renderWorkspace();
    fireEvent.click(await screen.findByRole("tab",{name:/pipeline/i}));
    expect(screen.getByText(/no persisted execution exists yet/i)).toBeTruthy();
  });

  it("shows draft-version citation and grounding warnings", async () => {
    mockCommonInternalCalls();
    vi.mocked(api.ticket).mockResolvedValue(baseTicket());
    vi.mocked(api.drafts).mockResolvedValue([{id:"bad",ticket_id:"t1",version_number:2,content:"Guaranteed unsupported fix",author_type:"engineer",citations:[],status:"engineer_edited",citation_validation_status:"invalid",validation:{citation:{valid:false,validation_errors:["Claim has no citation"]},grounding:{overall_status:"Unsupported",blocked:true}},created_at:"2026-09-01T10:00:00Z",updated_at:"2026-09-01T10:00:00Z"}]);
    renderWorkspace();
    expect((await screen.findByText(/blocked by citation or grounding validation/i)).textContent).toContain("blocked");
  });
});

describe("reviewer approval workflow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useAuth).mockReturnValue({
      user: { id: "reviewer-1", email: "reviewer@demo.com", full_name: "Reviewer", role: "reviewer", department_id: "d1", tenant_id: "tenant", permissions: ["ticket:review", "ai:view_summary"] },
      loading: false, login: vi.fn(), logout: vi.fn(),
      hasPermission: (p: string) => ["ticket:review", "ai:view_summary"].includes(p),
    });
  });

  it("submits an edited response and a comment through Modify & approve", async () => {
    mockCommonInternalCalls();
    vi.mocked(api.ticket).mockResolvedValue(baseTicket({ status: "pending_review" }));
    vi.mocked(api.drafts).mockResolvedValue([{ id: "d2", ticket_id: "t1", version_number: 2, content: "Engineer's draft response", author_type: "engineer", citations: [], status: "submitted_for_review", created_at: "2026-09-01T10:01:00Z", updated_at: "2026-09-01T10:01:00Z" }]);
    vi.mocked(api.reviewResponse).mockResolvedValue({ ticket_id: "t1", status: "resolved", final_response: "Reviewer's improved response" });

    renderWorkspace();
    fireEvent.click(await screen.findByRole("button", { name: /modify & approve/i }));

    const responseField = await screen.findByLabelText(/modified response/i);
    fireEvent.change(responseField, { target: { value: "Reviewer's improved response" } });
    const commentField = screen.getByLabelText(/review comment/i);
    fireEvent.change(commentField, { target: { value: "Clarified the reconnection steps." } });

    fireEvent.click(screen.getByRole("button", { name: /confirm decision/i }));

    await waitFor(() => expect(api.reviewResponse).toHaveBeenCalledWith("t1", expect.objectContaining({
      action: "modify_and_approve", response_content: "Reviewer's improved response", review_comment: "Clarified the reconnection steps.",
    })));
  });

  it("does not allow confirming Modify & approve without a review comment", async () => {
    mockCommonInternalCalls();
    vi.mocked(api.ticket).mockResolvedValue(baseTicket({ status: "pending_review" }));
    vi.mocked(api.drafts).mockResolvedValue([{ id: "d2", ticket_id: "t1", version_number: 2, content: "Engineer's draft response", author_type: "engineer", citations: [], status: "submitted_for_review", created_at: "2026-09-01T10:01:00Z", updated_at: "2026-09-01T10:01:00Z" }]);

    renderWorkspace();
    fireEvent.click(await screen.findByRole("button", { name: /modify & approve/i }));
    await screen.findByLabelText(/modified response/i);

    expect((screen.getByRole("button", { name: /confirm decision/i }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.reviewResponse).not.toHaveBeenCalled();
  });
});

describe("customer Release B boundary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useAuth).mockReturnValue({user:{id:"customer-1",email:"customer@demo.com",full_name:"Customer",role:"customer",department_id:null,tenant_id:"tenant",permissions:[]},loading:false,login:vi.fn(),logout:vi.fn(),hasPermission:()=>false});
    vi.mocked(api.ticket).mockResolvedValue(baseTicket({assignee_id:null,confidence_score:null,analysis:{}}));
    vi.mocked(api.attachment).mockResolvedValue(null as never);
    vi.mocked(api.timeline).mockResolvedValue([]);
  });

  it("never requests or renders internal Release B panels", async () => {
    renderWorkspace();
    await screen.findByText("Customer request");
    expect(screen.queryByRole("tab",{name:/technical information/i})).toBeNull();
    expect(screen.queryByText(/why did TicketSense/i)).toBeNull();
    expect(api.pipelineTrace).not.toHaveBeenCalled();
    expect(api.ticketExplanation).not.toHaveBeenCalled();
  });

  it("shows a loading state while the ticket request is pending", () => {
    vi.mocked(api.ticket).mockReturnValue(new Promise(() => undefined));
    renderWorkspace();
    expect(screen.getByText(/loading your ticket/i)).toBeTruthy();
  });
});
