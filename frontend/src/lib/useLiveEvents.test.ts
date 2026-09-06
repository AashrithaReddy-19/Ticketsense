import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { useLiveEvents } from "./useLiveEvents";

vi.mock("../api/client", () => ({
  API_BASE_URL: "http://localhost:8000",
  api: { mintEventStreamToken: vi.fn() },
}));

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners: Record<string, Array<(event: { data?: string }) => void>> = {};
  onerror: (() => void) | null = null;
  url: string;
  closed = false;
  constructor(url: string) { this.url = url; FakeEventSource.instances.push(this); }
  addEventListener(type: string, handler: (event: { data?: string }) => void) { (this.listeners[type] ||= []).push(handler); }
  dispatch(type: string, data?: unknown) { (this.listeners[type] || []).forEach(h => h({ data: data !== undefined ? JSON.stringify(data) : undefined })); }
  close() { this.closed = true; }
}

describe("useLiveEvents", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    FakeEventSource.instances = [];
    // @ts-expect-error test stub standing in for the browser's EventSource
    global.EventSource = FakeEventSource;
  });

  it("never connects when disabled, so polling stays the sole source of updates", async () => {
    renderHook(() => useLiveEvents(false, vi.fn()));
    await act(async () => { await Promise.resolve(); });
    expect(FakeEventSource.instances.length).toBe(0);
  });

  it("mints a real token and connects, reporting connected once the server confirms", async () => {
    vi.mocked(api.mintEventStreamToken).mockResolvedValue({ token: "tok123", expires_in: 120, poll_interval_seconds: 2 });
    const { result } = renderHook(() => useLiveEvents(true, vi.fn()));
    await waitFor(() => expect(FakeEventSource.instances.length).toBe(1));
    expect(FakeEventSource.instances[0].url).toBe("http://localhost:8000/api/v2/events/stream?token=tok123");
    act(() => FakeEventSource.instances[0].dispatch("connected"));
    await waitFor(() => expect(result.current.connected).toBe(true));
  });

  it("invokes the callback with the ticket id carried by a real ticket_updated message", async () => {
    vi.mocked(api.mintEventStreamToken).mockResolvedValue({ token: "tok123", expires_in: 120, poll_interval_seconds: 2 });
    const onEvent = vi.fn();
    renderHook(() => useLiveEvents(true, onEvent));
    await waitFor(() => expect(FakeEventSource.instances.length).toBe(1));
    act(() => FakeEventSource.instances[0].dispatch("ticket_updated", { ticket_id: "abc-123", event_type: "status_changed" }));
    expect(onEvent).toHaveBeenCalledWith("abc-123");
  });

  it("never throws on a malformed message, silently deferring to the polling fallback", async () => {
    vi.mocked(api.mintEventStreamToken).mockResolvedValue({ token: "tok123", expires_in: 120, poll_interval_seconds: 2 });
    const onEvent = vi.fn();
    renderHook(() => useLiveEvents(true, onEvent));
    await waitFor(() => expect(FakeEventSource.instances.length).toBe(1));
    expect(() => FakeEventSource.instances[0].listeners["ticket_updated"][0]({ data: "not json" })).not.toThrow();
    expect(onEvent).not.toHaveBeenCalled();
  });

  it("closes the connection on unmount", async () => {
    vi.mocked(api.mintEventStreamToken).mockResolvedValue({ token: "tok123", expires_in: 120, poll_interval_seconds: 2 });
    const { unmount } = renderHook(() => useLiveEvents(true, vi.fn()));
    await waitFor(() => expect(FakeEventSource.instances.length).toBe(1));
    unmount();
    expect(FakeEventSource.instances[0].closed).toBe(true);
  });

  it("does not connect at all when the flag is disabled (token mint would 404)", async () => {
    vi.mocked(api.mintEventStreamToken).mockRejectedValue(new Error("Feature 'real_time_events' is unavailable"));
    renderHook(() => useLiveEvents(true, vi.fn()));
    await waitFor(() => expect(api.mintEventStreamToken).toHaveBeenCalled());
    expect(FakeEventSource.instances.length).toBe(0);
  });
});
