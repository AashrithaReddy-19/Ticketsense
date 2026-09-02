import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { IconArrowLeft } from "../components/icons";
import { Button } from "../components/ui/Button";
import { TextArea, TextInput } from "../components/ui/Form";
import { FileUpload } from "../components/ui/FileUpload";

const ALLOWED_EXTENSIONS = [".png", ".jpg", ".jpeg", ".pdf", ".txt", ".log"];
const MAX_BYTES = 10 * 1024 * 1024;
const DESCRIPTION_MAX = 4000;

export function validateSelectedFile(file: File) {
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!ALLOWED_EXTENSIONS.includes(ext)) return "Unsupported file type. Use PNG, JPG, PDF, TXT or LOG.";
  if (file.size === 0) return "The selected file is empty.";
  if (file.size > MAX_BYTES) return "The selected file exceeds 10 MB.";
  return "";
}

export default function NewTicket() {
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [product, setProduct] = useState("");
  const [severity, setSeverity] = useState("");
  const [environment, setEnvironment] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    try {
      const ticket = await api.createTicket({ subject, description, category, product, severity, environment, error_message: errorMessage });
      if (file) await api.uploadAttachment(ticket.id, file);
      nav(`/tickets/${ticket.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to create ticket. Your entered details were kept — please try again.");
    } finally { setBusy(false); }
  }

  return (
    <div className="content narrow">
      <button className="back" onClick={() => nav(-1)}><IconArrowLeft size={14} />Back</button>
      <form className="panel form-page" onSubmit={submit} noValidate>
        <div className="panel-head">
          <div><h2>Create a support ticket</h2><p>Submit text with one optional secure attachment.</p></div>
        </div>

        <div className="section-title">Ticket information <small>required</small></div>
        <TextInput label="Title" required minLength={4} value={subject} onChange={e => setSubject(e.target.value)} placeholder="e.g. VPN keeps disconnecting after password reset" />
        <TextArea
          label="Description"
          required
          minLength={10}
          rows={7}
          value={description}
          onChange={e => setDescription(e.target.value.slice(0, DESCRIPTION_MAX))}
          placeholder="What happened, what you expected, and any error text or steps to reproduce."
          hint={`${description.length}/${DESCRIPTION_MAX} characters`}
        />
        <div className="form-row">
          <TextInput label="Category" hint="Optional — AI can infer this" value={category} onChange={e => setCategory(e.target.value)} />
          <TextInput label="Product" value={product} onChange={e => setProduct(e.target.value)} />
        </div>
        <div className="form-row">
          <label>Severity
            <select value={severity} onChange={e => setSeverity(e.target.value)}>
              <option value="">AI managed</option>
              <option>low</option><option>medium</option><option>high</option><option>urgent</option>
            </select>
          </label>
          <TextInput label="Environment" hint="Production, staging…" value={environment} onChange={e => setEnvironment(e.target.value)} />
        </div>
        <TextInput label="Error message" hint="Optional — paste the exact error text if you have it" value={errorMessage} onChange={e => setErrorMessage(e.target.value)} />

        <div className="section-title">Attachment</div>
        <FileUpload
          accept=".png,.jpg,.jpeg,.pdf,.txt,.log"
          maxBytes={MAX_BYTES}
          supportedLabel="PNG, JPG, PDF, TXT or LOG — maximum 10 MB"
          file={file}
          onSelect={setFile}
          validate={validateSelectedFile}
        />

        <div className="section-title">Review and submit</div>
        {error && <div className="error-box" role="alert">{error}</div>}
        <div className="form-actions">
          <Button type="button" variant="outline" onClick={() => nav(-1)}>Cancel</Button>
          <Button type="submit" variant="primary" loading={busy}>{busy ? (file ? "Uploading…" : "Submitting…") : "Submit ticket"}</Button>
        </div>
      </form>
    </div>
  );
}
