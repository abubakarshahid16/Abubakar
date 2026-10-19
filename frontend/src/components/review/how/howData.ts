/**
 * "How this was reviewed" (order 95, spec 1.4, piece 5): the plain-words
 * reading of what a run stored. Pure functions; no fetch, no React.
 *
 * NO NEW COUNTING. Every number here is a field the engine stored on the run
 * (`page_coverage`, including its `reading` record, and `requirement_split`,
 * including its `reader`), the length of a stored list, or a sum of two
 * stored fields - and each is printed with the field it came from. A field
 * the run does not hold is `null` and renders as NOT_RECORDED, never as 0 or
 * blank (CLAUDE.md rule 4). The one place a missing key counts as 0 is an
 * OCR state on a run whose ledger accounted for its pages: the ledger stores
 * only the states it saw, so an absent state there means no page in it.
 */
import type { PageCoverage, ReaderSummary, ReviewRunSummary } from "../../../types/api";
import { pageList } from "../reviewFormat";

/** The one wording for a field the run does not carry. */
export const NOT_RECORDED = "not recorded on this review";

/** The wording for a field the runs list does not send to this page at all
 *  (absent, as opposed to sent as null): the run may hold it elsewhere. */
export const NOT_SENT = "not sent to this page";

/** A value with the stored field it was read from. `value` null = not recorded. */
export interface Sourced<T = number> {
  value: T | null;
  source: string;
}

export function sourced<T>(value: T | null | undefined, source: string): Sourced<T> {
  return { value: value === undefined ? null : value, source };
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** The reader record the run stored, or null when it holds none. */
export function readerOf(run: ReviewRunSummary): ReaderSummary | null {
  return run.requirement_split?.reader ?? null;
}

/** The page numbers: each one a stored field or a stored list's length. */
export function pageFacts(run: ReviewRunSummary) {
  const pc = run.page_coverage ?? null;
  const reader = readerOf(run);
  // The ledger's OCR counts hold only the states it saw, so a missing state
  // is 0 pages - but only when the ledger accounted for the pages at all
  // (`pages_total` set). Without that, every OCR number is not recorded.
  const ocr = pc && isNumber(pc.pages_total) && pc.ocr ? pc.ocr : null;
  const ocrCount = (key: string): number => (ocr && isNumber(ocr[key]) ? ocr[key] : 0);
  // "scanned without OCR" = pages that need OCR and did not get it: the
  // ledger's `pending` plus `failed` counts (a sum of two stored fields).
  const withoutOcr = ocr ? ocrCount("pending") + ocrCount("failed") : null;
  return {
    total: sourced(pc?.pages_total ?? null, "page_coverage.pages_total"),
    readByCode: sourced(pc ? pc.fact_pages.length : null, "page_coverage.fact_pages (count of the list)"),
    readByCodePages: pc?.fact_pages ?? [],
    aiOff: reader?.engine === "off",
    readByAi: sourced(reader && reader.engine !== "off" ? reader.pages_read ?? null : null,
                      "requirement_split.reader.pages_read"),
    aiPages: sourced(reader?.pages ?? null, "requirement_split.reader.pages"),
    timedOut: sourced(reader && reader.engine !== "off" ? (reader.timed_out ?? []) : null,
                      "requirement_split.reader.timed_out"),
    // Absent = the run did not record it; never read as "no page unread".
    notRead: sourced(pc?.pages_not_read_into_fields ?? null, "page_coverage.pages_not_read_into_fields"),
    notReadReasons: pc?.not_read_reasons ?? {},
    aiNotRead: sourced(pc?.pages_ai_not_read ?? null, "page_coverage.pages_ai_not_read"),
    aiNotReadReasons: pc?.ai_not_read_reasons ?? {},
    reading: pc?.reading ?? null,
    withoutOcr: sourced(withoutOcr, "page_coverage.ocr.pending + page_coverage.ocr.failed"),
    ocrDone: sourced(ocr ? ocrCount("done") : null, "page_coverage.ocr.done"),
  };
}

/** Each incomplete page with the reasons the run stored for it
 *  (`not_read_reasons`, `ai_not_read_reasons`, `reading.failed_pages`). */
export function incompletePageReasons(pc: PageCoverage): { page: number; reasons: string[] }[] {
  const reading = pc.reading;
  if (!reading) return [];
  return reading.incomplete_pages.map((page) => {
    const key = String(page);
    const reasons = [pc.not_read_reasons?.[key], pc.ai_not_read_reasons?.[key], reading.failed_pages?.[key]]
      .filter((r): r is string => typeof r === "string" && r.trim() !== "");
    return { page, reasons };
  });
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** One line a manager can read about the pages, from the same stored
 *  fields. It says "all pages" only when the run stored its reading as
 *  complete (`page_coverage.reading.status`); otherwise it says what the run
 *  stored, and what it did not. */
export function pagesMeaning(run: ReviewRunSummary): string {
  const pc = run.page_coverage ?? null;
  const p = pageFacts(run);
  if (!pc || p.total.value === null) {
    return "No page of this document was accounted for on this review, so nothing can be called read or unread.";
  }
  const total = p.total.value;
  const reading = p.reading;
  const sentences: string[] = [];
  if (reading && reading.status === "incomplete") {
    const pages = reading.incomplete_pages;
    const why = incompletePageReasons(pc)
      .map(({ page, reasons }) => `page ${page}: ${reasons.length ? reasons.join("; ") : "no reason recorded"}`);
    const general = [...Object.entries(reading.reasons ?? {}).filter(([, on]) => on).map(([reason]) => reason),
                     ...(reading.notes ?? [])];
    sentences.push(pages.length
      ? `The run stored the reading as incomplete: ${pages.length} of ${total} pages were not read in full (pages ${pageList(pages)})${why.length ? ` - ${why.join("; ")}` : ""}.`
      : "The run stored the reading as incomplete.");
    if (general.length) sentences.push(`Also recorded: ${general.join("; ")}.`);
    sentences.push("A value that was not found may still be on those pages; an engineer should look at them.");
  } else if (reading && reading.status === "complete") {
    sentences.push(`The run stored the reading as complete for all ${total} pages (page_coverage.reading.status).`);
  } else {
    sentences.push(reading
      ? `The run stored the reading status as "${reading.status}".`
      : "The run did not record whether the reading was complete (page_coverage.reading), so it cannot be said that all pages were read.");
    const unread = p.notRead.value;
    const aiMissed = p.aiNotRead.value;
    if (unread && unread.length) sentences.push(`${unread.length} of ${total} pages were not read into fields (pages ${pageList(unread)}).`);
    if (aiMissed && aiMissed.length) sentences.push(`The AI reader did not read ${plural(aiMissed.length, "page")} (pages ${pageList(aiMissed)}).`);
  }
  if (p.notRead.value === null) {
    sentences.push("Which pages were not read into fields is not recorded on this review.");
  }
  return sentences.join(" ");
}

/** The clause numbers from `requirement_split`, each with its field. */
export function clauseFacts(run: ReviewRunSummary) {
  const s = run.requirement_split ?? null;
  const checked = s?.checked ?? null;
  const notChecked = s?.applies_not_checked ?? null;
  // "applied" = the clauses that apply to this document: checked plus
  // applies-but-not-checked (a sum of two stored fields).
  const applied = isNumber(checked) && isNumber(notChecked) ? checked + notChecked : null;
  return {
    applied: sourced(applied, "requirement_split.checked + requirement_split.applies_not_checked"),
    checked: sourced(checked, "requirement_split.checked"),
    notChecked: sourced(notChecked, "requirement_split.applies_not_checked"),
    notCheckedReasons: s?.applies_not_checked_reasons ?? [],
    doesNotApply: sourced(s?.does_not_apply ?? null, "requirement_split.does_not_apply"),
    doesNotApplyReasons: s?.does_not_apply_reasons ?? [],
    repeatsIgnored: sourced(s?.repeats_ignored ?? null, "requirement_split.repeats_ignored"),
    total: sourced(s?.total ?? null, "requirement_split.total"),
    notUsed: sourced(s?.not_used ?? null, "requirement_split.not_used"),
    storedShare: sourced(s?.unchecked_share ?? null, "requirement_split.unchecked_share"),
  };
}

/** The unchecked share, as a percent, from the two stored numbers it rests
 *  on: applies_not_checked / (checked + applies_not_checked). Null when the
 *  run holds no split or nothing applies (no percentage without a
 *  denominator). */
export function uncheckedShare(run: ReviewRunSummary): { percent: number; numerator: number; denominator: number } | null {
  const s = run.requirement_split;
  if (!s || !isNumber(s.checked) || !isNumber(s.applies_not_checked)) return null;
  const denominator = s.checked + s.applies_not_checked;
  if (denominator === 0) return null;
  return { percent: Math.round((s.applies_not_checked / denominator) * 1000) / 10,
           numerator: s.applies_not_checked, denominator };
}

/** Seconds between two stored timestamps, or null when either is missing. */
export function durationSeconds(start: string | null | undefined, end: string | null | undefined): number | null {
  if (!start || !end) return null;
  const a = new Date(start).getTime();
  const b = new Date(end).getTime();
  if (Number.isNaN(a) || Number.isNaN(b) || b < a) return null;
  return Math.round((b - a) / 1000);
}

/** `754` -> `12 min 34 s`; `40` -> `40 s`. */
export function durationLabel(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 60) return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${minutes % 60} min`;
}

/**
 * Whether each AI step is on or off BY DEFAULT in the backend's settings
 * (`backend/app/config.py`, read 18 Oct 2026). Rule 1 (#805): switching an
 * AI step off by default needs the owner's written approval, so the page
 * says which steps run unless someone turned them off, and which do not.
 * These are the defaults, not what this run did - the run's own record
 * says that, beside it.
 */
export const AI_STEP_DEFAULTS: Record<string, { label: string; onByDefault: boolean; setting: string }> = {
  reader: { label: "AI reader", onByDefault: true, setting: "DATASHEET_AI_READER" },
  matcher: { label: "AI matcher", onByDefault: true, setting: "MATCH_ENGINE" },
  clause_checks: { label: "AI clause checks", onByDefault: true, setting: "AI_CLAUSE_CHECKS_ENABLED" },
  applicability: { label: "AI applicability (does-not-apply proposals)", onByDefault: false, setting: "AI_APPLICABILITY_ENABLED" },
  applicability_reasoning: { label: "Applicability reasoning (scope decision)", onByDefault: true, setting: "APPLICABILITY_REASONING_ENABLED" },
  engineering_check: { label: "AI engineering check", onByDefault: true, setting: "REVIEW_AI_CHECK_ENABLED" },
  wording: { label: "AI wording of the comments", onByDefault: true, setting: "CRS_AI_WORDING_ENABLED" },
};

export function defaultLine(key: string): string {
  const d = AI_STEP_DEFAULTS[key];
  if (!d) return "";
  return d.onByDefault
    ? `On by default (setting ${d.setting}); rule 1: turning it off by default needs the owner's written approval.`
    : `Off by default (setting ${d.setting}); it runs only when switched on.`;
}
