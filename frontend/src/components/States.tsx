import { describeBadge } from "../lib/status";
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

/** Auto-detecting status pill kept for backward compatibility — every existing page calls
 * <Badge value={...}/> without saying which domain (status/priority/sentiment) it belongs to. */
export function Badge({ value }: { value?: string | null }) {
  const { label, tone } = describeBadge(value);
  return <span className={`badge ui-tone-${tone}`}>{label}</span>;
}
