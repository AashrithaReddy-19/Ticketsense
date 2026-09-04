import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, type Analytics } from "../api/client";
import AnalyticsDashboard from "./AnalyticsDashboard";

vi.mock("../api/client", () => ({ api: { analytics: vi.fn() } }));
vi.mock("../lib/useAutoRefresh", () => ({ useAutoRefresh: () => ({ status: "idle", lastSyncedAt: null, retryNow: vi.fn() }) }));

const analytics: Analytics = {
  total_tickets: 12, open_tickets: 3, resolved_tickets: 7, escalated_tickets: 2,
  average_confidence: 0.81, status_distribution: { resolved: 7, escalated: 2, submitted: 3 },
  ai_acceptance_rate: 0.5, engineer_edit_rate: 0.3, reviewer_modification_rate: 0.3,
  rejection_rate: 0.1, escalation_rate: 0.1, ai_human_agreement: 0.5,
  confidence_distribution: { low: 1, borderline: 3, high: 8 },
  average_response_time_hours: 1.5, average_resolution_time_hours: 6.2,
  department_performance: [{ department_id: "d1", department: "Networking", total_tickets: 8, resolved_tickets: 5, average_confidence: 0.77 }],
  pipeline_stage_latency: [{ stage: "classification", average_duration_ms: 12.5, sample_count: 12, failure_count: 0 }],
};

describe("analytics dashboard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows a loading state, then renders backend-computed stat tiles and section data", async () => {
    vi.mocked(api.analytics).mockResolvedValue(analytics);
    render(<AnalyticsDashboard />);
    expect(screen.getByText(/Loading analytics/)).toBeTruthy();

    await waitFor(() => expect(screen.getByText("Total tickets")).toBeTruthy());
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.getByText("Networking")).toBeTruthy();
    expect(screen.getByText(/n=12/)).toBeTruthy();
  });

  it("shows an error state with retry when the request fails", async () => {
    vi.mocked(api.analytics).mockRejectedValue(new Error("Unable to load analytics"));
    render(<AnalyticsDashboard />);
    await waitFor(() => expect(screen.getByText("Unable to load analytics")).toBeTruthy());
    expect(screen.getByRole("button", { name: /try again/i })).toBeTruthy();
  });

  it("shows an empty state for a section with no data instead of a broken chart", async () => {
    vi.mocked(api.analytics).mockResolvedValue({
      ...analytics, department_performance: [], pipeline_stage_latency: [],
      confidence_distribution: { low: 0, borderline: 0, high: 0 },
    });
    render(<AnalyticsDashboard />);
    await waitFor(() => expect(screen.getByText("No departments configured.")).toBeTruthy());
    expect(screen.getByText("No pipeline timing recorded yet.")).toBeTruthy();
    expect(screen.getByText("No scored tickets yet.")).toBeTruthy();
  });
});
