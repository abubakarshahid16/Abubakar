/**
 * #791 (R25): the review in five steps - read, choose standards, match,
 * decide, write the CRS - each with a green / amber / red light and one line
 * saying why (`pipelineLights`). The numbers come from the run's stored trace
 * and its AI numbers; nothing is recomputed. The lines behind each light open
 * under it, and a count of findings opens those findings (`onShowStatus`).
 */
import { useEffect, useState } from "react";

import { reviews as reviewsApi } from "../../api/client";
import type { ReviewRunSummary, ReviewTrace } from "../../types/api";
import { type Light, pipelineSteps } from "./pipelineLights";
import { statusRank, statusLabel, withDenominator } from "./reviewFormat";

const LIGHT: Record<Light, { label: string; className: string }> = {
  green: { label: "Green", className: "bg-signal-500" },
  amber: { label: "Amber", className: "bg-warn-500" },
  red: { label: "Red", className: "bg-danger-500" },
};

export function ReviewStepsPanel({ run, onShowStatus }: {
  run: ReviewRunSummary;
  /** #791: show the run's findings of this status (a count was clicked). */
  onShowStatus?: (status: string) => void;
}) {
  const [trace, setTrace] = useState<ReviewTrace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let live = true;
    void reviewsApi.reviewTrace(run.review_run_id).then((r) => {
      if (!live) return;
      if (r.ok) setTrace(r.data); else setError(r.error.message);
      setLoaded(true);
    });
    return () => { live = false; };
  }, [run.review_run_id]);

  if (!loaded) return <p className="text-xs text-slateish-400">Loading the review steps…</p>;
  const steps = pipelineSteps(run, trace);
  return (
    <section aria-label="Review steps" data-testid="review-steps" className="text-sm">
      <p className="text-slateish-300">The review in five steps</p>
      {error && (
        <p data-testid="review-steps-error" className="text-xs text-warn-500">
          The run's step record could not be loaded ({error}); the steps below say what is missing.
        </p>
      )}
      <ol className="mt-1 space-y-1">
        {steps.map((step, i) => (
          <li key={step.key} data-testid={`step-${step.key}`} data-light={step.light}>
            <details>
              <summary className="cursor-pointer">
                <span aria-hidden className={`mr-2 inline-block h-2.5 w-2.5 rounded-full ${LIGHT[step.light].className}`} />
                <span className="text-slateish-200">{`${i + 1}. ${step.title}`}</span>
                <span className="ml-2 text-xs text-slateish-400">{`${LIGHT[step.light].label}: ${step.reason}`}</span>
              </summary>
              {step.details.length > 0 && (
                <ul className="mt-0.5 list-disc ps-8 text-xs text-slateish-400">
                  {step.details.map((line) => <li key={line}>{line}</li>)}
                </ul>
              )}
              {onShowStatus && step.links && step.links.length > 0 && (
                <p className="mt-0.5 flex flex-wrap gap-2 ps-8 text-xs" data-testid={`step-${step.key}-links`}>
                  {[...step.links].sort((a, b) => statusRank(a.status) - statusRank(b.status)).map((link) => (
                    <button key={link.status} type="button" className="underline"
                            onClick={() => onShowStatus(link.status)}>
                      {`${statusLabel(link.status)} ${withDenominator(link.count, link.total)}`}
                    </button>
                  ))}
                </p>
              )}
            </details>
          </li>
        ))}
      </ol>
    </section>
  );
}
