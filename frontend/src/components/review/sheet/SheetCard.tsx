/**
 * One point on the Sheet screen (#967 PR 2), in the owner's order and words:
 * title, "We noticed", "The rule", "Our comment", two buttons, a trust line.
 *
 * EVERY ANSWER IS THE ISSUE GATE'S OWN DECISION (PF5, #885): accept or
 * reject through the same route the gate panel uses, with a reason, written
 * for every finding the card stands for. "Agree" needs no typing - the click
 * is the reason; "Not needed" leaves a comment off the sheet, so it asks why.
 * There is no un-confirm on the server by design, so a done card offers
 * "Change answer" (a new, recorded decision), never a silent undo.
 */
import { useEffect, useRef, useState } from "react";

import { reviews as reviewsApi } from "../../../api/client";
import type { ReviewFinding } from "../../../types/api";
import { orNothing } from "../reviewFormat";
import { type SheetCard as Card, cardTitle, groupLine, isAgreed, isNotNeeded, isTickFinding, trustLine, MIN_REASON } from "./sheetCards";

export const AGREE_REASON = "Engineer agreed on the review page: ask the contractor.";
/** rule_trust (#947): the tick is the PF5 accept on the finding; the server
 *  records it as the rule family's correct spot-check. */
export const TICK_REASON = "Engineer checked the safety field on the page and ticked it.";

export interface SheetCardProps {
  card: Card;
  runId: string;
  selected: boolean;
  standardNames: Map<string, string>;
  onSelect: () => void;
  onOpenRule: (finding: ReviewFinding) => void;
  onAnswered: () => void;
  /** #967 PR 4: scroll the datasheet to this card's page and pulse its frame
   *  (the T key does the same). */
  onShowOnPage?: () => void;
}

type Busy = { kind: "idle" } | { kind: "working" } | { kind: "error"; message: string };

export function SheetCard(props: SheetCardProps) {
  const { card, selected, onSelect } = props;
  const done = card.state !== "open";
  if (!selected) {
    return (
      <button
        type="button" onClick={onSelect}
        className="flex w-full items-center gap-2 rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 px-3 py-2 text-left text-sm text-slateish-200 hover:border-ink-600"
      >
        <span aria-hidden="true" className={done ? "text-signal-400" : isTickFinding(card.findings[0]) ? "text-signal-500" : "text-warn-500"}>{done ? "✓" : "●"}</span>
        <span className={`flex-1 truncate ${done ? "text-slateish-400" : ""}`}>{cardTitle(card)}</span>
        {done && <span className="text-xs text-slateish-500">{doneWords(card)}</span>}
      </button>
    );
  }
  return <OpenCard key={card.key} {...props} />;
}

function doneWords(card: Card): string {
  if (isTickFinding(card.findings[0])) return card.state === "agreed" ? "Ticked" : "Something is off";
  if (card.state === "agreed") return "Asked";
  if (card.state === "not_needed") return "Not needed";
  return "Answered";
}

function OpenCard({ card, runId, standardNames, onOpenRule, onAnswered, onShowOnPage }: SheetCardProps) {
  const leader = card.findings[0];
  const single = card.findings.length === 1;
  const done = card.state !== "open";
  const tick = isTickFinding(leader);
  const [busy, setBusy] = useState<Busy>({ kind: "idle" });
  const [why, setWhy] = useState("");
  const [askWhy, setAskWhy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(leader.engineer_comment ?? leader.required_action ?? "");
  const ref = useRef<HTMLElement | null>(null);
  // The opened card comes into view; jsdom and older engines have no scrollIntoView.
  useEffect(() => {
    const el = ref.current;
    if (el && typeof el.scrollIntoView === "function") {
      const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      el.scrollIntoView({ block: "nearest", behavior: still ? "auto" : "smooth" });
    }
  }, []);

  async function decide(decision: "accept" | "reject", reason: string) {
    setBusy({ kind: "working" });
    const targets = card.findings.filter((f) =>
      decision === "accept" ? !isAgreed(f) : !isNotNeeded(f));
    for (const f of targets) {
      const result = await reviewsApi.decideCrsFinding(runId, f.id, decision, reason);
      if (!result.ok) {
        setBusy({ kind: "error", message: result.error.message });
        onAnswered();
        return;
      }
    }
    setBusy({ kind: "idle" });
    setAskWhy(false);
    setWhy("");
    onAnswered();
  }

  function notNeeded() {
    if (!askWhy) { setAskWhy(true); return; }
    if (why.trim().length < MIN_REASON) {
      setBusy({ kind: "error", message: `Say why it is not needed (${MIN_REASON} characters or more).` });
      return;
    }
    void decide("reject", why.trim());
  }

  async function saveComment() {
    const text = draft.trim();
    if (!text) { setBusy({ kind: "error", message: "The comment cannot be empty." }); return; }
    setBusy({ kind: "working" });
    const result = await reviewsApi.update(leader.id, { engineer_comment: text });
    if (!result.ok) { setBusy({ kind: "error", message: result.error.message }); return; }
    setEditing(false);
    setBusy({ kind: "idle" });
    onAnswered();
  }

  const standard = standardNames.get(leader.standard_document_id ?? "") ?? "";
  const working = busy.kind === "working";
  return (
    <article
      ref={ref} aria-label={cardTitle(card)} data-selected-card=""
      className="sheet-card-in space-y-3 rounded-[var(--radius-md)] border border-signal-500/60 bg-ink-850 p-4 shadow-sm"
    >
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-semibold text-slateish-100">{cardTitle(card)}</h3>
          {groupLine(card) && <p className="text-xs text-slateish-400">{groupLine(card)}</p>}
        </div>
        {onShowOnPage && leader.contractor_page && (
          <button type="button" onClick={onShowOnPage} title="T"
            className="text-xs text-signal-300 underline-offset-2 hover:underline">
            Show on the page
          </button>
        )}
      </header>

      <section>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slateish-400">We noticed</h4>
        <p className="mt-1 text-sm text-slateish-200">{orNothing(leader.finding)}</p>
        {!single && (
          <ul className="mt-1 text-xs text-slateish-400">
            {card.findings.slice(1).map((f) => (
              <li key={f.id}>{[f.matched_phrase || f.contractor_section, f.contractor_page ? `p.${f.contractor_page}` : ""].filter(Boolean).join(" · ") || orNothing(f.finding)}</li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slateish-400">The rule</h4>
        <p className="mt-1 line-clamp-3 text-sm text-slateish-200">
          {orNothing(leader.requirement_source_text) || orNothing(leader.requirement)}
        </p>
        {(standard || leader.standard_clause) && (
          <button
            type="button" onClick={() => onOpenRule(leader)}
            className="mt-1 text-xs text-signal-300 underline-offset-2 hover:underline"
          >
            {[standard, leader.standard_clause ? `clause ${leader.standard_clause}` : ""].filter(Boolean).join(", ")}
            {leader.standard_page ? ` · open page ${leader.standard_page}` : " · open the rule"}
          </button>
        )}
      </section>

      {tick ? (
        <section>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slateish-400">Your check</h4>
          <p className="mt-1 text-sm text-slateish-100">
            A safety field: look at the value on the page yourself. Nothing goes to the contractor either way;
            your tick is recorded, and "something is off" takes the rule out of automatic use.
          </p>
        </section>
      ) : (
      <section>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slateish-400">Our comment</h4>
        {editing ? (
          <div className="mt-1 space-y-2">
            <label htmlFor={`comment-${leader.id}`} className="sr-only">Our comment</label>
            <textarea
              id={`comment-${leader.id}`} rows={3} value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="w-full rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-slateish-100"
            />
            <p className="text-xs text-slateish-400">Saving puts your words on the sheet and agrees it under your name.</p>
            <div className="flex gap-2">
              <button type="button" disabled={working} onClick={() => void saveComment()}
                className="rounded-[var(--radius-sm)] bg-signal-500 px-3 py-1.5 text-sm font-semibold text-ink-950 disabled:opacity-50">
                Save and agree
              </button>
              <button type="button" onClick={() => setEditing(false)}
                className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1.5 text-sm text-slateish-200">
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-1 flex items-start gap-2">
            <p className="flex-1 whitespace-pre-wrap text-sm text-slateish-100">
              {orNothing(leader.engineer_comment) || orNothing(leader.required_action) || orNothing(leader.finding)}
            </p>
            {single && !done && (
              <button type="button" onClick={() => setEditing(true)}
                className="text-xs text-signal-300 underline-offset-2 hover:underline">Edit</button>
            )}
          </div>
        )}
      </section>
      )}

      {done ? (
        <DoneRow card={card} working={working} onChange={() => {
          if (card.state === "not_needed") void decide("accept", tick ? TICK_REASON : AGREE_REASON);
          else setAskWhy(true);
        }} />
      ) : (
        <div className="flex flex-wrap gap-2">
          <button type="button" data-action="agree" disabled={working} onClick={() => void decide("accept", tick ? TICK_REASON : AGREE_REASON)}
            className="rounded-[var(--radius-sm)] bg-signal-500 px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50">
            {tick ? "I checked it, tick" : "Agree, ask the contractor"}
          </button>
          <button type="button" data-action="not-needed" disabled={working} onClick={notNeeded}
            className="rounded-[var(--radius-sm)] border border-ink-600 px-4 py-2 text-sm text-slateish-100 disabled:opacity-50">
            {tick ? "Something is off" : "Not needed"}
          </button>
        </div>
      )}

      {askWhy && (
        <div className="space-y-2">
          <label htmlFor={`why-${leader.id}`} className="block text-xs text-slateish-400">
            {tick
              ? "What is off? Your reason is kept, and the rule is taken out of automatic use until an engineer re-proves it."
              : "Why is this comment not needed? It is left off the sheet, and your reason is kept."}
          </label>
          <input
            id={`why-${leader.id}`} value={why} onChange={(e) => setWhy(e.target.value)}
            className="w-full rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-slateish-100"
          />
          <button type="button" disabled={working} onClick={notNeeded}
            className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1.5 text-sm text-slateish-100 disabled:opacity-50">
            {tick ? "Record that something is off" : "Leave it off the sheet"}
          </button>
        </div>
      )}

      {busy.kind === "error" && (
        <p role="alert" className="rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-sm text-danger-500">
          {busy.message}
        </p>
      )}

      <p className="text-xs text-slateish-500">{trustLine(card)}</p>
    </article>
  );
}

function DoneRow({ card, working, onChange }: { card: Card; working: boolean; onChange: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <span className="text-signal-300">✓ {isTickFinding(card.findings[0])
        ? (card.state === "agreed" ? "You checked it and ticked it." : "You said something is off: the rule is held for re-proof.")
        : card.state === "agreed" ? "You agreed: the contractor is asked."
        : card.state === "not_needed" ? "You said it is not needed: it is left off the sheet."
        : "Answered, part asked and part left off."}</span>
      <button type="button" disabled={working} onClick={onChange}
        className="text-xs text-slateish-300 underline-offset-2 hover:underline disabled:opacity-50">
        Change answer
      </button>
    </div>
  );
}
