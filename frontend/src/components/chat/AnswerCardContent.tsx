import type { AnswerPassage, CorpusFact, EvidenceRemoved, AnswerType, Message } from "../../types/api";
import { PassageLocation } from "./EvidencePanel";
/** The parts of an answer this card renders, from a live reply or a replay. */
export interface AnswerView {
  answer_type: AnswerType;
  answer: string | null;
  reason: string | null;
  passage: AnswerPassage | null;
  supporting: AnswerPassage[];
  passages: AnswerPassage[];
  cited: number[];
  rejected_citations: number[];
  model: string | null;
  /** generation hit the output-token cap; see contracts/types.ts */
  truncated: boolean;
  /** sources trimmed or dropped so the evidence would fit the context window */
  evidence_removed: EvidenceRemoved[];
  seconds: number | null;
  examples: string[];
  /** The library's answer, from the database. See contracts/types.ts. */
  corpus?: CorpusFact | null;
  /** Counts of documents in generated prose re-bounded to what was retrieved. */
  counts_bounded?: number;
}

/**
 * A Tier 2 upgrade of an extract that produced nothing showable.
 *
 * THE DEFECT THIS EXISTS FOR. Pressing "Explain in plain language" persists a
 * SECOND assistant turn with `explains_id` set. When the model cited no
 * supplied source, `answer.py` correctly refuses it — `answer_type` comes back
 * `insufficient_evidence`. The transcript then rendered that refusal as a peer
 * of the extract it was an upgrade of, so the screen said "here is your
 * answer, quoted from page 17" and "The documents do not answer this" at the
 * same time, stacked. Both statements were about the SAME question, and one of
 * them was false.
 *
 * The refusal itself is right and is not weakened here: the uncited prose is
 * still never shown. What changes is scope — a failed upgrade is reported on
 * the control that started it, as a failed upgrade, and the page-level "the
 * documents do not answer this" is reserved for a question the documents
 * genuinely did not answer.
 */
export interface UpgradeFailure {
  /** `insufficient_evidence` (refused) or `model_unavailable` (never ran). */
  answer_type: AnswerType;
  reason: string | null;
  /** What the model was given, so the reader can still judge for themselves. */
  considered: AnswerPassage[];
  activeSource: number | null;
  onSelectSource: (i: number) => void;
}

export function viewFromMessage(m: Message): AnswerView {
  const p = m.payload ?? {};
  return {
    answer_type: m.answer_type ?? "insufficient_evidence",
    answer: m.text,
    reason: m.reason,
    passage: p.passage ?? null,
    supporting: p.supporting ?? [],
    passages: p.passages ?? [],
    cited: p.cited ?? [],
    rejected_citations: p.rejected_citations ?? [],
    model: p.model ?? null,
    truncated: p.truncated ?? false,
    evidence_removed: p.evidence_removed ?? [],
    seconds: p.seconds ?? null,
    examples: p.examples ?? [],
    corpus: p.corpus ?? null,
    counts_bounded: p.counts_bounded ?? 0,
  };
}

/** The sources this answer is grounded in, in citation order. */
export function sourcesOf(v: AnswerView): AnswerPassage[] {
  // Guidance was never a document query, so it has nothing to cite. Showing
  // "what was considered" for a greeting would invent a search that never ran.
  if (v.answer_type === "guidance") return [];
  if (v.answer_type === "extract" && v.passage) return [v.passage, ...v.supporting];
  return v.passages;
}

/**
 * Does the question ask for a COMPARISON across documents?
 *
 * Deliberately a small, explicit list of phrasings rather than a heuristic.
 * A false positive puts a scope notice on an answer that never needed one,
 * and a notice the reader learns to ignore is worse than no notice: the cost
 * of missing an unusual phrasing is that the answer reads as it did before,
 * which is merely the old behaviour, while the cost of firing on an ordinary
 * question is a screen that contradicts itself.
 *
 * Pure and exported so it can be tested on its own phrasings.
 */
const COMPARISON_SIGNALS: readonly RegExp[] = [
  /\bcompar(?:e|es|ed|ing|ison|isons)\b/,
  /\bcontrast(?:s|ed|ing)?\b/,
  /\bdifferences?\s+between\b/,
  /\bversus\b/,
  /\bvs\.?\b/,
  /\bacross\s+all\b/,
  /\bbetween\s+all\b/,
  /\bfrom\s+all\s+(?:the\s+|of\s+the\s+)?documents\b/,
];

export function asksForComparison(question: string | null | undefined): boolean {
  if (typeof question !== "string") return false;
  const q = question.toLowerCase();
  return COMPARISON_SIGNALS.some((re) => re.test(q));
}

/**
 * The distinct documents THIS ANSWER IS DRAWN FROM, counted from the evidence
 * the message actually carries — never guessed, never assumed to be one.
 *
 * For an extract the answer IS the quoted passage: the other matched passages
 * are listed beside it but, as the report warning on this card already says,
 * they are "not merged into the quoted answer". For generated prose the
 * answer is drawn from what it CITED; when nothing resolved as cited the
 * whole supplied set is counted instead, which can only over-count and so can
 * only suppress the notice — the safe direction, because a notice that fires
 * wrongly is a false statement and a notice that stays silent is the state
 * this screen was already in.
 *
 * A refusal, an absent model and guidance draw on nothing, and return [].
 */
export function documentsAnsweredFrom(view: AnswerView): string[] {
  const ids: string[] = [];
  const add = (p: AnswerPassage | null | undefined) => {
    const id = p?.document_id;
    if (typeof id !== "string" || id === "") return;
    if (!ids.includes(id)) ids.push(id);
  };
  if (view.answer_type === "extract") {
    add(view.passage);
    return ids;
  }
  if (view.answer_type === "generated") {
    const cited = view.cited
      .map((n) => view.passages[n - 1])
      .filter((p): p is AnswerPassage => Boolean(p));
    for (const p of cited.length > 0 ? cited : view.passages) add(p);
    return ids;
  }
  return ids;
}

/**
 * What the reader asked for, and what this answer is. Rendered only when both
 * are known and they disagree: the question asks across documents and the
 * answer came from one. It states the count it was given rather than a fixed
 * word, so it cannot outlive the evidence it describes.
 *
 * Styled as the card's existing advisory notice — the amber meta band already
 * used for a truncated answer and for dropped evidence — so it is legible as
 * a statement ABOUT the answer and can never be mistaken for the document's
 * own words, which are serif on a quote rule.
 *
 * It promises nothing. Comparison across the corpus is not offered here, and
 * naming a screen that might do it would be a claim this component cannot
 * verify.
 */
/** Two sentences joined without punctuation read as one broken sentence:
 *  "…were not a credible match Nothing was made up to fill the gap." */
export function asSentence(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return "";
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

/**
 * Milliseconds are a developer's unit. "2755 ms" is a measurement; "2.8s" is
 * how long the reader waited.
 */
export function formatDuration(seconds: number): string {
  if (seconds < 10) return `${seconds.toFixed(1)}s`;
  return `${Math.round(seconds)}s`;
}

export function chipClass(active: boolean): string {
  return [
    "mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-[var(--radius-xs)] px-1 align-baseline font-mono text-xs leading-none",
    active
      ? "bg-signal-500/30 text-signal-300 ring-1 ring-signal-500/60"
      : "bg-ink-700 text-slateish-300 hover:bg-ink-600",
  ].join(" ");
}

/**
 * The chip as a plain mark, for when it sits INSIDE a row that is already a
 * button. It used to be a real button in both places, which put a <button>
 * inside a <button>: invalid HTML that React reported on every answer, and
 * that leaves the inner control unreachable by keyboard and ambiguous to a
 * screen reader. The row owns the action; here the number is only a label for
 * it, so it is announced as part of the row rather than as a second target.
 */
export function ChipMark({ n, active }: { n: number; active: boolean }) {
  return (
    <span aria-hidden="true" className={chipClass(active)}>
      {n}
    </span>
  );
}

export function Chip({
  n,
  onClick,
  active,
}: {
  n: number;
  onClick: () => void;
  active: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`Show source ${n}`}
      className={chipClass(active)}
    >
      {n}
    </button>
  );
}

/** Renders generated prose with `[S1]` turned into a clickable chip. */
export function CitedProse({
  text,
  onCite,
  activeSource,
}: {
  text: string;
  onCite: (index: number) => void;
  activeSource: number | null;
}) {
  const parts: React.ReactNode[] = [];
  const citation = /\[S(\d+)\]/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = citation.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const n = Number(match[1]);
    parts.push(
      <Chip
        key={`${match.index}-${n}`}
        n={n}
        active={activeSource === n - 1}
        onClick={() => onCite(n - 1)}
      />,
    );
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}

export function Label({
  tone,
  children,
}: {
  tone: "quote" | "generated" | "ocr";
  children: React.ReactNode;
}) {
  return (
    <p
      className={[
        "text-xs font-semibold uppercase tracking-wider",
        tone === "quote"
          ? "text-signal-400"
          : tone === "generated"
            ? "text-info-500"
            : "text-warn-500",
      ].join(" ")}
    >
      {children}
    </p>
  );
}

export function ReportAction({
  onSaveReport,
  savingReport,
  reportNotice,
  note,
}: {
  onSaveReport?: () => void;
  savingReport?: boolean;
  reportNotice?: string | null;
  note: string;
}) {
  if (!onSaveReport) return null;
  return (
    <div className="mt-3 border-t border-ink-700 pt-3">
      <button
        type="button"
        onClick={onSaveReport}
        disabled={savingReport}
        className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1.5 text-sm text-slateish-200 hover:bg-ink-700 disabled:opacity-60"
      >
        {savingReport ? "Saving..." : "Save as report"}
      </button>
      <p className="mt-1.5 text-xs text-slateish-500">{note}</p>
      {reportNotice && (
        <p className="mt-1.5 text-xs text-warn-500" role="status">
          {reportNotice}
        </p>
      )}
    </div>
  );
}

/**
 * The failed upgrade, reported where it was asked for.
 *
 * Two outcomes, two appearances, deliberately: the model being absent is a
 * fact about this machine and the reader fixes it with a command, while a
 * refusal is a fact about what the model wrote and there is nothing to fix.
 * Rendering them the same would be the "backend offline looks like request
 * failed" defect, one level down.
 *
 * Not exported: `provenance.enumerated.test.tsx` walks the source for exported
 * components taking an AnswerPassage, and the passages here are rendered by
 * `PassageLocation`, which already carries the OCR mark and is checked there.
 */
export function UpgradeFailureNotice({ failure }: { failure: UpgradeFailure }) {
  if (failure.answer_type === "model_unavailable") {
    return (
      <div
        role="alert"
        className="mt-2 rounded-[var(--radius-sm)] border border-warn-500/50 bg-warn-500/10 px-2.5 py-2"
      >
        <p className="text-xs font-semibold text-warn-500">
          The plain-language version could not be produced — the local answer
          model is not running
        </p>
        <p className="mt-1 text-xs text-slateish-300">
          {asSentence(failure.reason ?? "Ollama could not be reached")} This is
          the machine, not your question. The quoted answer above is unaffected
          — only the plain-language version needs the model.
        </p>
        <pre className="mt-1.5 overflow-x-auto rounded bg-ink-900 p-2 font-mono text-xs text-slateish-300">
ollama serve
        </pre>
      </div>
    );
  }

  return (
    <div
      role="status"
      className="mt-2 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-2.5 py-2"
    >
      <p className="text-xs font-semibold text-slateish-200">
        The plain-language version could not be produced
      </p>
      <p className="mt-1 text-xs text-slateish-400">
        {asSentence(
          failure.reason ?? "the model produced nothing that could be checked",
        )}{" "}
        Nothing is shown rather than prose you could not check against a source.
        The quoted answer above is unaffected and still stands.
      </p>
      {failure.considered.length > 0 && (
        <div className="mt-2">
          <p className="text-xs uppercase tracking-wide text-slateish-500">
            What the model was given, so you can judge for yourself
          </p>
          <ul className="mt-1.5 space-y-1">
            {failure.considered.map((p, i) => (
              <li key={p.chunk_id}>
                <button
                  type="button"
                  onClick={() => failure.onSelectSource(i)}
                  className={[
                    "w-full rounded-[var(--radius-sm)] border px-2 py-1.5 text-left hover:bg-ink-800",
                    failure.activeSource === i
                      ? "border-signal-500/60 bg-ink-800"
                      : "border-ink-700",
                  ].join(" ")}
                >
                  <PassageLocation passage={p} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}


export { AnswerCard } from "./AnswerCardView";
