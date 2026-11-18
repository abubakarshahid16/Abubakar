/**
 * The general review's comment CARDS (order 14, the planner's target design of 18 Nov 2026, owner: "not easy to read").
 *
 * One card per problem: a one-line title and a severity badge, then PAPER SAYS / RULE SAYS / WE ASK in that order, "Applies to" chips
 * (one per place, each opens that page), the quotes folded under "Show evidence", and the mark "AI, to be checked" with how the card was
 * proven. The severity is the server's (decided by code from the points, never from the wording); nothing is computed here. The summary
 * tiles filter the list; "Please confirm" cards are the confirmations, not sent, in their own closed part.
 *
 * Not built here: Accept / Edit / Reject per card. No engineer decision on a general review is stored yet, so no button pretends to.
 */
import { useMemo, useState } from "react";

import type { GeneralLine, GeneralReview, Severity } from "../../../api/generalReview";

export const SEVERITIES: Severity[] = ["Must fix", "Check a value", "Missing information", "Please confirm"];

/** Text label always shown beside the colour (colour is never the only signal). */
const TONE: Record<Severity, { badge: string; edge: string }> = {
  "Must fix": { badge: "border-pill-fail-border bg-pill-fail-bg text-pill-fail-fg", edge: "border-l-pill-fail-border" },
  "Check a value": { badge: "border-pill-review-border bg-pill-review-bg text-pill-review-fg", edge: "border-l-pill-review-border" },
  "Missing information": { badge: "border-pill-cond-border bg-pill-cond-bg text-pill-cond-fg", edge: "border-l-pill-cond-border" },
  "Please confirm": { badge: "border-ink-500 bg-ink-700 text-slateish-200", edge: "border-l-ink-500" },
};

export function hasCard(line: GeneralLine): boolean {
  return line.severity != null && !!line.title;
}

function pagesWords(line: GeneralLine): string {
  const pages = [...new Set((line.applies_to ?? []).map((a) => a.page).filter((p): p is number => p != null))].sort((a, b) => a - b);
  if (pages.length === 0) return "";
  return pages.length === 1 ? `page ${pages[0]}` : `pages ${pages.join(", ")}`;
}

function Box({ label, children, wide = false }: { label: string; children: string; wide?: boolean }) {
  if (!children) return null; // a part the card does not have renders as nothing
  return (
    <div className={`rounded-[var(--radius-sm)] border border-ink-600 bg-ink-850 p-3 ${wide ? "md:col-span-2" : ""}`}>
      <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slateish-400">{label}</h4>
      <p className="whitespace-pre-line text-sm text-slateish-100">{children}</p>
    </div>
  );
}

const CHIPS_SHOWN = 12;

export function CommentCard({ line, mark, onViewPage }: { line: GeneralLine; mark: string; onViewPage: (page: number) => void }) {
  const sev = (line.severity ?? "Check a value") as Severity;
  const tone = TONE[sev];
  const places = line.applies_to ?? [];
  const [allChips, setAllChips] = useState(false);
  const shownPlaces = allChips ? places : places.slice(0, CHIPS_SHOWN);
  const quotes = places.filter((a) => a.quote);
  return (
    <li data-testid="general-row" data-severity={sev} className={`space-y-3 rounded-[var(--radius-md)] border border-ink-600 border-l-4 bg-ink-800 p-4 ${tone.edge}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 data-testid="card-title" className="text-base font-semibold text-slateish-100">{line.title}</h3>
          <p className="text-xs text-slateish-400">{pagesWords(line) || line.field}</p>
        </div>
        <span data-testid="card-severity" className={`rounded-full border px-3 py-0.5 text-xs font-semibold ${tone.badge}`}>{sev}</span>
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        <Box label="Paper says">{line.paper_says ?? ""}</Box>
        <Box label="Rule says">{line.rule_says ?? ""}</Box>
        <Box label="We ask" wide>{line.we_ask ?? ""}</Box>
      </div>
      {places.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <em className="mr-1 not-italic text-slateish-400">Applies to</em>
          {shownPlaces.map((a, i) => {
            const text = [a.field, a.page != null ? `p${a.page}` : ""].filter(Boolean).join(" · ");
            return a.page != null
              ? <button key={i} type="button" aria-label={`page ${a.page}`} title={`Open page ${a.page}`} onClick={() => onViewPage(a.page!)}
                  className="rounded-[var(--radius-sm)] border border-ink-500 px-2 py-0.5 text-slateish-200 hover:bg-ink-700">{text}</button>
              : <span key={i} className="rounded-[var(--radius-sm)] border border-ink-500 px-2 py-0.5 text-slateish-200">{text}</span>;
          })}
          {places.length > CHIPS_SHOWN && (
            <button type="button" onClick={() => setAllChips((v) => !v)} className="text-signal-300 underline-offset-2 hover:underline">
              {allChips ? "show fewer" : `+${places.length - CHIPS_SHOWN} more`}
            </button>
          )}
        </div>
      )}
      {(quotes.length > 0 || line.comment) && (
        <details data-testid="card-evidence" className="text-sm text-slateish-300">
          <summary className="cursor-pointer">Show evidence{quotes.length > 0 ? ` (${quotes.length} quote${quotes.length === 1 ? "" : "s"})` : ""}</summary>
          <div className="mt-2 space-y-2">
            {line.comment && <p className="text-slateish-200">{line.comment}</p>}
            {quotes.map((a, i) => (
              <blockquote key={i} className="border-l-2 border-ink-500 pl-3 text-xs text-slateish-300">
                {a.page != null ? <span className="mr-2 text-slateish-400">page {a.page}</span> : null}{a.quote}
              </blockquote>
            ))}
            {line.quote_unverified && <p className="text-xs text-slateish-400">(code could not find this quote on the page)</p>}
          </div>
        </details>
      )}
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-slateish-400">
        <span data-testid="card-mark" className="rounded-[var(--radius-sm)] border border-dashed border-ink-500 px-2 py-0.5">
          {mark}{line.proven && line.proven !== mark ? ` · ${line.proven}` : ""}
        </span>
        {line.shown_label && <span className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-0.5">{line.shown_label}</span>}
      </div>
    </li>
  );
}

/** The four summary tiles. A severity with no count in the answer is left out (null renders as nothing), never 0. */
export function SeverityTiles({ counts, active, onPick }: {
  counts: Partial<Record<Severity, number>> | undefined; active: Severity | null; onPick: (s: Severity | null) => void;
}) {
  if (!counts) return null;
  return (
    <div data-testid="severity-tiles" className="flex flex-wrap gap-2">
      {SEVERITIES.filter((s) => counts[s] != null).map((s) => (
        <button key={s} type="button" aria-pressed={active === s} onClick={() => onPick(active === s ? null : s)}
          className={`min-w-[8.5rem] rounded-[var(--radius-md)] border px-3 py-2 text-left ${active === s ? "border-signal-400" : "border-ink-600"} bg-ink-800`}>
          <b className="block text-xl text-slateish-100">{counts[s]}</b>
          <span className="text-xs text-slateish-300">{s}{s === "Please confirm" ? " (separate part, not sent)" : ""}</span>
        </button>
      ))}
    </div>
  );
}

/** The comments as cards, with the severity and page filters. Lines without a card (an older answer) keep the plain row. */
export function CommentCards({ review, mark, onViewPage, renderPlain }: {
  review: GeneralReview; mark: string; onViewPage: (page: number) => void; renderPlain: (l: GeneralLine) => React.ReactNode;
}) {
  const [severity, setSeverity] = useState<Severity | null>(null);
  const [page, setPage] = useState<number | null>(null);
  const pages = useMemo(() => [...new Set(review.comments.flatMap((c) => (c.applies_to ?? []).map((a) => a.page)).filter((p): p is number => p != null))].sort((a, b) => a - b), [review.comments]);
  const shown = review.comments.filter((c) => (severity == null || c.severity === severity) && (page == null || (c.applies_to ?? []).some((a) => a.page === page)));
  const confirmations = review.confirmations ?? [];
  const anyCard = review.comments.some(hasCard);
  return (
    <div className="space-y-3">
      {anyCard && <SeverityTiles counts={review.counts.by_severity} active={severity} onPick={setSeverity} />}
      {anyCard && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span data-testid="card-filter-count" className="text-slateish-300">{shown.length === review.comments.length && severity == null && page == null ? `All ${shown.length}` : `${shown.length} of ${review.comments.length}`}</span>
          {pages.length > 1 && (
            <select aria-label="Show comments that apply to this page" value={page ?? ""} onChange={(e) => setPage(e.target.value === "" ? null : Number(e.target.value))}
              className="rounded-[var(--radius-sm)] border border-ink-500 bg-ink-850 px-2 py-1 text-sm text-slateish-100">
              <option value="">By page: all</option>
              {pages.map((p) => <option key={p} value={p}>page {p}</option>)}
            </select>
          )}
          {(severity != null || page != null) && <button type="button" onClick={() => { setSeverity(null); setPage(null); }} className="text-signal-300 underline-offset-2 hover:underline">Clear filters</button>}
        </div>
      )}
      {shown.length === 0 && <p className="text-sm text-slateish-300">{review.comments.length === 0 ? "This review has no comments." : "No comment matches this filter."}</p>}
      <ul className="space-y-3">{shown.map((l) => hasCard(l) ? <CommentCard key={`${l.n}-${l.item_id}`} line={l} mark={mark} onViewPage={onViewPage} /> : renderPlain(l))}</ul>
      {confirmations.length > 0 && severity == null && page == null && (
        <details data-testid="general-confirmations" className="rounded-[var(--radius-sm)] border border-ink-600 p-3">
          <summary className="cursor-pointer text-sm text-slateish-200">
            Confirmations, not sent ({confirmations.length}): the value is stated and nothing is suspected; the vendor is only asked to confirm it
          </summary>
          <ul className="mt-2 space-y-3">
            {confirmations.map((l) => hasCard(l)
              ? <CommentCard key={`c-${l.n}-${l.item_id}`} line={l} mark={mark} onViewPage={onViewPage} />
              : renderPlain(l))}
          </ul>
        </details>
      )}
    </div>
  );
}
