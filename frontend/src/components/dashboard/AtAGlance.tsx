/**
 * AT A GLANCE (owner, 26 Nov 2026, E5: "plain numbers: in, waiting, late, done; a one-line plain summary on every result; inside the
 * existing Dashboard"). A manager's view of the three kinds of work: contractor documents (their reviews), technical queries and CFCs,
 * and deliverables. Every number comes from a figure the app already serves (the review dashboard, the query counts, the deliverables
 * register and its overdue alerts); a figure that could not be loaded is said to be unknown, never shown as 0, and "late" says what it
 * is counted over (rule 4: every count states its boundary).
 */
import { useEffect, useState } from "react";

import { deliverables as deliverablesApi, reviews as reviewsApi } from "../../api/client";
import { technicalQueriesApi } from "../../api/technicalQueries";
import type { Deliverable, ReviewDashboard } from "../../types/api";

export interface GlanceRow {
  label: string;
  /** null = could not be loaded (said as such, never 0). */
  inCount: number | null;
  waiting: number | null;
  late: number | null;
  done: number | null;
  /** What "late" means for this row, or why it is not counted. */
  lateNote: string;
  /** The row's own plain sentence. */
  sentence: string;
}

const UNKNOWN = "could not be loaded";

export function reviewsRow(d: ReviewDashboard | null): GlanceRow {
  // ONE UNIT PER ROW: reviews (a contract or a specification is reviewed too, so counting documents in one column and reviews in the
  // next would not add up). The contractor documents not reviewed yet are said apart.
  if (!d) return { label: "Document reviews", inCount: null, waiting: null, late: null, done: null, lateNote: "", sentence: `Document reviews: ${UNKNOWN}.` };
  const signed = typeof d.reviews_signed === "number" ? d.reviews_signed : null;
  const waiting = d.reviews_awaiting_decision + d.reviews_running;
  const inCount = signed === null ? null : waiting + signed;
  return {
    label: "Document reviews",
    inCount,
    waiting,
    late: null,
    done: signed,
    lateNote: "a review has no due date; see Deliverables for due dates",
    sentence:
      `Document reviews: ${inCount === null ? "" : `${inCount} in; `}${waiting} waiting (${d.reviews_awaiting_decision} to sign off` +
      `${d.reviews_running ? `, ${d.reviews_running} being reviewed` : ""})${signed === null ? "" : `; ${signed} signed off`}. ` +
      `${d.submittals_awaiting_review} of ${d.submittals_total} contractor document${d.submittals_total === 1 ? "" : "s"} not reviewed yet.`,
  };
}

/** The query statuses that need nothing more from the team. */
const QUERY_DONE = ["resolved"];
const QUERY_SET_ASIDE = ["duplicate", "cancelled"];

export function queriesRow(m: Record<string, number> | null | "off"): GlanceRow | null {
  if (m === "off") return null; // technical queries are switched off on this computer: no row
  if (!m) return { label: "Technical queries and CFCs", inCount: null, waiting: null, late: null, done: null, lateNote: "", sentence: `Technical queries: ${UNKNOWN}.` };
  const setAside = QUERY_SET_ASIDE.reduce((n, s) => n + (m[s] ?? 0), 0);
  const inCount = (m.total ?? 0) - setAside;
  const done = QUERY_DONE.reduce((n, s) => n + (m[s] ?? 0), 0);
  const late = typeof m.overdue === "number" ? m.overdue : null;
  const withDue = typeof m.open_with_due_date === "number" ? m.open_with_due_date : null;
  return {
    label: "Technical queries and CFCs",
    inCount,
    waiting: inCount - done,
    late,
    done,
    lateNote: withDue === null ? "" : `past the due date, of ${withDue} open with a due date`,
    sentence:
      `Technical queries: ${inCount} in; ${inCount - done} waiting` +
      (late === null ? "" : `, ${late} of them late`) + `; ${done} answered and closed.`,
  };
}

export function deliverablesRow(items: Deliverable[] | null, overdue: number | null): GlanceRow {
  if (!items) return { label: "Deliverables", inCount: null, waiting: null, late: null, done: null, lateNote: "", sentence: `Deliverables: ${UNKNOWN}.` };
  const done = items.filter((d) => d.status === "approved").length;
  const closed = done + items.filter((d) => d.status === "superseded").length;
  const waiting = items.length - closed;
  return {
    label: "Deliverables",
    inCount: items.length,
    waiting,
    late: overdue,
    done,
    lateNote: overdue === null ? "" : "past the due date",
    sentence: `Deliverables: ${items.length} in; ${waiting} waiting` + (overdue === null ? "" : `, ${overdue} late`) + `; ${done} approved.`,
  };
}

/** The one plain line above the table: what is waiting and what is late, the manager's first question; the full row sentences stay
 *  available to a screen reader as the table's own cells. An unknown figure is said, never left out. */
export function glanceLine(rows: GlanceRow[]): string {
  const NAMES: Record<string, [string, string]> = {
    "Document reviews": ["document review", "document reviews"],
    "Technical queries and CFCs": ["query or CFC", "queries and CFCs"],
    Deliverables: ["deliverable", "deliverables"],
  };
  const name = (r: GlanceRow, n?: number | null) => (NAMES[r.label] ?? [r.label.toLowerCase(), r.label.toLowerCase()])[n === 1 ? 0 : 1];
  const waiting = rows.map((r) => (r.waiting === null ? `${name(r)}: unknown` : `${r.waiting} ${name(r, r.waiting)}`)).join(", ");
  const lateRows = rows.filter((r) => r.late !== null && r.late > 0);
  const unknownLate = rows.filter((r) => r.late === null && r.lateNote === "");
  const late = lateRows.length ? lateRows.map((r) => `${r.late} ${name(r, r.late)}`).join(", ") : "nothing";
  return `Waiting: ${waiting}. Late: ${late}${unknownLate.length ? ` (${unknownLate.map(name).join(", ")}: unknown)` : ""}.`;
}

function Cell({ value, tone }: { value: number | null; tone?: "late" }) {
  if (value === null) return <td className="px-3 py-2 text-slateish-400">—</td>;
  const late = tone === "late" && value > 0;
  return <td className={`px-3 py-2 text-lg font-semibold ${late ? "text-danger-500" : "text-slateish-100"}`}>{value}</td>;
}

export function AtAGlance() {
  const [review, setReview] = useState<ReviewDashboard | null | undefined>(undefined);
  const [queries, setQueries] = useState<Record<string, number> | null | "off" | undefined>(undefined);
  const [items, setItems] = useState<Deliverable[] | null | undefined>(undefined);
  const [overdue, setOverdue] = useState<number | null>(null);

  useEffect(() => {
    void reviewsApi.dashboard().then((r) => setReview(r.ok ? r.data : null));
    // switched off, the queries' routes answer "not found": no row, not an unknown one
    void technicalQueriesApi.metrics().then((r) => setQueries(r.ok ? r.data : !r.disconnected && r.error.code === "not_found" ? "off" : null));
    void deliverablesApi.list().then((r) => setItems(r.ok ? r.data.deliverables : null));
    void deliverablesApi.alerts().then((r) => setOverdue(r.ok ? r.data.alerts.length : null));
  }, []);

  if (review === undefined || queries === undefined || items === undefined) return null;
  const rows = [reviewsRow(review), queriesRow(queries), deliverablesRow(items, overdue)].filter((r): r is GlanceRow => r !== null);

  return (
    <section aria-labelledby="at-a-glance-title" data-testid="at-a-glance"
      className="mt-6 rounded-[var(--radius-lg)] border border-ink-700 bg-ink-850 p-4">
      <h2 id="at-a-glance-title" className="text-sm font-semibold text-slateish-200">At a glance</h2>
      <p data-testid="at-a-glance-summary" className="mt-1 text-sm text-slateish-200">{glanceLine(rows)}</p>
      <div className="relative mt-3 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs font-semibold text-slateish-400">
            <tr>
              <th scope="col" className="px-3 py-2"><span className="sr-only">Kind of work</span></th>
              <th scope="col" className="px-3 py-2">In</th>
              <th scope="col" className="px-3 py-2">Waiting</th>
              <th scope="col" className="px-3 py-2">Late</th>
              <th scope="col" className="px-3 py-2">Done</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} className="border-t border-ink-700/60" data-testid="at-a-glance-row">
                <th scope="row" className="px-3 py-2 font-medium text-slateish-200">{r.label}</th>
                <Cell value={r.inCount} />
                <Cell value={r.waiting} />
                <Cell value={r.late} tone="late" />
                <Cell value={r.done} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="mt-2 space-y-0.5 text-xs text-slateish-400">
        {rows.filter((r) => r.lateNote).map((r) => <li key={r.label}>{r.label}, late: {r.lateNote}.</li>)}
        <li>These counts cover only what you may open.</li>
      </ul>
    </section>
  );
}
