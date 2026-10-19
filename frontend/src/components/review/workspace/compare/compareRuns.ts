/**
 * OWNER: builder E (v2.2). "What changed since the last review".
 *
 * `compareRuns` is pure: it takes the comment lines of two reviews of the
 * same file (the comment sheet's own lines, built by `buildCrsRows`) and
 * sorts them into three plain lists: new this time, gone since last time,
 * and in both reviews. Only comments are compared (lines that met the standard
 * are not comments and are left out).
 *
 * Matching: a line is the same comment in both reviews when they share a
 * finding identity: the standard, the requirement inside it, the equipment
 * and the item the value was read for. Findings carry fresh ids on every
 * review, so ids are never used. A line whose findings name no requirement,
 * or that found no partner that way, is then matched by its normalised
 * comment text (case, spaces and punctuation ignored).
 *
 * `loadCommentLines` reads one review's sheet with the SAME four reads the
 * workspace uses (useWorkspaceRun: reviewRun, list, reviewRunStandards,
 * reviewRunSummary) and builds the lines with `buildCrsRows`. Read only:
 * nothing here writes or changes a decision.
 */
import { reviews as reviewsApi } from "../../../../api/client";
import type { ReviewFinding } from "../../../../types/api";
import { type CrsRow, buildCrsRows } from "../../crs/crsRows";
import { runFactsOf, serverTiersOf } from "../../crs/tiers";
import { fieldOf } from "../../sheet/sheetCards";
import { dayWords } from "../landing/dateWords";
import { type PlainError, plainError } from "../plainError";

export interface RunComparison {
  /** In the current review only. */
  added: CrsRow[];
  /** In the earlier review only. */
  gone: CrsRow[];
  /** In both; the current review's line. */
  still: CrsRow[];
}

function norm(text: string | null | undefined): string {
  return (text ?? "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

/** A finding's stable identity across reviews, or null when it names no
 *  requirement (then only the text can match it). */
export function findingIdentity(f: ReviewFinding): string | null {
  if (!f.requirement_id) return null;
  return ["req", f.standard_document_id ?? "", f.requirement_id, norm(f.equipment_tag), norm(fieldOf(f))].join("|");
}

/** The line's comment text, normalised: what the contractor would read. */
export function lineText(row: CrsRow): string {
  return norm([row.observation, row.requiredAction].filter(Boolean).join(" "));
}

/** Only the comments: lines that met the standard are not compared. */
export function commentLines(rows: CrsRow[]): CrsRow[] {
  return rows.filter((r) => r.tier.tier !== "A");
}

export function compareRuns(currentRows: CrsRow[], earlierRows: CrsRow[]): RunComparison {
  const current = commentLines(currentRows);
  const earlier = commentLines(earlierRows);
  const partner = new Map<number, number>(); // current index -> earlier index
  const taken = new Set<number>();

  // Pass 1: by finding identity.
  const byIdentity = new Map<string, number[]>();
  earlier.forEach((row, i) => {
    for (const f of row.findings) {
      const id = findingIdentity(f);
      if (id) byIdentity.set(id, [...(byIdentity.get(id) ?? []), i]);
    }
  });
  current.forEach((row, ci) => {
    for (const f of row.findings) {
      const id = findingIdentity(f);
      const hit = id ? (byIdentity.get(id) ?? []).find((ei) => !taken.has(ei)) : undefined;
      if (hit !== undefined) { partner.set(ci, hit); taken.add(hit); return; }
    }
  });

  // Pass 2: by normalised comment text, for the lines still unmatched.
  const byText = new Map<string, number[]>();
  earlier.forEach((row, i) => {
    if (taken.has(i)) return;
    const t = lineText(row);
    if (t) byText.set(t, [...(byText.get(t) ?? []), i]);
  });
  current.forEach((row, ci) => {
    if (partner.has(ci)) return;
    const t = lineText(row);
    const hit = t ? (byText.get(t) ?? []).find((ei) => !taken.has(ei)) : undefined;
    if (hit !== undefined) { partner.set(ci, hit); taken.add(hit); }
  });

  return {
    added: current.filter((_, ci) => !partner.has(ci)),
    gone: earlier.filter((_, ei) => !taken.has(ei)),
    still: current.filter((_, ci) => partner.has(ci)),
  };
}

/** "12 Oct 2026"; "" when not known (the one date style, landing/dateWords). */
export function reviewDay(value: string | null | undefined): string {
  return dayWords(value);
}

function comments(n: number): string {
  return `${n.toLocaleString()} ${n === 1 ? "comment" : "comments"}`;
}

/** The three count lines, each with its boundary (the earlier review's date). */
export function comparisonLines(c: RunComparison, earlierAt: string | null | undefined): { added: string; gone: string; still: string } {
  const day = reviewDay(earlierAt);
  const since = day ? `since the review of ${day}` : "since the earlier review";
  const both = day ? `in both reviews (this one and the review of ${day})` : "in both reviews";
  return {
    added: `${c.added.length.toLocaleString()} new ${c.added.length === 1 ? "comment" : "comments"} ${since}`,
    gone: `${comments(c.gone.length)} gone ${since}`,
    still: `${comments(c.still.length)} ${both}`,
  };
}

export const COULD_NOT_COMPARE = "Could not read one of the two reviews to compare them.";

export type LoadedLines = { ok: true; rows: CrsRow[] } | { ok: false; error: PlainError };

/** One review's comment sheet lines, read the way the workspace reads them. */
export async function loadCommentLines(runId: string): Promise<LoadedLines> {
  try {
    const [run, listed, stds, sum] = await Promise.all([
      reviewsApi.reviewRun(runId), reviewsApi.list({ review_run_id: runId }), reviewsApi.reviewRunStandards(runId),
      reviewsApi.reviewRunSummary(runId),
    ]);
    if (!run.ok) return { ok: false, error: plainError(COULD_NOT_COMPARE, run) };
    if (!listed.ok) return { ok: false, error: plainError(COULD_NOT_COMPARE, listed) };
    if (!run.data) return { ok: false, error: plainError(COULD_NOT_COMPARE, { error: { code: "not_found" } }) };
    const standards = stds.ok ? stds.data.standards : null;
    const missing = stds.ok ? (stds.data.missing_references ?? []) : [];
    const names = new Map((standards ?? []).filter((s) => s.filename).map((s) => [s.standard_document_id, s.filename as string]));
    const facts = runFactsOf(run.data, standards, missing);
    const server = sum.ok ? serverTiersOf(sum.data.rows) : null;
    return { ok: true, rows: buildCrsRows(listed.data.findings, facts, names, server) };
  } catch {
    return { ok: false, error: plainError(COULD_NOT_COMPARE, { disconnected: true }) };
  }
}
