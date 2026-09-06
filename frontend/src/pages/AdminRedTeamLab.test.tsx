import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { ToastProvider } from "../components/ui/Toast";
import AdminRedTeamLab from "./AdminRedTeamLab";

afterEach(() => cleanup());

vi.mock("../api/client", () => ({
  api: {
    redTeamRuns: vi.fn(),
    redTeamRunDetail: vi.fn(),
    runRedTeamSuite: vi.fn(),
  },
}));

const summary = {
  run_id: "run-1", suite_version: 1, status: "completed", started_at: "2026-01-01T00:00:00Z", completed_at: "2026-01-01T00:00:05Z",
  total_cases: 9, applicable_cases: 8, not_applicable_cases: 1,
  attack_success_rate: 0.125, block_rate: 0.875,
  by_category: { encoded_secrets: { total: 1, failed: 1 }, fabricated_citations: { total: 1, failed: 0 } },
  by_severity: { critical: { total: 3, failed: 0 }, medium: { total: 1, failed: 1 } },
  results: [
    { case_key: "fabricated_citation_rejected", category: "fabricated_citations", severity: "high", title: "Fabricated citation ID is rejected", expected_result: "rejected", observed_result: "rejected", passed: true, applicable: true, gate_responsible: "citation_validation", detail: "held" },
    { case_key: "encoded_secret_redaction_gap", category: "encoded_secrets", severity: "medium", title: "Base64-encoded secret redaction", expected_result: "redacted", observed_result: "not_redacted", passed: false, applicable: true, gate_responsible: "pii_secret_redaction", detail: "A base64-encoded secret is NOT caught." },
    { case_key: "system_prompt_disclosure_not_applicable", category: "system_prompt_disclosure", severity: "low", title: "System prompt disclosure applicability check", expected_result: "not_applicable", observed_result: "not_applicable", passed: true, applicable: false, gate_responsible: null, detail: "No LLM system prompt exists." },
  ],
};

function renderPage() {
  return render(<ToastProvider><AdminRedTeamLab /></ToastProvider>);
}

describe("Red-team lab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.redTeamRuns).mockResolvedValue({ items: [{ id: "run-1", suite_version: 1, status: "completed", started_at: "2026-01-01T00:00:00Z", completed_at: "2026-01-01T00:00:05Z" }], page: 1, page_size: 20, total: 1 });
    vi.mocked(api.redTeamRunDetail).mockResolvedValue(summary);
  });

  it("renders real case results, including the honestly-reported gap", async () => {
    renderPage();
    expect(await screen.findByText("gap found")).toBeTruthy();
    expect(screen.getByText(/A base64-encoded secret is NOT caught/)).toBeTruthy();
    expect(screen.getAllByText("held").length).toBeGreaterThan(0);
    expect(screen.getByText("not applicable")).toBeTruthy();
    expect(screen.getByText("12.5%")).toBeTruthy();
  });

  it("triggers a new run and reloads", async () => {
    vi.mocked(api.runRedTeamSuite).mockResolvedValue(summary);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /run red-team suite/i }));
    await waitFor(() => expect(api.runRedTeamSuite).toHaveBeenCalled());
  });
});
