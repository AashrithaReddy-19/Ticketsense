import { describeBadge } from "../lib/status";
import type { SyncStatus } from "../lib/useAutoRefresh";
import { IconAlertCircle, IconInbox, IconLock, IconRefresh, IconWifi } from "./icons";
import { Button } from "./ui/Button";
import { Skeleton } from "./ui/Utility";

export function Loading({ label = "Loading…", skeleton = false }: { label?: string; skeleton?: boolean }) {
  if (skeleton) return <Skeleton />;
  return (
    <div className="state-card" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const offline = /unable to connect|check that the backend/i.test(message);
  const Icon = offline ? IconWifi : IconAlertCircle;
  return (
    <div className="state-card state-card-error" role="alert">
      <Icon size={26} />
      <b>{offline ? "Backend unavailable" : "Unable to load data"}</b>
      <span>{message}</span>
      {onRetry && <Button variant="outline" size="sm" onClick={onRetry} icon={<IconRefresh size={14} />}>Try again</Button>}
    </div>
  );
}

export function PermissionDenied({ message = "Your account does not have permission to view this content." }: { message?: string }) {
  return (
    <div className="state-card">
      <IconLock size={26} />
      <b>Access restricted</b>
      <span>{message}</span>
    </div>
  );
}

export function Empty({ label = "No tickets found.", action }: { label?: string; action?: React.ReactNode }) {
  return (
    <div className="state-card">
      <IconInbox size={26} />
      <span>{label}</span>
      {action}
    </div>
  );
}

/** Shows whether this view's data is being kept in sync with the database (the
 * single source of truth) via background polling — never implies an optimistic,
 * unconfirmed update. */
export function SyncIndicator({ status, lastSyncedAt, onRetry }: { status: SyncStatus; lastSyncedAt: number | null; onRetry?: () => void }) {
  if (status === "error") return <span className="sync-indicator sync-indicator-error" role="status"><IconWifi size={13} />Reconnecting…{onRetry && <button type="button" className="sync-retry" onClick={onRetry}>Retry now</button>}</span>;
  if (status === "syncing" && !lastSyncedAt) return <span className="sync-indicator" role="status"><span className="spinner spinner-sm" aria-hidden="true" />Syncing…</span>;
  if (!lastSyncedAt) return null;
  return <span className="sync-indicator sync-indicator-live" role="status"><span className="sync-dot" aria-hidden="true" />Live · updated {new Date(lastSyncedAt).toLocaleTimeString()}</span>;
}

/** Auto-detecting status pill kept for backward compatibility — every existing page calls
 * <Badge value={...}/> without saying which domain (status/priority/sentiment) it belongs to. */
export function Badge({ value }: { value?: string | null }) {
  const { label, tone } = describeBadge(value);
  return <span className={`badge ui-tone-${tone}`}>{label}</span>;
}
