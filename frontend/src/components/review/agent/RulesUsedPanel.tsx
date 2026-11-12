/**
 * "Rules used": VIEW ONLY. For one review: every rule that was asked, every
 * rule left out and why, and the rule books we do not hold. The filter box
 * only narrows what is shown; nothing here edits anything.
 */
import { useEffect, useMemo, useState } from "react";

import { agentReview, isFeatureOff } from "../../../api/agentReview";
import type { AgentBookCoverage, AgentRulesUsed } from "../../../types/api";
import { LEFT_OUT_REASONS } from "./agentWords";
import { humanizeCode } from "./plainWords";
import { PaperTextNotice, paperTextStopped, plainStop } from "./PaperTextNotice";

export const NOT_MEASURED = "not measured";
export const LESS_THAN_HALF =
  "less than half of this book's requirement sentences are stored: weak or scanned pages must be re-read";

/** Less than half stored, from the two integers; null when not measured. */
export function belowHalf(b: AgentBookCoverage): boolean {
  const total = b.requirement_sentences;
  const got = b.covered_sentences;
  return total != null && got != null && total > 0 && got * 2 < total;
}

/** "412 of 530 requirement sentences stored (78%)", or "not measured" when
 *  either number is missing or the book has no counted sentence. */
export function coverageWords(b: AgentBookCoverage): string {
  const total = b.requirement_sentences;
  const got = b.covered_sentences;
  if (total == null || got == null || total <= 0) return NOT_MEASURED;
  // Below half is decided from the two numbers, and then the percentage is
  // rounded DOWN, so a warning never sits next to "50%".
  const pct = belowHalf(b) ? Math.floor((100 * got) / total) : Math.round((100 * got) / total);
  return `${got} of ${total} requirement sentences stored (${pct}%)`;
}
const pages = (n: number | null | undefined) => (n == null ? NOT_MEASURED : String(n));

export const NOT_AGENT_RULES = "This review was not made by the AI reviewer, so no rule list was kept for it.";

const UNDECIDED = new Set(["", "unknown", "not decided", "not known"]);

const has = (text: string, needle: string) => text.toLowerCase().includes(needle);

export const GENERAL_NO_RULES =
  "General review: no rule was asked. Rule books the paper cites that we do not hold are listed below.";

export function RulesUsedView({ data, general = false }: { data: AgentRulesUsed; general?: boolean }) {
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();
  const asked = useMemo(
    () => (needle ? data.asked.filter((r) => has(r.rule_book, needle) || has(r.tier, needle)) : data.asked),
    [data.asked, needle],
  );
  const leftOut = useMemo(
    () => (needle ? data.left_out.filter((r) => has(r.rule_book, needle) || has(r.reason, needle)) : data.left_out),
    [data.left_out, needle],
  );
  const undecided = UNDECIDED.has(data.paper_kind.trim().toLowerCase());
  const countKeys = [
    ...LEFT_OUT_REASONS.filter((r) => r in data.left_out_counts),
    ...Object.keys(data.left_out_counts).filter((r) => !(LEFT_OUT_REASONS as readonly string[]).includes(r)),
  ];

  return (
    <div className="space-y-6" data-testid="rules-used">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold text-slateish-100">Rules used</h2>
        <p className="text-sm text-slateish-100">
          Paper kind: <span className="font-medium">{undecided ? "not decided" : data.paper_kind}</span>
          {data.equipment_type ? <> · Equipment type: <span className="font-medium">{humanizeCode(data.equipment_type)}</span></> : null}
        </p>
        <PaperTextNotice paperText={data.paper_text} />
        {data.rule_set_changed_by != null && (
          <p data-testid="rules-changed-by" className="text-sm text-warn-500">Rule set changed by {data.rule_set_changed_by}</p>
        )}
        {(data.equipment_notes ?? []).length > 0 && (
          <ul data-testid="equipment-notes" className="list-disc pl-5 text-sm text-slateish-100">
            {data.equipment_notes.map((n) => <li key={n}>{humanizeCode(n)}</li>)}
          </ul>
        )}
        {data.candidates_from != null && (
          <p data-testid="candidates-from" className="text-sm text-slateish-100">
            The rules to ask were taken from: {data.candidates_from}.
            {data.same_rule_repeats != null && data.same_rule_repeats > 0 && (
              <> {data.same_rule_repeats} stored rule{data.same_rule_repeats === 1 ? " is" : "s are"} the same rule as another one in the list and {data.same_rule_repeats === 1 ? "is" : "are"} not listed twice.</>
            )}
          </p>
        )}
        {data.other_books != null && (
          <p data-testid="other-books" className="text-sm text-slateish-100">
            AI-approved rules of this paper kind in rule books this review did not select: {data.other_books.ai_approved_rules} in{" "}
            {data.other_books.books} book{data.other_books.books === 1 ? "" : "s"} (counted over {data.other_books.boundary}). They were not asked.
          </p>
        )}
        <p className="text-xs text-slateish-400">View only. The rules are chosen automatically; this page shows what was chosen.</p>
      </header>

      {general && <p data-testid="rules-general" className="text-sm text-slateish-100">{GENERAL_NO_RULES}</p>}
      {!general && <div>
        <label htmlFor="rules-filter" className="block text-sm text-slateish-200">Filter by rule book, approval or reason</label>
        <input id="rules-filter" type="search" value={filter} onChange={(e) => setFilter(e.target.value)}
          className="mt-1 w-full max-w-md rounded-[var(--radius-sm)] border border-ink-600 bg-ink-850 px-2 py-1 text-sm text-slateish-100" />
        <p className="text-xs text-slateish-400">The filter only narrows what is shown below; it changes no rule.</p>
      </div>}

      {!general && <>
      <section aria-labelledby="rules-books-title" className="space-y-1">
        <h3 id="rules-books-title" className="text-base font-semibold text-slateish-100">Rule books</h3>
        {data.books.length === 0 ? (
          <p data-testid="books-empty" className="text-sm text-slateish-300">No rule book coverage was recorded for this review.</p>
        ) : (
          <ul className="space-y-2 text-sm" data-testid="books">
            {data.books.filter((b) => !needle || has(b.rule_book, needle)).map((b) => (
              <li key={b.rule_book} className="text-slateish-100">
                <span className="font-medium">{b.rule_book}</span>: {coverageWords(b)}
                <span className="block text-xs text-slateish-400">
                  unreadable pages: {pages(b.unreadable_pages)} · weak pages: {pages(b.weak_pages)}
                </span>
                {belowHalf(b) && (
                  <span role="note" className="block text-xs text-warn-500">Warning: {LESS_THAN_HALF}.</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="rules-asked-title" className="space-y-1">
        <h3 id="rules-asked-title" className="text-base font-semibold text-slateish-100">Asked</h3>
        <p className="text-sm text-slateish-400" data-testid="asked-count">
          Showing {asked.length} of {data.asked.length} rule{data.asked.length === 1 ? "" : "s"} asked for this paper.
        </p>
        {data.asked.length === 0 ? (
          <p data-testid="asked-empty" className="text-sm text-slateish-300">
            {paperTextStopped(data.paper_text)
              ? `No rule was asked. ${data.paper_text?.sentence ?? ""}`
              : data.stop_reason
                ? plainStop(data.stop_reason)
                : undecided ? "No rule was asked: the paper kind could not be decided." : "No rule was asked of this paper."}
          </p>
        ) : asked.length === 0 ? (
          <p className="text-sm text-slateish-300">No asked rule matches the filter.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Rules asked of this paper</caption>
              <thead className="text-xs text-slateish-400">
                <tr>
                  {["Rule book", "Clause", "Quote", "Paper kind", "Field", "Equipment", "Approval"].map((h) => (
                    <th key={h} scope="col" className="py-1 pr-3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {asked.map((r, i) => (
                  <tr key={`${r.rule_book}-${r.clause}-${i}`} className="border-t border-ink-700 align-top">
                    <td className="py-1 pr-3">{r.rule_book}</td><td className="pr-3">{r.clause}</td>
                    <td className="break-words pr-3">{r.quote}</td><td className="pr-3">{r.paper_kind}</td>
                    <td className="pr-3">{r.field ?? ""}</td><td className="pr-3">{r.equipment ? humanizeCode(r.equipment) : ""}</td>
                    <td>{r.tier}{r.read_from === "scan" && <span className="block text-xs text-warn-500">read from a scan</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-labelledby="rules-left-title" className="space-y-1">
        <h3 id="rules-left-title" className="text-base font-semibold text-slateish-100">Left out</h3>
        {countKeys.length > 0 && (
          <ul className="text-sm text-slateish-100" data-testid="left-out-counts">
            {countKeys.map((k) => <li key={k}>{k}: <span className="font-mono">{data.left_out_counts[k]}</span></li>)}
          </ul>
        )}
        <p className="text-sm text-slateish-400" data-testid="left-count">
          Showing {leftOut.length} of {data.left_out.length} rule{data.left_out.length === 1 ? "" : "s"} left out of this paper.
        </p>
        {data.left_out.length === 0 ? (
          <p data-testid="left-empty" className="text-sm text-slateish-300">No rule was left out.</p>
        ) : leftOut.length === 0 ? (
          <p className="text-sm text-slateish-300">No left-out rule matches the filter.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Rules left out of this paper</caption>
              <thead className="text-xs text-slateish-400">
                <tr><th scope="col" className="py-1 pr-3">Rule book</th><th scope="col" className="pr-3">Clause</th><th scope="col">Reason</th></tr>
              </thead>
              <tbody>
                {leftOut.map((r, i) => (
                  <tr key={`${r.rule_book}-${r.clause}-${i}`} className="border-t border-ink-700">
                    <td className="py-1 pr-3">{r.rule_book}</td><td className="pr-3">{r.clause}</td><td>{r.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      </>}
      <section aria-labelledby="rules-missing-title" className="space-y-1">
        <h3 id="rules-missing-title" className="text-base font-semibold text-slateish-100">Rule books we do not hold</h3>
        {data.missing_books.length === 0 ? (
          <p data-testid="missing-empty" className="text-sm text-slateish-300">None: every rule book this paper cites is held.</p>
        ) : (
          <>
            <ul className="list-disc pl-5 text-sm text-slateish-100">
              {data.missing_books.map((b) => <li key={b.name}>{b.name}: {b.why}</li>)}
            </ul>
            <p className="text-xs text-slateish-400">Listed only: these are not counted against the review.</p>
          </>
        )}
      </section>
    </div>
  );
}

export function RulesUsedPanel({ runId }: { runId: string }) {
  const [data, setData] = useState<AgentRulesUsed | null>(null);
  const [general, setGeneral] = useState(false);
  const [state, setState] = useState<"loading" | "ok" | "none" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setState("loading"); setData(null);
    void Promise.all([agentReview.rulesUsed(runId), agentReview.summary(runId)]).then(([r, sum]) => {
      if (!live) return;
      if (r.ok) { setGeneral(sum.ok && sum.data.mode === "general review"); setData(r.data); setState("ok"); return; }
      if (isFeatureOff(r)) { setState("none"); return; }
      setError(r.error.message); setState("error");
    });
    return () => { live = false; };
  }, [runId]);
  if (state === "loading") return <p role="status" className="text-sm text-slateish-400">Reading the rules used…</p>;
  if (state === "none") return <p data-testid="rules-not-agent" className="text-sm text-slateish-300">{NOT_AGENT_RULES}</p>;
  if (state === "error" || !data) return <p role="alert" className="text-sm text-red-400">{error}</p>;
  return <RulesUsedView data={data} general={general} />;
}
