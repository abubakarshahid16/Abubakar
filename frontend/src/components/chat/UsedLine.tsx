/**
 * The grey line above an answer: what was used and how long it took, how many
 * of its points were found on the page, and - on request - how it got there.
 *
 * Every word here is the server's (`used_line`, `verification`, `steps`); the
 * screen adds none. In particular the "found on the page" badge renders only
 * when the server sent a verification, which it does only where that is
 * literally true (chat_presentation.verification) - never a count of citation
 * numbers standing in for a count of checked points.
 */
import { useId, useState } from "react";

import type { ChatStep, ChatVerification } from "../../types/api";

export function verificationText(v: ChatVerification): string {
  return `${v.verified} of ${v.total} point${v.total === 1 ? "" : "s"} found on the page`;
}

export function VerificationBadge({ verification }: { verification: ChatVerification }) {
  const all = verification.verified === verification.total;
  return (
    <span
      className={[
        "inline-flex items-center gap-1 rounded-[var(--radius-full)] border px-2 py-0.5 text-xs",
        all
          ? "border-signal-500/40 bg-signal-500/10 text-signal-300"
          : "border-warn-500/40 bg-warn-500/10 text-warn-500",
      ].join(" ")}
    >
      <span aria-hidden>{all ? "✓" : "!"}</span>
      {verificationText(verification)}
    </span>
  );
}

export function StepList({ steps }: { steps: ChatStep[] }) {
  return (
    <ul className="space-y-1">
      {steps.map((s, i) => (
        <li key={`${s.label}-${i}`} className="flex items-center gap-2 text-sm text-slateish-300">
          {s.done ? (
            <span aria-hidden className="w-3 text-center text-signal-400">✓</span>
          ) : (
            <span aria-hidden className="mx-0.5 h-2 w-2 rounded-full bg-warn-500 motion-safe:animate-pulse" />
          )}
          <span>
            {s.label}
            {s.count != null && <span className="text-slateish-500"> · {s.count.toLocaleString()}</span>}
          </span>
          {!s.done && <span className="sr-only">(in progress)</span>}
        </li>
      ))}
    </ul>
  );
}

export function UsedLine({
  text,
  verification,
  steps,
  method,
  label,
}: {
  text: string | null | undefined;
  verification?: ChatVerification | null;
  steps?: ChatStep[];
  /** One sentence on how the points were checked, when they were. */
  method?: string | null;
  /** A standing label the answer must carry, e.g. "not the document's words". */
  label?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  const hasDetail = (steps?.length ?? 0) > 0 || Boolean(verification);
  if (!text && !verification && !hasDetail && !label) return null;
  return (
    <div className="mb-2">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-slateish-500">
        <div className="flex flex-wrap items-center gap-2">
          {text && <span data-testid="used-line">{text}</span>}
          {verification && <VerificationBadge verification={verification} />}
          {label && <span className="text-slateish-400">{label}</span>}
        </div>
        {hasDetail && (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={panel}
            onClick={() => setOpen((o) => !o)}
            className="text-xs text-signal-400 underline decoration-signal-500/40 underline-offset-2 hover:text-signal-300"
          >
            How I got this {open ? "▴" : "▾"}
          </button>
        )}
      </div>
      {hasDetail && open && (
        <div id={panel} className="mt-2 rounded-[var(--radius-sm)] border border-ink-700 bg-ink-850 px-3 py-2.5">
          {(steps?.length ?? 0) > 0 && <StepList steps={steps!} />}
          {verification && (
            <p className="mt-2 text-xs text-slateish-400">
              {verification.method === "verbatim quotation"
                ? "The answer is the document's own words, so each quoted passage is on its page by definition."
                : "Each point's quoted words were looked up on the page it cites; a point whose words were not there was removed before you saw it."}
              {method ? ` ${method}` : ""}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/** Live progress while an answer is being written. */
export function ProgressSteps({ steps }: { steps: ChatStep[] }) {
  if (steps.length === 0) return null;
  return (
    <div
      role="status"
      aria-label="Progress"
      className="mb-3 rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 px-3 py-2.5"
    >
      <StepList steps={steps} />
    </div>
  );
}
