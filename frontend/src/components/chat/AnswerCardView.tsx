import { useEffect } from "react";
import { Citation, Highlighted, PassageLocation } from "./EvidencePanel";
import { ProvenanceMark, isRecognised, provenanceDetail } from "./Provenance";
import { ComparisonScopeNotice as ComparisonScopeNoticeView } from "./ComparisonScopeNotice";
import { type AnswerView, type UpgradeFailure, asksForComparison, documentsAnsweredFrom, sourcesOf, asSentence, formatDuration, Chip, ChipMark, CitedProse, Label, ReportAction, UpgradeFailureNotice } from "./AnswerCardContent";
import { CorpusPart, CountsBoundedNote, GuidanceAnswer, MetadataAnswer } from "./AnswerNonDocument";
import { InsufficientAnswer } from "./AnswerInsufficient";
import { ScopeNotice, VerdictNotice, WithheldNotice } from "./AnswerVerdict";
import type { AnswerPassage } from "../../types/api";

function RetrievalDetails({ passage }: { passage: AnswerPassage }) {
  return passage.score == null ? null : (
    <details className="mt-1 ms-7 rounded-[var(--radius-xs)] border border-ink-700 px-2 py-1 text-xs text-slateish-500">
      <summary className="cursor-pointer">Retrieval details</summary>
      <p className="mt-1">This passage’s rerank score was {passage.score.toFixed(3)}. It is a ranking diagnostic, not a quality verdict.</p>
    </details>
  );
}

/**
 * One answer, and - when the question asked about the LIBRARY as well as its
 * content - the library's half above it, clearly separated.
 *
 * "How many standards cover hydrotesting" is two questions. The library's
 * count comes from the database ("272 company standards are loaded and
 * readable by you"); what covers hydrotesting comes from retrieval. They are
 * rendered as two labelled parts, never one sentence, because blending them is
 * how "there are 12 distinct standards" happened: a count of three retrieved
 * passages, read as a count of the library.
 *
 * No hooks here, deliberately: the body keeps every hook it had, in the order
 * it had them, so wrapping it changes nothing about how it renders.
 */
export function AnswerCard(props: Parameters<typeof AnswerCardBody>[0]) {
  const { view } = props;
  if (view.withheld) return <WithheldNotice text={view.answer} />;
  const twoPart = view.corpus != null && view.answer_type !== "metadata";
  const bounded = (view.counts_bounded ?? 0) > 0;
  const verdict = view.answerability;
  const notices = (
    <>
      {/* A refusal card already says it cannot determine this; saying it twice is noise. */}
      {verdict && view.answer_type !== "insufficient_evidence" && <VerdictNotice verdict={verdict.verdict} reason={verdict.reason} evidence={verdict.evidence} />}
      <ScopeNotice understanding={view.understanding} ambiguity={view.scope_ambiguity} />
    </>
  );
  if (!twoPart && !bounded) {
    return (
      <div className="space-y-3">
        {notices}
        <AnswerCardBody {...props} />
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {notices}
      {twoPart && view.corpus && <CorpusPart fact={view.corpus} />}
      {twoPart && (
        <p className="text-xs uppercase tracking-wide text-slateish-500">
          From the documents
        </p>
      )}
      <AnswerCardBody {...props} />
      {bounded && <CountsBoundedNote count={view.counts_bounded ?? 0} />}
    </div>
  );
}

function AnswerCardBody({
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
  upgradeFailure,
  question,
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
  /** A Tier 2 upgrade OF THIS ANSWER that produced nothing showable. Scoped
   *  to the control that started it rather than shown as a second answer. */
  upgradeFailure?: UpgradeFailure | null;
  /** The reader's question, as they typed it. Used for one thing only: to say
   *  so when a question that asks across documents is answered from one. */
  question?: string | null;
}) {
  const sources = sourcesOf(view);
  // Counted from this answer's own evidence. The notice renders only at
  // exactly one document — at zero there is nothing that could be counted
  // honestly, and silence is correct.
  const answeredFrom = documentsAnsweredFrom(view);
  const comparisonFromOneDocument =
    asksForComparison(question) && answeredFrom.length === 1;

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
    return <GuidanceAnswer view={view} />;
  }

  if (view.answer_type === "metadata") {
    return <MetadataAnswer view={view} />;
  }

  // ---------------------------------------------------------- no answer
  if (view.answer_type === "insufficient_evidence") {
    return <InsufficientAnswer view={view} onSelectSource={onSelectSource} />;
  }

  if (view.answer_type === "model_unavailable") {
    return (
      <div role="alert" className="surface-card rounded-[var(--radius-md)] border border-warn-500/50 bg-warn-500/10 p-4">
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
      <div className="surface-card rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4">
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
            <span className="font-mono text-xs text-slateish-500">
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
            "mt-2 border-l-2 border-signal-500/60 bg-ink-900 py-2.5 ps-4 pe-3 text-slateish-100",
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
          <>
            <div className="mt-2.5 flex flex-wrap items-baseline gap-2 border-t border-ink-700/60 pt-2">
              <Chip n={1} active={activeSource === 0} onClick={() => onSelectSource(0)} />
              <Citation passage={p} />
            </div>
            <RetrievalDetails passage={p} />
          </>
        )}

        {comparisonFromOneDocument && (
          <ComparisonScopeNoticeView documents={answeredFrom.length} />
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
                    className="flex w-full items-center gap-2 rounded-[var(--radius-sm)] border border-ink-700 px-2 py-1.5 text-left hover:bg-ink-800"
                  >
                    <ChipMark n={i + 2} active={activeSource === i + 1} />
                    <PassageLocation passage={s} />
                  </button>
                  <RetrievalDetails passage={s} />
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
              className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1.5 text-sm text-slateish-200 hover:bg-ink-700 disabled:opacity-60"
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
          <p className="mt-2 rounded-[var(--radius-sm)] border border-warn-500/40 bg-warn-500/[0.08] px-2.5 py-1.5 text-xs text-warn-500">
            This report will freeze the quoted passage above as the answer.
            Other matched passages stay in the evidence section, but they are
            not merged into the quoted answer.
          </p>
        )}

        {(onExplain || upgradeFailure) && (
          <div className="mt-3 border-t border-ink-700 pt-3">
            {onExplain && (
              <>
                <button
                  type="button"
                  onClick={onExplain}
                  disabled={explaining}
                  className="rounded-[var(--radius-sm)] border border-info-500/50 px-3 py-1.5 text-sm text-info-500 hover:bg-info-500/10 disabled:opacity-60"
                >
                  {explaining
                    ? `Explaining… ${explainSeconds ?? 0}s`
                    : upgradeFailure
                      ? "Try the plain-language version again"
                      : "Explain in plain language"}
                </button>
                <p className="mt-1.5 text-xs text-slateish-500">
                  {explaining
                    ? "Generation is not streamed. It typically finishes around 50 seconds on this machine."
                    : "Runs the local model over these passages. Takes about 50 seconds on this hardware — the quotation above is already the answer."}
                </p>
              </>
            )}
            {/* Rendered whether or not the button is on offer: a failed
                upgrade that leaves no trace is indistinguishable from a
                button that did nothing. */}
            {upgradeFailure && !explaining && (
              <UpgradeFailureNotice failure={upgradeFailure} />
            )}
          </div>
        )}
      </div>
    );
  }

  // ------------------------------------------------------ tier 2: generated
  return (
    <div className="surface-card accent-edge rounded-[var(--radius-md)] border border-info-500/30 bg-info-500/[0.05] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label tone="generated">
          Written by the model{view.model ? ` · ${view.model}` : ""} — not the document's words
        </Label>
        {view.seconds != null && (
          <span className="font-mono text-xs text-slateish-500">
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
        <p className="mt-2 rounded-[var(--radius-sm)] border border-warn-500/40 bg-warn-500/[0.08] px-2.5 py-1.5 text-xs text-warn-500">
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
      {comparisonFromOneDocument && (
        <ComparisonScopeNoticeView documents={answeredFrom.length} />
      )}

      {view.evidence_removed.length > 0 && (
        <div className="mt-2 rounded-[var(--radius-sm)] border border-warn-500/40 bg-warn-500/[0.08] px-2.5 py-1.5 text-xs text-warn-500">
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
                className="flex w-full items-center gap-2 rounded-[var(--radius-sm)] border border-ink-700 px-2 py-1.5 text-left hover:bg-ink-800"
              >
                <ChipMark n={i + 1} active={activeSource === i} />
                <PassageLocation passage={s} />
              </button>
              <RetrievalDetails passage={s} />
            </li>
          ))}
        </ul>
      )}

      {view.rejected_citations.length > 0 && (
        <p className="mt-3 rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 px-2 py-1.5 text-xs text-slateish-300">
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
