/**
 * #845 (Stage B, "AI numbers first"): what each AI step of this run did, as
 * the run stored it - the reader, the matcher, the AI engineering check and
 * the AI wording.
 *
 * EVERY LINE COMES FROM THE SERVER WITH ITS DENOMINATOR ("2 of 3 pages",
 * "of 4 proposed: 3 used"); this panel prints them verbatim and adds no
 * number of its own. Where the step ran ("local model" / "cloud model") is
 * shown only when the record names it.
 *
 * NULL RENDERS AS NOTHING: a step the run holds no record of is left out,
 * never shown as zero, and a run with no AI record shows no panel at all.
 */
import type { AiNumbers, AiStepNumbers } from "../../types/api";

const ORDER: (keyof AiNumbers)[] = ["reader", "matcher", "engineering_check", "wording"];

export function AiNumbersPanel({ numbers }: { numbers: AiNumbers | null | undefined }) {
  const steps = ORDER.map((key) => numbers?.[key]).filter((s): s is AiStepNumbers => Boolean(s));
  if (steps.length === 0) return null;
  return (
    <section aria-label="AI numbers for this run" data-testid="ai-numbers" className="text-sm">
      <p className="text-slateish-300">AI numbers for this run</p>
      <ul className="mt-1 space-y-1">
        {steps.map((step) => (
          <li key={step.step} data-testid={`ai-step-${step.step}`}>
            <span className="text-slateish-200">{step.step}</span>
            <span className="ml-2 text-xs text-slateish-400">
              {[step.state, step.where].filter(Boolean).join(", ")}
            </span>
            <ul className="mt-0.5 list-disc ps-5 text-xs text-slateish-400">
              {step.lines.map((line) => <li key={line}>{line}</li>)}
              {/* #842: said once - the AI check's own sentence may already carry it */}
              {step.local_instead && !step.lines.some((l) => l.includes(step.local_instead ?? "")) && (
                <li>{`This step ${step.local_instead}.`}</li>
              )}
            </ul>
          </li>
        ))}
      </ul>
    </section>
  );
}
