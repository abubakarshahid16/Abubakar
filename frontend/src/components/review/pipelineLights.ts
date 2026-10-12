/**
 * #791 (R25, owner approved 12 Oct): the review in five steps, each with a
 * green / amber / red light and a one-line reason, from what the run stored -
 * the run trace (#802) and the run's AI numbers (#845). No review logic here:
 * only which light the stored numbers earn.
 *
 *   green = the step completed and no AI part of it failed;
 *   amber = the step completed, but part of it fell back, timed out, was
 *           refused or was off (said which);
 *   red   = the step failed or produced nothing it should have.
 *
 * NEVER GREEN WHEN THE AI WAS ASKED AND RETURNED NOTHING, and never green on
 * a gap: a step whose record is missing says so, in amber, rather than
 * passing for a step that worked. A missing number is named, never shown as 0.
 */
import type { AiStepNumbers, ReviewRunSummary, ReviewTrace, ReviewTraceStep } from "../../types/api";

export type Light = "green" | "amber" | "red";

export interface PipelineStep {
  key: "read" | "standards" | "match" | "decide" | "crs";
  title: string;
  light: Light;
  /** One line: why this light. */
  reason: string;
  /** The numbers behind it, verbatim from the stored records. */
  details: string[];
}

function traceStep(trace: ReviewTrace | null, name: string): ReviewTraceStep | undefined {
  return trace?.steps.find((s) => s.step === name);
}

function num(value: number | null | undefined): number | null {
  return typeof value === "number" ? value : null;
}

/** The AI part of a step: amber reasons when it was off, incomplete or
 *  silent; null when it ran and returned something. */
function aiFallback(ai: AiStepNumbers | null | undefined, name: string, asked: number | null,
                    returned: number | null): string | null {
  if (!ai) return `no ${name} record for this run`;
  if (ai.state === "off") return `${name} off`;
  if (ai.state === "not run") return `${name} did not run`;
  if (ai.state === "incomplete") return `${name} incomplete`;
  if (asked !== null && asked > 0 && returned === 0) return `${name} was asked and returned nothing`;
  return null;
}

function readStep(run: ReviewRunSummary, trace: ReviewTrace | null): PipelineStep {
  const read = traceStep(trace, "READ");
  const ai = run.ai_numbers?.reader;
  const c = ai?.counts ?? {};
  const details = [read?.summary, ...(ai?.lines ?? [])].filter((l): l is string => Boolean(l));
  const base = { key: "read" as const, title: "Read the datasheet", details };
  if (!read) return { ...base, light: "amber", reason: "no read record for this run" };
  if (num(read.counts.values) === 0) return { ...base, light: "red", reason: "no value was read from the datasheet" };
  const added = num(c.ai_only);
  if ((c.timed_out ?? 0) > 0) {
    return { ...base, light: "amber",
      reason: `AI timed out on ${c.timed_out} of ${c.pages} pages, ${added ?? "an unrecorded number of"} values added` };
  }
  const returned = c.agreed === undefined ? null : (c.agreed ?? 0) + (c.conflicts ?? 0) + (c.ai_only ?? 0);
  const fallback = aiFallback(ai, "AI reader", num(c.pages_read), returned);
  if (fallback) return { ...base, light: "amber", reason: fallback };
  return { ...base, light: "green",
    reason: `AI read ${c.pages_read} of ${c.pages} pages; ${added} values added, ${c.agreed} agreed` };
}

function standardsStep(trace: ReviewTrace | null): PipelineStep {
  const step = traceStep(trace, "STANDARDS");
  const base = { key: "standards" as const, title: "Choose standards", details: step ? [step.summary] : [] };
  if (!step) return { ...base, light: "amber", reason: "no standards record for this run" };
  const chosen = num(step.counts.chosen);
  const missing = num(step.counts.cited_not_held);
  if (chosen === 0) return { ...base, light: "red", reason: "no standard was chosen" };
  if (missing) return { ...base, light: "amber", reason: `${missing} cited standard(s) not in the library` };
  return { ...base, light: "green", reason: `${chosen} standard(s) in scope` };
}

function matchStep(run: ReviewRunSummary, trace: ReviewTrace | null): PipelineStep {
  const rules = traceStep(trace, "RULES");
  const ai = run.ai_numbers?.matcher;
  const c = ai?.counts ?? {};
  const details = [rules?.summary, ...(ai?.lines ?? [])].filter((l): l is string => Boolean(l));
  const base = { key: "match" as const, title: "Match values to rules", details };
  if (!rules) return { ...base, light: "amber", reason: "no matching record for this run" };
  const findings = num(rules.counts.findings);
  const paired = num(rules.counts.paired);
  if (findings && paired === 0) return { ...base, light: "red", reason: `none of ${findings} requirements was paired with a value` };
  const fallback = aiFallback(ai, "AI matcher", num(c.asked), num(c.proposed));
  if (fallback) return { ...base, light: "amber", reason: fallback };
  return { ...base, light: "green",
    reason: `${paired} of ${findings} requirements paired; AI proposed ${c.proposed}, ${c.used} used, ${c.held} held` };
}

function decideStep(run: ReviewRunSummary, trace: ReviewTrace | null): PipelineStep {
  const decide = traceStep(trace, "DECIDE");
  const ai = run.ai_numbers?.engineering_check;
  const details = [decide?.summary, ...(ai?.lines ?? [])].filter((l): l is string => Boolean(l));
  const base = { key: "decide" as const, title: "Decide", details };
  if (run.findings_total === 0) return { ...base, light: "red", reason: "the run produced no findings" };
  if (decide?.warning) return { ...base, light: "amber", reason: decide.warning };
  const c = ai?.counts ?? {};
  // a check that ran and proposed nothing was asked and returned nothing
  const fallback = aiFallback(ai, "AI engineering check", ai ? 1 : null, num(c.proposed));
  if (fallback) return { ...base, light: "amber", reason: fallback };
  return { ...base, light: "green",
    reason: `${run.findings_total} findings decided; AI check kept ${c.kept} of ${c.proposed}` };
}

function crsStep(run: ReviewRunSummary, trace: ReviewTrace | null): PipelineStep {
  const crs = traceStep(trace, "CRS");
  const ai = run.ai_numbers?.wording;
  const issue = run.engineer_final_code
    ? "ready to issue to the contractor"
    : "the issue copy waits for the engineer's final code (the internal copy can be exported)";
  const details = [crs?.summary, ...(ai?.lines ?? []), `Export: ${issue}.`]
    .filter((l): l is string => Boolean(l));
  const base = { key: "crs" as const, title: "Write the CRS", details };
  if (!crs) return { ...base, light: "amber", reason: "no CRS record for this run" };
  if (crs.status === "failed") return { ...base, light: "red", reason: crs.warning ?? "the CRS could not be written" };
  const rows = num(crs.counts.rows);
  if (rows === 0) return { ...base, light: "red", reason: "the CRS has no rows" };
  const c = ai?.counts ?? {};
  const fallback = aiFallback(ai, "AI wording", num(c.tried), num(c.accepted));
  if (fallback) return { ...base, light: "amber", reason: fallback };
  return { ...base, light: "green", reason: `${rows} rows written, ${c.accepted} AI-worded` };
}

export function pipelineSteps(run: ReviewRunSummary, trace: ReviewTrace | null): PipelineStep[] {
  return [readStep(run, trace), standardsStep(trace), matchStep(run, trace),
          decideStep(run, trace), crsStep(run, trace)];
}
