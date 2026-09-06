import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { ToastProvider } from "../components/ui/Toast";
import AdminV2Governance from "./AdminV2Governance";

afterEach(() => cleanup());

vi.mock("../api/client", () => ({
  api: {
    featureFlags: vi.fn(),
    providerModels: vi.fn(),
    aiUsage: vi.fn(),
    updateFeatureFlag: vi.fn(),
    compareChampionChallenger: vi.fn(),
    runShadowSample: vi.fn(),
    championHealthCheck: vi.fn(),
  },
}));

const flag = {
  id: "flag-1",
  key: "evaluation_lab",
  description: "Reproducible evaluation laboratory",
  owner: "AI Governance",
  global_default: false,
  kill_switch: false,
  prerequisites: [],
  evaluation: { enabled: false, reason_code: "DISABLED", reason: "Disabled by global default.", source: "global_default" },
};

function renderPage() {
  return render(<ToastProvider><AdminV2Governance /></ToastProvider>);
}

describe("V2 AI governance", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.featureFlags).mockResolvedValue({ items: [flag], page: 1, page_size: 50, total: 1 });
    vi.mocked(api.providerModels).mockResolvedValue({ items: [], page: 1, page_size: 50 });
    vi.mocked(api.aiUsage).mockResolvedValue({ window_days: 30, metrics_source: "persisted_ai_usage_events", groups: [], empty_state: "No measured provider usage exists." });
    vi.mocked(api.updateFeatureFlag).mockResolvedValue({ ...flag, kill_switch: true });
  });

  it("renders persisted feature decisions without sample metrics", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("evaluation lab")).toBeTruthy());
    expect(screen.getByText("No sample metrics")).toBeTruthy();
    expect(screen.getByText("Disabled by global default.")).toBeTruthy();
  });

  it("activates the audited server-side kill switch", async () => {
    renderPage();
    const button = await screen.findByRole("button", { name: /^kill switch$/i });
    fireEvent.click(button);
    await waitFor(() => expect(api.updateFeatureFlag).toHaveBeenCalledWith("evaluation_lab", {
      kill_switch: true,
      reason: "Activate emergency kill switch from Admin governance UI",
    }));
  });

  it("shows real champion/challenger comparison stats, never fabricated ones", async () => {
    vi.mocked(api.compareChampionChallenger).mockResolvedValue({
      sample_size: 15, data_sufficient: false, reason: "Only 15 labelled comparisons recorded (minimum 20).",
      agreement_rate: 0.7333, champion_accuracy: 0.7333, challenger_accuracy: 0.9333, challenger_accuracy_ci: [0.7018, 0.9881],
      avg_champion_latency_ms: 171.7, avg_challenger_latency_ms: 4.2,
    });
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: /shadow & challenger/i }));
    expect(await screen.findByText("insufficient data")).toBeTruthy();
    expect(screen.getByText(/Only 15 labelled comparisons/)).toBeTruthy();
    expect(screen.getByText(/93\.3% \(95% CI 70\.2–98\.8%\)/)).toBeTruthy();
    expect(api.compareChampionChallenger).toHaveBeenCalledWith("department");
  });

  it("runs a shadow sample and re-loads the comparison", async () => {
    vi.mocked(api.compareChampionChallenger).mockResolvedValue({ sample_size: 0, data_sufficient: false, reason: null, agreement_rate: null, champion_accuracy: null, challenger_accuracy: null, challenger_accuracy_ci: null, avg_champion_latency_ms: null, avg_challenger_latency_ms: null });
    vi.mocked(api.runShadowSample).mockResolvedValue({ status: "sampled", sample_size: 20, missing: [], reason: null });
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: /shadow & challenger/i }));
    fireEvent.click(await screen.findByRole("button", { name: /run shadow sample/i }));
    await waitFor(() => expect(api.runShadowSample).toHaveBeenCalledWith("department", 20));
    await waitFor(() => expect(api.compareChampionChallenger).toHaveBeenCalledTimes(2));
  });
});
