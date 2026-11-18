/**
 * "How this review was made" (order 14, piece H): every step of one general review, in the order it ran, from the stored run.
 *
 * Seven short sections: the paper (what the AI decided it is), the rule books chosen with WHY each was chosen and the ones we do not
 * hold, the checklist, every check (book, clause, the paper's words, what code compared), the comment sheet, the time and cost per
 * step, and the completeness count. Nothing is computed here that the server did not say: a missing value renders as nothing (never
 * 0), a reason that was not recorded says so, and a rule book the viewer may not open is counted, never named (the server already
 * leaves it out of `books`; the check rows already carry its words instead of its name).
 */
import { type ReactNode, useMemo, useState } from "react";

import type { GeneralCall, GeneralLine, GeneralReview } from "../../../api/generalReview";

/** The words of a book whose reason was not stored; the server says the same ones (and "not shown: it names a book you may not read"). */
const NO_REASON = "the reason was not recorded for this review";

/** The plain name of each step the run's calls are grouped under; a step this table does not know is shown by its own name. */
export const STEP_NAMES: Record<string, string> = {
  aim_read_pages: "Read the paper",
  aim_identify: "Name the paper",
  aim_select: "Choose rule books",
  aim_checklist: "Write the checklist",
  aim_checklist_retry: "Write the checklist (retry)",
  aim_checklist_knowledge: "Add engineering-knowledge items",
  aim_attack: "A second model attacks the checklist",
  aim_judge: "Check each item",
  aim_edit: "Write the comments",
  ledger: "Read the spend ledger",
};

export interface StepTotals { step: string; name: string; calls: number; models: string[]; seconds: number; usd: number | null }

/** One row per step, in the order the steps first appear. `usd` is null when no call of the step carried a cost (never 0). */
export function totalsByStep(calls: GeneralCall[]): StepTotals[] {
  const by = new Map<string, StepTotals>();
  for (const c of calls) {
    const row = by.get(c.step) ?? { step: c.step, name: STEP_NAMES[c.step] ?? c.step, calls: 0, models: [], seconds: 0, usd: null };
    row.calls += 1;
    if (c.model && !row.models.includes(c.model)) row.models.push(c.model);
    row.seconds += typeof c.seconds === "number" && Number.isFinite(c.seconds) ? c.seconds : 0;
    if (typeof c.usd === "number" && Number.isFinite(c.usd)) row.usd = (row.usd ?? 0) + c.usd;
    by.set(c.step, row);
  }
  return [...by.values()];
}

function Section({ n, title, why, id, children }: { n: number; title: string; why: string; id: string; children: ReactNode }) {
  return (
    <section aria-label={title} data-testid={id} className="space-y-2 rounded-[var(--radius-md)] border border-ink-600 p-3">
      <h3 className="font-semibold text-slateish-100">
        <span className="mr-2 inline-block h-6 w-6 rounded-full bg-ink-600 text-center text-xs leading-6">{n}</span>
        {title}
      </h3>
      <p className="text-xs text-slateish-400">{why}</p>
      {children}
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value == null || value === "") return null; // null renders as nothing
  return (
    <div className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1.5">
      <span className="block text-xs text-slateish-400">{label}</span>
      <span className="text-sm text-slateish-100">{value}</span>
    </div>
  );
}

const bookOf = (l: GeneralLine) => [l.standard || "engineering knowledge", l.clause].filter(Boolean).join(", clause ");

function Checks({ points }: { points: GeneralLine[] }) {
  const [text, setText] = useState("");
  const [result, setResult] = useState("");
  const results = useMemo(() => [...new Set(points.map((p) => p.shown_label).filter(Boolean))], [points]);
  const shown = useMemo(() => {
    const q = text.trim().toLowerCase();
    return points.filter((p) => (!result || p.shown_label === result) && (!q || JSON.stringify(p).toLowerCase().includes(q)));
  }, [points, text, result]);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Search field, book, words" aria-label="Search the checks"
          className="rounded-[var(--radius-sm)] border border-ink-500 bg-ink-850 px-2 py-1 text-sm text-slateish-100" />
        <select value={result} onChange={(e) => setResult(e.target.value)} aria-label="Show checks with this result"
          className="rounded-[var(--radius-sm)] border border-ink-500 bg-ink-850 px-2 py-1 text-sm text-slateish-100">
          <option value="">All results</option>
          {results.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <span data-testid="how-checks-count" className="text-xs text-slateish-400">{shown.length} of {points.length} checks</span>
      </div>
      <div className="max-h-[32rem] overflow-auto rounded-[var(--radius-sm)] border border-ink-600">
        <table className="w-full min-w-[40rem] text-left text-xs">
          <thead className="sticky top-0 bg-ink-850 text-slateish-400">
            <tr><th className="p-2">#</th><th className="p-2">Result</th><th className="p-2">Field on the paper</th><th className="p-2">Page</th>
              <th className="p-2">Rule book, clause</th><th className="p-2">What code compared</th><th className="p-2">Comment and the paper's words</th></tr>
          </thead>
          <tbody>
            {shown.map((p) => (
              <tr key={`${p.n}-${p.item_id}`} data-testid="how-check" className="border-t border-ink-600 align-top text-slateish-200">
                <td className="p-2">{p.n}</td>
                <td className="p-2">{p.shown_label}</td>
                <td className="p-2">{p.field || p.item_id}{p.topic ? <span className="block text-slateish-400">{p.topic}</span> : null}</td>
                <td className="p-2">{p.page ?? ""}</td>
                <td className="p-2">{bookOf(p)}{p.source ? <span className="block text-slateish-400">{p.source}</span> : null}</td>
                <td className="p-2">{p.compared ? <>{p.compared}{p.compare_kind ? <span className="block text-slateish-400">{p.compare_kind}</span> : null}</> : <span className="text-slateish-400">nothing compared by code</span>}</td>
                <td className="p-2">{p.comment}{p.quote ? <span className="block italic text-slateish-300">Paper: “{p.quote}”{p.quote_unverified ? " (code could not find this quote on the page)" : ""}</span> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Section 7's sentence on the confirmations: shown only when the server counted them (an older run has no such count). */
export function confirmationsLine(review: GeneralReview): string | null {
  const { comments, confirmations, comment_lines: inComments, confirmation_lines: inConfirmations } = review.counts;
  if (confirmations == null) return null;
  const pts = (n: number) => `${n} point${n === 1 ? "" : "s"}`;
  const sent = `${comments} comment${comments === 1 ? "" : "s"} sent${inComments != null ? ` (covering ${pts(inComments)})` : ""}`;
  const held = `${confirmations} confirmation${confirmations === 1 ? "" : "s"} not sent${inConfirmations != null ? ` (covering ${pts(inConfirmations)})` : ""}`;
  const total = inComments != null && inConfirmations != null ? `; together ${pts(inComments + inConfirmations)} qualified to be sent` : "";
  return `${sent} and ${held}${total}. Every point stays in "Every check".`;
}

const minutes = (s: number) => `${(Math.round((s / 60) * 10) / 10).toString()} min`;

export function HowReviewMade({ review }: { review: GeneralReview }) {
  const id = review.identity;
  const steps = useMemo(() => totalsByStep(review.calls ?? []), [review.calls]);
  const totalSeconds = steps.reduce((a, s) => a + s.seconds, 0);
  const c = review.completeness;
  const k = review.checklist;
  return (
    <div data-testid="how-made" className="space-y-3">
      <Section n={1} id="how-paper" title="What the AI decided the paper is"
        why="The first step. Every later step depends on this answer: which rule books, which checklist.">
        <div className="flex flex-wrap gap-2">
          <Fact label="Kind of paper" value={id.kind} />
          <Fact label="Equipment or subject" value={id.equipment_type} />
          <Fact label="Subject in the paper's words" value={id.subject} />
        </div>
        {!id.kind && !id.equipment_type && !id.subject && <p className="text-slateish-400">This review did not record what the paper is.</p>}
      </Section>

      <Section n={2} id="how-books" title={`Rule books used (${review.books.length}${review.books_not_readable ? `, and ${review.books_not_readable} you may not open` : ""})`}
        why="The books the review carried, and why each one was chosen. Then the books it needed that we do not hold.">
        {review.documents_listed && <p data-testid="how-listed" className="text-xs text-slateish-300">{review.documents_listed.sentence}</p>}
        {review.books.length === 0 ? <p className="text-slateish-400">none</p> : (
          <ul className="space-y-1">
            {review.books.map((b) => (
              <li key={b.id} data-testid="how-book"><span className="text-slateish-100">{b.title}</span>
                <span className="block text-xs text-slateish-400">Why chosen: {b.why || NO_REASON}</span></li>
            ))}
          </ul>
        )}
        <h4 className="pt-1 text-sm font-semibold text-slateish-100">Needed but not held ({review.not_held.length})</h4>
        {review.not_held.length === 0 ? <p className="text-slateish-400">none</p> : (
          <ul className="space-y-1" data-testid="how-not-held">
            {review.not_held.map((b) => <li key={b.name}><span className="text-slateish-100">{b.name}</span>{b.why ? <span className="block text-xs text-slateish-400">Why needed: {b.why}</span> : null}</li>)}
          </ul>
        )}
        {review.unlisted_books.sentence && <p data-testid="general-unlisted" className="text-slateish-200">{review.unlisted_books.sentence}</p>}
      </Section>

      <Section n={3} id="how-checklist" title="The checklist"
        why="Written from the rule books only, without looking at the paper; then a second model attacked it to find gaps.">
        {k.key ? (
          <div className="flex flex-wrap gap-2">
            <Fact label="Checklist name" value={k.key} />
            <Fact label="Items" value={k.items} />
            <Fact label="Items every review checks" value={k.always_items || null} />
            <Fact label="Reused or new" value={k.reused == null ? null : k.reused ? "reused from an earlier review" : "built for this review"} />
            <Fact label="Built from" value={k.built_from} />
          </div>
        ) : <p className="text-slateish-400">This review did not record its checklist.</p>}
      </Section>

      <Section n={4} id="how-checks" title={`Every check the review made (${review.points.length})`}
        why="One row per point: which rule book and clause, what the paper says, what code compared, and the result. Every row is marked “AI, to be checked”.">
        <Checks points={review.points} />
      </Section>

      <Section n={5} id="how-sheet" title={`The comment sheet: what is sent (${review.comments.length})`}
        why="Only these rows go on the comment sheet. Points that repeat the same finding are joined into one comment that lists every place.">
        {review.comments.length === 0 ? <p className="text-slateish-400">This review has no comments.</p> : (
          <div className="max-h-[24rem] overflow-auto rounded-[var(--radius-sm)] border border-ink-600">
            <table className="w-full min-w-[32rem] text-left text-xs">
              <thead className="sticky top-0 bg-ink-850 text-slateish-400"><tr><th className="p-2">#</th><th className="p-2">Result</th><th className="p-2">Field</th><th className="p-2">Page</th><th className="p-2">Rule book, clause</th><th className="p-2">Comment</th></tr></thead>
              <tbody>
                {review.comments.map((l) => (
                  <tr key={`${l.n}-${l.item_id}`} data-testid="how-comment" className="border-t border-ink-600 align-top text-slateish-200">
                    <td className="p-2">{l.n}</td><td className="p-2">{l.shown_label}</td><td className="p-2">{l.field || l.item_id}</td>
                    <td className="p-2">{l.page ?? ""}</td><td className="p-2">{bookOf(l)}</td><td className="p-2 whitespace-pre-line">{l.comment}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section n={6} id="how-time" title="Time and cost per step"
        why="Every call the review made, grouped by step. Seconds add up each call's own time; calls that ran side by side overlap, so the sum can be longer than the clock time.">
        <div className="flex flex-wrap gap-2">
          <Fact label="Clock time" value={typeof review.seconds === "number" ? minutes(review.seconds) : null} />
          <Fact label="Cost of the review" value={review.cost.usd != null ? `USD ${review.cost.usd.toFixed(2)}` : null} />
        </div>
        {review.cost.usd == null && <p data-testid="how-cost-unread" className="text-xs text-slateish-400">{review.cost.note ?? "The cost of this review was not read from the spend ledger."}</p>}
        {steps.length === 0 ? <p className="text-slateish-400">No calls were recorded for this review.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[28rem] text-left text-xs">
              <thead className="text-slateish-400"><tr><th className="p-2">Step</th><th className="p-2">Calls</th><th className="p-2">Model</th><th className="p-2">Seconds</th><th className="p-2">Share of time</th><th className="p-2">USD</th></tr></thead>
              <tbody>
                {steps.map((s) => (
                  <tr key={s.step} data-testid="how-step" className="border-t border-ink-600 text-slateish-200">
                    <td className="p-2">{s.name}</td><td className="p-2">{s.calls}</td><td className="p-2">{s.models.join(", ")}</td>
                    <td className="p-2">{Math.round(s.seconds)}</td>
                    <td className="p-2"><div className="h-2 w-24 rounded bg-ink-600"><div className="h-2 rounded bg-signal-400" style={{ width: `${totalSeconds > 0 ? Math.round((s.seconds / totalSeconds) * 100) : 0}%` }} /></div></td>
                    <td className="p-2">{s.usd != null ? s.usd.toFixed(3) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section n={7} id="how-complete" title="Completeness check"
        why="Points on the page = rows in the database = rows in the Excel file. If they differ, the file is refused.">
        <div className="flex flex-wrap gap-2">
          <Fact label="Points on the page" value={c.page} />
          <Fact label="Lines in the database" value={c.database} />
          <Fact label="Rows in the file" value={c.file_rows} />
          <Fact label="Result" value={c.ok ? "all three agree" : "they differ: the file is refused"} />
        </div>
        {confirmationsLine(review) && <p data-testid="how-confirmations" className="text-slateish-200">{confirmationsLine(review)}</p>}
      </Section>
    </div>
  );
}
