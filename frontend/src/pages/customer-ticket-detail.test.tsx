import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CustomerAttachment, customerTimeline } from "./TicketWorkspace";
import type { AttachmentMeta, Ticket } from "../api/client";

const ticket = (status: string): Ticket => ({
  id: "ticket-1", subject: "VPN issue", description: "Cannot connect", status,
  priority: "high", sentiment: "negative", confidence_score: null,
  created_at: "2026-09-01T10:00:00Z", updated_at: "2026-09-01T11:00:00Z", analysis: {},
});

describe("customer-safe ticket detail", () => {
  it("shows safe attachment metadata but never extracted text or OCR diagnostics", () => {
    const attachment: AttachmentMeta = {
      id: "a1", ticket_id: "ticket-1", original_filename: "error.log",
      detected_mime_type: "text/plain", file_extension: ".log", file_size_bytes: 2048,
      status: "ready", extraction_status: "ready", sanitized_text: "SECRET INTERNAL TEXT",
      ocr_confidence: 0.98, ocr_confidence_available: true, created_at: "2026-09-01T10:00:00Z",
    };
    render(<CustomerAttachment attachment={attachment} />);
    expect(screen.getByText("error.log")).toBeTruthy();
    expect(screen.getByText("Processed")).toBeTruthy();
    expect(screen.queryByText("SECRET INTERNAL TEXT")).toBeNull();
    expect(screen.queryByText(/OCR confidence/i)).toBeNull();
  });

  it("does not mark future lifecycle stages complete", () => {
    const steps = customerTimeline(ticket("pending_review"));
    expect(steps.find(step => step.key === "submitted")?.done).toBe(true);
    expect(steps.find(step => step.key === "pending_review")?.active).toBe(true);
    expect(steps.find(step => step.key === "resolved")?.done).toBe(false);
  });
});
