/** Centralized status/priority/sentiment → visual tone mapping. One source of truth so
 * badge colors are never redefined ad hoc on individual pages. Vocabulary matches the
 * backend's DB check constraints exactly — see db/migrations/versions/0001_initial_schema.py
 * (ticket status/priority/sentiment) and the attachment/ai_drafts migrations (0009, 0010). */

export type Tone = "neutral" | "info" | "violet" | "success" | "warning" | "danger";

export interface BadgeMeta { label: string; tone: Tone }

const TICKET_STATUS: Record<string, BadgeMeta> = {
  submitted: { label: "Submitted", tone: "info" },
  needs_clarification: { label: "Needs clarification", tone: "warning" },
  ai_processing: { label: "AI processing", tone: "info" },
  awaiting_assignment: { label: "Awaiting assignment", tone: "warning" },
  processing: { label: "Processing", tone: "info" },
  classified: { label: "Classified", tone: "info" },
  routed: { label: "Routed", tone: "violet" },
  assigned: { label: "Assigned", tone: "violet" },
  in_progress: { label: "In progress", tone: "info" },
  awaiting_customer: { label: "Awaiting customer", tone: "warning" },
  pending_review: { label: "Pending review", tone: "warning" },
  changes_requested: { label: "Changes requested", tone: "warning" },
  approved: { label: "Approved", tone: "success" },
  escalated: { label: "Escalated", tone: "danger" },
  resolved: { label: "Resolved", tone: "success" },
  resolved_by_ai: { label: "Resolved by AI", tone: "success" },
  resolved_by_engineer: { label: "Resolved by Engineer", tone: "success" },
  ai_processing_failed: { label: "AI processing failed", tone: "danger" },
  closed: { label: "Closed", tone: "neutral" },
  reopened: { label: "Reopened", tone: "warning" },
};

const PRIORITY: Record<string, BadgeMeta> = {
  low: { label: "Low", tone: "neutral" },
  medium: { label: "Medium", tone: "info" },
  high: { label: "High", tone: "warning" },
  urgent: { label: "Urgent", tone: "danger" },
};

const SENTIMENT: Record<string, BadgeMeta> = {
  positive: { label: "Positive", tone: "success" },
  neutral: { label: "Neutral", tone: "neutral" },
  negative: { label: "Negative", tone: "warning" },
};

const GENERATION_STATUS: Record<string, BadgeMeta> = {
  pending: { label: "Pending", tone: "neutral" },
  generated: { label: "Generated", tone: "info" },
  ready: { label: "Ready", tone: "success" },
  failed: { label: "Generation failed", tone: "danger" },
  failed_validation: { label: "Validation failed", tone: "danger" },
};

const CITATION_VALIDATION: Record<string, BadgeMeta> = {
  valid: { label: "Citations valid", tone: "success" },
  invalid: { label: "Citations invalid", tone: "danger" },
  pending: { label: "Not yet validated", tone: "neutral" },
};

const EXTRACTION_STATUS: Record<string, BadgeMeta> = {
  pending: { label: "Pending", tone: "neutral" },
  processing: { label: "Processing", tone: "info" },
  ready: { label: "Extracted", tone: "success" },
  empty: { label: "No text found", tone: "warning" },
  failed: { label: "Extraction failed", tone: "danger" },
};

const ATTACHMENT_STATUS: Record<string, BadgeMeta> = {
  uploaded: { label: "Uploaded", tone: "neutral" },
  validating: { label: "Validating", tone: "info" },
  processing: { label: "Processing", tone: "info" },
  ready: { label: "Ready", tone: "success" },
  rejected: { label: "Rejected", tone: "danger" },
  failed: { label: "Failed", tone: "danger" },
};

const SEVERITY: Record<string, BadgeMeta> = {
  low: { label: "Low", tone: "neutral" },
  medium: { label: "Medium", tone: "info" },
  high: { label: "High", tone: "warning" },
  critical: { label: "Critical", tone: "danger" },
};

const KNOWLEDGE_ARTICLE_STATUS: Record<string, BadgeMeta> = {
  draft: { label: "Draft", tone: "neutral" },
  pending_review: { label: "Pending review", tone: "warning" },
  published: { label: "Published", tone: "success" },
  rejected: { label: "Rejected", tone: "danger" },
  stale: { label: "Stale", tone: "warning" },
  current: { label: "Current", tone: "success" },
};

const ALL_DOMAINS = [TICKET_STATUS, PRIORITY, SENTIMENT, GENERATION_STATUS, CITATION_VALIDATION, EXTRACTION_STATUS, ATTACHMENT_STATUS, SEVERITY, KNOWLEDGE_ARTICLE_STATUS];

/** Auto-detects which domain a raw backend value belongs to. Existing call sites pass a
 * bare status/priority/sentiment string without saying which — this preserves that. */
export function describeBadge(value?: string | null): BadgeMeta {
  if (!value) return { label: "—", tone: "neutral" };
  for (const domain of ALL_DOMAINS) {
    const match = domain[value];
    if (match) return match;
  }
  return { label: value.replaceAll("_", " "), tone: "neutral" };
}

export function describeTicketStatus(value?: string | null): BadgeMeta {
  return (value && TICKET_STATUS[value]) || describeBadge(value);
}
export function describePriority(value?: string | null): BadgeMeta {
  return (value && PRIORITY[value]) || describeBadge(value);
}
export function describeSentiment(value?: string | null): BadgeMeta {
  return (value && SENTIMENT[value]) || describeBadge(value);
}
export function describeGenerationStatus(value?: string | null): BadgeMeta {
  return (value && GENERATION_STATUS[value]) || describeBadge(value);
}
export function describeCitationValidation(value?: string | null): BadgeMeta {
  return (value && CITATION_VALIDATION[value]) || describeBadge(value);
}
export function describeExtractionStatus(value?: string | null): BadgeMeta {
  return (value && EXTRACTION_STATUS[value]) || describeBadge(value);
}
export function describeAttachmentStatus(value?: string | null): BadgeMeta {
  return (value && ATTACHMENT_STATUS[value]) || describeBadge(value);
}
