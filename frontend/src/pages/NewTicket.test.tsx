import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import NewTicket from "./NewTicket";

vi.mock("../api/client", () => ({
  api: {
    assistDescription: vi.fn(),
    createTicket: vi.fn(),
    uploadAttachment: vi.fn(),
  },
}));

describe("customer description assistant", () => {
  beforeEach(() => vi.clearAllMocks());

  it("keeps the original until the customer accepts the editable suggestion", async () => {
    vi.mocked(api.assistDescription).mockResolvedValue({
      original: "vpn not connect from morning tried restart",
      suggested: "I am unable to connect to the VPN since this morning. I tried restarting.",
      missing_information_questions: ["What exact error message is displayed?"],
      mode: "deterministic-development:description-clarity-rules-v1",
    });
    render(<MemoryRouter><NewTicket /></MemoryRouter>);

    fireEvent.change(screen.getByRole("textbox", { name: /title/i }), { target: { value: "vpn error" } });
    const original = screen.getByRole("textbox", { name: /^description/i });
    fireEvent.change(original, { target: { value: "vpn not connect from morning tried restart" } });
    fireEvent.click(screen.getByRole("button", { name: "Improve description" }));

    expect(await screen.findByDisplayValue(/I am unable to connect to the VPN/)).toBeTruthy();
    expect((original as HTMLTextAreaElement).value).toBe("vpn not connect from morning tried restart");
    expect(screen.getByText("What exact error message is displayed?")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Accept suggestion" }));
    await waitFor(() => expect((original as HTMLTextAreaElement).value).toMatch(/unable to connect to the VPN/));
  });
});

