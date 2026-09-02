import type { ReactNode } from "react";

export function Card({ children, className = "", padded = true }: { children: ReactNode; className?: string; padded?: boolean }) {
  return <div className={`ui-card ${padded ? "ui-card-padded" : ""} ${className}`.trim()}>{children}</div>;
}

export function CardHeader({ title, description, action }: { title: ReactNode; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="ui-card-head">
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function StatCard({ label, value, sub, icon, tone = "violet" }: { label: string; value: string; sub?: string; icon?: ReactNode; tone?: "violet" | "success" | "warning" | "danger" | "info" }) {
  return (
    <div className="ui-stat-card">
      {icon && <div className={`ui-stat-icon ui-tone-${tone}`}>{icon}</div>}
      <div>
        <p>{label}</p>
        <strong>{value}</strong>
        {sub && <span>{sub}</span>}
      </div>
    </div>
  );
}

export function EvidenceCard({
  citationId, title, version, department, snippet, similarity, active, cardRef,
}: {
  citationId: string; title: string; version: string; department: string; snippet: string; similarity: number;
  active?: boolean; cardRef?: (el: HTMLElement | null) => void;
}) {
  return (
    <article ref={cardRef} className={`ui-evidence-card ${active ? "is-focused" : ""}`} tabIndex={-1}>
      <div className="ui-evidence-card-head">
        <span className="ui-citation-pill is-static">{citationId}</span>
        <div>
          <b>{title}</b>
          <small>Version {version} · {department}</small>
        </div>
        <strong>{(similarity * 100).toFixed(1)}%</strong>
      </div>
      <p>{snippet}</p>
    </article>
  );
}

export function AttachmentCard({ children }: { children: ReactNode }) {
  return <div className="ui-attachment-card">{children}</div>;
}
