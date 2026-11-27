/**
 * The general review's comment CARDS (order 14, the planner's target design of 18 Nov 2026, owner: "not easy to read").
 *
 * One card per problem: a one-line title and a severity badge, then PAPER SAYS / RULE SAYS / WE ASK in that order, "Applies to" chips
 * (one per place, each opens that page), the quotes folded under "Show evidence", and the mark "AI, to be checked" with how the card was
 * proven. The severity is the server's (decided by code from the points, never from the wording); nothing is computed here. The summary
 * tiles filter the list; "Please confirm" cards are the confirmations, not sent, in their own closed part.
 *
 * Each card has Accept / Edit / Reject: the engineer's decision, stored append-only on the server (the latest one is shown; the earlier
 * ones stay). Edit needs the engineer's text, Reject a one-line reason. Only a signed-in user who may read the
 * paper can decide; the server's own sentence is shown when it refuses. No contractor copy follows from a decision here.
 */
import { useEffect, useMemo, useState } from "react";

import { type CommentDecision, type DecisionState, type GeneralLine, type GeneralReview, type Severity, generalReview } from "../../../api/generalReview";
import { dayTimeWords } from "../workspace/landing/dateWords";
import { Button, LinkButton, ShowMore, Tiles } from "../../kit/Kit";

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
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-slateish-400">{label}</h4>
      <p className="whitespace-pre-line text-sm text-slateish-100">{children}</p>
    </div>
  );
}

const CHIPS_SHOWN = 12;
const CHIP_VALUE = 36;
/** A long value is cut with a mark; the whole text is under "Show evidence" and in the chip's title. */
const clip = (v: string) => (v.length > CHIP_VALUE ? `${v.slice(0, CHIP_VALUE)}…` : v);
const MIN_REASON = 10;

export type DecideFn = (line: GeneralLine, state: DecisionState, text?: string, reason?: string) => Promise<string | null>;

/** The decision on a card: what the engineer decided (by whom, when), and the three buttons. Edit and Reject ask for what they need. */
function DecisionBar({ line, decision, onDecide }: { line: GeneralLine; decision: CommentDecision | null | undefined; onDecide: DecideFn }) {
  const [open, setOpen] = useState<"edit" | "reject" | null>(null);
  const [text, setText] = useState(line.we_ask ?? "");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function send(state: DecisionState) {
    setBusy(true);
    setProblem(null);
    const bad = await onDecide(line, state, state === "edit" ? text : undefined, state === "reject" ? reason : undefined);
    setBusy(false);
    if (bad) setProblem(bad);
    else setOpen(null);
  }

  const tone = decision?.state === "reject" ? "text-pill-fail-fg" : decision ? "text-pill-pass-fg" : "text-slateish-400";
  return (
    <div data-testid="card-decision" className="space-y-2 border-t border-ink-600 pt-3">
      <div className="flex flex-wrap items-center gap-2">
        {decision ? (
          <p data-testid="card-decision-state" className={`text-sm ${tone}`}>
            <strong>{decision.words}</strong> by {decision.by}, {dayTimeWords(decision.at)}
            {decision.state === "edit" && decision.text ? <span className="block text-slateish-200">Engineer's text: {decision.text}</span> : null}
            {decision.state === "reject" && decision.reason ? <span className="block text-slateish-200">Reason: {decision.reason}</span> : null}
            {decision.revisions > 1 ? <span className="ml-2 text-xs text-slateish-400">({decision.revisions} decisions on record; the latest counts)</span> : null}
          </p>
        ) : <p className="text-sm text-slateish-400">Not decided yet</p>}
        <span className="ml-auto flex gap-1.5">
          <Button variant="primary" size="sm" disabled={busy} onClick={() => void send("accept")}>Accept</Button>
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => { setOpen(open === "edit" ? null : "edit"); setProblem(null); }}>Edit</Button>
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => { setOpen(open === "reject" ? null : "reject"); setProblem(null); }}>Reject</Button>
        </span>
      </div>
      {open === "edit" && (
        <div className="space-y-1">
          <label className="block text-xs text-slateish-400" htmlFor={`edit-${line.n}`}>Your text for this comment</label>
          <textarea id={`edit-${line.n}`} value={text} onChange={(e) => setText(e.target.value)} rows={3}
            className="w-full rounded-[var(--radius-sm)] border border-ink-500 bg-ink-850 p-2 text-sm text-slateish-100" />
          <div className="flex gap-2">
            <Button variant="primary" size="sm" disabled={busy || !text.trim()} onClick={() => void send("edit")}>Save my text</Button>
            <LinkButton tone="inherit" size="sm" onClick={() => setOpen(null)}>Cancel</LinkButton>
          </div>
        </div>
      )}
      {open === "reject" && (
        <div className="space-y-1">
          <label className="block text-xs text-slateish-400" htmlFor={`reject-${line.n}`}>One line: why this comment is rejected</label>
          <input id={`reject-${line.n}`} value={reason} onChange={(e) => setReason(e.target.value)}
            className="w-full rounded-[var(--radius-sm)] border border-ink-500 bg-ink-850 p-2 text-sm text-slateish-100" />
          <div className="flex gap-2">
            <Button variant="primary" size="sm" disabled={busy || reason.trim().length < MIN_REASON} onClick={() => void send("reject")}>Save rejection</Button>
            <LinkButton tone="inherit" size="sm" onClick={() => setOpen(null)}>Cancel</LinkButton>
          </div>
        </div>
      )}
      {problem && <p role="alert" data-testid="card-decision-problem" className="text-sm text-danger-500">{problem}</p>}
    </div>
  );
}

export function CommentCard({ line, mark, onViewPage, decision, onDecide }: {
  line: GeneralLine; mark: string; onViewPage: (page: number) => void; decision?: CommentDecision | null; onDecide?: DecideFn;
}) {
  const sev = (line.severity ?? "Check a value") as Severity;
  const tone = TONE[sev];
  const places = line.applies_to ?? [];
  const [allChips, setAllChips] = useState(false);
  const shownPlaces = allChips ? places : places.slice(0, CHIPS_SHOWN);
  // every member's quote with ITS OWN page (older runs carry one quote on the place: it goes with the place's page)
  const quotes = places.flatMap((a) => (a.quotes && a.quotes.length > 0 ? a.quotes : a.quote ? [{ page: a.page ?? null, quote: a.quote }] : []));
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
            const name = a.tag || a.field;
            const value = a.value ? clip(a.value) : "";
            const label = [name, value].filter(Boolean).join(" · ");
            const pages = a.pages && a.pages.length > 0 ? a.pages : a.page != null ? [a.page] : [];
            const title = (p: number) => `Open page ${p}${a.field ? `: ${a.field}` : ""}${a.value ? `: ${a.value}` : ""}`;
            const cls = "rounded-[var(--radius-sm)] border border-ink-500 px-2 py-0.5 text-slateish-200";
            if (pages.length === 1) {
              return <button key={i} type="button" aria-label={`page ${pages[0]}`} title={title(pages[0])} onClick={() => onViewPage(pages[0])}
                className={`${cls} hover:bg-ink-700`}>{[name, `p${pages[0]}`, value].filter(Boolean).join(" · ")}</button>;
            }
            if (pages.length === 0) return <span key={i} className={cls}>{label}</span>;
            // one chip per field: its name once, then a button per page
            return (
              <span key={i} className={`${cls} inline-flex flex-wrap items-center gap-1`} data-testid="chip-field">
                <span>{label}</span>
                {pages.map((p) => (
                  <Button variant="secondary" key={p} aria-label={`page ${p}`} title={title(p)} onClick={() => onViewPage(p)}>p{p}</Button>
                ))}
              </span>
            );
          })}
          {places.length > CHIPS_SHOWN && (
            <LinkButton tone="action" onClick={() => setAllChips((v) => !v)}>
              {allChips ? "show fewer" : `+${places.length - CHIPS_SHOWN} more`}
            </LinkButton>
          )}
        </div>
      )}
      {(quotes.length > 0 || line.comment) && (
        <details data-testid="card-evidence" className="text-sm text-slateish-300">
          <summary className="cursor-pointer">Show evidence{quotes.length > 0 ? ` (${quotes.length} quote${quotes.length === 1 ? "" : "s"})` : ""}</summary>
          <div className="mt-2 space-y-2">
            {line.comment && <p className="text-slateish-200">{line.comment}</p>}
            {quotes.map((a, i) => (
              <blockquote key={i} className="border-l-2 border-ink-500 pl-3 text-xs text-slateish-300" data-testid="card-quote">
                {a.page != null ? <span className="mr-2 text-slateish-400">page {a.page}</span> : null}{a.quote}
              </blockquote>
            ))}
            {line.quote_unverified && <p className="text-xs text-slateish-400">(code could not find this quote on the page)</p>}
          </div>
        </details>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs text-slateish-400">
        <span data-testid="card-mark" className="rounded-[var(--radius-sm)] border border-dashed border-ink-500 px-2 py-0.5">
          {mark}{line.proven && line.proven !== mark ? ` · ${line.proven}` : ""}
        </span>
        {line.shown_label && <span className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-0.5">{line.shown_label}</span>}
        {line.paired && (
          <span data-testid="card-paired" className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-0.5">Values paired by the AI; compared by code</span>
        )}
        {line.cut?.map((c, i) => (
          <span key={i} data-testid="card-cut" className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-0.5">Part answered on page {(c.pages ?? [c.page]).join(", ")} taken out. Before: {c.before}</span>
        ))}
        {line.readers && (
          <span data-testid="card-readers" className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-0.5"
            title={[line.readers.first && `First reader: ${line.readers.first}`, line.readers.second && `Second reader: ${line.readers.second}`, line.readers.reason].filter(Boolean).join(". ")}>
            Two readers differ{line.readers.first || line.readers.second ? ` (${line.readers.first || "?"} / ${line.readers.second || "?"})` : ""}
          </span>
        )}
      </div>
      {onDecide && <DecisionBar line={line} decision={decision ?? line.decision} onDecide={onDecide} />}
    </li>
  );
}

/** The four summary tiles. A severity with no count in the answer is left out (null renders as nothing), never 0. */
export function SeverityTiles({ counts, active, onPick }: {
  counts: Partial<Record<Severity, number>> | undefined; active: Severity | null; onPick: (s: Severity | null) => void;
}) {
  if (!counts) return null;
  return (
    // one even row from the kit's tile grid (H's audit #58, 27 Nov 2026: each box was as wide as its own words)
    <Tiles label="Comments by kind" testId="severity-tiles">
      {SEVERITIES.filter((s) => counts[s] != null).map((s) => (
        <button key={s} type="button" aria-pressed={active === s} onClick={() => onPick(active === s ? null : s)}
          className={`rounded-[var(--radius-md)] border px-3 py-2 text-left ${active === s ? "border-signal-400" : "border-ink-600"} bg-ink-800`}>
          <b className="block text-xl text-slateish-100">{counts[s]}</b>
          <span className="text-xs text-slateish-300">{s}{s === "Please confirm" ? " (separate part, not sent)" : ""}</span>
        </button>
      ))}
    </Tiles>
  );
}

/** Comment cards drawn at first, and added per press of "Show more" (H's audit #59, 27 Nov 2026: 57 cards made a 40,000 px page). */
export const COMMENTS_PAGE = 15;

/** The comments as cards, with the severity and page filters. Lines without a card (an older answer) keep the plain row. */
export function CommentCards({ review, mark, onViewPage, renderPlain, onDecided }: {
  review: GeneralReview; mark: string; onViewPage: (page: number) => void; renderPlain: (l: GeneralLine) => React.ReactNode;
  /** Called after a decision was recorded (the sign-off bar re-reads what is still undecided). */
  onDecided?: () => void;
}) {
  const [severity, setSeverity] = useState<Severity | null>(null);
  const [page, setPage] = useState<number | null>(null);
  const [limit, setLimit] = useState(COMMENTS_PAGE);
  // a new filter starts again from the first cards
  useEffect(() => setLimit(COMMENTS_PAGE), [severity, page]);
  const [decided, setDecided] = useState<Record<string, CommentDecision>>({});
  /** Records one decision on the server; null when it was recorded, else the server's own sentence. The card then shows it. */
  const decide = (part: "comment" | "confirmation"): DecideFn => async (line, state, text, reason) => {
    const res = await generalReview.decide(review.paper_document_id, { run_id: review.run_id, comment: line.n, part, state, text, reason });
    if (!res.ok) return res.error.code === "unauthenticated" ? "Sign in to record a decision." : res.error.message;
    setDecided((was) => ({ ...was, [`${part}:${line.n}`]: res.data.decision }));
    onDecided?.();
    return null;
  };
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
          {(severity != null || page != null) && <LinkButton tone="action" onClick={() => { setSeverity(null); setPage(null); }}>Clear filters</LinkButton>}
        </div>
      )}
      {shown.length === 0 && <p className="text-sm text-slateish-300">{review.comments.length === 0 ? "This review has no comments." : "No comment matches this filter."}</p>}
      <ul className="space-y-3">{shown.slice(0, limit).map((l) => hasCard(l) ? <CommentCard key={`${l.n}-${l.item_id}`} line={l} mark={mark} onViewPage={onViewPage} decision={decided[`comment:${l.n}`]} onDecide={decide("comment")} /> : renderPlain(l))}</ul>
      <ShowMore testId="comments-more" shown={Math.min(limit, shown.length)} total={shown.length} step={COMMENTS_PAGE} onMore={() => setLimit((n) => n + COMMENTS_PAGE)} />
      {confirmations.length > 0 && severity == null && page == null && (
        <details data-testid="general-confirmations" className="rounded-[var(--radius-sm)] border border-ink-600 p-3">
          <summary className="cursor-pointer text-sm text-slateish-200">
            Confirmations, not sent ({confirmations.length}): the value is stated and nothing is suspected; the vendor is only asked to confirm it
          </summary>
          <ul className="mt-2 space-y-3">
            {confirmations.map((l) => hasCard(l)
              ? <CommentCard key={`c-${l.n}-${l.item_id}`} line={l} mark={mark} onViewPage={onViewPage} decision={decided[`confirmation:${l.n}`]} onDecide={decide("confirmation")} />
              : renderPlain(l))}
          </ul>
        </details>
      )}
    </div>
  );
}
