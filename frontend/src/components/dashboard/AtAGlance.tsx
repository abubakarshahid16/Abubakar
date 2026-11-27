/**
 * AT A GLANCE (owner, 26 Nov 2026, E5: "plain numbers: in, waiting, late, done; a one-line plain summary on every result; inside the
 * existing Dashboard"). A manager's view of the three kinds of work: contractor documents (their reviews), technical queries and CFCs,
 * and deliverables. Every number comes from a figure the app already serves (the review dashboard, the query counts, the deliverables
 * register and its overdue alerts); a figure that could not be loaded is said to be unknown, never shown as 0, and "late" says what it
 * is counted over (rule 4: every count states its boundary).
 */
import { useContext, useEffect, useState } from "react";

import { GlanceTiles } from "./GlanceTiles";
import { NavigationContext } from "../NavLink";
import { NEW_LOOK } from "../../look";
import { InfoFold } from "../look/LookParts";
import { deliverables as deliverablesApi, reviews as reviewsApi } from "../../api/client";
import { technicalQueriesApi } from "../../api/technicalQueries";
import type { Deliverable, ReviewDashboard } from "../../types/api";

export interface GlanceRow {
  label: string;
  /** null = could not be loaded (said as such, never 0). */
  inCount: number | null;
  waiting: number | null;
  /** In progress, NOT waiting for you: a review still running, a query the AI is still working on, being sent or with the contractor.
   *  null when it cannot be worked out (never 0 for an unknown, rule 4). */
  working?: number | null;
  /** A number only when it was counted over a stated, non-empty set (rule 4: a count over nothing is not a 0). */
  late: number | null;
  done: number | null;
  /** counted: `late` is a real count over `lateNote`'s set; no_due_dates: nothing open has a due date, so nothing can be late;
   *  not_tracked: this kind of work has no due date; unknown: a figure could not be loaded. */
  lateStatus: "counted" | "no_due_dates" | "not_tracked" | "unknown";
  /** What "late" is counted over, or why it is not counted. */
  lateNote: string;
}

const UNKNOWN_ROW = (label: string): GlanceRow => ({
  label, inCount: null, waiting: null, late: null, done: null, lateStatus: "unknown", lateNote: "could not be loaded",
});

export function reviewsRow(d: ReviewDashboard | null): GlanceRow {
  // ONE UNIT PER ROW: reviews (a contract or a specification is reviewed too, so counting documents in one column and reviews in the
  // next would not add up).
  if (!d) return UNKNOWN_ROW("Document reviews");
  const signed = typeof d.reviews_signed === "number" ? d.reviews_signed : null;
  // a review still RUNNING is not waiting for you (F's walk, 27 Nov 2026): it is in progress until it can be decided
  const waiting = d.reviews_awaiting_decision;
  const working = d.reviews_running;
  return {
    label: "Document reviews",
    inCount: signed === null ? null : waiting + working + signed,
    waiting,
    working,
    late: null,
    done: signed,
    lateStatus: "not_tracked",
    lateNote: "a review has no due date; see Deliverables for due dates",
  };
}

/** The query statuses that need nothing more from the team (the server's CLOSED_STATUSES: never waiting, never late). */
const QUERY_DONE = ["resolved"];
const QUERY_SET_ASIDE = ["duplicate", "cancelled"];

export function queriesRow(m: Record<string, number> | null | "off"): GlanceRow | null {
  if (m === "off") return null; // technical queries are switched off on this computer: no row
  if (!m || typeof m.total !== "number") return UNKNOWN_ROW("Technical queries and CFCs");
  const setAside = QUERY_SET_ASIDE.reduce((n, s) => n + (m[s] ?? 0), 0);
  const inCount = m.total - setAside;
  const done = QUERY_DONE.reduce((n, s) => n + (m[s] ?? 0), 0);
  // WAITING = waiting for a person (F's walk, 27 Nov 2026: "34 waiting for you" counted the 13 the AI was still working on): a reply
  // ready for approval, and an approved reply not sent yet (the engineer sends the Word file; H's read of #1998)
  const forPerson = ["awaiting_review", "approved", "send_pending"];
  const waiting = forPerson.every((k) => typeof m[k] === "number") ? forPerson.reduce((n, k) => n + m[k], 0) : null;
  const working = waiting === null ? null : Math.max(0, inCount - done - waiting);
  const row = { label: "Technical queries and CFCs", inCount, waiting, working, done };
  // late only with BOTH the count and its boundary, and only over a set that is not empty
  if (typeof m.overdue !== "number" || typeof m.open_with_due_date !== "number") {
    return { ...row, late: null, lateStatus: "unknown", lateNote: "could not be loaded" };
  }
  if (m.open_with_due_date === 0) return { ...row, late: null, lateStatus: "no_due_dates", lateNote: "no open query has a due date" };
  return { ...row, late: m.overdue, lateStatus: "counted", lateNote: `past the due date, of ${m.open_with_due_date} open with a due date` };
}

/** An overdue alert of the deliverables register (the server's own list; it also lists items due TODAY). */
export interface OverdueAlert { days_overdue: number }

export function deliverablesRow(items: Deliverable[] | null, alerts: OverdueAlert[] | null): GlanceRow {
  if (!items) return UNKNOWN_ROW("Deliverables");
  const done = items.filter((d) => d.status === "approved").length;
  const open = items.filter((d) => d.status !== "approved" && d.status !== "superseded");
  const row = { label: "Deliverables", inCount: items.length, waiting: open.length, done };
  // a due date the server can read (YYYY-MM-DD...): its alerts skip any other, so only these can ever be late
  const withDue = open.filter((d) => /^\d{4}-\d{2}-\d{2}/.test((d.due_date ?? "").trim())).length;
  if (withDue === 0) return { ...row, late: null, lateStatus: "no_due_dates", lateNote: "no open deliverable has a due date" };
  if (!alerts) return { ...row, late: null, lateStatus: "unknown", lateNote: "could not be loaded" };
  // past the due date, as for queries: an item due today is not late yet
  const late = alerts.filter((a) => a.days_overdue > 0).length;
  return { ...row, late, lateStatus: "counted", lateNote: `past the due date, of ${withDue} open with a due date` };
}

/** The one SHORT plain line above the table (owner, 26 Nov 2026: "one short plain line"): how much is waiting and whether anything is
 *  late, as a total. The per-kind numbers are in the table; what each figure counts over is behind the info button. Never "none late"
 *  where nothing could be late (rule 4), and an unknown figure is said, never left out. */
export function glanceLine(rows: GlanceRow[]): string {
  const known = rows.filter((r) => r.waiting !== null);
  const waiting = known.reduce((n, r) => n + (r.waiting ?? 0), 0);
  const someUnknown = known.length < rows.length;
  const counted = rows.filter((r) => r.lateStatus === "counted");
  const late = counted.reduce((n, r) => n + (r.late ?? 0), 0);
  const lateWords = late > 0 ? `${late} late` : counted.length ? "none late" : rows.some((r) => r.lateStatus === "unknown") ? "late unknown" : "nothing has a due date";
  return `${waiting} waiting${someUnknown ? " (some figures could not be loaded)" : ""}, ${lateWords}.`;
}

/** The owner's headline over the tiles (27 Nov 2026 03:34): "41 items are waiting for a decision". An unknown figure is said, never 0. */
export function waitingHeadline(rows: GlanceRow[]): string {
  const known = rows.filter((r) => r.waiting !== null);
  const n = known.reduce((sum, r) => sum + (r.waiting ?? 0), 0);
  const unknown = known.length < rows.length ? " (some figures could not be loaded)" : "";
  return `${n} item${n === 1 ? " is" : "s are"} waiting for a decision${unknown}`;
}

/** What a tile says under "done" when nothing can be late: never a dash. */
export function lateWords(r: GlanceRow): string | undefined {
  if (r.lateStatus === "counted") return r.late ? undefined : "none late";
  if (r.lateStatus === "unknown") return "late not known";
  return "no due dates set";
}

/** The tile's short name and the list it opens. */
export const TILE: Record<string, { name: string; view: "review" | "technicalQueries" | "deliverables" }> = {
  "Document reviews": { name: "Document reviews", view: "review" },
  "Technical queries and CFCs": { name: "Queries and CFCs", view: "technicalQueries" },
  Deliverables: { name: "Deliverables", view: "deliverables" },
};

function Cell({ value, tone, title }: { value: number | null; tone?: "late"; title?: string }) {
  if (value === null) return <td className="px-3 py-2 text-slateish-400" title={title}>—</td>;
  const late = tone === "late" && value > 0;
  return <td className={`px-3 py-2 text-lg font-semibold ${late ? "text-danger-500" : "text-slateish-100"}`}>{value}</td>;
}

export function AtAGlance() {
  const navigate = useContext(NavigationContext);
  const [review, setReview] = useState<ReviewDashboard | null | undefined>(undefined);
  const [queries, setQueries] = useState<Record<string, number> | null | "off" | undefined>(undefined);
  const [items, setItems] = useState<Deliverable[] | null | undefined>(undefined);
  const [alerts, setAlerts] = useState<OverdueAlert[] | null | undefined>(undefined);

  useEffect(() => {
    void reviewsApi.dashboard().then((r) => setReview(r.ok ? r.data : null));
    // switched off, the queries' routes answer "not found": no row, not an unknown one
    void technicalQueriesApi.metrics().then((r) => setQueries(r.ok ? r.data : !r.disconnected && r.error.code === "not_found" ? "off" : null));
    void deliverablesApi.list().then((r) => setItems(r.ok ? r.data.deliverables : null));
    void deliverablesApi.alerts().then((r) => setAlerts(r.ok ? r.data.alerts : null));
  }, []);

  // drawn once every figure has answered: a figure still loading is never shown as "unknown"
  if (review === undefined || queries === undefined || items === undefined || alerts === undefined) return null;
  const rows = [reviewsRow(review), queriesRow(queries), deliverablesRow(items, alerts)].filter((r): r is GlanceRow => r !== null);

  // THE OWNER'S THREE TILES (27 Nov 2026 03:34), built only from the shared kit (GlanceTiles.tsx, listed in kitPages.ts)
  if (NEW_LOOK) return <GlanceTiles rows={rows} onOpen={(view) => navigate?.(view)} />;

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
                <Cell value={r.late} tone="late" title={r.lateStatus === "counted" ? undefined : r.lateNote} />
                <Cell value={r.done} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <InfoFold title="What these numbers count" className="mt-2 text-xs">
        <ul className="space-y-0.5">
          {rows.map((r) => <li key={r.label}>{r.label}, late: {r.lateNote}.</li>)}
          <li>These counts cover only what you may open.</li>
        </ul>
      </InfoFold>
    </section>
  );
}
