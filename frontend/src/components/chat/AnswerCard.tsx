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
import type { AnswerPassage, AnswerType, Message } from "../../types/api";
import { Citation, PassageLocation } from "./EvidencePanel";

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
      className={[
        "mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded px-1 align-baseline font-mono text-[11px] leading-none",
        active
          ? "bg-signal-500/30 text-signal-300 ring-1 ring-signal-500/60"
          : "bg-ink-700 text-slateish-300 hover:bg-ink-600",
      ].join(" ")}
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

function Label({ tone, children }: { tone: "quote" | "generated"; children: React.ReactNode }) {
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

export function AnswerCard({
  view,
  onSelectSource,
  activeSource,
  onExplain,
  explaining,
  explainSeconds,
  explainsEarlier,
}: {
  view: AnswerView;
  onSelectSource: (i: number) => void;
  activeSource: number | null;
  onExplain?: () => void;
  explaining?: boolean;
  explainSeconds?: number;
  explainsEarlier?: boolean;
}) {
  const sources = sourcesOf(view);

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
    return (
      <div className="rounded-lg border border-ink-600 bg-ink-850 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Label tone="quote">Quoted verbatim from the document</Label>
          {view.seconds != null && (
            <span className="font-mono text-[11px] text-slateish-500">
              {Math.round(view.seconds * 1000)} ms · no model involved
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
          {view.answer}
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
                    <Chip n={i + 2} active={activeSource === i + 1} onClick={() => onSelectSource(i + 1)} />
                    <PassageLocation passage={s} />
                  </button>
                </li>
              ))}
            </ul>
          </details>
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
            {Math.round(view.seconds * 1000)} ms
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

      {sources.length > 0 && (
        <ul className="mt-3 space-y-1">
          {sources.map((s, i) => (
            <li key={s.chunk_id}>
              <button
                type="button"
                onClick={() => onSelectSource(i)}
                className="flex w-full items-center gap-2 rounded border border-ink-700 px-2 py-1.5 text-left hover:bg-ink-800"
              >
                <Chip n={i + 1} active={activeSource === i} onClick={() => onSelectSource(i)} />
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
    </div>
  );
}
