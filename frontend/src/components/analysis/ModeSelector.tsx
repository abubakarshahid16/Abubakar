/**
 * Analysis mode + optional-section toggles.
 *
 * A real radio group in a <fieldset>: native radios already give arrow-key
 * navigation, a single tab stop and correct announcement, so nothing here is
 * re-implemented. The timing words are honest ranges measured on this machine,
 * never percentages or progress promises.
 *
 * The three optional sections are meaningless in "quote" mode (no model runs),
 * so the checkboxes are disabled there rather than hidden - the reader can still
 * see what switching mode would unlock.
 */
import { useId } from "react";

export type AnalysisMode = "quote" | "focused" | "comprehensive";

export interface AnalysisToggles {
  gaps: boolean;
  market: boolean;
  recommendation: boolean;
}

const MODES: { value: AnalysisMode; label: string; description: string }[] = [
  {
    value: "quote",
    label: "Quote",
    description: "The document's own words. ~2 seconds. No model involved.",
  },
  {
    value: "focused",
    label: "Focused",
    description: "A generated answer over the top passages. About a minute on this machine.",
  },
  {
    value: "comprehensive",
    label: "Comprehensive",
    description: "Every authorised document, batch by batch. Several minutes; you can cancel.",
  },
];

const TOGGLES: { key: keyof AnalysisToggles; label: string; hint: string }[] = [
  { key: "gaps", label: "Gap analysis", hint: "Compare documents against a nominated baseline." },
  {
    key: "market",
    label: "Public market sample (sample data)",
    hint: "Offline machine: rows are illustrative samples, never live.",
  },
  {
    key: "recommendation",
    label: "Generate recommendation",
    hint: "Advisory only. Computed after gaps and market; shown near the top.",
  },
];

export function ModeSelector({
  mode,
  onChange,
  toggles,
  onToggle,
  disabled = false,
}: {
  mode: AnalysisMode;
  onChange: (m: AnalysisMode) => void;
  toggles: AnalysisToggles;
  onToggle: (k: keyof AnalysisToggles, v: boolean) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const togglesDisabled = disabled || mode === "quote";

  return (
    <div className="space-y-3">
      <fieldset
        disabled={disabled}
        className="rounded-lg border border-ink-600 bg-ink-850 p-3 disabled:opacity-60"
      >
        <legend className="px-1 text-xs uppercase tracking-wide text-slateish-500">
          Analysis mode
        </legend>
        <div className="mt-1 space-y-2">
          {MODES.map((m) => {
            const inputId = `${id}-mode-${m.value}`;
            const descId = `${inputId}-desc`;
            const checked = mode === m.value;
            return (
              <label
                key={m.value}
                htmlFor={inputId}
                className={[
                  "flex cursor-pointer items-start gap-3 rounded border px-3 py-2",
                  checked
                    ? "border-signal-500/60 bg-signal-500/10"
                    : "border-ink-700 hover:bg-ink-800",
                ].join(" ")}
              >
                <input
                  id={inputId}
                  type="radio"
                  name={`${id}-mode`}
                  value={m.value}
                  checked={checked}
                  onChange={() => onChange(m.value)}
                  aria-describedby={descId}
                  className="mt-1 h-4 w-4 shrink-0 accent-signal-500"
                />
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-slateish-100">{m.label}</span>
                  <span id={descId} className="block text-xs text-slateish-400">
                    {m.description}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      <fieldset
        disabled={togglesDisabled}
        className="rounded-lg border border-ink-600 bg-ink-850 p-3 disabled:opacity-60"
      >
        <legend className="px-1 text-xs uppercase tracking-wide text-slateish-500">
          Optional sections
        </legend>
        {mode === "quote" && (
          <p className="mt-1 text-xs text-slateish-500">
            Not available in Quote mode &mdash; these sections need the model.
          </p>
        )}
        <div className="mt-1 space-y-2">
          {TOGGLES.map((t) => {
            const inputId = `${id}-toggle-${t.key}`;
            const hintId = `${inputId}-hint`;
            return (
              <label
                key={t.key}
                htmlFor={inputId}
                className="flex cursor-pointer items-start gap-3 rounded px-1 py-1"
              >
                <input
                  id={inputId}
                  type="checkbox"
                  checked={toggles[t.key]}
                  onChange={(e) => onToggle(t.key, e.target.checked)}
                  aria-describedby={hintId}
                  className="mt-0.5 h-4 w-4 shrink-0 accent-signal-500"
                />
                <span className="min-w-0">
                  <span className="block text-sm text-slateish-200">{t.label}</span>
                  <span id={hintId} className="block text-xs text-slateish-500">
                    {t.hint}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>
    </div>
  );
}
