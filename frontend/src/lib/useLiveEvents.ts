import { useEffect, useRef, useState } from "react";
import { API_BASE_URL, api } from "../api/client";

/**
 * Opts into low-latency server-sent ticket-update nudges (real_time_events
 * feature flag). This is purely an accelerant on top of useAutoRefresh, not
 * a replacement for it: it only ever triggers an earlier re-fetch through
 * the caller's own authorized REST call. If the flag is off, minting a
 * token 404s and this hook simply never connects — polling keeps running
 * unchanged, so no update is ever silently dropped because SSE failed.
 */
export function useLiveEvents(enabled: boolean, onTicketEvent: (ticketId: string) => void) {
  const [connected, setConnected] = useState(false);
  const onEventRef = useRef(onTicketEvent);
  onEventRef.current = onTicketEvent;

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") { setConnected(false); return; }
    let cancelled = false;
    let source: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    async function connect() {
      if (cancelled) return;
      try {
        const { token } = await api.mintEventStreamToken();
        if (cancelled) return;
        source = new EventSource(`${API_BASE_URL}/api/v2/events/stream?token=${encodeURIComponent(token)}`);
        source.addEventListener("connected", () => { attempt = 0; setConnected(true); });
        source.addEventListener("ticket_updated", (event) => {
          try {
            const data = JSON.parse((event as MessageEvent).data);
            if (data?.ticket_id) onEventRef.current(data.ticket_id);
          } catch { /* a malformed nudge is ignored; polling still covers the update */ }
        });
        source.onerror = () => {
          setConnected(false);
          source?.close();
          if (cancelled) return;
          attempt += 1;
          retryTimer = setTimeout(connect, Math.min(1000 * 2 ** attempt, 30000));
        };
      } catch {
        setConnected(false);
        if (!cancelled) retryTimer = setTimeout(connect, 10000);
      }
    }
    connect();
    return () => {
      cancelled = true;
      setConnected(false);
      source?.close();
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [enabled]);

  return { connected };
}
