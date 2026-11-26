/**
 * HOME: the three jobs first (owner, 26 Nov 2026, G9: "we want an app that is very easy to use; ... some features are not even
 * understandable"). Three big buttons in everyday words, one line each on what the job does, the open work beside it, and one obvious
 * next button. Counts come from the screens' own calls (the review dashboard and the query counts by status); a count that could not be
 * read is not shown (never a 0), and each count says whose work it counts.
 */
import { useEffect, useState } from "react";

import { reviews as reviewsApi } from "../api/client";
import { technicalQueriesApi } from "../api/technicalQueries";
import type { ViewId } from "../components/Shell";
import type { AuthStatus } from "../types/api";

/** The query states that wait for our side: read, prepared, drafted or sent back for changes, not yet approved. */
export const QUERY_STATES_WAITING = ["received", "triage", "drafting", "awaiting_review", "changes_requested"] as const;

export interface HomeCounts {
  reviewsWaiting: number | null;
  queriesWaiting: number | null;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** The one next step: the open work first (reviews, then queries), else the first job. */
export function nextStep(counts: HomeCounts, queriesOn: boolean): { label: string; view: ViewId } {
  if (counts.reviewsWaiting) {
    return { label: `Open the ${plural(counts.reviewsWaiting, "review", "reviews")} waiting for your decision`, view: "review" };
  }
  if (queriesOn && counts.queriesWaiting) {
    return { label: `Open the ${plural(counts.queriesWaiting, "query", "queries")} waiting for an answer`, view: "technicalQueries" };
  }
  return { label: "Review a contractor document", view: "review" };
}

export function HomeView({ auth, onNavigate }: { auth: AuthStatus | null; onNavigate: (view: ViewId) => void }) {
  const queriesOn = auth?.technical_queries === true;
  const [counts, setCounts] = useState<HomeCounts>({ reviewsWaiting: null, queriesWaiting: null });

  useEffect(() => {
    let live = true;
    void reviewsApi.dashboard().then((result) => {
      if (live && result.ok) setCounts((c) => ({ ...c, reviewsWaiting: result.data.reviews_awaiting_decision }));
    });
    if (queriesOn) {
      void technicalQueriesApi.metrics().then((result) => {
        if (!live || !result.ok) return;
        const waiting = QUERY_STATES_WAITING.reduce((sum, state) => sum + (result.data[state] ?? 0), 0);
        setCounts((c) => ({ ...c, queriesWaiting: waiting }));
      });
    }
    return () => {
      live = false;
    };
  }, [queriesOn]);

  const next = nextStep(counts, queriesOn);
  const jobs: Array<{ view: ViewId; title: string; line: string; count: string | null; off?: string }> = [
    {
      view: "review",
      title: "Review a contractor document",
      line: "Pick the contractor's document; the app checks it against our standards and writes a comment sheet for an engineer to sign.",
      count: counts.reviewsWaiting === null ? null : `${plural(counts.reviewsWaiting, "review", "reviews")} waiting for your decision (of the reviews you may see)`,
    },
    {
      view: "technicalQueries",
      title: "Answer a contractor query (TQ / CFC)",
      line: "Read the contractor's question, see the contract clauses that answer it, and approve a reply.",
      count: !queriesOn || counts.queriesWaiting === null ? null : `${plural(counts.queriesWaiting, "query", "queries")} waiting for an answer (of the queries you may see)`,
      off: queriesOn ? undefined : "Switched off on this server. An administrator can switch it on.",
    },
    {
      view: "chat",
      title: "Ask a question about our documents",
      line: "Type a question; the answer quotes our documents with the page it comes from.",
      count: null,
    },
  ];

  return (
    <section className="mx-auto w-full max-w-4xl px-4 py-8" aria-labelledby="home-title">
      <h1 id="home-title" className="text-2xl font-semibold text-slateish-100">What do you want to do?</h1>
      <p className="mt-1 text-sm text-slateish-300" data-testid="screen-purpose">
        Pick one of the three jobs below. Each button opens the screen where you do it.
      </p>
      <button type="button" onClick={() => onNavigate(next.view)} data-testid="home-next"
        className="mt-4 rounded-[var(--radius-sm)] bg-signal-500 px-4 py-2 text-sm font-semibold text-white">
        {next.label}
      </button>
      <ul className="mt-6 grid gap-4 md:grid-cols-3">
        {jobs.map((job) => (
          <li key={job.view} className="flex flex-col rounded-lg border border-ink-700 bg-ink-850 p-4" data-testid={`home-job-${job.view}`}>
            <button type="button" disabled={Boolean(job.off)} onClick={() => onNavigate(job.view)}
              className="rounded-[var(--radius-sm)] bg-ink-700 px-3 py-3 text-left text-base font-semibold text-slateish-100 hover:bg-ink-600 disabled:opacity-50">
              {job.title}
            </button>
            <p className="mt-2 text-sm text-slateish-300">{job.off ?? job.line}</p>
            {job.count && <p className="mt-2 text-sm font-semibold text-signal-300">{job.count}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}
