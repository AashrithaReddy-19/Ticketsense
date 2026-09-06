import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { ToastProvider } from "../components/ui/Toast";
import AdminConnectors from "./AdminConnectors";

afterEach(() => cleanup());

vi.mock("../api/client", () => ({
  api: {
    connectors: vi.fn(),
    configureConnector: vi.fn(),
    verifyConnector: vi.fn(),
  },
}));

const slack = { id: "conn-1", provider: "slack", name: "Slack", enabled: false, config_reference: null, status: "not_configured", last_verified_at: null, last_verified_by: null, last_error: null };

function renderPage() {
  return render(<ToastProvider><AdminConnectors /></ToastProvider>);
}

describe("External connectors", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.connectors).mockResolvedValue({ items: [slack] });
  });

  it("renders a real connector row in its honest not-configured state", async () => {
    renderPage();
    expect(await screen.findByText("Slack")).toBeTruthy();
    expect(screen.getByText("not configured")).toBeTruthy();
    expect((screen.getByRole("button", { name: /verify/i }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("saves a config_reference through the configure modal", async () => {
    vi.mocked(api.configureConnector).mockResolvedValue({ ...slack, config_reference: "env:SLACK_WEBHOOK_URL", status: "unverified" });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /^configure$/i }));
    fireEvent.change(await screen.findByPlaceholderText("env:SLACK_WEBHOOK_URL"), { target: { value: "env:SLACK_WEBHOOK_URL" } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(api.configureConnector).toHaveBeenCalledWith("conn-1", "env:SLACK_WEBHOOK_URL"));
  });

  it("verifies a configured connector and shows the honest failure reason", async () => {
    const configured = { ...slack, config_reference: "env:SLACK_WEBHOOK_URL", status: "unverified" };
    vi.mocked(api.connectors).mockResolvedValue({ items: [configured] });
    vi.mocked(api.verifyConnector).mockResolvedValue({ ...configured, status: "failed", last_error: "Environment variable 'SLACK_WEBHOOK_URL' is not set in this deployment" });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /^verify$/i }));
    await waitFor(() => expect(api.verifyConnector).toHaveBeenCalledWith("conn-1"));
    expect(await screen.findByText(/is not set in this deployment/)).toBeTruthy();
  });
});
