import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { ToastProvider } from "../components/ui/Toast";
import AdminOcrBenchmarkLab from "./AdminOcrBenchmarkLab";

afterEach(() => cleanup());

vi.mock("../api/client", () => ({
  api: {
    ocrEngines: vi.fn(),
    ocrDatasets: vi.fn(),
    createOcrDataset: vi.fn(),
    ocrCases: vi.fn(),
    createOcrCase: vi.fn(),
    ocrRuns: vi.fn(),
    createOcrRun: vi.fn(),
    ocrRunDetail: vi.fn(),
  },
}));

const engines = {
  tesseract: { available: false, reason: "Tesseract is not installed or not on PATH in this environment: TesseractNotFoundError" },
  easyocr: { available: false, reason: "The easyocr package is not installed in this environment" },
  paddleocr: { available: false, reason: "The paddleocr package is not installed in this environment" },
};

const dataset = { id: "dataset-1", key: "error-screenshots", name: "Error dialog screenshots", description: "", case_count: 2, created_at: "2026-01-01T00:00:00Z" };

function renderPage() {
  return render(<ToastProvider><AdminOcrBenchmarkLab /></ToastProvider>);
}

describe("OCR benchmark lab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.ocrEngines).mockResolvedValue({ engines });
    vi.mocked(api.ocrDatasets).mockResolvedValue({ items: [dataset] });
    vi.mocked(api.ocrCases).mockResolvedValue({ items: [] });
    vi.mocked(api.ocrRuns).mockResolvedValue({ items: [], page: 1, page_size: 50, total: 0 });
  });

  it("renders real engine availability including honest not-configured reasons", async () => {
    renderPage();
    expect(await screen.findByText("tesseract")).toBeTruthy();
    expect(screen.getAllByText("not configured").length).toBe(3);
    expect(screen.getByText(/easyocr package is not installed/)).toBeTruthy();
  });

  it("registers a new dataset through the form", async () => {
    vi.mocked(api.createOcrDataset).mockResolvedValue({ ...dataset, id: "dataset-2", key: "new-suite", name: "New suite", case_count: 0 });
    renderPage();
    await screen.findByText("error-screenshots");
    fireEvent.change(screen.getByPlaceholderText("error-screenshots"), { target: { value: "new-suite" } });
    fireEvent.change(screen.getByPlaceholderText("Error dialog screenshots"), { target: { value: "New suite" } });
    fireEvent.click(screen.getByRole("button", { name: /register dataset/i }));
    await waitFor(() => expect(api.createOcrDataset).toHaveBeenCalledWith({ key: "new-suite", name: "New suite" }));
  });

  it("triggers a benchmark run against a selected dataset and shows the honest result", async () => {
    const run = { id: "run-1", dataset_id: "dataset-1", engine: "tesseract", status: "engine_unavailable", unavailable_reason: "Tesseract is not installed", row_count_considered: 0, mean_character_error_rate: null, mean_word_error_rate: null, mean_latency_ms: null, environment_info: {}, started_at: "2026-01-01T00:00:00Z", completed_at: "2026-01-01T00:00:01Z", created_at: "2026-01-01T00:00:00Z" };
    vi.mocked(api.createOcrRun).mockResolvedValue(run);
    vi.mocked(api.ocrRunDetail).mockResolvedValue({ ...run, results: [] });
    renderPage();
    fireEvent.click(await screen.findByText("Error dialog screenshots"));
    fireEvent.click(await screen.findByRole("button", { name: /run benchmark/i }));
    await waitFor(() => expect(api.createOcrRun).toHaveBeenCalledWith({ dataset_id: "dataset-1", engine: "tesseract" }));
  });
});
