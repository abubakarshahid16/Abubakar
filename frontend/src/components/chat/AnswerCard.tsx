/**
 * One assistant turn.
 *
 * The single most important thing this component does is make a QUOTATION and
 * GENERATED PROSE impossible to confuse. Tier 1 is the document's own words,
 * set in serif on a quote rule, labelled verbatim. Tier 2 is the model's
 * words, set in sans on an amber rule, labelled as written by the model. An
 * engineer must be able to tell at a glance which one they are reading,
 * because only one of them is the specification.
 */
import { useEffect } from "react";

import type { AnswerPassage, EvidenceRemoved, AnswerType, Message } from "../../types/api";
import { Citation, Highlighted, PassageLocation } from "./EvidencePanel";
import { ProvenanceMark, isRecognised, provenanceDetail } from "./Provenance";

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

/** Two sentences joined without punctuation read as one broken sentence:
 *  "…were not a credible match Nothing was made up to fill the gap." */
function asSentence(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return "";
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

/**
 * Milliseconds are a developer's unit. "2755 ms" is a measurement; "2.8s" is
 * how long the reader waited.
 */
function formatDuration(seconds: number): string {
  if (seconds < 10) return `${seconds.toFixed(1)}s`;
  return `${Math.round(seconds)}s`;
}

function chipClass(active: boolean): string {
  return [
    "mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded px-1 align-baseline font-mono text-[11px] leading-none",
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
function ChipMark({ n, active }: { n: number; active: boolean }) {
  return (
    <span aria-hidden="true" className={chipClass(active)}>
      {n}
    </span>
  );
}

function Chip({
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

const CITATION = /\[S(\d+)\]/g;

/** Renders generated prose with `[S1]` turned into a clickable chip. */
function CitedProse({
  text,
  onCite,
  activeSource,
}: {
  text: string;
  onCite: (index: number) => void;
  activeSource: number | null;
}) {
  const parts: React.ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  CITATION.lastIndex = 0;
  while ((match = CITATION.exec(text)) !== null) {
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

function Label({
  tone,
  children,
}: {
  tone: "quote" | "generated" | "ocr";
  children: React.ReactNode;
}) {
  return (
    <p
      className={[
        "text-[11px] font-semibold uppercase tracking-wider",
        tone === "quote" ? "text-signal-400" : "text-warn-500",
      ].join(" ")}
    >
      {children}
    </p>
  );
}

function ReportAction({
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
        className="rounded border border-ink-600 px-3 py-1.5 text-sm text-slateish-200 hover:bg-ink-700 disabled:opacity-60"
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

export function AnswerCard({
  view,
  onSelectSource,
  activeSource,
  onExplain,
  explaining,
  onSaveReport,
  savingReport,
  reportNotice,
  explainSeconds,
  explainsEarlier,
}: {
  view: AnswerView;
  onSelectSource: (i: number) => void;
  activeSource: number | null;
  onExplain?: () => void;
  explaining?: boolean;
  /** Freeze this answer as a PDF. Absent when the message cannot become one. */
  onSaveReport?: () => void;
  savingReport?: boolean;
  /** What the last attempt did, in the reader's words. A refusal from the
   *  route (a message with no citations) is shown here rather than swallowed:
   *  a button that does nothing is the defect this replaces. */
  reportNotice?: string | null;
  explainSeconds?: number;
  explainsEarlier?: boolean;
}) {
  const sources = sourcesOf(view);

  // For a RECOGNISED passage the page image is not a verification the reader
  // may want - it is the only evidence the answer is real, so it is shown
  // rather than offered. A label that says "check it against the page" while
  // the page sits behind a click is a label that expects to be ignored.
  // Extracted text keeps the collapsed default. See ADR-0006 s1C.
  const autoExpand =
    view.answer_type === "extract" && view.passage?.text_source === "recognised";
  useEffect(() => {
    if (autoExpand && activeSource === null) onSelectSource(0);
    // onSelectSource identity changes per render in the parent; depending on
    // it would re-fire the effect forever.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoExpand, activeSource]);

  // ----------------------------------------------------------- guidance
  // Not a document question, so this is not a refusal and carries no
  // evidence. Styled as a plain note rather than an answer card, so it does
  // not read as something the documents said.
  if (view.answer_type === "guidance") {
    // The backend appends its examples to the reply text for callers that
    // only read `answer`. Here they are rendered as a list, so the text is
    // split back apart on the heading rather than shown twice.
    const [lead, ...rest] = (view.answer ?? "").split("Try one of these:");
    return (
      <div className="rounded-lg border border-ink-700 bg-ink-850/60 p-4">
        <p className="text-sm text-slateish-300">{lead.trim()}</p>
        {view.examples.length > 0 && (
          <>
            <p className="mt-3 text-xs uppercase tracking-wide text-slateish-500">
              Questions your documents can answer
            </p>
            <ul className="mt-1.5 space-y-1">
              {view.examples.map((q) => (
                <li key={q} className="text-sm text-slateish-400">
                  <span aria-hidden className="mr-2 text-slateish-500">
                    &bull;
                  </span>
                  {q}
                </li>
              ))}
            </ul>
          </>
        )}
        {view.examples.length === 0 && rest.length > 0 && (
          <p className="mt-2 whitespace-pre-wrap text-sm text-slateish-400">{rest.join("")}</p>
        )}
      </div>
    );
  }

  // ---------------------------------------------------------- no answer
  if (view.answer_type === "insufficient_evidence") {
    return (
      <div className="rounded-lg border border-ink-600 bg-ink-850 p-4">
        <p className="text-sm font-semibold text-slateish-200">
          The documents do not answer this
        </p>
        <p className="mt-1 text-sm text-slateish-400">
          {asSentence(view.reason ?? "Nothing credible was retrieved")} Nothing
          was made up to fill the gap.
        </p>
        {sources.length > 0 && (
          <div className="mt-3">
            <p className="text-xs uppercase tracking-wide text-slateish-500">
              What was considered, so you can judge for yourself
            </p>
            <ul className="mt-1.5 space-y-1">
              {sources.map((p, i) => (
                <li key={p.chunk_id}>
                  <button
                    type="button"
                    onClick={() => onSelectSource(i)}
                    className="w-full rounded border border-ink-700 px-2 py-1.5 text-left hover:bg-ink-800"
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

  if (view.answer_type === "model_unavailable") {
    return (
      <div role="alert" className="rounded-lg border border-warn-500/50 bg-warn-500/10 p-4">
        <p className="text-sm font-semibold text-warn-500">
          The local answer model is not running
        </p>
        <p className="mt-1 text-sm text-slateish-300">
          {asSentence(view.reason ?? "Ollama could not be reached")} The quoted
          answer above is unaffected — only the explanation needs the model.
        </p>
        <pre className="mt-2 overflow-x-auto rounded bg-ink-900 p-2 font-mono text-xs text-slateish-300">
ollama serve
        </pre>
      </div>
    );
  }

  // ------------------------------------------------------ tier 1: quotation
  if (view.answer_type === "extract") {
    const p = view.passage;
    // POSITIVE PREDICATE. The verbatim claim is asserted only when provenance
    // says "extracted" - never as the fallback for everything that is not
    // recognised. `viewFromMessage` builds from `m.payload ?? {}`, so a
    // message whose payload is missing or trimmed yields passage: null, and
    // the old `recognised && p ? OCR : VERBATIM` branch rendered that under
    // the strongest claim the product can make, with no passage, no citation
    // and no evidence panel behind it. Absence of provenance is not evidence
    // of provenance.
    const recognised = isRecognised(p);
    const extracted = p?.text_source === "extracted";
    return (
      <div className="rounded-lg border border-ink-600 bg-ink-850 p-4">
        {/* THE LABEL IS THE CLAIM. "Quoted verbatim" is literally true only
            when the characters came out of the PDF's own text layer. OCR read
            them off a page image - a guess about pixels, measured producing
            `Pyblish` for "Publish" and `≦` where a specification says `≤` -
            and putting that under a verbatim label is the single outcome this
            feature must not produce. Branch on provenance, never on anything
            else. See ADR-0006. */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          {recognised && p ? (
            <ProvenanceMark passage={p} variant="full" />
          ) : extracted ? (
            <Label tone="quote">Quoted verbatim from the document</Label>
          ) : (
            <Label tone="ocr">Provenance unknown — source not attached</Label>
          )}
          {view.seconds != null && (
            <span className="font-mono text-[11px] text-slateish-500">
              {formatDuration(view.seconds)}
              {" · "}
              {p
                ? provenanceDetail(p)
                : "this answer arrived without its source passage — it cannot be checked"}
            </span>
          )}
        </div>

        <blockquote
          className={[
            "mt-2 border-l-2 border-signal-500/60 bg-ink-900 py-2.5 pl-4 pr-3 text-slateish-100",
            p?.kind === "table"
              ? "document-table"
              : "document-quote whitespace-pre-wrap text-[15px]",
          ].join(" ")}
        >
          {/* Marked only when the quotation IS the passage and the passage is
              prose. `answer` is documented as the passage text verbatim, but a
              mismatch would slice the wrong offsets into the wrong string, and
              a table's column pairing is positional so a span inside it means
              nothing. Both cases fall back to the plain text rather than
              risking a confidently wrong emphasis. */}
          {p && p.kind !== "table" && view.answer === p.text ? (
            <Highlighted passage={p} />
          ) : (
            view.answer
          )}
        </blockquote>

        {p && (
          <div className="mt-2.5 flex flex-wrap items-baseline gap-2 border-t border-ink-700/60 pt-2">
            <Chip n={1} active={activeSource === 0} onClick={() => onSelectSource(0)} />
            <Citation passage={p} />
          </div>
        )}

        {view.supporting.length > 0 && (
          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-slateish-400 hover:text-slateish-300">
              {view.supporting.length} other passage
              {view.supporting.length === 1 ? "" : "s"} matched
            </summary>
            <ul className="mt-1.5 space-y-1">
              {view.supporting.map((s, i) => (
                <li key={s.chunk_id}>
                  <button
                    type="button"
                    onClick={() => onSelectSource(i + 1)}
                    className="flex w-full items-center gap-2 rounded border border-ink-700 px-2 py-1.5 text-left hover:bg-ink-800"
                  >
                    <ChipMark n={i + 2} active={activeSource === i + 1} />
                    <PassageLocation passage={s} />
                  </button>
                </li>
              ))}
            </ul>
          </details>
        )}

        {onSaveReport && (
          <div className="mt-3 border-t border-ink-700 pt-3">
            <button
              type="button"
              onClick={onSaveReport}
              disabled={savingReport}
              className="rounded border border-ink-600 px-3 py-1.5 text-sm text-slateish-200 hover:bg-ink-700 disabled:opacity-60"
            >
              {savingReport ? "Saving…" : "Save as report"}
            </button>
            <p className="mt-1.5 text-xs text-slateish-500">
              Freezes this answer, its passages and the documents they came
              from into a PDF. The evidence is captured as it is now — later
              edits to those documents are reported, never silently used.
            </p>
            {reportNotice && (
              <p className="mt-1.5 text-xs text-warn-500" role="status">
                {reportNotice}
              </p>
            )}
          </div>
        )}

        {onSaveReport && view.supporting.length > 0 && (
          <p className="mt-2 rounded border border-warn-500/40 bg-warn-500/[0.08] px-2.5 py-1.5 text-xs text-warn-500">
            This report will freeze the quoted passage above as the answer.
            Other matched passages stay in the evidence section, but they are
            not merged into the quoted answer.
          </p>
        )}

        {onExplain && (
          <div className="mt-3 border-t border-ink-700 pt-3">
            <button
              type="button"
              onClick={onExplain}
              disabled={explaining}
              className="rounded border border-warn-500/50 px-3 py-1.5 text-sm text-warn-500 hover:bg-warn-500/10 disabled:opacity-60"
            >
              {explaining ? `Explaining… ${explainSeconds ?? 0}s` : "Explain in plain language"}
            </button>
            <p className="mt-1.5 text-xs text-slateish-500">
              {explaining
                ? "Generation is not streamed. It typically finishes around 50 seconds on this machine."
                : "Runs the local model over these passages. Takes about 50 seconds on this hardware — the quotation above is already the answer."}
            </p>
          </div>
        )}
      </div>
    );
  }

  // ------------------------------------------------------ tier 2: generated
  return (
    <div className="rounded-lg border border-warn-500/40 bg-warn-500/[0.06] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label tone="generated">
          Written by the model{view.model ? ` · ${view.model}` : ""} — not the document's words
        </Label>
        {view.seconds != null && (
          <span className="font-mono text-[11px] text-slateish-500">
            {formatDuration(view.seconds)}
          </span>
        )}
      </div>

      {explainsEarlier && (
        <p className="mt-1 text-xs text-slateish-500">
          An explanation of the quoted answer above. The quotation remains the
          authoritative text.
        </p>
      )}

      <p className="model-prose mt-2 text-[15px] text-slateish-200">
        <CitedProse
          text={view.answer ?? ""}
          onCite={onSelectSource}
          activeSource={activeSource}
        />
      </p>

      {/* An answer that simply stops reads as broken, whatever its citations
          say, and the reader cannot otherwise tell whether the model finished,
          ran out of budget, or crashed. Those are three different situations
          and only one of them is a defect. A half-written citation marker has
          already been removed server-side, because `[S2` with no closing
          bracket looks like a fault in the citation system rather than a
          length limit. */}
      {view.truncated && (
        <p className="mt-2 rounded border border-warn-500/40 bg-warn-500/[0.08] px-2.5 py-1.5 text-xs text-warn-500">
          This answer reached its length limit and stops early — the model had
          more to say. The passages below are complete; open them for the rest.
        </p>
      )}

      {/* The same gap at the other end of the pipe. Output truncation has been
          shown to the reader since the token cap was raised; INPUT truncation
          was invisible, and it is the more serious of the two - the model
          answers from evidence it was never given, and cites sources it never
          saw.

          A numeric table costs about one token per character, so three table
          passages need ~3,645 tokens against a 1,536-token window. Each
          removal is named, because "some evidence was dropped" is not
          something a reader can act on and "page 598 was dropped" is. */}
      {view.evidence_removed.length > 0 && (
        <div className="mt-2 rounded border border-warn-500/40 bg-warn-500/[0.08] px-2.5 py-1.5 text-xs text-warn-500">
          <p>
            {view.evidence_removed.length === 1
              ? "One source did not fit the model's context window."
              : `${view.evidence_removed.length} sources did not fit the model's context window.`}{" "}
            This answer was written without {view.evidence_removed.length === 1 ? "it" : "them"}.
          </p>
          <ul className="mt-1 space-y-0.5">
            {view.evidence_removed.map((e) => (
              <li key={`${e.index}-${e.filename ?? ""}`}>
                <span className="font-mono">{e.filename ?? "a source"}</span>
                {e.page_start !== null && <> p{e.page_start}</>}
                {" — "}
                {e.action === "dropped"
                  ? "not used at all"
                  : `shortened, ${e.characters_dropped.toLocaleString()} characters left out`}
              </li>
            ))}
          </ul>
        </div>
      )}

      {sources.length > 0 && (
        <ul className="mt-3 space-y-1">
          {sources.map((s, i) => (
            <li key={s.chunk_id}>
              <button
                type="button"
                onClick={() => onSelectSource(i)}
                className="flex w-full items-center gap-2 rounded border border-ink-700 px-2 py-1.5 text-left hover:bg-ink-800"
              >
                <ChipMark n={i + 1} active={activeSource === i} />
                <PassageLocation passage={s} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {view.rejected_citations.length > 0 && (
        <p className="mt-3 rounded border border-danger-500/40 bg-danger-500/10 px-2 py-1.5 text-xs text-slateish-300">
          The model cited {view.rejected_citations.map((n) => `[S${n}]`).join(", ")}, which
          {view.rejected_citations.length === 1 ? " was" : " were"} not among the sources
          supplied. Removed from the answer above rather than shown to you.
        </p>
      )}

      <ReportAction
        onSaveReport={onSaveReport}
        savingReport={savingReport}
        reportNotice={reportNotice}
        note="Freezes this generated explanation and its cited passages into a PDF. Use this when the explanation combines multiple cited sources that the quoted extract did not merge."
      />
    </div>
  );
}
