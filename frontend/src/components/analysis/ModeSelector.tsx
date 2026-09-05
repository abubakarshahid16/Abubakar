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
    <div className="grid gap-3 lg:grid-cols-[1.15fr_0.85fr]">
      <fieldset
        disabled={disabled}
        className="rounded-lg border border-ink-600 bg-ink-850 p-4 disabled:opacity-60"
      >
        <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-slateish-400">
          Analysis mode
        </legend>
        <div className="mt-2 grid gap-2 md:grid-cols-3 lg:grid-cols-1">
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
                    ? "border-signal-500 bg-signal-500/10 shadow-sm"
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
                <span className="min-w-0 space-y-1">
                  <span className="block text-sm font-semibold text-slateish-100">{m.label}</span>
                  <span id={descId} className="block text-xs leading-5 text-slateish-400">
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
        className="rounded-lg border border-ink-600 bg-ink-850 p-4 disabled:opacity-60"
      >
        <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-slateish-400">
          Optional sections
        </legend>
        {mode === "quote" && (
          <p className="mt-2 rounded border border-ink-700 bg-ink-900 px-2 py-1.5 text-xs text-slateish-500">
            Quote mode runs only cited document evidence. Switch to Focused or
            Comprehensive to run these optional sections.
          </p>
        )}
        <div className="mt-2 space-y-2">
          {TOGGLES.map((t) => {
            const inputId = `${id}-toggle-${t.key}`;
            const hintId = `${inputId}-hint`;
            return (
              <label
                key={t.key}
                htmlFor={inputId}
                className={[
                  "flex cursor-pointer items-start gap-3 rounded border px-3 py-2",
                  toggles[t.key]
                    ? "border-signal-500/60 bg-signal-500/10"
                    : "border-ink-700 hover:bg-ink-800",
                ].join(" ")}
              >
                <input
                  id={inputId}
                  type="checkbox"
                  checked={toggles[t.key]}
                  onChange={(e) => onToggle(t.key, e.target.checked)}
                  aria-describedby={hintId}
                  className="mt-0.5 h-4 w-4 shrink-0 accent-signal-500"
                />
                <span className="min-w-0 space-y-1">
                  <span className="block text-sm font-medium text-slateish-200">{t.label}</span>
                  <span id={hintId} className="block text-xs leading-5 text-slateish-500">
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
