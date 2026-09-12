/**
 * The document-type filter, and the one place its rules live.
 *
 * THREE RULES, EACH OF WHICH WAS A DEFECT SOMEWHERE ELSE FIRST.
 *
 * 1. THE TYPES COME FROM THE REGISTER, never from a constant in this file. A
 *    deployment whose register carries different types must not be shown a
 *    filter for types it does not have. `useVocabulary` reads
 *    `/api/classification/vocabulary`; until it answers, this control renders
 *    nothing rather than a plausible-looking guess.
 *
 * 2. NOTHING TICKED MEANS NO FILTER - the same thing the backend means by an
 *    empty array. It does not mean "match nothing". A reader who unticks
 *    everything gets the whole corpus back, which is the only behaviour that
 *    cannot silently hide a document from them.
 *
 * 3. THE SCOPE COUNT IS THE SERVER'S NUMBER. `documents_in_scope` comes back
 *    on `applied_scope` and is rendered verbatim. The frontend cannot compute
 *    it: the intersection with the caller's grants happens in the backend, and
 *    a locally computed "62 of 96" is wrong in exactly the direction that
 *    tells a reader a document is there when they cannot read it - or that it
 *    is missing when they can.
 *
 * A CLASSIFICATION FILTER IS NOT AN ACCESS CONTROL. It changes what is
 * searched, never what may be read. See `backend/app/classification.py`.
 */
import { useCallback, useEffect, useState } from "react";

import {
  classification,
  type AppliedScope,
  type ClassificationCoverage,
  type ClassificationScope,
  type ClassificationVocabulary,
} from "../../api/client";

/** The vocabulary plus per-type counts, or nothing. Deliberately NOT a
 *  Loadable: no screen should render an error state for this control - a
 *  filter that cannot load is a filter that is not offered, and the screen
 *  behind it works exactly as it did before classification existed. */
export interface TypeVocabulary {
  types: string[];
  /** `uploaded` per type, from `/classification/coverage`. One request for
   *  every type, rather than asking each document what it is. */
  countByType: Record<string, number>;
  unconfirmedByType: Record<string, number>;
  /** Documents this caller can read with no confirmed classification. */
  needsClassification: number;
  /** True when these counts cover the whole corpus (admin), false when they
   *  cover this caller's grants. A count with no stated boundary reads as
   *  total, so a screen using it must say which. */
  corpusWide: boolean;
  registerLoaded: boolean;
}

/**
 * Reads the vocabulary and the coverage counts once.
 *
 * Returns `null` while loading AND on failure, on purpose: see the comment on
 * `TypeVocabulary`. The two requests are independent, so a coverage failure
 * still yields a usable filter with no counts rather than no filter at all.
 */
export interface TypeVocabularyLoad {
  vocabulary: TypeVocabulary | null;
  /** True after the vocabulary request has answered, including failure. */
  settled: boolean;
}

export function useTypeVocabularyLoad(enabled = true): TypeVocabularyLoad {
  const [vocab, setVocab] = useState<ClassificationVocabulary | null>(null);
  const [coverage, setCoverage] = useState<ClassificationCoverage | null>(null);
  const [failed, setFailed] = useState(false);
  const [settled, setSettled] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void (async () => {
      const [v, c] = await Promise.all([
        classification.vocabulary(),
        classification.coverage(),
      ]);
      if (cancelled) return;
      if (v.ok) setVocab(v.data);
      else setFailed(true);
      if (c.ok) setCoverage(c.data);
      setSettled(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  if (!enabled) return { vocabulary: null, settled: true };

  // BOTH CONDITIONS ARE LOAD-BEARING. `!vocab` is "the answer has not
  // arrived"; the Array check is "the answer arrived malformed". Returning a
  // TypeVocabulary whose `types` is not an array satisfies the type system and
  // throws in every consumer that reads `.length` - which is exactly what
  // happened. The client now shape-checks this route as well; this stays
  // because the hook is exported and must be safe on its own.
  if (failed || !vocab || !Array.isArray(vocab.types)) {
    return { vocabulary: null, settled };
  }

  const countByType: Record<string, number> = {};
  const unconfirmedByType: Record<string, number> = {};
  for (const row of coverage?.by_type ?? []) {
    countByType[row.type] = row.uploaded;
    unconfirmedByType[row.type] = row.unconfirmed;
  }
  return {
    settled,
    vocabulary: {
      types: vocab.types,
      countByType,
      unconfirmedByType,
      needsClassification: vocab.needs_classification,
      corpusWide: coverage?.corpus_wide ?? false,
      registerLoaded: coverage?.register_loaded ?? false,
    },
  };
}

export function useTypeVocabulary(enabled = true): TypeVocabulary | null {
  return useTypeVocabularyLoad(enabled).vocabulary;
}

/** Selected types, and the scope object to send. Held by the screen so that
 *  one screen's choice never leaks into another's. */
export function useTypeScope() {
  const [selected, setSelected] = useState<string[]>([]);

  const toggle = useCallback((type: string) => {
    setSelected((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type],
    );
  }, []);

  const clear = useCallback(() => setSelected([]), []);

  /** `null` when nothing is ticked, so callers send no `scope` key at all and
   *  the route behaves byte for byte as it did before this feature. */
  const scope: ClassificationScope | null =
    selected.length > 0 ? { types: selected } : null;

  /** The repeatable query params `/api/search` wants - that route is a GET
   *  and takes `?types=a&types=b`, not a JSON object. */
  const searchParams = selected.map((t) => ["types", t] as const);

  return { selected, toggle, clear, scope, searchParams, filtering: selected.length > 0 };
}

export function TypeFilter({
  vocabulary,
  selected,
  onToggle,
  onClear,
  applied,
  label = "Search in",
  layout = "row",
}: {
  vocabulary: TypeVocabulary | null;
  selected: string[];
  onToggle: (type: string) => void;
  onClear?: () => void;
  /** The server's echo from the last run. Absent before the first run, which
   *  is why the count line is absent too rather than showing a guess. */
  applied?: AppliedScope | null;
  label?: string;
  layout?: "row" | "column";
}) {
  // RULE 1: no vocabulary, no control. Not a hardcoded fallback.
  if (!vocabulary || vocabulary.types.length === 0) return null;

  return (
    <div
      className={
        layout === "row"
          ? "flex flex-wrap items-center gap-2"
          : "flex flex-col gap-1.5"
      }
    >
      <span className="mr-1 text-[11px] font-semibold uppercase tracking-wide text-slateish-400">
        {label}
      </span>
      {vocabulary.types.map((type) => {
        const on = selected.includes(type);
        const count = vocabulary.countByType[type];
        return (
          <button
            key={type}
            type="button"
            role="checkbox"
            aria-checked={on}
            onClick={() => onToggle(type)}
            className={[
              "inline-flex items-center gap-2 rounded border px-2.5 py-1 text-[13px] transition-colors",
              layout === "column" ? "justify-start" : "",
              on
                ? "border-signal-500/40 bg-signal-500/10 text-signal-400"
                : "border-ink-600 bg-ink-800 text-slateish-300 hover:bg-ink-700",
            ].join(" ")}
          >
            <span
              aria-hidden
              className={[
                "h-3 w-3 shrink-0 rounded-sm border",
                on ? "border-signal-400 bg-signal-400" : "border-slateish-500",
              ].join(" ")}
            />
            {type}
            {/* A COUNT ONLY WHEN COVERAGE ANSWERED. Rendering 0 for "we do not
                know" reads as "there are none of these", which is a different
                claim and sometimes a false one. */}
            {count != null && (
              <span className="font-mono text-[11px] opacity-75">{count}</span>
            )}
          </button>
        );
      })}

      {onClear && selected.length > 0 && (
        <button
          type="button"
          onClick={onClear}
          className="rounded border border-ink-600 px-2 py-1 text-[11px] text-slateish-400 hover:text-slateish-200"
        >
          Clear
        </button>
      )}

      {/* RULE 3: the server's number, or no number. */}
      {applied?.applied && (
        <span className="ml-auto font-mono text-[11px] tabular-nums text-slateish-400">
          {applied.documents_in_scope} document
          {applied.documents_in_scope === 1 ? "" : "s"} in scope
        </span>
      )}
    </div>
  );
}

/** The sentence a screen shows when a filter is on but the last run predates
 *  it, so no `applied_scope` exists yet. Kept here so every screen says the
 *  same thing. */
export function pendingFilterNotice(selected: string[]): string | null {
  if (selected.length === 0) return null;
  return `Filter set to ${selected.join(", ")}. Run again to apply it.`;
}
