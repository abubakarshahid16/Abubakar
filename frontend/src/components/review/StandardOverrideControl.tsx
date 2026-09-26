import { useEffect, useState } from "react";
import { reviews as reviewsApi } from "../../api/client";
import type { ReviewRunMissingReference, ReviewRunStandard } from "../../types/api";

/**
 * P2: the engineer adds or removes a standard on a review, with a reason.
 *
 * The server records who, when and why, and recomputes the findings; this
 * control only asks. It never pre-fills a reason - an override with no reason
 * is indistinguishable from a mistake - and it says so when the run already
 * carries an engineer's final code, instead of offering a button that fails.
 */
export function StandardOverrideControl({ runId, decided, onChanged }: {
  runId: string;
  decided: boolean;
  onChanged: (standards: ReviewRunStandard[], missing: ReviewRunMissingReference[]) => void;
}) {
  const [all, setAll] = useState<ReviewRunStandard[] | null>(null);
  const [target, setTarget] = useState<{ id: string; include: boolean } | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void reviewsApi.reviewRunStandardsAll(runId).then((r) => {
      if (!cancelled) setAll(r.ok ? r.data.standards : []);
    });
    return () => { cancelled = true; };
  }, [runId]);

  if (decided) {
    return (
      <p className="text-xs text-slateish-400" data-testid="override-locked">
        An engineer has recorded the final code for this review, so its standards
        can no longer be changed. Start a new review to use a different set.
      </p>
    );
  }
  if (all === null) return null;
  const applied = all.filter((s) => s.included);
  const notApplied = all.filter((s) => !s.included);
  const name = (s: ReviewRunStandard) => s.filename ?? s.standard_document_id;

  async function submit() {
    if (!target) return;
    setBusy(true);
    setError(null);
    const result = await reviewsApi.overrideRunStandard(runId, {
      standard_document_id: target.id, include: target.include, reason: reason.trim(),
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.error.message);
      return;
    }
    setAll(result.data.standards);
    setTarget(null);
    setReason("");
    onChanged(result.data.standards.filter((s) => s.included), result.data.missing_references ?? []);
  }

  return (
    <section aria-label="Change the standards for this review"
      className="space-y-2 rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-3 text-sm">
      <p className="font-medium text-slateish-100">Engineer: change the standards</p>
      <ul className="space-y-1">
        {applied.map((s) => (
          <li key={s.standard_document_id}>
            <button type="button" className="text-xs text-rose-300 underline"
              onClick={() => { setTarget({ id: s.standard_document_id, include: false }); setError(null); }}>
              Remove {name(s)}
            </button>
          </li>
        ))}
      </ul>
      {notApplied.length > 0 && (
        <label className="block text-xs text-slateish-300">
          Add a standard
          <select className="ms-2 rounded border border-ink-600 bg-ink-800 px-2 py-1"
            value={target?.include ? target.id : ""}
            onChange={(e) => setTarget(e.target.value ? { id: e.target.value, include: true } : null)}>
            <option value="">Choose a standard…</option>
            {notApplied.map((s) => (
              <option key={s.standard_document_id} value={s.standard_document_id}>{name(s)}</option>
            ))}
          </select>
        </label>
      )}
      {target && (
        <div className="space-y-1">
          <label className="block text-xs text-slateish-300">
            {target.include ? "Why does this standard apply?" : "Why does this standard not apply?"}
            <textarea className="mt-1 block w-full rounded border border-ink-600 bg-ink-800 p-2"
              value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
          </label>
          <button type="button" disabled={busy || reason.trim().length < 3}
            className="rounded border border-ink-600 px-3 py-1 text-xs disabled:opacity-50"
            onClick={() => { void submit(); }}>
            {target.include ? "Add and recompute the findings" : "Remove and recompute the findings"}
          </button>
        </div>
      )}
      {error && <p role="alert" className="text-xs text-rose-300">{error}</p>}
    </section>
  );
}
