/**
 * The Administration page's Review model section (planner 25 Nov 2026 22:40; lead-4, 26 Nov 2026): the local model of the
 * general review's Local only runs, one default and, where wanted, one per step. Saved in the app's database by the server
 * (`PUT /api/admin/review-model`), never in a settings file.
 *
 * WHAT THIS SCREEN DOES NOT DECIDE: which model may be chosen. The server says so for each model (approved, priced, installed,
 * small enough) and gives the reason when not; this file only shows it. Claude stays the main engine: its models are listed as
 * the method's own, as scored, with no picker. A local model always says the server's rough-draft label, with its own note.
 */
import { useCallback, useEffect, useState } from "react";

import { request } from "../../api/core";
import { formatWhen } from "../../format/when";

export interface ReviewModelOption {
  name: string;
  engine: "claude" | "local";
  selectable: boolean;
  why: string | null;
  score_words: string;
  used_for?: string;
  price_words?: string;
  is_default?: boolean | null;
  measured?: string | null;
}
export interface ReviewModelOptions {
  claude: ReviewModelOption[];
  local: ReviewModelOption[];
  engine_down: boolean;
  engine_down_words: string | null;
  steps: string[];
  answer_model: string;
  /** Set when ANSWER_MODEL names a model that cannot be used here and the code's default is used instead: the reason. */
  answer_model_why?: string | null;
  used_by: string;
  stored: { default: string | null; steps: Record<string, string>; set_by: string | null; set_at: string | null };
  /** The latest changes, newest first (ids only: the slot, the models, the administrator's id, the time). */
  history?: { slot: string; old_model: string | null; new_model: string | null; changed_by: string | null; changed_at: string }[];
  /** Since when changes are kept (UTC) and the update that brought the history; an empty history says so. */
  history_since?: string | null;
  history_since_update?: string | null;
}

const isOptions = (b: unknown): boolean =>
  typeof b === "object" && b !== null && Array.isArray((b as ReviewModelOptions).claude)
  && Array.isArray((b as ReviewModelOptions).local) && Array.isArray((b as ReviewModelOptions).steps)
  && typeof (b as ReviewModelOptions).stored === "object" && (b as ReviewModelOptions).stored !== null;

export const reviewModelApi = {
  load: () => request<ReviewModelOptions>("/admin/review-model", undefined, isOptions),
  save: (choice: { default: string | null; steps: Record<string, string> }) =>
    request<{ stored: ReviewModelOptions["stored"] }>("/admin/review-model", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(choice),
    }),
};

export function ReviewModelSection({ api = reviewModelApi }: { api?: typeof reviewModelApi }) {
  const [options, setOptions] = useState<ReviewModelOptions | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [choice, setChoice] = useState<{ default: string; steps: Record<string, string> }>({ default: "", steps: {} });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ error: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    const r = await api.load();
    if (!r.ok) { setFailure(r.error.message); return; }
    setFailure(null);
    setOptions(r.data);
    setChoice({ default: r.data.stored.default ?? "", steps: { ...r.data.stored.steps } });
  }, [api]);
  useEffect(() => { void load(); }, [load]);

  async function save() {
    setBusy(true); setMessage(null);
    const steps = Object.fromEntries(Object.entries(choice.steps).filter(([, m]) => m));
    const r = await api.save({ default: choice.default || null, steps });
    setBusy(false);
    if (!r.ok) { setMessage({ error: true, text: r.error.message }); return; }
    setMessage({ error: false, text: "Saved. The next Local only review uses it." });
    await load();
  }

  const choosable = (options?.local ?? []).filter((m) => m.selectable);
  // a saved model that is no longer offered (removed, too large) stays visible in its picker, so the screen never hides it
  const pick = (value: string, onChange: (v: string) => void, label: string, empty: string) => (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} disabled={busy}
      className="rounded-[var(--radius-xs)] border border-ink-500 bg-ink-900 px-2 py-1 text-sm">
      <option value="">{empty}</option>
      {choosable.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
      {value && !choosable.some((m) => m.name === value) && <option value={value}>{value} (no longer offered)</option>}
    </select>
  );

  return (
    <section aria-labelledby="admin-review-model-heading" data-testid="admin-review-model" className="space-y-3">
      <h2 id="admin-review-model-heading" className="text-sm font-semibold text-slateish-200">Review model</h2>
      {failure && <p role="alert" className="text-xs text-warn-500">The review model setting could not be loaded: {failure}</p>}
      {options && (
        <>
          <p className="text-xs text-slateish-300">{options.used_by}</p>
          {options.answer_model_why && (
            <p role="note" data-testid="review-model-fell-back" className="text-xs text-warn-500">{options.answer_model_why}.</p>
          )}
          <div className="space-y-1">
            <h3 className="text-xs font-semibold text-slateish-300">Claude (the main engine)</h3>
            <ul className="space-y-0.5 text-xs text-slateish-300">
              {options.claude.map((m) => (
                <li key={m.name}><span className="font-mono">{m.name}</span>: {m.used_for}; {m.score_words}. {m.why}.</li>
              ))}
            </ul>
          </div>
          <div className="space-y-1">
            <h3 className="text-xs font-semibold text-slateish-300">Local models on this computer</h3>
            {options.engine_down && <p role="note" className="text-xs text-warn-500">{options.engine_down_words}.</p>}
            <ul className="space-y-0.5 text-xs text-slateish-300">
              {options.local.map((m) => (
                <li key={m.name} data-testid="review-model-local">
                  <span className="font-mono">{m.name}</span>{m.is_default ? " (default)" : ""}: {m.score_words}; {m.price_words}
                  {m.measured ? `; ${m.measured}` : ""}
                  {m.selectable ? "" : `; cannot be chosen: ${m.why}`}
                </li>
              ))}
            </ul>
          </div>
          <div className="grid gap-2 text-sm sm:grid-cols-[10rem_1fr]">
            <span className="text-slateish-300">Default</span>
            {pick(choice.default, (v) => setChoice((c) => ({ ...c, default: v })), "Default local model",
              `the answer model (${options.answer_model})`)}
            {options.steps.map((s) => (
              <span key={s} className="contents">
                <span className="text-slateish-300">{s}</span>
                {pick(choice.steps[s] ?? "", (v) => setChoice((c) => ({ ...c, steps: { ...c.steps, [s]: v } })),
                  `Local model for ${s}`, "the default")}
              </span>
            ))}
          </div>
          <div className="flex items-center gap-3">
            <button type="button" onClick={() => void save()} disabled={busy}
              className="rounded-[var(--radius-sm)] bg-signal-500 px-3 py-1 text-sm font-semibold text-ink-950 disabled:opacity-50">
              Save
            </button>
            {options.stored.set_at && (
              <span className="text-xs text-slateish-400">Last saved {formatWhen(options.stored.set_at)}</span>
            )}
          </div>
          {(options.history ?? []).length === 0 && options.history_since && (
            <p data-testid="review-model-no-history" className="text-xs text-slateish-400">
              No change recorded since {formatWhen(options.history_since)}{options.history_since_update ? ` (${options.history_since_update})` : ""}.
            </p>
          )}
          {(options.history ?? []).length > 0 && (
            <div className="space-y-1">
              <h3 className="text-xs font-semibold text-slateish-300">Latest changes</h3>
              <ul data-testid="review-model-history" className="space-y-0.5 text-xs text-slateish-400">
                {(options.history ?? []).map((h) => (
                  <li key={`${h.changed_at}-${h.slot}`}>
                    {formatWhen(h.changed_at)} · {h.slot}: {h.old_model ?? "the default"} → {h.new_model ?? "the default"}
                    {h.changed_by ? ` (by ${h.changed_by})` : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {message && <p role={message.error ? "alert" : "status"}
            className={`text-xs ${message.error ? "text-danger-500" : "text-slateish-300"}`}>{message.text}</p>}
        </>
      )}
    </section>
  );
}
