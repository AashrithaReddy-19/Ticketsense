import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeRoute } from "../App";
import { useAuth } from "../auth/AuthContext";
import { api } from "../api/client";
import { ToastProvider } from "../components/ui/Toast";

afterEach(() => cleanup());

function renderRoute() {
  return render(<ToastProvider><KnowledgeRoute /></ToastProvider>);
}

vi.mock("../auth/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("../api/client", () => ({
  api: {
    knowledge: vi.fn().mockResolvedValue([]),
    knowledgeArticles: vi.fn().mockResolvedValue([]),
    generateKnowledgeArticle: vi.fn(),
    approveKnowledgeArticle: vi.fn(),
    rejectKnowledgeArticle: vi.fn(),
    knowledgeGaps: vi.fn().mockResolvedValue({ window_days: 30, weak_evidence_by_category: [], heavy_edit_by_category: [] }),
    knowledgeHealth: vi.fn().mockResolvedValue({ stale_after_days: 180, articles: [] }),
  },
}));

const mockedUseAuth = vi.mocked(useAuth);

describe("Admin Knowledge navigation", () => {
  beforeEach(() => { vi.clearAllMocks(); mockedUseAuth.mockReset(); });

  it("shows the read-only knowledge search for a user without knowledge:manage", async () => {
    mockedUseAuth.mockReturnValue({ user: null, loading: false, login: vi.fn(), logout: vi.fn(), hasPermission: () => false });
    renderRoute();
    await waitFor(() => expect(screen.getByText("Knowledge")).toBeTruthy());
    expect(screen.queryByText("Knowledge management")).toBeNull();
  });

  it("shows the full knowledge-management experience for a user with knowledge:manage", async () => {
    mockedUseAuth.mockReturnValue({ user: null, loading: false, login: vi.fn(), logout: vi.fn(), hasPermission: (p: string) => p === "knowledge:manage" });
    vi.mocked(api.knowledgeArticles).mockResolvedValue([
      { id: "a1", title: "VPN reconnect steps", status: "pending_review", version: "1.0", department_id: "d1", source_ticket_ids: ["t1"], source_signal: "no_cited_evidence_at_resolution", published_knowledge_base_id: null, rejected_reason: null, created_at: new Date().toISOString() },
    ]);
    renderRoute();
    await waitFor(() => expect(screen.getByText("Knowledge management")).toBeTruthy());
    expect(screen.getByText("VPN reconnect steps")).toBeTruthy();
    expect(screen.getByText("Auto-drafted (knowledge gap)")).toBeTruthy();
    expect(screen.getByRole("button", { name: /approve & publish/i })).toBeTruthy();
  });

  it("approves a pending article and refreshes the list", async () => {
    mockedUseAuth.mockReturnValue({ user: null, loading: false, login: vi.fn(), logout: vi.fn(), hasPermission: () => true });
    vi.mocked(api.knowledgeArticles).mockResolvedValue([
      { id: "a1", title: "SAP authorization fix", status: "pending_review", version: "1.0", department_id: "d1", source_ticket_ids: [], source_signal: "manual", published_knowledge_base_id: null, rejected_reason: null, created_at: new Date().toISOString() },
    ]);
    vi.mocked(api.approveKnowledgeArticle).mockResolvedValue({ id: "a1", status: "published", knowledge_base_id: "kb1" });
    renderRoute();
    await waitFor(() => expect(screen.getByText("SAP authorization fix")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /approve & publish/i }));
    await waitFor(() => expect(api.approveKnowledgeArticle).toHaveBeenCalledWith("a1"));
    await waitFor(() => expect(api.knowledgeArticles).toHaveBeenCalledTimes(2));
  });

  it("switches to the knowledge-gaps tab and shows a real data-derived signal", async () => {
    mockedUseAuth.mockReturnValue({ user: null, loading: false, login: vi.fn(), logout: vi.fn(), hasPermission: () => true });
    vi.mocked(api.knowledgeGaps).mockResolvedValue({
      window_days: 30,
      weak_evidence_by_category: [{ category: "vpn", count: 4, example_ticket_ids: ["t1", "t2"] }],
      heavy_edit_by_category: [],
    });
    renderRoute();
    await waitFor(() => expect(screen.getByText("Knowledge management")).toBeTruthy());
    fireEvent.click(screen.getByRole("tab", { name: "Knowledge gaps" }));
    await waitFor(() => expect(screen.getByText("vpn")).toBeTruthy());
    expect(screen.getByText("4 tickets")).toBeTruthy();
  });
});
