import { useEffect, useState } from "react";

import type { ReviewDisposition, ReviewFinding, ReviewFindingEvent, ReviewFindingUpdate, ReviewStatus } from "../../types/api";
import { reviews as reviewsApi } from "../../api/client";

type Props = {
  findings: ReviewFinding[];
  onUpdate: (id: string, update: ReviewFindingUpdate) => Promise<void>;
  documents?: DocumentOption[];
};
type DocumentOption = { id: string; filename: string };

const statusLabels: Record<ReviewStatus, string> = {
  open: "Open",
  in_progress: "In progress",
  awaiting_response: "Awaiting response",
  resolved: "Resolved",
  deferred: "Deferred",
};

export function ReviewWorkflowPanel({ findings, onUpdate, documents = [] }: Props) {
  if (findings.length === 0) return null;
  return (
    <section aria-label="Engineering review workflow" className="card-3d surface-card rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slateish-300">Engineering review workflow</h3>
          <p className="mt-1 text-xs text-slateish-500">Respond to cited findings, record the disposition, and submit them for approval.</p>
        </div>
        <span className="text-xs text-slateish-500">{findings.length} finding{findings.length === 1 ? "" : "s"}</span>
      </div>
      <ul className="mt-3 divide-y divide-ink-700/70">
        {findings.map((finding) => <FindingRow key={finding.id} finding={finding} onUpdate={onUpdate} documents={documents} />)}
      </ul>
    </section>
  );
}

function FindingRow({ finding, onUpdate, documents }: { finding: ReviewFinding; onUpdate: Props["onUpdate"]; documents: DocumentOption[] }) {
  const [response, setResponse] = useState(finding.response_text ?? "");
  const [disposition, setDisposition] = useState<ReviewDisposition | "">(finding.disposition ?? "");
  const [status, setStatus] = useState<ReviewStatus>(finding.status);
  const [approval, setApproval] = useState(finding.approval_status);
  const [owner, setOwner] = useState(finding.owner_user_id ?? "");
  const [dueDate, setDueDate] = useState(finding.due_date ?? "");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [history, setHistory] = useState<ReviewFindingEvent[] | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [traceability, setTraceability] = useState<import("../../types/api").ReviewTraceability | null>(null);
  const [automaticBaseline, setAutomaticBaseline] = useState<import("../../types/api").BaselineSelection | null>(null);
  const [baselineOverride, setBaselineOverride] = useState(finding.baseline_document_id ?? "");
  const [baselineMessage, setBaselineMessage] = useState<string | null>(null);

  useEffect(() => {
    if (documents.length === 0) return;
    let cancelled = false;
    void reviewsApi.baselineSelection(finding.document_id).then((result) => {
      if (cancelled) return;
      if (result.ok) setAutomaticBaseline(result.data);
      else setBaselineMessage(result.error.message);
    });
    return () => { cancelled = true; };
  }, [documents.length, finding.document_id]);

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      await onUpdate(finding.id, {
        response_text: response.trim() || null,
        disposition: disposition || null,
        status,
        approval_status: approval,
        owner_user_id: owner.trim() || null,
        due_date: dueDate || null,
      });
      setMessage("Saved");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save");
    } finally {
      setSaving(false);
    }
  }

  async function showHistory() {
    setLoadingHistory(true);
    try {
      const result = await reviewsApi.history(finding.id);
      if (result.ok) setHistory(result.data.events);
      else setMessage(result.error.message);
    } finally {
      setLoadingHistory(false);
    }
  }

  async function showTraceability() {
    const result = await reviewsApi.traceability(finding.id);
    if (result.ok) setTraceability(result.data);
    else setMessage(result.error.message);
  }

  return (
    <li className="py-4 first:pt-3 last:pb-1">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded-[var(--radius-xs)] bg-danger-500/15 px-2 py-0.5 font-semibold uppercase tracking-wide text-danger-500">{finding.severity}</span>
        <span className="text-slateish-400">{finding.category.replaceAll("_", " ")}</span>
        <span className="text-slateish-500">{finding.id.slice(0, 8)}</span>
      </div>
      <p className="mt-2 text-sm text-slateish-200">{finding.finding}</p>
      <p className="mt-1 text-xs text-slateish-400">Required action: {finding.required_action}</p>
      {documents.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slateish-400">
          <span className="font-medium text-slateish-300">Baseline</span>
          {automaticBaseline?.automatic && <span className="rounded-[var(--radius-xs)] bg-signal-500/15 px-2 py-0.5 text-signal-300">Auto-selected based on document type</span>}
          <select aria-label="Review baseline override" value={baselineOverride || automaticBaseline?.document_id || ""} onChange={(e) => setBaselineOverride(e.target.value)} className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200">
            <option value="">No baseline selected</option>
            {[...new Map([
              ...(automaticBaseline?.document_id ? [[automaticBaseline.document_id, "Auto-selected baseline"] as const] : []),
              ...documents.map((document) => [document.id, document.filename] as const),
            ]).entries()].map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
          {baselineMessage !== null && <span role="alert" className="text-danger-500">{baselineMessage}</span>}
        </div>
      )}
      <div className="mt-3 grid gap-2 lg:grid-cols-[1fr_auto_auto]">
        <textarea value={response} onChange={(e) => setResponse(e.target.value)} rows={2} placeholder="Engineer response or corrective-action explanation" className="w-full rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-slateish-200" />
        <select value={disposition} onChange={(e) => setDisposition(e.target.value as ReviewDisposition | "")} className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-slateish-200">
          <option value="">Disposition</option>
          <option value="accepted">Accepted</option>
          <option value="partially_accepted">Partially accepted</option>
          <option value="rejected">Rejected</option>
          <option value="not_applicable">Not applicable</option>
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value as ReviewStatus)} className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-slateish-200">
          {(Object.keys(statusLabels) as ReviewStatus[]).map((key) => <option key={key} value={key}>{statusLabels[key]}</option>)}
        </select>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <label className="text-xs text-slateish-500">Owner
          <input value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="Engineer ID" className="ms-1 w-32 rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200" />
        </label>
        <label className="text-xs text-slateish-500">Due
          <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} className="ms-1 rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200" />
        </label>
        <select value={approval} onChange={(e) => setApproval(e.target.value as typeof approval)} className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200">
          <option value="pending">Approval pending</option>
          <option value="accepted">Approved</option>
          <option value="rejected">Approval rejected</option>
          <option value="not_required">Approval not required</option>
        </select>
        <button type="button" disabled={saving} onClick={() => void save()} className="rounded-[var(--radius-xs)] bg-signal-500/20 px-3 py-1.5 text-xs font-medium text-signal-300 ring-1 ring-signal-500/50 hover:bg-signal-500/30 disabled:opacity-50">{saving ? "Saving…" : "Save response"}</button>
        {message !== null && <span className="text-xs text-slateish-400" role="status">{message}</span>}
        <button type="button" onClick={() => void showHistory()} disabled={loadingHistory} className="rounded-[var(--radius-xs)] border border-ink-600 px-3 py-1.5 text-xs text-slateish-300 hover:border-signal-500/60 disabled:opacity-50">{loadingHistory ? "Loading history…" : history === null ? "View history" : "Refresh history"}</button>
        <button type="button" onClick={() => void showTraceability()} className="rounded-[var(--radius-xs)] border border-signal-500/50 px-3 py-1.5 text-xs text-signal-300 hover:bg-signal-500/10">{traceability === null ? "View full chain" : "Refresh full chain"}</button>
      </div>
      {history !== null && <ol className="mt-3 space-y-1 border-l border-ink-600 ps-3 text-xs text-slateish-500" aria-label="Finding history">
        {history.map((event) => <li key={event.id}><span className="text-slateish-400">{event.event_type === "created" ? "Created" : "Updated"}</span> · {new Date(event.created_at).toLocaleString()} · {Object.keys(event.changes).join(", ") || "no field changes"}</li>)}
      </ol>}
      {traceability !== null && <div aria-label="Finding traceability" className="mt-3 rounded-[var(--radius-xs)] border border-signal-500/30 bg-signal-500/[0.04] p-3 text-xs text-slateish-300"><p className="font-semibold uppercase tracking-wide text-signal-400">Full traceability chain</p><p className="mt-2">Finding → {traceability.document.filename} → {traceability.baseline?.filename ?? "No baseline"} → {traceability.citations.length} citation(s) → {traceability.deliverables.length} deliverable(s) → {traceability.owner?.display_name || traceability.owner?.email || "No owner assigned"} → {traceability.action || finding.required_action}</p></div>}
    </li>
  );
}
