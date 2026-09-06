import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { ToastProvider } from "../components/ui/Toast";
import AdminKnowledgeConflicts from "./AdminKnowledgeConflicts";

afterEach(() => cleanup());

vi.mock("../api/client", () => ({
  api: {
    knowledgeConflicts: vi.fn(),
    scanKnowledgeConflicts: vi.fn(),
    reviewKnowledgeConflict: vi.fn(),
  },
}));

const conflict = {
  id: "conflict-1", article_a_id: "article-1", article_b_id: "article-2", conflict_type: "contradictory_steps",
  severity: "high", evidence_excerpt_a: "VPN access is required for all remote employees.", evidence_excerpt_b: "VPN access is prohibited.",
  confidence: 0.9, sample_size: null, affected_ticket_ids: [], review_state: "open", resolved_by: null, resolved_at: null,
  resolution_note: null, created_at: "2026-01-01T00:00:00Z",
};

function renderPage() {
  return render(<ToastProvider><AdminKnowledgeConflicts /></ToastProvider>);
}

describe("Knowledge conflicts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.knowledgeConflicts).mockResolvedValue({ items: [conflict], page: 1, page_size: 50, total: 1 });
  });

  it("renders a real detected conflict with its severity and open state", async () => {
    renderPage();
    expect(await screen.findByText("contradictory steps")).toBeTruthy();
    expect(screen.getByText(/VPN access is required for all remote employees/)).toBeTruthy();
    expect(screen.getByText("1 open of 1 total")).toBeTruthy();
  });

  it("resolves a conflict through the review modal", async () => {
    vi.mocked(api.reviewKnowledgeConflict).mockResolvedValue({ ...conflict, review_state: "resolved", resolution_note: "Fixed the article." });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /^review$/i }));
    fireEvent.change(await screen.findByLabelText(/note/i), { target: { value: "Fixed the article." } });
    fireEvent.click(screen.getByRole("button", { name: /save decision/i }));
    await waitFor(() => expect(api.reviewKnowledgeConflict).toHaveBeenCalledWith("conflict-1", { review_state: "resolved", resolution_note: "Fixed the article." }));
  });

  it("triggers a scan and reloads the list", async () => {
    vi.mocked(api.scanKnowledgeConflicts).mockResolvedValue({ new_conflicts: 0, conflicts: [] });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /run conflict scan/i }));
    await waitFor(() => expect(api.scanKnowledgeConflicts).toHaveBeenCalled());
  });
});
