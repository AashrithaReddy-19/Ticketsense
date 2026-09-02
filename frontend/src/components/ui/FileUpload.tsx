import { useId, useRef, useState, type DragEvent } from "react";
import { IconFile, IconFileText, IconImage, IconTrash, IconUpload } from "../icons";

function iconFor(name: string) {
  const ext = name.slice(name.lastIndexOf(".")).toLowerCase();
  if ([".png", ".jpg", ".jpeg"].includes(ext)) return IconImage;
  if ([".txt", ".log"].includes(ext)) return IconFileText;
  return IconFile;
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface FileUploadProps {
  accept: string;
  maxBytes: number;
  supportedLabel: string;
  file: File | null;
  onSelect: (file: File | null) => void;
  validate: (file: File) => string;
  error?: string;
}

/** Drag-and-drop attachment zone with a real <input type=file> underneath, so it stays fully
 * usable via keyboard/screen reader (Tab to the button, Enter/Space opens the file picker) —
 * drag-and-drop is a convenience layered on top, never the only way to attach a file. */
export function FileUpload({ accept, supportedLabel, file, onSelect, validate, error }: FileUploadProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [localError, setLocalError] = useState("");

  function choose(next: File | null) {
    if (!next) { onSelect(null); setLocalError(""); return; }
    const issue = validate(next);
    if (issue) { setLocalError(issue); onSelect(null); return; }
    setLocalError("");
    onSelect(next);
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) choose(dropped);
  }

  const shownError = error || localError;
  const Icon = file ? iconFor(file.name) : IconUpload;

  return (
    <div className="ui-field">
      <label htmlFor={inputId}>Attachment <em>optional</em></label>
      <div
        className={`ui-dropzone ${dragOver ? "is-dragover" : ""} ${shownError ? "has-error" : ""}`}
        onDragOver={e => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        {!file ? (
          <>
            <IconUpload size={26} />
            <p><b>Drag and drop a file</b> or <button type="button" className="ui-link-btn" onClick={() => inputRef.current?.click()}>browse your device</button></p>
            <small>{supportedLabel}</small>
          </>
        ) : (
          <div className="ui-selected-file">
            <Icon size={22} />
            <div>
              <b>{file.name}</b>
              <small>{file.type || "Unknown type"} · {formatBytes(file.size)}</small>
            </div>
            <button type="button" className="ui-icon-btn ui-btn-ghost" onClick={() => choose(null)} aria-label="Remove selected file"><IconTrash size={16} /></button>
          </div>
        )}
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          accept={accept}
          className="ui-visually-hidden-input"
          onChange={e => choose(e.target.files?.[0] || null)}
        />
      </div>
      {shownError && <span className="ui-field-error" role="alert">{shownError}</span>}
    </div>
  );
}

export { formatBytes };
