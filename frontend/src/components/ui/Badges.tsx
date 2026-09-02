import { describeAttachmentStatus, describeCitationValidation, describeExtractionStatus, describeGenerationStatus, describePriority, describeSentiment, describeTicketStatus, type Tone } from "../../lib/status";
import { IconAlert, IconCheckCircle, IconClock, IconInfo, IconXCircle } from "../icons";

const TONE_ICON: Record<Tone, typeof IconInfo | null> = {
  success: IconCheckCircle,
  danger: IconXCircle,
  warning: IconAlert,
  info: IconInfo,
  violet: null,
  neutral: null,
};

export function Pill({ label, tone, icon }: { label: string; tone: Tone; icon?: boolean }) {
  const Icon = icon ? TONE_ICON[tone] : null;
  return (
    <span className={`ui-pill ui-tone-${tone}`}>
      {Icon && <Icon size={12} />}
      {label}
    </span>
  );
}

/** Auto-detecting status pill — matches the original <Badge value=.../> call signature used
 * across every existing page, so no call site needs to change. */
export function StatusBadge({ value }: { value?: string | null }) {
  return <Pill {...describeTicketStatus(value)} />;
}
export function PriorityBadge({ value }: { value?: string | null }) {
  return <Pill {...describePriority(value)} icon />;
}
export function SentimentBadge({ value }: { value?: string | null }) {
  return <Pill {...describeSentiment(value)} />;
}
export function GenerationStatusBadge({ value }: { value?: string | null }) {
  return <Pill {...describeGenerationStatus(value)} icon />;
}
export function CitationValidationBadge({ value }: { value?: string | null }) {
  return <Pill {...describeCitationValidation(value)} icon />;
}
export function ExtractionStatusBadge({ value }: { value?: string | null }) {
  return <Pill {...describeExtractionStatus(value)} icon />;
}
export function AttachmentStatusBadge({ value }: { value?: string | null }) {
  return <Pill {...describeAttachmentStatus(value)} icon />;
}
export function DepartmentBadge({ value }: { value?: string | null }) {
  return <span className="ui-pill ui-tone-neutral ui-pill-outline">{value || "Unassigned"}</span>;
}
export function CitationPill({ id, active, onClick }: { id: string; active?: boolean; onClick?: () => void }) {
  return (
    <button type="button" className={`ui-citation-pill ${active ? "is-active" : ""}`} onClick={onClick}>
      {id}
    </button>
  );
}
export function ReadOnlyPill() {
  return <span className="ui-pill ui-tone-neutral ui-pill-outline"><IconClock size={12} />Read-only access</span>;
}
