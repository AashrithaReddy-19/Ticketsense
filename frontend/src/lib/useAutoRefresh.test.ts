import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAutoRefresh } from "./useAutoRefresh";

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
}

describe("useAutoRefresh", () => {
  beforeEach(() => { vi.useFakeTimers(); setVisibility("visible"); });
  afterEach(() => { vi.useRealTimers(); });

  it("re-fetches authoritative data on the configured interval while the tab is visible", async () => {
    const callback = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useAutoRefresh(callback, 1000, true));

    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(callback).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(callback).toHaveBeenCalledTimes(3);
  });

  it("stops polling while the tab is hidden and resumes with a fresh fetch when visible again", async () => {
    const callback = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useAutoRefresh(callback, 1000, true));

    setVisibility("hidden");
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(callback).not.toHaveBeenCalled();

    await act(async () => { setVisibility("visible"); await Promise.resolve(); });
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("surfaces a reconnecting status on failure without throwing, and clears it on the next success", async () => {
    const callback = vi.fn().mockRejectedValueOnce(new Error("network")).mockResolvedValue(undefined);
    const { result } = renderHook(() => useAutoRefresh(callback, 1000, true));

    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(result.current.status).toBe("error");

    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(result.current.status).toBe("live");
    expect(result.current.lastSyncedAt).not.toBeNull();
  });

  it("never polls when disabled", async () => {
    const callback = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useAutoRefresh(callback, 1000, false));
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(callback).not.toHaveBeenCalled();
  });
});
