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
import { startNewReview } from "./newReview";

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
 *  already knows. Left out, it is asked before anything is uploaded. */
export function NewReviewDropZone({ onStarted, isAdmin }: NewReviewDropZoneProps & { isAdmin?: boolean }) {
  const [phase, setPhase] = useState<NewReviewPhase>({ kind: "idle" });
  const [filename, setFilename] = useState<string | null>(null);
  /** Said when several files were dropped: one review takes one file. */
  const [onlyFirst, setOnlyFirst] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
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
    const outcome = await startNewReview(file, (next) => {
      if (mounted.current) setPhase(next);
    }, { isAdmin });
    // Gone (the reader left): the review runs on, but never drag them back.
    if (outcome.ok && mounted.current) onStarted(outcome.runId);
  }

  const words = phaseWords(phase, filename);

  return (
    <section aria-labelledby="new-review-heading" data-testid="new-review-drop-zone">
      <h2 id="new-review-heading" className="text-lg font-semibold text-slateish-100">New review</h2>
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
      </div>
    </section>
  );
}
