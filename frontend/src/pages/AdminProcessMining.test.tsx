import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { ToastProvider } from "../components/ui/Toast";
import AdminProcessMining from "./AdminProcessMining";

afterEach(() => cleanup());

vi.mock("../api/client", () => ({
  api: {
    processMiningRuns: vi.fn(),
    runProcessMining: vi.fn(),
    processMiningRunDetail: vi.fn(),
  },
}));

const completedRun = {
  id: "run-1", status: "completed", ticket_count_considered: 5, event_count_considered: 12,
  variants: [{ sequence: ["ticket_submitted", "resolved"], ticket_count: 3, percentage: 0.6 }],
  bottlenecks: [{ from_event_type: "ticket_submitted", to_event_type: "resolved", sample_size: 3, mean_seconds: 110, median_seconds: 110, p90_seconds: 118 }],
  insufficiency_reason: null, started_at: "2026-01-01T00:00:00Z", completed_at: "2026-01-01T00:00:05Z", created_at: "2026-01-01T00:00:00Z",
};

function renderPage() {
  return render(<ToastProvider><AdminProcessMining /></ToastProvider>);
}

describe("Process mining", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.processMiningRuns).mockResolvedValue({ items: [completedRun], page: 1, page_size: 20, total: 1 });
    vi.mocked(api.processMiningRunDetail).mockResolvedValue(completedRun);
  });

  it("renders real variants and bottlenecks from a completed run", async () => {
    renderPage();
    await screen.findByText("Process variants");
    expect(screen.getAllByText("ticket_submitted → resolved").length).toBeGreaterThan(0);
    expect(screen.getByText((_, node) => node?.textContent === "60.0%")).toBeTruthy();
    expect(screen.getByText("Bottlenecks (slowest transitions first)")).toBeTruthy();
  });

  it("shows the honest insufficient-data reason instead of fabricated results", async () => {
    const insufficient = { ...completedRun, status: "insufficient_data", variants: [], bottlenecks: [], insufficiency_reason: "Only 2 ticket(s) have any recorded events; at least 5 are required." };
    vi.mocked(api.processMiningRuns).mockResolvedValue({ items: [insufficient], page: 1, page_size: 20, total: 1 });
    vi.mocked(api.processMiningRunDetail).mockResolvedValue(insufficient);
    renderPage();
    expect(await screen.findByText(/at least 5 are required/)).toBeTruthy();
  });

  it("triggers a new analysis run and reloads", async () => {
    vi.mocked(api.runProcessMining).mockResolvedValue(completedRun);
    renderPage();
    await screen.findByText("Process variants");
    fireEvent.click(screen.getByRole("button", { name: /run analysis/i }));
    await waitFor(() => expect(api.runProcessMining).toHaveBeenCalled());
  });
});
