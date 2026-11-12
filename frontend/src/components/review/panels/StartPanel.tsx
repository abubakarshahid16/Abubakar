/**
 * The pre-start panel behind "Check it" (owner, 12 Nov 2026: "Show engine, whether text leaves the Mac, and cost before start",
 * and the screen lists every document that will leave before the review starts). It loads the plan for the chosen engine,
 * shows it in the plan's own words, lists the documents (`LeavingList`) and starts with exactly the list shown.
 *
 * FAIL CLOSED: when the plan cannot be loaded, no Claude start is offered; Local only stays possible (nothing leaves).
 */
import { useEffect, useState } from "react";

import { type Engine, type ReviewPlan, reviewPlan } from "../../../api/reviewPlan";
import { LeavingList } from "./LeavingList";

const CHOICES: { value: Engine; label: string }[] = [
  { value: "automatic", label: "Automatic" },
  { value: "claude", label: "Claude" },
  { value: "local", label: "Local only" },
];

type Loaded = { kind: "loading" } | { kind: "ready"; plan: ReviewPlan } | { kind: "failed" };

export function StartPanel({ submittalId, starting, onStart, onCancel }: {
  submittalId: string;
  starting: boolean;
  onStart: (engine: Engine, shownDocumentIds: string[]) => void;
  onCancel: () => void;
}) {
  const [engine, setEngine] = useState<Engine>("automatic");
  const [loaded, setLoaded] = useState<Loaded>({ kind: "loading" });

  useEffect(() => {
    let live = true;
    setLoaded({ kind: "loading" });
    reviewPlan
      .plan(submittalId, engine)
      .then((result) => {
        if (live) setLoaded(result.ok ? { kind: "ready", plan: result.data } : { kind: "failed" });
      })
      .catch(() => {
        if (live) setLoaded({ kind: "failed" });
      });
    return () => {
      live = false;
    };
  }, [submittalId, engine]);

  const failed = loaded.kind === "failed";
  const plan = loaded.kind === "ready" ? loaded.plan : null;
  // A plan that could not be loaded offers Local only and nothing else; a refused plan offers no start.
  const choices = failed ? CHOICES.filter((c) => c.value === "local") : CHOICES;
  const listUnreadable = plan?.documents.unreadable === true;
  const chosen: Engine = failed ? "local" : engine;
  const canStart = !starting && (chosen === "local" ? true : plan !== null && !plan.refused && !listUnreadable);

  function start() {
    if (chosen === "local") return onStart("local", []);
    if (plan) onStart(chosen, plan.documents.leaving.map((d) => d.id));
  }

  const cost = plan?.cost;
  // The explicit choice of Claude is the consent: say plainly, before Start, that a contract's text goes out.
  const sendsContract = chosen === "claude" && plan?.text_leaves === true && plan.documents.leaving.some((d) => d.contract);
  const draftNote = chosen === "claude" && plan?.text_leaves === true && plan.unscored ? plan.unscored_note : undefined;
  return (
    <div role="dialog" aria-label="Before the review starts"
      className="space-y-3 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 p-3 text-sm">
      <fieldset className="flex flex-wrap gap-3">
        <legend className="sr-only">Engine</legend>
        {choices.map((c) => (
          <label key={c.value} className="flex items-center gap-1 text-slateish-100">
            <input type="radio" name="review-engine" checked={chosen === c.value}
              onChange={() => setEngine(c.value)} />
            {c.label}
          </label>
        ))}
      </fieldset>
      {loaded.kind === "loading" && <p className="text-slateish-300" aria-live="polite">Working out what would run…</p>}
      {failed && (
        <p role="alert" className="text-danger-500">
          The plan could not be loaded, so Claude is not offered. Local only keeps everything on this Mac.
        </p>
      )}
      {plan && (
        <>
          {plan.sentence && <p className="text-slateish-200">{plan.sentence}</p>}
          <p className="font-medium text-slateish-100">Text leaves this Mac: {plan.text_leaves ? "yes" : "no"}</p>
          <p className="text-slateish-300">
            {cost?.at_most_usd != null ? (cost.basis ?? `At most USD ${cost.at_most_usd}`) : "No cost: nothing is sent to Claude."}
          </p>
          {plan.refused && <p role="alert" className="text-danger-500">{plan.refused}</p>}
          {listUnreadable && (
            <p role="alert" className="text-danger-500">
              {plan.documents.summary ?? "The documents that would leave could not be worked out, so no Claude start is offered."}
            </p>
          )}
          {sendsContract && (
            <p role="note" className="font-medium text-slateish-100" data-testid="contract-line">
              This sends the contract's text to Claude (Anthropic). You chose Claude for this review.
            </p>
          )}
          {draftNote && <p role="note" className="text-slateish-300">{draftNote} Internal copy only.</p>}
          <LeavingList
            leaving={plan.documents.leaving}
            notSent={plan.documents.not_sent}
            notReadable={plan.documents.not_readable}
            textLeaves={plan.text_leaves}
          />
        </>
      )}
      <div className="flex gap-2">
        <button type="button" onClick={start} disabled={!canStart}
          className="rounded-[var(--radius-sm)] bg-signal-500 px-4 py-2 font-semibold text-ink-950 disabled:opacity-50">
          Start review
        </button>
        <button type="button" onClick={onCancel}
          className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-slateish-300">
          Cancel
        </button>
      </div>
    </div>
  );
}
