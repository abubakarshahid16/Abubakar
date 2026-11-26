/**
 * HOME: the three jobs first (owner, 26 Nov 2026, G9: "we want an app that is very easy to use; ... some features are not even
 * understandable"). Three big buttons in everyday words, one line each on what the job does, the open work beside it, and one obvious
 * next button. Counts come from the screens' own calls (the review dashboard and the query counts by status); a count that could not be
 * read is not shown (never a 0), and each count says whose work it counts. Built from the shared component set (components/ui).
 */
import { useEffect, useState } from "react";

import { reviews as reviewsApi } from "../api/client";
import { technicalQueriesApi } from "../api/technicalQueries";
import type { ViewId } from "../components/Shell";
import { Button, Card, PageHeader } from "../components/ui";
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

/** The Home page itself, from its counts: the live Home and the preview (invented counts) draw the same thing. */
export function HomeJobs({ counts, queriesOn, onNavigate }: { counts: HomeCounts; queriesOn: boolean; onNavigate: (view: ViewId) => void }) {
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
    <section className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8" aria-labelledby="home-title">
      <PageHeader id="home-title" title="What do you want to do?" purpose="Pick what you want to do below. Each button opens the screen where you do it." />
      <Button tone="primary" size="lg" onClick={() => onNavigate(next.view)} data-testid="home-next" className="mt-6">
        {next.label}
      </Button>
      <ul className="mt-8 grid gap-4 md:grid-cols-3">
        {jobs.map((job) => (
          <Card as="li" key={job.view} className="flex flex-col" data-testid={`home-job-${job.view}`}>
            <Button size="lg" disabled={Boolean(job.off)} onClick={() => onNavigate(job.view)} className="w-full justify-start text-left">
              {job.title}
            </Button>
            <p className="mt-3 text-sm text-slateish-300">{job.off ?? job.line}</p>
            {job.count && <p className="mt-3 text-sm font-semibold text-signal-300">{job.count}</p>}
          </Card>
        ))}
      </ul>
    </section>
  );
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

  return <HomeJobs counts={counts} queriesOn={queriesOn} onNavigate={onNavigate} />;
}
