import { Fragment, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { IconChevronRight, IconSearch } from "../icons";

export function Skeleton({ rows = 4, height = 44 }: { rows?: number; height?: number }) {
  return (
    <div className="ui-skeleton-list" role="status" aria-label="Loading content">
      {Array.from({ length: rows }).map((_, i) => (
        <div className="ui-skeleton-row" key={i} style={{ height }} />
      ))}
      <span className="ui-visually-hidden">Loading…</span>
    </div>
  );
}

export function Breadcrumbs({ items }: { items: Array<{ label: string; to?: string }> }) {
  return (
    <nav aria-label="Breadcrumb" className="ui-breadcrumbs">
      {items.map((item, index) => (
        <Fragment key={item.label}>
          {index > 0 && <IconChevronRight size={13} aria-hidden="true" />}
          {item.to ? <Link to={item.to}>{item.label}</Link> : <span aria-current="page">{item.label}</span>}
        </Fragment>
      ))}
    </nav>
  );
}

export function Pagination({ page, pageSize, total, onPageChange }: { page: number; pageSize: number; total: number; onPageChange: (page: number) => void }) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  if (pageCount <= 1) return null;
  return (
    <nav className="ui-pagination" aria-label="Pagination">
      <button disabled={page <= 1} onClick={() => onPageChange(page - 1)}>Previous</button>
      <span>Page {page} of {pageCount}</span>
      <button disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>Next</button>
    </nav>
  );
}

export function SearchInput({ value, onChange, placeholder = "Search…", ariaLabel }: { value: string; onChange: (value: string) => void; placeholder?: string; ariaLabel?: string }) {
  return (
    <label className="ui-search-input">
      <IconSearch size={15} aria-hidden="true" />
      <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} aria-label={ariaLabel || placeholder} type="search" />
    </label>
  );
}

export function Tooltip({ label, children }: { label: string; children: ReactNode }) {
  const [visible, setVisible] = useState(false);
  return (
    <span className="ui-tooltip-wrap" onMouseEnter={() => setVisible(true)} onMouseLeave={() => setVisible(false)} onFocus={() => setVisible(true)} onBlur={() => setVisible(false)}>
      {children}
      {visible && <span role="tooltip" className="ui-tooltip">{label}</span>}
    </span>
  );
}

export interface TimelineStep { key: string; label: string; done: boolean; active?: boolean; timestamp?: string }
export function Timeline({ steps }: { steps: TimelineStep[] }) {
  return (
    <ol className="ui-timeline">
      {steps.map(step => (
        <li key={step.key} className={step.done ? "is-done" : step.active ? "is-active" : ""}>
          <span className="ui-timeline-dot" aria-hidden="true" />
          <div>
            <b>{step.label}</b>
            {step.timestamp && <small>{new Date(step.timestamp).toLocaleString()}</small>}
          </div>
        </li>
      ))}
    </ol>
  );
}

export function FilterBar({ children }: { children: ReactNode }) {
  return <div className="ui-filter-bar" role="search">{children}</div>;
}
