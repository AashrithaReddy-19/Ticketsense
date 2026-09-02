import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

interface FieldChrome { label: ReactNode; hint?: string; error?: string; required?: boolean }

export function Field({ label, hint, error, required, children }: FieldChrome & { children: (describedBy: string | undefined, id: string) => ReactNode }) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className={`ui-field ${error ? "has-error" : ""}`}>
      <label htmlFor={id}>{label}{required && <em> required</em>}</label>
      {children(describedBy, id)}
      {hint && !error && <span id={hintId} className="ui-field-hint">{hint}</span>}
      {error && <span id={errorId} className="ui-field-error" role="alert">{error}</span>}
    </div>
  );
}

export function TextInput({ label, hint, error, required, ...props }: FieldChrome & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <Field label={label} hint={hint} error={error} required={required}>
      {(describedBy, id) => <input id={id} aria-describedby={describedBy} aria-invalid={!!error} required={required} {...props} />}
    </Field>
  );
}

export function TextArea({ label, hint, error, required, ...props }: FieldChrome & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <Field label={label} hint={hint} error={error} required={required}>
      {(describedBy, id) => <textarea id={id} aria-describedby={describedBy} aria-invalid={!!error} required={required} {...props} />}
    </Field>
  );
}

export function Select({ label, hint, error, required, children, ...props }: FieldChrome & SelectHTMLAttributes<HTMLSelectElement> & { children: ReactNode }) {
  return (
    <Field label={label} hint={hint} error={error} required={required}>
      {(describedBy, id) => <select id={id} aria-describedby={describedBy} required={required} {...props}>{children}</select>}
    </Field>
  );
}

export function Checkbox({ label, ...props }: { label: ReactNode } & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <label className="ui-checkbox" htmlFor={id}>
      <input id={id} type="checkbox" {...props} />
      <span>{label}</span>
    </label>
  );
}

export function CharCount({ value, max }: { value: string; max: number }) {
  const over = value.length > max;
  return <span className={`ui-char-count ${over ? "is-over" : ""}`} aria-live="polite">{value.length}/{max}</span>;
}
