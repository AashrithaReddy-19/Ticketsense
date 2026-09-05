import { useEffect, useState, type FormEvent } from "react";
import { api, type Playbook } from "../api/client";
import { Badge, Empty, ErrorState, Loading } from "../components/States";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Dialog";
import { useToast } from "../components/ui/Toast";

const STATUS_TABS: Array<[string, string]> = [["", "All"], ["draft", "Draft"], ["approved", "Approved"], ["active", "Active"], ["inactive", "Inactive"], ["superseded", "Superseded"]];

const emptyForm = { playbook_key: "", title: "", category: "", applicable_error_codes: "", clarification_questions: "", diagnostic_steps: "", safety_warnings: "", resolution_template: "", auto_resolution_eligible: false, reason: "" };

function toLines(value: string): string[] {
  return value.split("\n").map(v => v.trim()).filter(Boolean);
}

export default function AdminPlaybooks() {
  const toast = useToast();
  const [statusFilter, setStatusFilter] = useState("");
  const [playbooks, setPlaybooks] = useState<Playbook[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);

  async function load() {
    setLoading(true); setError("");
    try { setPlaybooks(await api.playbooks(statusFilter)); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to load playbooks"); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [statusFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api.createPlaybook({
        playbook_key: form.playbook_key, title: form.title, category: form.category,
        applicable_error_codes: toLines(form.applicable_error_codes),
        clarification_questions: toLines(form.clarification_questions),
        diagnostic_steps_template: toLines(form.diagnostic_steps).map(instruction => ({ title: instruction.slice(0, 60), instruction, evidence_required: false })),
        safety_warnings: toLines(form.safety_warnings),
        resolution_template: form.resolution_template || null,
        auto_resolution_eligible: form.auto_resolution_eligible,
        reason: form.reason,
      });
      setOpen(false); setForm(emptyForm);
      toast("Draft playbook created", "success");
      await load();
    } catch (err) { toast(err instanceof Error ? err.message : "Unable to create the playbook", "danger"); }
  }

  async function transition(playbook: Playbook, action: "approve" | "activate" | "deactivate") {
    setBusy(playbook.id);
    try {
      const fn = action === "approve" ? api.approvePlaybook : action === "activate" ? api.activatePlaybook : api.deactivatePlaybook;
      await fn(playbook.id);
      toast(`Playbook ${action}d`, "success");
      await load();
    } catch (err) { toast(err instanceof Error ? err.message : `Unable to ${action} this playbook`, "danger"); }
    finally { setBusy(null); }
  }

  return (
    <div className="content">
      <div className="page-title"><div><h1>Resolution playbooks</h1><p>Versioned, Admin-approved playbooks for recurring issues. The policy engine — never a playbook alone — decides auto-resolution eligibility.</p></div>
        <Button variant="primary" onClick={() => setOpen(true)}>New playbook</Button></div>
      <div className="tabs" role="tablist">
        {STATUS_TABS.map(([key, label]) => <button key={key} role="tab" aria-selected={statusFilter === key} className={statusFilter === key ? "active" : ""} onClick={() => setStatusFilter(key)}>{label}</button>)}
      </div>
      {loading ? <Loading skeleton /> : error ? <ErrorState message={error} onRetry={load} /> : playbooks.length ? (
        <div className="panel ticket-list">
          <div className="list-head admin-engineer-row"><span>Playbook</span><span>Category</span><span>Version</span><span>Auto-resolution</span><span>Actions</span></div>
          {playbooks.map(playbook => (
            <article className="list-row admin-engineer-row" key={playbook.id}>
              <div><b>{playbook.title}</b><small>{playbook.playbook_key}</small></div>
              <span>{playbook.category}</span>
              <span><Badge value={playbook.status} /> v{playbook.version}</span>
              <span>{playbook.auto_resolution_eligible ? "Eligible" : "Human review required"}</span>
              <div className="review-actions">
                {playbook.status === "draft" && <Button size="sm" variant="primary" loading={busy === playbook.id} onClick={() => transition(playbook, "approve")}>Approve</Button>}
                {playbook.status === "approved" && <Button size="sm" variant="primary" loading={busy === playbook.id} onClick={() => transition(playbook, "activate")}>Activate</Button>}
                {playbook.status === "active" && <Button size="sm" variant="outline" loading={busy === playbook.id} onClick={() => transition(playbook, "deactivate")}>Deactivate</Button>}
              </div>
            </article>
          ))}
        </div>
      ) : <Empty label="No playbooks match this filter." />}
      <Modal open={open} onClose={() => setOpen(false)} title="Author a resolution playbook" footer={null}>
        <form onSubmit={create} className="admin-engineer-form">
          <label className="ui-field"><span>Key (stable identifier, lowercase_with_underscores)</span><input required pattern="[a-z0-9_]+" value={form.playbook_key} onChange={e => setForm({ ...form, playbook_key: e.target.value })} /></label>
          <label className="ui-field"><span>Title</span><input required minLength={3} value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} /></label>
          <label className="ui-field"><span>Category</span><input required minLength={2} value={form.category} onChange={e => setForm({ ...form, category: e.target.value })} placeholder="vpn, sap, payment, cloud, general_it…" /></label>
          <label className="ui-field"><span>Applicable error codes (one per line)</span><textarea rows={2} value={form.applicable_error_codes} onChange={e => setForm({ ...form, applicable_error_codes: e.target.value })} /></label>
          <label className="ui-field"><span>Clarification questions (one per line)</span><textarea rows={3} value={form.clarification_questions} onChange={e => setForm({ ...form, clarification_questions: e.target.value })} /></label>
          <label className="ui-field"><span>Diagnostic steps (one instruction per line)</span><textarea rows={3} value={form.diagnostic_steps} onChange={e => setForm({ ...form, diagnostic_steps: e.target.value })} /></label>
          <label className="ui-field"><span>Safety warnings (one per line)</span><textarea rows={2} value={form.safety_warnings} onChange={e => setForm({ ...form, safety_warnings: e.target.value })} /></label>
          <label className="ui-field"><span>Resolution template</span><textarea rows={2} value={form.resolution_template} onChange={e => setForm({ ...form, resolution_template: e.target.value })} /></label>
          <label className="ui-field-inline"><input type="checkbox" checked={form.auto_resolution_eligible} onChange={e => setForm({ ...form, auto_resolution_eligible: e.target.checked })} /> Allow auto-resolution eligibility (still gated by every other policy check)</label>
          <label className="ui-field"><span>Reason</span><input required minLength={3} value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })} /></label>
          <div className="form-actions"><Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" variant="primary">Save draft</Button></div>
        </form>
      </Modal>
    </div>
  );
}
