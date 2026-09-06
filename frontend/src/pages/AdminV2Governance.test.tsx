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
});
