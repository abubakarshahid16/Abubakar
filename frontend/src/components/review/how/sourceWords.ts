/**
 * "How it was reviewed" shows where each number comes from in plain words; the stored field path stays in a tooltip (`title`) for
 * support. ONE place: `plainSource` turns every stored field path inside a sentence (`page_coverage.pages_total`,
 * `requirement_split.reader.pages_read`, `completed_at`) into words a reader knows. Nothing here changes a number or a fact.
 */

const CONTAINERS: Record<string, string> = {
  page_coverage: "the page record",
  requirement_split: "the rule count",
  standards_change: "the change in standards",
  coverage_pair: "the coverage pair",
  clause_coverage: "the clause coverage",
};

/** The paths the screen names most, in their own words. Anything else falls back to the generic rule below. */
const LABELS: Record<string, string> = {
  "page_coverage.pages_total": "the page record: pages in the document",
  "page_coverage.fact_pages": "the page record: pages with values read into fields",
  "page_coverage.pages_not_read": "the page record: pages not read",
  "page_coverage.pages_not_read_into_fields": "the page record: pages no field was read from",
  "page_coverage.pages_ai_not_read": "the page record: pages the AI reader did not read",
  "page_coverage.pages_read_no_field": "the page record: pages read with no field found",
  "page_coverage.reading.status": "the page record: reading status",
  "page_coverage.reading.incomplete_pages": "the page record: incomplete pages",
  "page_coverage.reading": "the page record: reading status",
  "requirement_split.reader.pages": "pages given to the AI reader",
  "requirement_split.reader.pages_read": "pages the AI reader read",
  "requirement_split.reader.engine": "the reader's setting",
  "requirement_split.reader.seconds": "the reader's time",
  "requirement_split.reader.timed_out": "the pages the reader timed out on",
  "requirement_split.reader.code_only": "the pages left to the code readers",
  completed_at: "the time the review finished",
  created_at: "the time the review started",
  standards_in_scope: "the standards in scope",
  findings_total: "the findings of this review",
};

const TOKEN = /\b[a-z][a-z0-9]*(?:[._][a-z0-9]+)+\b/g;
const SPACE = (s: string) => s.replace(/_/g, " ");

function one(path: string): string {
  if (LABELS[path]) return LABELS[path];
  const [head, ...rest] = path.split(".");
  if (CONTAINERS[head]) return rest.length ? `${CONTAINERS[head]}: ${SPACE(rest.join(" "))}` : CONTAINERS[head];
  return SPACE(path.replace(/\./g, " "));
}

/** Every stored field path in `text`, in plain words. Words with no dot or underscore are left as they are. */
export function plainSource(text: string): string {
  return text.replace(TOKEN, (m) => (m.includes("_") || CONTAINERS[m.split(".")[0]] ? one(m) : m));
}
