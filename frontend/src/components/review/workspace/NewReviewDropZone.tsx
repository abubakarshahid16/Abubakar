/**
 * OWNER: builder D. "New review": drop a file (or choose one) and the review
 * starts by itself. From the landing page that is two clicks ("Choose a
 * file", then the file in the picker) or one drag; never more than three.
 *
 * Each step is said in plain words while it runs; a failure stops there and
 * says why, and no review is started. One review takes one file: when
 * several are dropped, the first is used and the page says so.
 *
 * Leaving the page mid-way does not cancel the review (it may still start,
 * and the finished notice still says so), but nothing moves the reader to
 * the new run once this zone is gone.
 */
import { useEffect, useRef, useState } from "react";

import type { NewReviewDropZoneProps, NewReviewPhase } from "./contract";
import { type AskFirst, type OfferMark, continueNewReview, markAndReview, markOfferWords, startNewReview } from "./newReview";
import { priorDecisionWords } from "./priorDecisionWords";

function phaseWords(phase: NewReviewPhase, filename: string | null): string | null {
  const name = filename ?? "your file";
  switch (phase.kind) {
    case "uploading": return `Uploading ${name}: ${phase.percent}%`;
    case "marking": return `Marking ${name} as a document from a contractor…`;
    case "waiting": return `Reading ${name} in. This can take a few minutes…`;
    case "starting": return "Starting the review…";
    case "started": return "The review has started.";
    default: return null;
  }
}

/** `isAdmin`: whether the reader is an administrator, when the screen
 *  already knows. Left out, it is asked before anything is uploaded.
 *  `heading`: the zone's own title; null when it sits inside a card that
 *  already has one (the v2.1 landing's "New review" card). */
export function NewReviewDropZone({ onStarted, isAdmin, heading = "New review" }: NewReviewDropZoneProps & {
  isAdmin?: boolean;
  heading?: string | null;
}) {
  const [phase, setPhase] = useState<NewReviewPhase>({ kind: "idle" });
  const [filename, setFilename] = useState<string | null>(null);
  /** Said when several files were dropped: one review takes one file. */
  const [onlyFirst, setOnlyFirst] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  /** v2.1 L10: the dropped file is already in the library under another
   *  role; an administrator may choose to re-mark it (one confirm). */
  const [offer, setOffer] = useState<OfferMark | null>(null);
  const [confirming, setConfirming] = useState(false);
  /** v2.1: the dropped file is already a contractor submittal whose latest
   *  review is signed, coded or unchanged; asked before anything starts. */
  const [ask, setAsk] = useState<AskFirst | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const busy = phase.kind !== "idle" && phase.kind !== "error" && phase.kind !== "started";

  async function begin(files: FileList | File[] | null) {
    const all = files ? Array.from(files) : [];
    const file = all[0];
    if (!file || busy) return;
    setFilename(file.name);
    setOnlyFirst(all.length > 1 ? file.name : null);
    setOffer(null);
    setConfirming(false);
    setAsk(null);
    const outcome = await startNewReview(file, (next) => {
      if (mounted.current) setPhase(next);
    }, { isAdmin });
    if (!outcome.ok && "offerMark" in outcome && mounted.current) setOffer(outcome.offerMark);
    if (!outcome.ok && "askFirst" in outcome && mounted.current) setAsk(outcome.askFirst);
    // Gone (the reader left): the review runs on, but never drag them back.
    if (outcome.ok && mounted.current) onStarted(outcome.runId);
  }

  /** The administrator confirmed: re-mark through the existing role write,
   *  then the review starts like a new upload. */
  async function markAndStart() {
    if (!offer || busy) return;
    const target = offer;
    setOffer(null);
    setConfirming(false);
    const outcome = await markAndReview(target, filename ?? "your file", (next) => {
      if (mounted.current) setPhase(next);
    }, { isAdmin });
    if (outcome.ok && mounted.current) onStarted(outcome.runId);
  }

  /** The reader said yes to the ask-first question. */
  async function goOn() {
    if (!ask || busy) return;
    const target = ask;
    setAsk(null);
    const outcome = await continueNewReview(target, (next) => {
      if (mounted.current) setPhase(next);
    }, { isAdmin });
    if (outcome.ok && mounted.current) onStarted(outcome.runId);
  }

  const words = phaseWords(phase, filename);

  return (
    <section aria-labelledby={heading !== null ? "new-review-heading" : undefined} aria-label={heading === null ? "Drop a file to start a new review" : undefined} data-testid="new-review-drop-zone">
      {heading !== null && (
        <h2 id="new-review-heading" className="text-lg font-semibold text-slateish-100">{heading}</h2>
      )}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void begin(e.dataTransfer.files);
        }}
        className={[
          "mt-2 rounded-lg border-2 border-dashed p-6 text-center motion-safe:transition-colors",
          dragging ? "border-signal-500 bg-signal-500/10" : "border-ink-600 bg-ink-850/50",
        ].join(" ")}
      >
        <p className="text-sm text-slateish-300">
          Drop a contractor's PDF or Word file here and the review starts by itself, or{" "}
          <button
            type="button"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
            className="font-medium text-signal-400 underline decoration-dotted underline-offset-4 hover:text-signal-300 disabled:opacity-50"
          >
            choose a file
          </button>
        </p>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.docx"
          aria-label="Choose a contractor file to review"
          className="sr-only"
          onChange={(e) => {
            void begin(e.target.files);
            e.target.value = "";
          }}
        />
        {onlyFirst && (
          <p data-testid="only-first-file" className="mt-3 text-sm text-slateish-300">Only the first file was used: {onlyFirst}</p>
        )}
        {words && (
          <p role="status" className="mt-3 text-sm text-slateish-200">{words}</p>
        )}
        {phase.kind === "uploading" && (
          <div
            className="mx-auto mt-2 h-1 w-full max-w-md overflow-hidden rounded bg-ink-700"
            role="progressbar"
            aria-label={`Uploading ${filename ?? "your file"}`}
            aria-valuenow={phase.percent}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div className="h-full bg-signal-500" style={{ width: `${phase.percent}%` }} />
          </div>
        )}
        {phase.kind === "error" && (
          <p role="alert" className="mt-3 text-sm text-danger-500">{phase.message}</p>
        )}
        {ask && (
          <span role="group" aria-label="Start a new review?" data-testid="drop-ask-first" className="mt-3 flex flex-wrap items-center justify-center gap-2 text-sm text-slateish-200">
            <span>{ask.filename}: {priorDecisionWords(ask.prior)}</span>
            <button
              type="button" onClick={() => void goOn()}
              className="rounded-[var(--radius-md)] bg-signal-500 px-3 py-1.5 text-sm font-medium text-ink-950 hover:bg-signal-400"
            >
              Yes, start a new review
            </button>
            <button
              type="button" onClick={() => setAsk(null)}
              className="rounded-[var(--radius-md)] border border-ink-600 px-3 py-1.5 text-sm font-medium text-slateish-100 hover:border-signal-500"
            >
              Cancel
            </button>
          </span>
        )}
        {offer && phase.kind === "error" && isAdmin !== false && (
          <div className="mt-3 text-sm text-slateish-200" data-testid="mark-offer">
            {confirming ? (
              <span role="group" aria-label="Mark as contractor submittal?" className="flex flex-wrap items-center justify-center gap-2">
                <span>{markOfferWords(offer)}</span>
                <button
                  type="button" onClick={() => void markAndStart()}
                  className="rounded-[var(--radius-md)] bg-signal-500 px-3 py-1.5 text-sm font-medium text-ink-950 hover:bg-signal-400"
                >
                  Yes, mark it and start the review
                </button>
                <button
                  type="button" onClick={() => setConfirming(false)}
                  className="rounded-[var(--radius-md)] border border-ink-600 px-3 py-1.5 text-sm font-medium text-slateish-100 hover:border-signal-500"
                >
                  Cancel
                </button>
              </span>
            ) : (
              <button
                type="button" onClick={() => setConfirming(true)}
                className="rounded-[var(--radius-md)] border border-ink-600 px-3 py-1.5 text-sm font-medium text-slateish-100 hover:border-signal-500"
              >
                Mark as contractor submittal and review
              </button>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
