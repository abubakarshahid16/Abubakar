/**
 * What the machine is doing while a reader waits, and why it takes this long.
 *
 * A Tier 2 answer takes 20-75 seconds on this hardware. The screen used to
 * show one spinner reading "Searching the documents" for all of it, which
 * reads as broken - and a client who thinks it is broken never learns that
 * the slowness is the point: nothing leaves the machine, so the work has to
 * happen on a 15 W laptop CPU instead of in somebody's datacentre.
 *
 * NO FAKE PROGRESS. Every stage shown here was REPORTED BY THE BACKEND when it
 * actually happened (`/api/progress/{id}`), never inferred from the clock.
 * Retrieval usually finishes in about 2.5 s and generation takes the rest, so
 * a timer could guess the stage and be right most of the time - and on the run
 * where retrieval is slow it would tell the reader the model was writing while
 * the search was still going. There is also no percentage bar: the length of a
 * generation is unknown until it ends, so a bar would be an invention.
 *
 * The elapsed counter is the client's own, so it keeps counting even if a poll
 * is missed. It is the one number here that needs nothing from the server.
 */
import type { Progress } from "../../types/api";

const STAGES: { id: Progress["stage"]; label: string; blurb: string }[] = [
  {
    id: "retrieving",
    label: "Searching",
    blurb: "Keyword and vector search across the indexed documents.",
  },
  {
    id: "reranking",
    label: "Ranking",
    blurb: "A cross-encoder re-reads the candidates and scores them properly.",
  },
  {
    id: "reading",
    label: "Reading",
    blurb: "The best passages are prepared as evidence.",
  },
  {
    id: "generating",
    label: "Writing",
    blurb: "The local model writes an answer from those passages, and cites them.",
  },
];

function order(stage: Progress["stage"] | null): number {
  if (stage === null) return -1;
  if (stage === "done") return STAGES.length;
  return STAGES.findIndex((s) => s.id === stage);
}

export function LocalWork({
  elapsed,
  progress,
}: {
  /** Seconds, counted by the client. Never waits on a poll. */
  elapsed: number;
  /** null until the first poll returns - the stage is not guessed meanwhile. */
  progress: Progress | null;
}) {
  const current = order(progress?.stage ?? null);

  return (
    <div
      className="max-w-[52rem] rounded-lg border border-ink-700 bg-ink-850 p-4"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium text-slateish-200">
          {progress === null
            ? "Working on this machine"
            : STAGES[current]?.blurb ?? "Finishing"}
        </p>
        <span className="shrink-0 font-mono text-sm tabular-nums text-slateish-300">
          {elapsed}s
        </span>
      </div>

      <ol className="mt-3 flex flex-wrap gap-x-2 gap-y-1.5">
        {STAGES.map((s, i) => {
          // Three states, and none of them is a guess: done (the backend
          // reported a later stage), now (it reported this one), or not yet.
          const done = current > i;
          const now = current === i;
          return (
            <li key={s.id} className="flex items-center gap-2">
              <span
                className={[
                  "rounded px-2 py-0.5 text-xs",
                  done
                    ? "bg-ink-700 text-slateish-300"
                    : now
                      ? "bg-signal-500/20 text-signal-300 ring-1 ring-signal-500/50"
                      : "text-slateish-500",
                ].join(" ")}
              >
                {now && (
                  <span
                    aria-hidden="true"
              className="mr-1.5 inline-block h-2 w-2 motion-safe:animate-pulse rounded-full bg-signal-400 align-middle"
                  />
                )}
                {s.label}
                {now && progress?.detail ? (
                  <span className="ml-1.5 font-mono text-xs opacity-80">
                    {progress.detail}
                  </span>
                ) : null}
              </span>
              {i < STAGES.length - 1 && (
                <span aria-hidden="true" className="text-slateish-500">
                  ›
                </span>
              )}
            </li>
          );
        })}
      </ol>

      <p className="mt-3 border-t border-ink-700/60 pt-2.5 text-xs text-slateish-400">
        This runs entirely on this machine — a 15&nbsp;W laptop CPU, no GPU.{" "}
        <span className="text-slateish-300">Nothing you ask, and no part of any
        document, leaves it.</span>{" "}
        Writing the answer is the slow part and normally takes 20–50 seconds.
      </p>
    </div>
  );
}
