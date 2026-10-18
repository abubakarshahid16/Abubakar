/**
 * The evidence drawer's navigation and its plain lines (order 95 piece 4,
 * absorbing order 94a; Part of #967).
 *
 * COMMENT-DRIVEN: on a long document the engineer moves from comment to
 * comment, and from one page that carries a comment to the next, never
 * through the empty pages in between. The strip lists the pages with a
 * comment plus the first and last page, so "page 1 of 100" is always one
 * click away and the document's length is never hidden.
 *
 * Pure functions; display only. No verdict is read or changed here.
 */
import type { ReviewFinding } from "../../../types/api";
import { fieldOf } from "../sheet/sheetCards";
import { orNothing, statusLabel, whenLabel } from "../reviewFormat";
import type { CrsRow } from "./crsRows";

/** The row before or after `key` in the list the engineer is looking at;
 *  null at either end (the drawer does not wrap: an end is an end). */
export function stepRow(rows: CrsRow[], key: string, step: -1 | 1): CrsRow | null {
  const at = rows.findIndex((r) => r.key === key);
  if (at < 0) return null;
  return rows[at + step] ?? null;
}

/** The pages that carry a comment (Tier B or C), ascending, each once. */
export function commentPages(rows: CrsRow[]): number[] {
  const pages = new Set<number>();
  for (const r of rows) if (r.tier.tier !== "A" && typeof r.page === "number") pages.add(r.page);
  return [...pages].sort((a, b) => a - b);
}

/** The pager strip: the comment pages plus the first and the last page of the
 *  document. Without a page count, the comment pages alone (nothing invented). */
export function pagerStrip(pages: number[], pageCount: number | null): number[] {
  const strip = new Set(pages.filter((p) => p >= 1 && (pageCount === null || p <= pageCount)));
  if (pageCount !== null && pageCount >= 1) { strip.add(1); strip.add(pageCount); }
  return [...strip].sort((a, b) => a - b);
}

/** The next or previous comment page from `page` (PageDown / PageUp); null
 *  when there is none in that direction. */
export function stepPage(pages: number[], page: number | null, step: -1 | 1): number | null {
  if (step === 1) return pages.find((p) => page === null || p > page) ?? null;
  const before = pages.filter((p) => page !== null && p < page);
  return before.length ? before[before.length - 1] : null;
}

/** The first row on `page` among the rows shown, or null. */
export function firstRowOnPage(rows: CrsRow[], page: number): CrsRow | null {
  return rows.find((r) => r.page === page) ?? null;
}

/** A typed page number, when it is a whole page of this document; else null. */
export function parsePage(text: string, pageCount: number | null): number | null {
  if (!/^\s*\d+\s*$/.test(text)) return null;
  const page = Number(text);
  if (page < 1 || (pageCount !== null && page > pageCount)) return null;
  return page;
}

/** One line: what the datasheet says against what the rule asks, and the
 *  result. A part that was not recorded is left out, never shown as "0". */
export function comparisonLine(f: ReviewFinding): string {
  const field = fieldOf(f);
  const said = orNothing(f.contractor_evidence_text);
  const asks = orNothing(f.requirement_source_text) || orNothing(f.requirement);
  const parts = [
    said ? `${field ? `${field}: ` : ""}the datasheet says "${said}"` : field ? `${field}: not found on the datasheet` : "",
    asks ? `the rule asks: ${asks}` : "",
  ].filter(Boolean);
  const result = statusLabel(f.compliance_status);
  return [parts.join("; "), result].filter(Boolean).join(" - ");
}

export interface HistoryEntry {
  when: string;
  what: string;
}

/** What happened to the findings of one row, oldest first, from the fields
 *  the findings carry. Who did it is shown as recorded; a time not recorded
 *  is left blank, never guessed. */
export function historyOf(findings: ReviewFinding[]): HistoryEntry[] {
  const out: { at: string; what: string }[] = [];
  for (const f of findings) {
    out.push({ at: f.created_at, what: "Found by the review" });
    if (f.confirmed_at || f.confirmed_by) {
      out.push({ at: f.confirmed_at ?? "", what: `Confirmed${f.confirmed_by ? ` by ${f.confirmed_by}` : ""}` });
    }
    if (f.approval_status === "accepted" || f.approval_status === "rejected") {
      const verb = f.approval_status === "accepted" ? "Comment accepted" : "Comment removed";
      out.push({ at: f.approved_at ?? "", what: `${verb}${f.approved_by ? ` by ${f.approved_by}` : ""}` });
    }
    if (orNothing(f.engineer_comment)) out.push({ at: "", what: "Wording edited by an engineer" });
  }
  const seen = new Set<string>();
  return out
    .filter((e) => { const k = `${e.at}|${e.what}`; if (seen.has(k)) return false; seen.add(k); return true; })
    .sort((a, b) => (a.at || "￿").localeCompare(b.at || "￿"))
    .map((e) => ({ when: whenLabel(e.at), what: e.what }));
}
