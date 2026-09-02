import { useEffect, useRef, type ReactNode } from "react";
import { IconClose } from "../icons";
import { Button } from "./Button";

const FOCUSABLE = 'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

/** Shared focus-trap + Escape-to-close + return-focus behavior for Modal, ConfirmDialog and Drawer. */
function useDialogBehavior(open: boolean, onClose: () => void, panelRef: React.RefObject<HTMLElement>) {
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    const first = panel?.querySelector<HTMLElement>(FOCUSABLE);
    (first || panel)?.focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key !== "Tab" || !panel) return;
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (focusable.length === 0) return;
      const [firstEl, lastEl] = [focusable[0], focusable[focusable.length - 1]];
      if (e.shiftKey && document.activeElement === firstEl) { e.preventDefault(); lastEl.focus(); }
      else if (!e.shiftKey && document.activeElement === lastEl) { e.preventDefault(); firstEl.focus(); }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previouslyFocused.current?.focus();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
}

export function Modal({ open, onClose, title, description, children, footer }: {
  open: boolean; onClose: () => void; title: string; description?: string; children: ReactNode; footer?: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  useDialogBehavior(open, onClose, panelRef);
  if (!open) return null;
  return (
    <div className="ui-modal-bg" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="ui-modal" role="dialog" aria-modal="true" aria-labelledby="ui-modal-title" ref={panelRef} tabIndex={-1}>
        <div className="ui-modal-head">
          <div>
            <h2 id="ui-modal-title">{title}</h2>
            {description && <p>{description}</p>}
          </div>
          <button className="ui-icon-btn ui-btn-ghost" onClick={onClose} aria-label="Close dialog"><IconClose size={18} /></button>
        </div>
        <div className="ui-modal-body">{children}</div>
        {footer && <div className="ui-modal-actions">{footer}</div>}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open, onClose, onConfirm, title, description, confirmLabel = "Confirm", variant = "primary", busy = false, requireReason = false, reason, onReasonChange,
}: {
  open: boolean; onClose: () => void; onConfirm: () => void; title: string; description: string;
  confirmLabel?: string; variant?: "primary" | "destructive"; busy?: boolean;
  requireReason?: boolean; reason?: string; onReasonChange?: (value: string) => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  useDialogBehavior(open, onClose, panelRef);
  if (!open) return null;
  const reasonTooShort = requireReason && (reason || "").trim().length < 3;
  return (
    <div className="ui-modal-bg" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="ui-modal ui-modal-sm" role="alertdialog" aria-modal="true" aria-labelledby="ui-confirm-title" ref={panelRef} tabIndex={-1}>
        <div className="ui-modal-head">
          <div><h2 id="ui-confirm-title">{title}</h2><p>{description}</p></div>
          <button className="ui-icon-btn ui-btn-ghost" onClick={onClose} aria-label="Close dialog"><IconClose size={18} /></button>
        </div>
        {requireReason && (
          <div className="ui-modal-body">
            <label className="ui-field">
              <span>Reason <em>required</em></span>
              <textarea rows={3} value={reason || ""} onChange={e => onReasonChange?.(e.target.value)} placeholder="Explain the decision for the ticket record…" />
            </label>
          </div>
        )}
        <div className="ui-modal-actions">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button variant={variant} onClick={onConfirm} loading={busy} disabled={reasonTooShort}>{confirmLabel}</Button>
        </div>
      </div>
    </div>
  );
}

export function Drawer({ open, onClose, children, label }: { open: boolean; onClose: () => void; children: ReactNode; label: string }) {
  const panelRef = useRef<HTMLDivElement>(null);
  useDialogBehavior(open, onClose, panelRef);
  if (!open) return null;
  return (
    <div className="ui-drawer-bg" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="ui-drawer" role="dialog" aria-modal="true" aria-label={label} ref={panelRef} tabIndex={-1}>
        {children}
      </div>
    </div>
  );
}
