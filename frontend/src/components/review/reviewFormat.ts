/**
 * How a review reads on screen.
 *
 * THE UI OBEYS THE SAME HONESTY RULES AS THE ENGINE (CLAUDE.md rule 4), and
 * they are collected here rather than spread across four components:
 *
 *  - null renders as NOTHING, never 0 and never a guess;
 *  - every count shows its denominator;
 *  - confidence never reads "high";
 *  - MISSING_INFORMATION is never coloured or worded as a failure. A field
 *    nobody filled in is a question for the contractor, not a breach, and a
 *    red badge would turn 1,578 unanswered requirements into 1,578 accusations;
 *  - NOT_IN_DOCUMENT_SCOPE is neither a failure NOR the contractor's omission
 *    (B9): its words never say "missing" and its tone is not missing's;
 *  - a nominal estimate says it is nominal.
 */
import type { ComplianceStatus, ReviewRunSummary } from "../../types/api";

/**
 * The order a reviewer's attention should travel in.
 *
 * NON_COMPLIANT first because it is the only status that asserts the
 * submittal is wrong. MISSING_INFORMATION last because it is the largest
 * group by far and the least actionable - on the drum sheet it is 1,578 of
 * 1,580, and a table that leads with it buries the two rows that need a
 * person.
 */
export const STATUS_ORDER: ComplianceStatus[] = [
  "NON_COMPLIANT",
  "NEEDS_ENGINEER_REVIEW",
  "CONDITIONAL",
  "COMPLIANT",
  "NOT_APPLICABLE",
  "MISSING_INFORMATION",
  // Last: nothing on this submittal can act on it (B9).
  "NOT_IN_DOCUMENT_SCOPE",
];

export function statusRank(status: string | null | undefined): number {
  const index = STATUS_ORDER.indexOf((status ?? "") as ComplianceStatus);
  return index === -1 ? STATUS_ORDER.length : index;
}

/** What each status means, in the words §12 uses. */
export const STATUS_LABEL: Record<ComplianceStatus, string> = {
  NON_COMPLIANT: "Non-compliant",
  NEEDS_ENGINEER_REVIEW: "Needs engineer review",
  CONDITIONAL: "Conditional",
  COMPLIANT: "Compliant",
  NOT_APPLICABLE: "Not applicable",
  MISSING_INFORMATION: "No evidence submitted",
  // The owner's approved client-facing wording, 2026-09-22.
  NOT_IN_DOCUMENT_SCOPE:
    "Requires another document - not answerable from this submittal type",
};

/**
 * The tone each status is allowed to carry.
 *
 * `MISSING_INFORMATION` is NEUTRAL on purpose. "Missing information is not
 * automatically non-compliance" (§12), and colour is an assertion: a reader
 * scanning a table reads red as "this failed" long before they read the word.
 */
export const STATUS_TONE: Record<ComplianceStatus, string> = {
  NON_COMPLIANT: "border-rose-500/40 bg-rose-500/10 text-rose-200",
  NEEDS_ENGINEER_REVIEW: "border-amber-500/40 bg-amber-500/10 text-amber-200",
  CONDITIONAL: "border-sky-500/40 bg-sky-500/10 text-sky-200",
  COMPLIANT: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
  NOT_APPLICABLE: "border-ink-600 bg-ink-800 text-slateish-300",
  MISSING_INFORMATION: "border-ink-600 bg-ink-800 text-slateish-300",
  // Neutral like missing, but DASHED and dimmer so the two never read alike:
  // one is a question for the contractor, the other is not about them.
  NOT_IN_DOCUMENT_SCOPE: "border-dashed border-ink-600 bg-ink-900 text-slateish-400",
};

export function statusLabel(status: string | null | undefined): string {
  if (!status) return "";
  return STATUS_LABEL[status as ComplianceStatus] ?? status;
}

export function statusTone(status: string | null | undefined): string {
  if (!status) return "border-ink-600 bg-ink-800 text-slateish-300";
  return STATUS_TONE[status as ComplianceStatus]
    ?? "border-ink-600 bg-ink-800 text-slateish-300";
}

/**
 * A value as the document wrote it, or nothing at all.
 *
 * NULL IS NOT ZERO AND NOT "N/A". An empty cell says the sheet did not state
 * it; `0` says the sheet stated zero, and those are different facts about the
 * contractor's submission.
 */
export function orNothing(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return String(value);
  return value.trim();
}

/** "2 of 1,580 (0.1%)" - never a bare count and never a bare percentage. */
export function withDenominator(count: number, total: number): string {
  if (!total) return `${count.toLocaleString()}`;
  const share = (count / total) * 100;
  const rounded = share >= 0.1 ? share.toFixed(1) : "<0.1";
  return `${count.toLocaleString()} of ${total.toLocaleString()} (${rounded}%)`;
}

/**
 * Confidence, and it never says "high" (CLAUDE.md rule 4).
 *
 * The backend already caps the vocabulary at "medium"; this refuses anything
 * else rather than trusting that, because the screen is the last place the
 * word can be stopped.
 */
export function confidenceLabel(value: string | null | undefined): string {
  if (!value) return "";
  const text = value.toLowerCase();
  if (text === "low" || text === "medium") return text;
  return "not recorded";
}

/** How the pairing was made. A rule and a guess must not read alike. */
export function matchMethodLabel(method: string | null | undefined): string {
  if (!method) return "";
  if (method === "containment") return "matched by rule";
  if (method === "model") return "paired by model";
  return method;
}

export function matchMethodTone(method: string | null | undefined): string {
  if (method === "model") return "border-violet-500/40 bg-violet-500/10 text-violet-200";
  if (method === "containment") return "border-ink-600 bg-ink-800 text-slateish-200";
  return "border-ink-600 bg-ink-800 text-slateish-300";
}

/**
 * The completeness line, WITH the word "nominal" when the denominator is one.
 *
 * `comparison._insufficient_reason` spells this out and the screen must not
 * quietly drop it: "42 of 385" reads like somebody counted the sheet, and
 * nobody did - 385 is pages times a nominal 35 fields per page.
 */
export function completenessLine(run: ReviewRunSummary): string {
  const block = run.completeness;
  if (!block) return "";
  const read = block.fields_read;
  const estimated = block.fields_estimated;
  if (read === undefined || read === null) return "";
  if (estimated === undefined || estimated === null) {
    return `${read.toLocaleString()} fields read`;
  }
  return `${read.toLocaleString()} of approximately ${estimated.toLocaleString()} fields`
    + ` (a NOMINAL estimate: ${block.pages ?? "?"} pages x 35 fields per page,`
    + ` not a count of this document)`;
}

/** A timestamp as a person reads it, or nothing when there is none. */
export function whenLabel(value: string | null | undefined): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}
