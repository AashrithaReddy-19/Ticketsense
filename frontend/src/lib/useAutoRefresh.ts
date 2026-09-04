import { useCallback, useEffect, useRef, useState } from "react";

export type SyncStatus = "idle" | "syncing" | "live" | "error";

// Configurable per deployment; defaults to a short interval so role-based
// dashboards stay close to the database (the single source of truth)
// without hammering the API. Tabs in the background stop polling entirely.
export const SYNC_POLL_INTERVAL_MS = Number(import.meta.env.VITE_SYNC_POLL_INTERVAL_MS) || 15000;

/**
 * Polls `callback` on an interval while the tab is visible, re-fetching
 * authoritative data through the same authorized endpoints normal loads use.
 * Never applies optimistic state — callers own how the fetched data is merged.
 */
export function useAutoRefresh(callback: () => Promise<void>, intervalMs: number = SYNC_POLL_INTERVAL_MS, enabled = true) {
  const [status, setStatus] = useState<SyncStatus>("idle");
  const [lastSyncedAt, setLastSyncedAt] = useState<number | null>(null);
  const callbackRef = useRef(callback);
  callbackRef.current = callback;
  const runningRef = useRef(false);

  const run = useCallback(async () => {
    if (runningRef.current) return;
    runningRef.current = true;
    setStatus(s => (s === "idle" ? "syncing" : s));
    try {
      await callbackRef.current();
      setStatus("live");
      setLastSyncedAt(Date.now());
    } catch {
      setStatus("error");
    } finally {
      runningRef.current = false;
    }
  }, []);

  useEffect(() => {
    if (!enabled) { setStatus("idle"); return; }
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    function tick() { if (!cancelled && document.visibilityState === "visible") run(); }
    function start() { if (!timer) timer = setInterval(tick, intervalMs); }
    function stop() { if (timer) { clearInterval(timer); timer = null; } }
    function onVisibility() { if (document.visibilityState === "visible") { run(); start(); } else stop(); }

    document.addEventListener("visibilitychange", onVisibility);
    start();
    return () => { cancelled = true; stop(); document.removeEventListener("visibilitychange", onVisibility); };
  }, [enabled, intervalMs, run]);

  return { status, lastSyncedAt, retryNow: run };
}
