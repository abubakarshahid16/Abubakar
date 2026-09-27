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
  // WHAT WAS CHECKED, not what the contractor did (honesty audit 50): the
  // engine knows no field it read answered this, not that nothing was sent.
  MISSING_INFORMATION: "No value found in the fields read",
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
  // 2g: theme tokens (index.css), AA in BOTH themes. The pale "-200" text
  // they replace was unreadable on the light theme's white card.
  NON_COMPLIANT: "border-pill-fail-border bg-pill-fail-bg text-pill-fail-fg",
  NEEDS_ENGINEER_REVIEW: "border-pill-review-border bg-pill-review-bg text-pill-review-fg",
  CONDITIONAL: "border-pill-cond-border bg-pill-cond-bg text-pill-cond-fg",
  COMPLIANT: "border-pill-pass-border bg-pill-pass-bg text-pill-pass-fg",
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

/** B3: the reason code a finding's rationale leads with when its value may
 *  sit on a page the system has not read into fields yet. */
export const UNREAD_PAGES = "UNREAD_PAGES";

/** The owner's plain wording for those findings (2026-09-25), so the drop in
 *  "missing information" reads as honesty, not as a regression. */
export const PAGES_NOT_READABLE_LABEL = "Pages not yet readable - needs engineer review";

/** Honesty audit entry 68: the value was not found on a page read only by the
 *  geometry/vision (page) reader - an engineer checks the page; it is never
 *  the contractor's missing information. */
export const PAGE_READER_ONLY = "PAGE_READER_ONLY";
export const PAGE_READER_ONLY_LABEL = "Value not found by the page reader - engineer to check the page";

/**
 * A FINDING's label, not just its status's: one status can carry different
 * truths. A NEEDS_ENGINEER_REVIEW finding whose reason is UNREAD_PAGES says
 * so in plain words; every other finding reads as its status does.
 */
/** Owner order 2d: an AI engineering check item (kind C). A draft - never a
 *  verdict, never from the standard's text. */
export const AI_ENGINEERING_CHECK = "ai_engineering_check";
export const AI_ENGINEERING_CHECK_LABEL =
  "AI engineering check - not from the standard text - engineer to confirm";

export function findingLabel(finding: {
  compliance_status?: string | null; ai_rationale?: string | null; origin?: string | null;
}): string {
  if (finding.origin === AI_ENGINEERING_CHECK) return AI_ENGINEERING_CHECK_LABEL;
  if (finding.compliance_status === "NEEDS_ENGINEER_REVIEW"
      && (finding.ai_rationale ?? "").startsWith(UNREAD_PAGES)) {
    return PAGES_NOT_READABLE_LABEL;
  }
  if (finding.compliance_status === "NEEDS_ENGINEER_REVIEW"
      && (finding.ai_rationale ?? "").startsWith(PAGE_READER_ONLY)) {
    return PAGE_READER_ONLY_LABEL;
  }
  return statusLabel(finding.compliance_status);
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
 * The completeness line in plain words (owner order 2g): what was COUNTED -
 * the fields read. The estimate of how many a sheet holds is not a count of
 * this document, so it is never in this line; `estimateDetail` states it,
 * labelled nominal, under "Details".
 */
export function completenessLine(run: ReviewRunSummary): string {
  const read = run.completeness?.fields_read;
  if (read === undefined || read === null) return "";
  return `Checked ${read.toLocaleString()} datasheet field${read === 1 ? "" : "s"}.`;
}

/** The nominal estimate behind the completeness gate, for "Details" only. */
export function estimateDetail(run: ReviewRunSummary): string {
  const block = run.completeness;
  if (!block || block.fields_estimated === undefined || block.fields_estimated === null) return "";
  return `${(block.fields_read ?? 0).toLocaleString()} of approximately `
    + `${block.fields_estimated.toLocaleString()} fields (a NOMINAL estimate: `
    + `${block.pages ?? "?"} pages x 35 fields per page, not a count of this document).`;
}

/** `[1, 2, 3, 7]` -> `1-3, 7`, the same shape the backend writes in findings. */
export function pageList(pages: number[]): string {
  const sorted = [...pages].sort((a, b) => a - b);
  const out: string[] = [];
  let start: number | null = null;
  let prev: number | null = null;
  for (const p of [...sorted, Number.NaN]) {
    if (prev !== null && p === prev + 1) { prev = p; continue; }
    if (start !== null && prev !== null) out.push(start === prev ? `${start}` : `${start}-${prev}`);
    start = p; prev = p;
  }
  return out.join(", ");
}

/**
 * B3: WHICH PAGES THE REVIEW READ INTO FIELDS, with its denominator, and the
 * pages it did not - so "no value found" is never read as "the contractor
 * left it out". Nothing when the run predates the ledger (null is nothing).
 */
export function pageCoverageLine(run: ReviewRunSummary): string {
  const pc = run.page_coverage;
  if (!pc) return "";
  if (pc.pages_total === null || pc.pages_total === undefined) {
    return "No page of this submittal was accounted for; no value can be called missing.";
  }
  const read = pc.fact_pages.length;
  const head = `Fields read from ${read} of ${pc.pages_total} pages`
    + (read ? ` (${read === 1 ? "page" : "pages"} ${pageList(pc.fact_pages)})` : "");
  const unread = pc.pages_not_read_into_fields;
  if (!unread.length) return `${head}.`;
  return `${head}; ${unread.length === 1 ? "page" : "pages"} ${pageList(unread)}`
    + " not read into fields, so a value not found may still be there.";
}

/** A timestamp as a person reads it, or nothing when there is none. */
export function whenLabel(value: string | null | undefined): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

/** 2e: why the in-scope count moved - "Since the previous run: 4 standards
 *  removed (A, B, ...); 1 added (C)". Nothing when there is no earlier run
 *  or nothing changed. */
export function standardsChangeLine(run: ReviewRunSummary): string {
  const change = run.standards_change;
  if (!change) return "";
  const part = (names: string[], verb: string) => names.length
    ? `${names.length} standard${names.length === 1 ? "" : "s"} ${verb} (${names.join(", ")})`
    : "";
  const parts = [part(change.removed, "removed"), part(change.added, "added")].filter(Boolean);
  return parts.length
    ? `Since the previous run: ${parts.join("; ")}.`
    : "Same standards in scope as the previous run.";
}

/** Owner order section 1: which KIND of comment a finding is. "" for a
 *  comparison against a standard (kind A), which carries its own citation. */
export function kindLabel(finding: { origin?: string | null }): string {
  if (finding.origin === "datasheet_check") return "Datasheet check";
  if (finding.origin === AI_ENGINEERING_CHECK) return "AI engineering check";
  return "";
}

/** Owner order section 3: the four totals, in plain words.
 *
 *  THE BOUNDARY IS STATED: `counted` is the run's comparison and datasheet
 *  findings. AI engineering check items (kind C) are drafts with no
 *  compliance status and are never counted; engineer comments filed from
 *  chat are comments, not verdicts. "Not applicable" is its own number so
 *  the four plus it add up to `counted`. A requirement with no value found
 *  is "could not be checked" - never "meets" (rule 4). */
export interface SummaryTotals {
  meets: number;
  doesNotMeet: number;
  needsDecision: number;
  couldNotCheck: number;
  notApplicable: number;
  counted: number;
}

export function summaryTotals(
  findings: { compliance_status?: string | null; origin?: string | null; approval_status?: string | null }[],
): SummaryTotals {
  const totals: SummaryTotals = {
    meets: 0, doesNotMeet: 0, needsDecision: 0, couldNotCheck: 0, notApplicable: 0, counted: 0,
  };
  for (const f of findings) {
    if (f.origin === AI_ENGINEERING_CHECK || f.origin === "chat") continue;
    if (f.approval_status === "rejected") continue;
    const status = f.compliance_status;
    if (!status) continue;
    totals.counted += 1;
    if (status === "COMPLIANT") totals.meets += 1;
    else if (status === "NON_COMPLIANT") totals.doesNotMeet += 1;
    else if (status === "NEEDS_ENGINEER_REVIEW" || status === "CONDITIONAL") totals.needsDecision += 1;
    else if (status === "NOT_APPLICABLE") totals.notApplicable += 1;
    else totals.couldNotCheck += 1;
  }
  return totals;
}

/** Owner order section 3: comments by kind. A - checked against the text
 *  of a held standard; B - the datasheet against itself; C - AI engineering
 *  check, split confirmed / unconfirmed because only a confirmed one goes to
 *  the contractor. Rejected comments are not counted. */
export interface KindCounts { a: number; b: number; cConfirmed: number; cUnconfirmed: number }

export function kindCounts(
  findings: { origin?: string | null; confirmed_by?: string | null; approval_status?: string | null }[],
): KindCounts {
  const counts: KindCounts = { a: 0, b: 0, cConfirmed: 0, cUnconfirmed: 0 };
  for (const f of findings) {
    if (f.approval_status === "rejected" || f.origin === "chat") continue;
    if (f.origin === "datasheet_check") counts.b += 1;
    else if (f.origin === AI_ENGINEERING_CHECK) {
      if (f.confirmed_by) counts.cConfirmed += 1;
      else counts.cUnconfirmed += 1;
    } else counts.a += 1;
  }
  return counts;
}

/** Owner order section 3: runs grouped per document, latest first. The
 *  first run of each group is the one shown; the rest are "earlier runs". */
export function groupRunsByDocument<T extends { submittal_document_id: string; created_at?: string | null; review_run_id: string }>(
  runs: T[],
): { documentId: string; latest: T; earlier: T[] }[] {
  const groups = new Map<string, T[]>();
  for (const run of runs) {
    const list = groups.get(run.submittal_document_id) ?? [];
    list.push(run);
    groups.set(run.submittal_document_id, list);
  }
  const newestFirst = (a: T, b: T) =>
    (b.created_at ?? "").localeCompare(a.created_at ?? "") || b.review_run_id.localeCompare(a.review_run_id);
  return [...groups.entries()]
    .map(([documentId, list]) => {
      const [latest, ...earlier] = [...list].sort(newestFirst);
      return { documentId, latest, earlier };
    })
    .sort((x, y) => newestFirst(x.latest, y.latest));
}

/** Owner order section 3: the readiness strip's page line, with its
 *  denominator. Nothing when the page count is unknown (null renders as
 *  nothing). */
export function pagesReadLine(r: { pages_total: number | null; pages_read: number }): string {
  if (r.pages_total == null) return "";
  return `Pages read: ${r.pages_read} of ${r.pages_total}`;
}
