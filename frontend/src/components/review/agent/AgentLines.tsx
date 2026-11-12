/**
 * The CRS lines of the AI reviewer, one block per class. "Pass" and "Fail"
 * appear only in the "Proven by code" block (see agentWords.lineView, which
 * holds even if the API sends otherwise). The class "AI opinion, rule not yet
 * approved" has its own block. Paging is by the server's cursor.
 */
import { useEffect, useState } from "react";

import { agentReview } from "../../../api/agentReview";
import type { AgentLine, AgentMode } from "../../../types/api";
import {
  CLASS_ORDER, CLASS_STYLE, DATA_ERROR_NOTE, GENERAL_CLASS_ORDER, MODEL_WORDS_MARK, NOT_REVIEWED_NOTE, PART_ORDER, PART_WORDS,
  lineView, tierWords,
} from "./agentWords";

function Block({ title, mark, border, lines, onOpen, mode }: {
  title: string; mark: string; border: string; lines: AgentLine[]; onOpen: (itemId: string) => void; mode: AgentMode;
}) {
  const general = mode === "general review";
  return (
    <section aria-label={title} data-testid={`block-${title}`} className="space-y-1">
      <h3 className={`pl-2 text-sm font-semibold text-slateish-100 ${border}`}>
        <span aria-hidden="true">{mark} </span>{title} <span className="font-normal text-slateish-400">({lines.length} loaded)</span>
      </h3>
      {title === "Not reviewed" && <p className="pl-2 text-xs text-slateish-400">{NOT_REVIEWED_NOTE}</p>}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{title}</caption>
          <thead className="text-xs text-slateish-400">
            <tr>
              <th scope="col" className="py-1 pr-3">Line</th><th scope="col" className="pr-3">Word</th>
              {general && <th scope="col" className="pr-3">Part</th>}<th scope="col" className="pr-3">Page</th><th scope="col" className="pr-3">Rule book</th>
              <th scope="col" className="pr-3">Clause</th><th scope="col" className="pr-3">Rule approval</th>
              <th scope="col">Reason</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => {
              const view = lineView(line, mode);
              return (
                <tr key={line.item_id} className="border-t border-ink-700 align-top">
                  <td className="py-1 pr-3">
                    <button type="button" onClick={() => onOpen(line.item_id)}
                      aria-label={`Open the trace of line ${line.item_id}`}
                      className="text-signal-300 underline-offset-2 hover:underline">{line.item_id}</button>
                  </td>
                  <td className="pr-3" data-testid={`word-${line.item_id}`}>
                    {view.word ?? view.klass ?? "unknown class"}
                    {view.dataError && <span role="note" className="block text-xs text-warn-500">{DATA_ERROR_NOTE}</span>}
                  </td>
                  {general && <td className="pr-3">{line.part ? PART_WORDS[line.part] ?? "" : ""}</td>}
                  <td className="pr-3">{line.page != null ? line.page : ""}</td>
                  <td className="pr-3">{line.rule_book}</td>
                  <td className="pr-3">{line.clause}</td>
                  <td className="pr-3">{tierWords(line.verdict_class, line.rule_tier)}</td>
                  <td className="whitespace-pre-line break-words" data-testid={`reason-${line.item_id}`}>
                    {line.reason}
                    {line.text_source === "the model's words" && <span className="block text-xs text-slateish-400" data-testid={`model-words-${line.item_id}`}>{MODEL_WORDS_MARK}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function AgentLines({ runId, onOpenTrace, mode = "rule review" }: {
  runId: string; onOpenTrace: (itemId: string) => void; mode?: AgentMode;
}) {
  const general = mode === "general review";
  const [lines, setLines] = useState<AgentLine[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(cursor: string | null, replace: boolean) {
    setBusy(true);
    setError(null);
    const r = await agentReview.lines(runId, cursor);
    setBusy(false);
    if (!r.ok) { setError(r.error.message); return; }
    setLines((prev) => (replace ? r.data.lines : [...prev, ...r.data.lines]));
    setNext(r.data.next ?? null);
    setLoaded(true);
  }
  useEffect(() => {
    setLines([]); setNext(null); setLoaded(false);
    void load(null, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const unknown = lines.filter((l) => lineView(l, mode).klass === null);
  return (
    <section aria-labelledby="agent-lines-title" data-testid="agent-lines" className="space-y-4">
      <h2 id="agent-lines-title" className="text-lg font-semibold text-slateish-100">Lines</h2>
      {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
      {!loaded && !error && <p role="status" className="text-sm text-slateish-400">Reading the lines…</p>}
      {loaded && lines.length === 0 && <p className="text-sm text-slateish-400">This review has no lines.</p>}
      {(general ? GENERAL_CLASS_ORDER : CLASS_ORDER).map((c) => {
        const mine = lines.filter((l) => lineView(l, mode).klass === c);
        // AI notes are grouped by part.
        if (general && c === "AI note, no rule book") {
          mine.sort((a, b) => PART_ORDER.indexOf(a.part ?? "checklist") - PART_ORDER.indexOf(b.part ?? "checklist"));
        }
        return mine.length === 0 ? null : (
          <Block key={c} title={c} mark={CLASS_STYLE[c].mark} border={CLASS_STYLE[c].border} lines={mine} onOpen={onOpenTrace} mode={mode} />
        );
      })}
      {loaded && !general && !next && lines.length > 0 && !lines.some((l) => lineView(l, mode).klass === "AI opinion, rule not yet approved") && (
        <section aria-label="AI opinion, rule not yet approved" data-testid="block-empty-not-approved" className="space-y-1">
          <h3 className={`pl-2 text-sm font-semibold text-slateish-100 ${CLASS_STYLE["AI opinion, rule not yet approved"].border}`}>
            <span aria-hidden="true">{CLASS_STYLE["AI opinion, rule not yet approved"].mark} </span>AI opinion, rule not yet approved
          </h3>
          <p className="pl-2 text-sm text-slateish-400">No rule was asked that is not AI approved.</p>
        </section>
      )}
      {unknown.length > 0 && (
        <Block title="Unknown class (data error)" mark="!" border="border-l-4 border-solid border-red-400" lines={unknown} onOpen={onOpenTrace} mode={mode} />
      )}
      {loaded && (
        <p className="text-sm text-slateish-400" data-testid="agent-lines-boundary">
          {lines.length} line{lines.length === 1 ? "" : "s"} loaded so far{next ? "; more lines are waiting." : "; that is every line of this review."}
        </p>
      )}
      {next && (
        <button type="button" disabled={busy} onClick={() => void load(next, false)}
          className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1.5 text-sm text-slateish-100 disabled:opacity-50">
          {busy ? "Loading…" : "Load more lines"}
        </button>
      )}
    </section>
  );
}
