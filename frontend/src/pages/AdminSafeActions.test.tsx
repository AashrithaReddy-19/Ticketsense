import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminSafeActions from "./AdminSafeActions";
import { api } from "../api/client";

afterEach(() => cleanup());

vi.mock("../api/client", () => ({
  api: { safeActions: vi.fn().mockResolvedValue([]), safeActionExecutions: vi.fn().mockResolvedValue([]) },
}));

describe("Admin safe actions", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows available actions with their risk level and sandbox labelling", async () => {
    vi.mocked(api.safeActions).mockResolvedValue([
      { action_key: "check_service_status", display_name: "Check service status", description: "Sandboxed check.", category: "diagnostics",
        risk_level: "low", required_capability: "safe_action:execute", parameter_schema: {}, requires_confirmation: false,
        requires_customer_consent: false, enabled: true, connector: "sandbox", timeout_seconds: 10, supports_dry_run: true, supports_rollback: false },
    ]);
    render(<AdminSafeActions />);
    await waitFor(() => expect(screen.getByText("Check service status")).toBeTruthy());
    expect(screen.getByText("(sandbox)")).toBeTruthy();
  });

  it("shows a recent execution's sandbox-labelled result", async () => {
    vi.mocked(api.safeActionExecutions).mockResolvedValue([
      { id: "e1", action_key: "check_service_status", ticket_id: null, department_id: null, requested_by: "u1", mode: "execute",
        status: "succeeded", requires_approval: false, error_summary: null, started_at: null, completed_at: null, duration_ms: 12,
        created_at: new Date().toISOString(), result: { summary: "Sandbox check: Jira reports operational.", data: {}, evidence: [], sandbox: true, rollback_available: false, rolled_back: false } },
    ]);
    render(<AdminSafeActions />);
    await waitFor(() => expect(screen.getByText(/sandbox check: jira reports operational.*\(sandbox\)/i)).toBeTruthy());
  });
});
