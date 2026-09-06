import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { ToastProvider } from "../components/ui/Toast";
import AdminEvaluationLab from "./AdminEvaluationLab";

afterEach(() => cleanup());

vi.mock("../api/client", () => ({
  api: {
    datasets: vi.fn(),
    createDataset: vi.fn(),
    datasetVersions: vi.fn(),
    importDataset: vi.fn(),
    evaluationRuns: vi.fn(),
    createEvaluationRun: vi.fn(),
    evaluationRunDetail: vi.fn(),
    evaluationRunExamples: vi.fn(),
    simulateThreshold: vi.fn(),
    thresholdSimulations: vi.fn(),
  },
}));

const dataset = {
  id: "ds-1", key: "q1_ticket_labels", name: "Q1 ticket labels", kind: "ticket_labels" as const,
  description: "Curated department-labelled tickets for classifier evaluation.", license_notes: "", created_at: "2026-01-01T00:00:00Z",
};

const run = {
  id: "run-1", dataset_version_id: "ver-1", target: "department" as const, model_artifact_path: "ai/models/artifacts/department_classifier.joblib",
  model_artifact_hash: "abc123", git_commit: null, environment_info: {}, config_snapshot: {}, split_used: "test",
  status: "completed" as const, row_count_considered: 6, row_count_excluded: 1, exclusion_reasons: {}, started_at: "2026-01-01T00:00:00Z",
  completed_at: "2026-01-01T00:01:00Z", notes: null, created_at: "2026-01-01T00:01:00Z",
};

function renderPage() {
  return render(<ToastProvider><AdminEvaluationLab /></ToastProvider>);
}

describe("Evaluation lab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.datasets).mockResolvedValue({ items: [dataset], page: 1, page_size: 50, total: 1 });
    vi.mocked(api.evaluationRuns).mockResolvedValue({ items: [run], page: 1, page_size: 50, total: 1 });
    vi.mocked(api.datasetVersions).mockResolvedValue({ items: [] });
    vi.mocked(api.createDataset).mockResolvedValue(dataset);
    vi.mocked(api.thresholdSimulations).mockResolvedValue({ items: [], page: 1, page_size: 50, total: 0 });
  });

  it("renders registered datasets without sample metrics", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Q1 ticket labels")).toBeTruthy());
    expect(screen.getByText("No sample metrics")).toBeTruthy();
  });

  it("registers a new dataset through the form", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Q1 ticket labels")).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText("q1_ticket_labels"), { target: { value: "new_ds" } });
    fireEvent.change(screen.getByPlaceholderText("Q1 ticket labels"), { target: { value: "New dataset" } });
    fireEvent.change(screen.getByPlaceholderText("Source and purpose"), { target: { value: "A description long enough to pass validation." } });
    fireEvent.click(screen.getByRole("button", { name: /register dataset/i }));
    await waitFor(() => expect(api.createDataset).toHaveBeenCalledWith({
      key: "new_ds", name: "New dataset", kind: "ticket_labels", description: "A description long enough to pass validation.",
    }));
  });

  it("shows evaluation runs and drills into a run's real metrics", async () => {
    vi.mocked(api.evaluationRunDetail).mockResolvedValue({
      ...run,
      overall_metrics: { accuracy: 0.83 },
      per_class_metrics: { Networking: { precision: 0.9, recall: 0.8, f1: 0.85, support: 3 } },
      confusion_matrix: { labels: ["Networking", "SAP"], matrix: [[3, 0], [1, 2]] },
    });
    vi.mocked(api.evaluationRunExamples).mockResolvedValue({
      items: [{ id: "ex-1", dataset_row_id: "row-1", true_label: "SAP", predicted_label: "Networking", correct: false, top_3_hit: null, predicted_confidence: 0.6, redacted_text: "SAP transport failed" }],
      page: 1, page_size: 50, total: 1,
    });
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: /evaluation runs/i }));
    fireEvent.click(await screen.findByText("department", { selector: "b" }));
    await waitFor(() => expect(screen.getByText("accuracy")).toBeTruthy());
    expect(screen.getByText("83.00%")).toBeTruthy();
    expect(screen.getByText("SAP transport failed")).toBeTruthy();
  });

  it("runs a threshold simulation and shows an honest insufficient-data result", async () => {
    vi.mocked(api.simulateThreshold).mockResolvedValue({
      id: "sim-1", department_id: null, category: null, proposed_threshold: 0.85, sample_size: 4,
      auto_resolved_at_threshold: 2, data_sufficient: false,
      insufficiency_reasons: ["Only 4 historical decisions have a recorded confidence score in this scope (minimum 30)."],
      estimated_coverage: 0.5, estimated_referral_rate: 0.5, historical_false_resolution_rate: 0,
      confidence_interval: [0, 0.6], sensitive_category_override: false, based_on: "ticket_decisions", created_at: "2026-01-01T00:00:00Z",
    });
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: /threshold simulation/i }));
    fireEvent.click(await screen.findByRole("button", { name: /run simulation/i }));
    await waitFor(() => expect(api.simulateThreshold).toHaveBeenCalledWith({ proposed_threshold: 0.85, category: undefined }));
    expect(await screen.findByText("insufficient data")).toBeTruthy();
    expect(screen.getByText(/Only 4 historical decisions/)).toBeTruthy();
  });
});
