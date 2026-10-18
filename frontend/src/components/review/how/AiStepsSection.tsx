/**
 * Section 4: the AI steps, from `ai_numbers` (#845), `ai_check_status` and
 * `requirement_split.reader`. The counts are the ones the server stored
 * under each step's `counts`, named by their key; the server's own lines
 * (each with its denominator) are printed verbatim beneath. Rule 1 (#805):
 * each step says whether it is on or off by default.
 */
import type { AiStepNumbers, ReviewRunSummary } from "../../../types/api";
import { AI_STEP_DEFAULTS, NOT_RECORDED, defaultLine, readerOf } from "./howData";
import { HowSection, type HowSectionMeta } from "./HowPrimitives";

export const AI_META: HowSectionMeta = {
  id: "ai-steps", number: 4, title: "AI steps",
  explains: "Which AI steps ran on this review, on which model, and how often each one was asked, answered, was confirmed by code or was refused. Code verifies every AI answer; the AI never decides a verdict.",
};

/** Which stored count stands for each column, per step. A step with no key
 *  for a column shows NOT_RECORDED there. */
const COLUMNS = ["asked", "proposed", "confirmed", "refused", "timed_out"] as const;
type Column = (typeof COLUMNS)[number];
const COLUMN_LABEL: Record<Column, string> = {
  asked: "Asked", proposed: "Proposed", confirmed: "Confirmed by code", refused: "Refused", timed_out: "Timed out / unavailable",
};
/** What each count is a count of (from `backend/app/ai_numbers.py`), so a
 *  number is never bare: the reader's pages and its values differ. */
const COUNT_UNITS: Record<string, Partial<Record<Column, string>>> = {
  reader: { asked: "pages", proposed: "pages", confirmed: "values", refused: "values", timed_out: "pages" },
  matcher: { asked: "requirements", proposed: "requirements", confirmed: "requirements", refused: "requirements", timed_out: "requirements" },
  clause_checks: { asked: "sentences", proposed: "sentences", refused: "sentences", timed_out: "sentences" },
  engineering_check: { asked: "items", proposed: "items", confirmed: "items", refused: "items" },
  wording: { asked: "CRS rows", proposed: "CRS rows", confirmed: "CRS rows", refused: "CRS rows" },
};
const COUNT_KEYS: Record<string, Partial<Record<Column, string>>> = {
  reader: { asked: "pages", proposed: "pages_read", confirmed: "agreed", refused: "refused_by_gate", timed_out: "timed_out" },
  matcher: { asked: "asked", proposed: "proposed", confirmed: "used", refused: "refused_by_rule", timed_out: "unavailable" },
  clause_checks: { asked: "asked", proposed: "proposed", refused: "refused", timed_out: "could_not_read" },
  engineering_check: { asked: "requested_items", proposed: "proposed_items", confirmed: "kept_items", refused: "rejected" },
  wording: { asked: "tried", proposed: "accepted", confirmed: "accepted", refused: "refused" },
};

interface StepView {
  key: string;
  state: string | null;
  where: string | null;
  model: string | null;
  lines: string[];
  counts: Record<string, number>;
  countsSource: string;
}

/** The engineering check's stored counts; `rejected` is the sum of the
 *  stored per-reason rejections (`ai_check_status.rejected`). */
function engineeringCounts(run: ReviewRunSummary): Record<string, number> {
  const s = run.ai_check_status;
  if (!s) return {};
  return {
    calls_made: s.calls_made, requested_items: s.requested_items, proposed_items: s.proposed_items,
    kept_items: s.kept_items, rejected: Object.values(s.rejected ?? {}).reduce((a, b) => a + b, 0),
  };
}

function stepViews(run: ReviewRunSummary): StepView[] {
  const ai = run.ai_numbers ?? null;
  const reader = readerOf(run);
  const of = (key: string, step: AiStepNumbers | null | undefined, extra: Partial<StepView> = {}): StepView => ({
    key, state: step?.state ?? null, where: step?.where ?? null, model: step?.model ?? null,
    lines: step?.lines ?? [], counts: step?.counts ?? {}, countsSource: `ai_numbers.${key}.counts`, ...extra,
  });
  return [
    of("reader", ai?.reader, {
      state: ai?.reader?.state ?? (reader ? (reader.engine === "off" ? "off" : "ran") : null),
      model: ai?.reader?.model ?? reader?.model ?? null,
      where: ai?.reader?.where ?? (reader && reader.engine !== "off" ? `engine ${reader.engine}` : null),
    }),
    of("matcher", ai?.matcher),
    of("clause_checks", ai?.clause_checks),
    { key: "applicability", state: null, where: null, model: null, lines: [], counts: {}, countsSource: "(not on the run object)" },
    { key: "applicability_reasoning", state: null, where: null, model: null, lines: [], counts: {}, countsSource: "(not on the run object)" },
    of("engineering_check", ai?.engineering_check, {
      state: ai?.engineering_check?.state ?? (run.ai_check_status ? (run.ai_check_status.ran ? (run.ai_check_status.complete ? "ran" : "incomplete") : "not run") : null),
      counts: { ...engineeringCounts(run), ...(ai?.engineering_check?.counts ?? {}) },
      countsSource: "ai_check_status",
      lines: ai?.engineering_check?.lines ?? (run.ai_check_status ? [run.ai_check_status.plain] : []),
    }),
    of("wording", ai?.wording),
  ];
}

function CountCell({ step, column }: { step: StepView; column: Column }) {
  const key = COUNT_KEYS[step.key]?.[column];
  const value = key !== undefined ? step.counts[key] : undefined;
  const unit = COUNT_UNITS[step.key]?.[column];
  if (typeof value !== "number") {
    return <td className="py-1 pr-3 text-xs italic text-slateish-400">{NOT_RECORDED}</td>;
  }
  return (
    <td className="py-1 pr-3 tabular-nums text-slateish-100">
      {value.toLocaleString()}{unit ? ` ${unit}` : ""} <span className="text-xs text-slateish-500">({key})</span>
    </td>
  );
}

function StepRow({ step }: { step: StepView }) {
  const meta = AI_STEP_DEFAULTS[step.key];
  return (
    <li data-testid={`ai-step-${step.key}`} className="space-y-1 py-2">
      <p className="text-sm">
        <span className="font-medium text-slateish-100">{meta?.label ?? step.key}</span>
        <span className="ml-2 text-xs text-slateish-400">
          {step.state ? `${step.state}${step.where ? `, ${step.where}` : ""}` : NOT_RECORDED}
          {" · model: "}{step.model ?? NOT_RECORDED}
        </span>
      </p>
      <div className="overflow-x-auto">
        <table className="text-sm">
          <caption className="sr-only">
            {meta?.label ?? step.key} counts, from {step.countsSource}
          </caption>
          <thead>
            <tr className="text-left text-xs text-slateish-400">
              {COLUMNS.map((col) => <th key={col} scope="col" className="py-1 pr-3 font-medium">{COLUMN_LABEL[col]}</th>)}
            </tr>
          </thead>
          <tbody>
            <tr>{COLUMNS.map((col) => <CountCell key={col} step={step} column={col} />)}</tr>
          </tbody>
        </table>
        <p className="text-xs text-slateish-500">counts from {step.countsSource}</p>
      </div>
      {step.lines.length > 0 && (
        <ul className="list-disc ps-5 text-xs text-slateish-300">
          {step.lines.map((line) => <li key={line}>{line}</li>)}
        </ul>
      )}
      <p className="text-xs text-slateish-400">{defaultLine(step.key)}</p>
    </li>
  );
}

export function AiStepsSection({ run }: { run: ReviewRunSummary }) {
  return (
    <HowSection meta={AI_META}>
      <ul className="divide-y divide-ink-700">
        {stepViews(run).map((step) => <StepRow key={step.key} step={step} />)}
      </ul>
    </HowSection>
  );
}
