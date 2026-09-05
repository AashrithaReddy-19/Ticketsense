import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminPrevention from "./AdminPrevention";
import { api } from "../api/client";
import { ToastProvider } from "../components/ui/Toast";

afterEach(() => cleanup());

vi.mock("../api/client", () => ({
  api: {
    preventionRecommendations: vi.fn().mockResolvedValue([]),
    scanForPreventionRecommendations: vi.fn(),
    preventionRecommendation: vi.fn().mockResolvedValue(null),
    acceptRecommendation: vi.fn(),
    rejectRecommendation: vi.fn(),
    investigateRecommendation: vi.fn(),
    dismissRecommendation: vi.fn(),
    convertRecommendationToKnowledge: vi.fn(),
    linkRecommendationToIncident: vi.fn(),
  },
}));

function renderPage() {
  return render(<ToastProvider><AdminPrevention /></ToastProvider>);
}

const recommendation = {
  id: "r1", department_id: "d1", category: "vpn", recommendation_type: "create_knowledge_article",
  title: "Create a knowledge article for recurring 'vpn' issues", description: "5 tickets in the last 30 days.",
  window_days: 30, supporting_ticket_count: 5, evidence_strength: "medium" as const,
  expected_benefit: "Faster future resolution.", status: "new", decision_reason: null,
  linked_incident_id: null, linked_knowledge_article_id: null, generated_at: new Date().toISOString(),
  decided_by: null, decided_at: null, created_at: new Date().toISOString(),
};

describe("Admin predictive prevention", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows a recommendation with its evidence strength and supporting count", async () => {
    vi.mocked(api.preventionRecommendations).mockResolvedValue([recommendation]);
    renderPage();
    await waitFor(() => expect(screen.getByText(recommendation.title)).toBeTruthy());
    expect(screen.getByText("5")).toBeTruthy();
  });

  it("accepts a recommendation after viewing its details", async () => {
    vi.mocked(api.preventionRecommendations).mockResolvedValue([recommendation]);
    vi.mocked(api.preventionRecommendation).mockResolvedValue({ ...recommendation, evidence: [], actions: [] });
    vi.mocked(api.acceptRecommendation).mockResolvedValue({ ...recommendation, status: "accepted" });
    renderPage();
    await waitFor(() => expect(screen.getByText(recommendation.title)).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /view details/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /^accept$/i })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /^accept$/i }));
    await waitFor(() => expect(api.acceptRecommendation).toHaveBeenCalledWith("r1"));
  });

  it("never presents the recommendation as a confirmed cause", async () => {
    vi.mocked(api.preventionRecommendations).mockResolvedValue([recommendation]);
    renderPage();
    await waitFor(() => expect(screen.getByText(/never a confirmed cause/i)).toBeTruthy());
  });
});
