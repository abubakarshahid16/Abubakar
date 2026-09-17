/**
 * The advisory recommendation.
 *
 * Not a documented requirement, and the card never lets that be forgotten: the
 * advisory label sits in the <summary> so it stays visible when the card is
 * collapsed, and the engineer-review sentence the plan mandates is rendered on
 * every recommendation, verbatim.
 *
 * Confidence is a WORD, never a number, bar or percentage - a number would be a
 * claim of calibration that nothing here can back. The word was computed from a
 * checklist of countable facts (docs/design-analysis-and-synthesis.md), and the
 * checklist is shown so the reader can see WHY it says "low". There is no
 * "high"; the type forbids it and no branch here renders it.
 */
import type { Recommendation } from "../../types/analysis";
import { CitedText } from "./SummaryCard";

const REVIEW_SENTENCE = "Review and approval by a qualified engineer is required.";

export function RecommendationCard({
  recommendation,
  onCite,
}: {
  recommendation: Recommendation | null;
  onCite: (evidenceId: string) => void;
}) {
  if (recommendation === null) {
    return <p className="text-sm text-slateish-500">No recommendation was generated.</p>;
  }

  const r = recommendation;
  const fired = r.checks.filter((c) => c.fired).length;

  return (
    <details
      open
      className="card-3d accent-edge relative surface-card rounded-[var(--radius-md)] border border-info-500/30 bg-info-500/[0.05]"
    >
      <summary className="cursor-pointer list-item px-4 py-3 text-xs font-semibold uppercase tracking-wider text-info-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-info-500">
        AI Advisory — not a documented requirement
      </summary>

      <div className="border-t border-info-500/20 px-4 pb-4">
        <p
          role="note"
          className="mt-3 rounded-[var(--radius-xs)] border border-warn-500/60 bg-warn-500/[0.12] px-3 py-2 text-sm font-semibold text-warn-500"
        >
          {REVIEW_SENTENCE}
        </p>

        <p className="model-prose mt-3 text-[15px] text-slateish-200">
          <CitedText text={r.text} evidenceIds={r.citation_ids} onCite={onCite} />
        </p>

        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          <dt className="text-slateish-500">Basis</dt>
          <dd className="text-slateish-200">
            {r.basis === "documents_only"
              ? "Based on documents only"
              : "Based on documents and public market sample"}
            {r.basis === "documents_and_public_market" && (
              <span className="ml-2 text-xs font-semibold uppercase tracking-wider text-warn-500">
                market rows are sample data, not live
              </span>
            )}
          </dd>

          <dt className="text-slateish-500">Confidence</dt>
          <dd className="text-slateish-200">
            {r.confidence === null ? (
              <span className="text-slateish-500">not assessed</span>
            ) : (
              <span className="font-semibold">{r.confidence}</span>
            )}
            {r.checks.length > 0 && (
              <span className="ml-2 text-xs text-slateish-500">
                {fired} of {r.checks.length} check{r.checks.length === 1 ? "" : "s"} fired
              </span>
            )}
          </dd>
        </dl>

        {r.checks.length > 0 && (
          <div className="mt-3">
            <p className="text-xs uppercase tracking-wide text-slateish-500">
              How the confidence word was computed
            </p>
            <ul className="mt-1.5 space-y-1">
              {r.checks.map((c) => (
                <li key={c.label} className="flex items-baseline gap-2 text-sm">
                  <span
                    className={[
                      "w-16 shrink-0 font-mono text-xs",
                      c.fired ? "text-warn-500" : "text-slateish-500",
                    ].join(" ")}
                  >
                    {c.fired ? "▲ fired" : "— clear"}
                  </span>
                  <span className={c.fired ? "text-slateish-200" : "text-slateish-400"}>
                    {c.label}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-1.5 text-xs text-slateish-500">
              A fired check lowers confidence. "High" is never issued: nothing here is calibrated.
            </p>
          </div>
        )}
      </div>
    </details>
  );
}
