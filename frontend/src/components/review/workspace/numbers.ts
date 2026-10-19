/**
 * OWNER: builder B. THE ONE SOURCE OF NUMBERS for the review workspace.
 *
 * Pure: no fetching, no React. Every count on the workspace comes from
 * `computeReviewNumbers`; nothing else in the workspace counts rows,
 * findings or pages. The rules are SPEC.md section 4 and match what
 * CrsSheetView shows today (rowCounts, headlineFieldsOf, the removed count
 * `summary?.counts.removed ?? splitRejected(findings).rejected`), so the old
 * screen and the workspace never disagree.
 */
import type { ActionStep, ReviewNumbers, ReviewNumbersInput } from "./contract";
import type { ReviewRunSummary } from "../../../types/api";
import { headlineFieldsOf, rowCounts, splitRejected } from "../crs/crsRows";
import { pageList } from "../reviewFormat";

function uniqueSortedPages(pages: number[]): number[] {
  return [...new Set(pages.filter((p) => Number.isFinite(p)))].sort((a, b) => a - b);
}

function uniqueStrings(list: string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of list) {
    const s = (raw ?? "").trim();
    if (!s || seen.has(s)) continue;
    seen.add(s);
    out.push(s);
  }
  return out;
}

export function computeReviewNumbers(input: ReviewNumbersInput): ReviewNumbers {
  const { run, findings, rows, summary, readiness, decisions } = input;
  const counts = rowCounts(rows);
  const fields = headlineFieldsOf(run, summary?.how_reviewed ?? null);
  const commentRows = rows.filter((r) => r.tier.tier !== "A");
  const undecidedKeys = commentRows
    .filter((r) => !decisions.decisions[r.key] && r.priorState !== "agreed")
    .map((r) => r.key);
  const signedAt = run.crs_issued_at ?? null;
  return {
    comments: counts.comment + counts.needsYou,
    needsYou: counts.needsYou,
    findingsInComments: commentRows.reduce((sum, r) => sum + r.findings.length, 0),
    met: counts.met,
    notApplicable: typeof fields.doesNotApply === "number" ? fields.doesNotApply : counts.notApplicable,
    anotherDocument: counts.anotherDocument,
    removed: summary?.counts.removed ?? splitRejected(findings).rejected,
    unreadPages: uniqueSortedPages([...fields.unreadPages, ...(readiness?.unread_pages ?? [])]),
    missingStandards: uniqueStrings([...input.missingStandards, ...(readiness?.standards_missing ?? [])]),
    undecided: undecidedKeys.length,
    undecidedKeys,
    unopenedNeedsYou: rows.filter((r) => r.tier.tier === "C" && !decisions.opened[r.key]).length,
    unsaved: input.unsaved.length,
    signed: Boolean(signedAt),
    signedAt,
  };
}

/** "1-3, 7" -> "1-3 and 7" (the way CrsSheetView's headline says a list). */
function spoken(list: string): string {
  const at = list.lastIndexOf(", ");
  return at < 0 ? list : `${list.slice(0, at)} and ${list.slice(at + 2)}`;
}

/** "Pages 4, 9 and 12" / "Page 4"; "" for none. */
export function pagesDetail(pages: number[]): string {
  if (pages.length === 0) return "";
  return `${pages.length === 1 ? "Page" : "Pages"} ${spoken(pageList(pages))}`;
}

/** The four buttons of "What you need to do", always in this order:
 *  standards, pages, decide, sign. A step with nothing left is done (a
 *  quiet tick), never hidden. Sign is enabled only when the other three are
 *  done, nothing is unsaved and the run is not signed yet. */
export function actionSteps(numbers: ReviewNumbers): ActionStep[] {
  const standards = numbers.missingStandards.length;
  const pages = numbers.unreadPages.length;
  const decide = numbers.undecided;
  const blockersClear = standards === 0 && pages === 0 && decide === 0;
  const pagesHelp = pagesDetail(numbers.unreadPages);
  const standardsHelp = numbers.missingStandards.join(", ");
  return [
    {
      id: "standards", label: `Upload missing standards (${standards})`, count: standards,
      done: standards === 0, enabled: standards > 0, ...(standardsHelp ? { detail: standardsHelp } : {}),
    },
    {
      id: "pages", label: `Check unread pages (${pages})`, count: pages,
      done: pages === 0, enabled: pages > 0, ...(pagesHelp ? { detail: pagesHelp } : {}),
    },
    {
      id: "decide", label: `Decide comments (${decide})`, count: decide,
      done: decide === 0, enabled: decide > 0,
    },
    {
      id: "sign", label: numbers.signed ? "Signed" : "Sign and export", count: null,
      done: numbers.signed, enabled: blockersClear && numbers.unsaved === 0 && !numbers.signed,
    },
  ];
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "19 Oct 2026"; "" when there is no readable date. */
export function signedDate(value: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

function known(n: number | null | undefined): n is number {
  return typeof n === "number" && Number.isFinite(n);
}

/** One piece of the verdict sentence; `count` names the shared count a
 *  number piece shows, so the bar can mark it with `data-count`. */
export interface VerdictPiece {
  text: string;
  count?: "comments" | "needsYou";
}

/** The verdict sentence in pieces (see `verdictLine`). */
export function verdictPieces(numbers: ReviewNumbers): VerdictPiece[] {
  if (numbers.signed) {
    const when = signedDate(numbers.signedAt);
    return [{ text: when ? `Signed on ${when}.` : "Signed." }];
  }
  const out: VerdictPiece[] = [];
  if (known(numbers.comments)) {
    if (numbers.comments === 0) out.push({ text: "No comments" });
    else {
      out.push({ text: numbers.comments.toLocaleString(), count: "comments" });
      out.push({ text: numbers.comments === 1 ? " comment" : " comments" });
      if (known(numbers.needsYou) && numbers.needsYou > 0) {
        out.push({ text: ", " });
        out.push({ text: numbers.needsYou.toLocaleString(), count: "needsYou" });
        out.push({ text: numbers.needsYou === 1 ? " needs your judgement" : " need your judgement" });
      }
    }
    out.push({ text: ". " });
  }
  const ready = actionSteps(numbers).find((s) => s.id === "sign")?.enabled ?? false;
  out.push({ text: ready ? "Ready to sign." : "Not signed yet." });
  return out;
}

/** The one plain sentence at the top of the bar. An unknown number is left
 *  out (never shown as 0). Examples: "12 comments, 3 need your judgement.
 *  Not signed yet." / "No comments. Ready to sign." / "Signed on 19 Oct 2026." */
export function verdictLine(numbers: ReviewNumbers, _run: ReviewRunSummary): string {
  return verdictPieces(numbers).map((p) => p.text).join("");
}
