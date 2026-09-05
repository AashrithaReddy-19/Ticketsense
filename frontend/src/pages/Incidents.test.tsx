import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Incidents from "./Incidents";
import { api } from "../api/client";
import { ToastProvider } from "../components/ui/Toast";

afterEach(() => cleanup());

vi.mock("../api/client", () => ({
  api: {
    incidents: vi.fn().mockResolvedValue([]),
    scanForIncidents: vi.fn(),
    incidentTickets: vi.fn().mockResolvedValue([]),
    incidentRootCause: vi.fn().mockResolvedValue(null),
    confirmIncident: vi.fn(),
    dismissIncident: vi.fn(),
    notifyIncidentCustomers: vi.fn(),
    resolveIncident: vi.fn(),
  },
}));

function renderPage() {
  return render(<ToastProvider><Incidents /></ToastProvider>);
}

const candidateIncident = {
  id: "i1", title: "Possible vpn incident", service: "Networking", status: "candidate", severity: "high",
  ticket_count: 4, growth_rate: 33.3, common_symptom: "vpn connection drops", detection_reason: "4 tickets in the vpn category within 72 hours.",
};

describe("Incidents page", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows a candidate incident and lets an Admin confirm it after viewing details", async () => {
    vi.mocked(api.incidents).mockResolvedValue([candidateIncident as never]);
    vi.mocked(api.confirmIncident).mockResolvedValue({ ...candidateIncident, status: "investigating" } as never);
    renderPage();
    await waitFor(() => expect(screen.getByText("Possible vpn incident")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /view details/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /confirm incident/i })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /confirm incident/i }));
    await waitFor(() => expect(api.confirmIncident).toHaveBeenCalledWith("i1"));
  });

  it("labels the root-cause view as a hypothesis, never a confirmed fact", async () => {
    vi.mocked(api.incidents).mockResolvedValue([candidateIncident as never]);
    vi.mocked(api.incidentRootCause).mockResolvedValue({
      incident_id: "i1", status: "hypothesis", disclaimer: "This is an inferred hypothesis, not a confirmed root cause.",
      likely_symptom: "vpn connection drops", recurring_error_codes: [{ code: "vpn-809", occurrences: 3 }],
      supporting_ticket_ids: ["t1", "t2", "t3"], ticket_count: 3,
    });
    renderPage();
    await waitFor(() => expect(screen.getByText("Possible vpn incident")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /view details/i }));
    await waitFor(() => expect(screen.getByText(/not a confirmed root cause/i)).toBeTruthy());
  });

  it("runs a manual scan and reports the result", async () => {
    vi.mocked(api.scanForIncidents).mockResolvedValue([candidateIncident as never]);
    renderPage();
    await waitFor(() => expect(api.incidents).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /scan now/i }));
    await waitFor(() => expect(api.scanForIncidents).toHaveBeenCalled());
  });
});
