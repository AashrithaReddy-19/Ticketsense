import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminPlaybooks from "./AdminPlaybooks";
import { api } from "../api/client";
import { ToastProvider } from "../components/ui/Toast";

afterEach(() => cleanup());

vi.mock("../api/client", () => ({
  api: {
    playbooks: vi.fn().mockResolvedValue([]),
    createPlaybook: vi.fn(),
    approvePlaybook: vi.fn(),
    activatePlaybook: vi.fn(),
    deactivatePlaybook: vi.fn(),
  },
}));

function renderPage() {
  return render(<ToastProvider><AdminPlaybooks /></ToastProvider>);
}

describe("Admin playbooks", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists playbooks with their lifecycle status and version", async () => {
    vi.mocked(api.playbooks).mockResolvedValue([
      { id: "p1", playbook_key: "vpn_connection_failure", title: "VPN Connection Failure", category: "vpn", version: 1, status: "active",
        applicable_error_codes: [], clarification_questions: [], evidence_requirements: [], diagnostic_steps_template: [],
        approved_actions: [], safety_warnings: [], resolution_template: null, escalation_rules: [], auto_resolution_eligible: true,
        superseded_by_id: null, reason: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
    ]);
    renderPage();
    await waitFor(() => expect(screen.getByText("VPN Connection Failure")).toBeTruthy());
    expect(screen.getByText("Eligible")).toBeTruthy();
    expect(screen.getByRole("button", { name: /deactivate/i })).toBeTruthy();
  });

  it("approves a draft playbook and refreshes the list", async () => {
    vi.mocked(api.playbooks).mockResolvedValue([
      { id: "p2", playbook_key: "test_playbook", title: "Draft Playbook", category: "general_it", version: 1, status: "draft",
        applicable_error_codes: [], clarification_questions: [], evidence_requirements: [], diagnostic_steps_template: [],
        approved_actions: [], safety_warnings: [], resolution_template: null, escalation_rules: [], auto_resolution_eligible: false,
        superseded_by_id: null, reason: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
    ]);
    vi.mocked(api.approvePlaybook).mockResolvedValue({} as never);
    renderPage();
    await waitFor(() => expect(screen.getByText("Draft Playbook")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /approve/i }));
    await waitFor(() => expect(api.approvePlaybook).toHaveBeenCalledWith("p2"));
    await waitFor(() => expect(api.playbooks).toHaveBeenCalledTimes(2));
  });

  it("shows an empty state when no playbooks match the filter", async () => {
    vi.mocked(api.playbooks).mockResolvedValue([]);
    renderPage();
    await waitFor(() => expect(screen.getByText("No playbooks match this filter.")).toBeTruthy());
  });
});
