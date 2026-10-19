/**
 * The CRS-first Sheet's rows (order 95 piece 2, spec 1.2; Part of #967).
 *
 * ONE ROW PER COMMENT, in the client's seven columns: comment no., page or
 * section, item, clause and standard, observation, required action, status.
 *
 * ORDER 139 PART 2: A ROW IS THE FILE'S ROW. The server groups the findings
 * (`crs_mapping.crs_groups`, one comment per datasheet field) and sends each
 * finding's row (`crs_group`), the row's place in the file's order
 * (`crs_order`) and its action line (`crs_action`) on the run summary. The
 * screen groups by those and never by a rule of its own, so the sheet on
 * screen and the file cannot disagree about what one comment is. A finding
 * the server put on no row (a met value, not applicable, a newer finding) is
 * one row of its own, after the grouped comments. When the server sent no
 * grouping (an older server, or the summary read failed) every finding is a
 * row of its own and the sheet says so once (`UNGROUPED_NOTE`) - never the
 * old screen-side grouping, which would be a guess dressed as the file's.
 *
 * Met and not-applicable rows hide behind one line by default; anything else
 * needs the engineer. A finding the engineer already rejected is not on the
 * sheet at all; the footer counts it.
 *
 * Display only. Stored statuses do not change here.
 */
import type { ReviewFinding, ReviewRunSummary, ReviewRunTierSummary, RunSummaryHowReviewed, RunSummaryTierRow } from "../../../types/api";
import { splitReason } from "../reasonWords";
import { orNothing, pageList } from "../reviewFormat";
import {
  type CardState, type SheetCard, clauseGroups, fieldOf, groupLine, isAgreed, isNotNeeded, isPageNote, isTickFinding,
} from "../sheet/sheetCards";
import { type RunFacts, type ServerTiers, type TierCounts, type TierResult, countTiers, tierFor, tierOfGroup } from "./tiers";

/** Order 139 part 2: said once on the sheet when the server sent no grouping. */
export const UNGROUPED_NOTE = "Shown one row per finding: the sheet's grouping could not be read from the server.";

/** Order 139 part 2: a row lists at most this many supporting clauses (the
 *  file's `crs_mapping.MAX_CLAUSE_LINES`), then "and k more of these n". */
export const MAX_CLAUSE_LINES = 10;

/** The run summary's CRS grouping, per finding id; null when the server sent
 *  none (`crs_grouping` false or absent, or no summary). */
export type ServerGroups = ReadonlyMap<string, RunSummaryTierRow>;

export function serverGroupsOf(summary: ReviewRunTierSummary | null | undefined): ServerGroups | null {
  if (!summary?.crs_grouping) return null;
  return new Map(summary.rows.filter((r) => r.crs_group || r.crs_note).map((r) => [r.finding_id, r]));
}

/** Order 139 part 2 (covers #1177's screen gap): a finding the file put on
 *  no comment row (`crs_note`) - one it counts in its Review notes, or a
 *  datasheet check about a value another row already raises - is never a
 *  comment row to decide on screen either. */
export function isServerNote(f: ReviewFinding, groups: ServerGroups | null): boolean {
  return Boolean(groups?.get(f.id)?.crs_note);
}

/** How many of the run's findings (rejected ones aside) the file puts on no
 *  comment row (`crs_note`) - said once under the sheet. */
export function serverNoteCount(all: ReviewFinding[], groups: ServerGroups | null): number {
  return splitRejected(all).findings.filter((f) => isServerNote(f, groups)).length;
}

/** The line under the sheet for `serverNoteCount`; "" when there are none. */
export function serverNotesLine(n: number): string {
  if (n <= 0) return "";
  const one = n === 1;
  return `${n.toLocaleString()} ${one ? "finding of this review is not a comment row" : "findings of this review are not comment rows"}`
    + ` of the sheet: ${one ? "it is" : "they are"} in its Review notes (the engineer's internal list), or`
    + ` ${one ? "repeats" : "repeat"} a value another comment row already raises.`;
}

export interface CrsRow {
  key: string;
  /** Leader first, by page. */
  findings: ReviewFinding[];
  tier: TierResult;
  /** 1..N over the comments (Tier B and C) in page order; null on a Met or
   *  not-applicable row, which is not a comment. */
  commentNo: number | null;
  pageOrSection: string;
  item: string;
  clauseAndStandard: string;
  observation: string;
  requiredAction: string;
  /** "Open" on a new comment; "Kept earlier" when an engineer already
   *  agreed it on the card view; the tier's own word on a Tier A row. */
  status: string;
  /** The card view's state for the same findings (rejected ones are
   *  filtered out first, so "open" or "agreed"). */
  priorState: CardState;
  /** rule_trust (#947): a safety field shown for the engineer's own tick. */
  tick: boolean;
  page: number | null;
  /* Order 139 part 2 fields below are optional only so a row built by hand
   * (older tests, contract stubs) still type-checks; `buildCrsRows` always
   * sets them. */
  /** Order 139 part 2: "server" when the row is the file's row (the run
   *  summary's grouping), "none" when the server sent no grouping and every
   *  finding is shown as a row of its own (the sheet then says
   *  `UNGROUPED_NOTE`). */
  grouping?: "server" | "none";
  /** The file's row this is (`crs_group`), its place in the file's order
   *  (`crs_order`) and its action line (`crs_action`, on a field row asking
   *  two or more things); null when the server put the finding on no row. */
  crsGroup?: string | null;
  crsOrder?: number | null;
  crsAction?: string | null;
  /** The row's rank and its word as the server sent them (order 139 section
   *  f); null / "" when not sent - never a guessed rank. */
  priority?: number | null;
  priorityLabel?: string;
  /** How many distinct named clauses the row's findings cite (the boundary
   *  of "Supporting clauses (n)"), and the first MAX_CLAUSE_LINES of them in
   *  the clause column's own words. */
  clauseCount?: number;
  clauses?: string[];
}

/** The client's seven columns, in the client's order and words (spec 1.2). */
export const CRS_COLUMNS = [
  "Comment no.", "Page or section", "Item", "Clause and standard", "Observation", "Required action", "Status",
] as const;

export type Depth = "critical" | "standard" | "everything";

export const DEPTHS: { id: Depth; label: string; help: string }[] = [
  { id: "critical", label: "Critical only", help: "Rows that need you, and clear failures." },
  { id: "standard", label: "Standard", help: "Every comment and every row that needs you." },
  { id: "everything", label: "Everything", help: "Also the values that met the standard." },
];

function pageOf(f: ReviewFinding): number {
  return typeof f.contractor_page === "number" ? f.contractor_page : Number.MAX_SAFE_INTEGER;
}

function pageOrSectionOf(findings: ReviewFinding[]): string {
  const pages = [...new Set(findings.map((f) => f.contractor_page).filter((p): p is number => typeof p === "number"))];
  const section = orNothing(findings[0].contractor_section);
  const pageText = pages.length === 0 ? "" : pages.length === 1 ? `p. ${pages[0]}` : `pp. ${pageList(pages)}`;
  if (pageText && section && findings.length === 1 && section !== fieldOf(findings[0])) return `${pageText}, ${section}`;
  return pageText || section;
}

function itemOf(findings: ReviewFinding[]): string {
  const fields = [...new Set(findings.map(fieldOf).filter(Boolean))];
  if (fields.length === 0) return orNothing(findings[0].equipment_tag);
  if (fields.length <= 2) return fields.join(" and ");
  return `${fields[0]}, ${fields[1]} and ${fields.length - 2} more`;
}

function clauseAndStandardOf(f: ReviewFinding, standardNames: Map<string, string>): string {
  const standard = standardNames.get(f.standard_document_id ?? "") ?? "";
  const clause = orNothing(f.standard_clause);
  const page = typeof f.standard_page === "number" ? `p. ${f.standard_page}` : "";
  return [standard, clause ? `clause ${clause}` : "", page].filter(Boolean).join(", ");
}

function statusOf(state: CardState, tier: TierResult): string {
  if (tier.tier === "A") return tier.label;
  return state === "agreed" ? "Kept earlier" : "Open";
}

/** Order 112: a finding's text may open with the review's internal reason
 *  code ("no_field_matched: ...", "ambiguous_match: ..."). The words after
 *  the colon are already plain; the code itself is not for the engineer.
 *  Order 120: the one split lives in `reasonWords`. */
export function plainObservation(text: string): string {
  return splitReason(text).rest;
}

/** The row's distinct named clauses, in the clause column's words. */
function namedClauses(findings: ReviewFinding[], standardNames: Map<string, string>): string[] {
  const card = { key: "", findings, state: "open", page: null, pages: [] } as SheetCard;
  return clauseGroups(card)
    .filter((g) => g.standardId !== "" || g.clause !== "")
    .map((g) => clauseAndStandardOf(g.leader, standardNames));
}

function rowOf(
  key: string, findings: ReviewFinding[], state: CardState, tier: TierResult, standardNames: Map<string, string>,
  grouping: CrsRow["grouping"], server: RunSummaryTierRow | null,
): CrsRow {
  const leader = findings[0];
  const extra = findings.length > 1 ? groupLine({ key, findings, state, page: null, pages: [] }) : "";
  const clauses = namedClauses(findings, standardNames);
  const crsAction = orNothing(server?.crs_action) || null;
  return {
    key, findings, tier, commentNo: null,
    pageOrSection: pageOrSectionOf(findings),
    item: itemOf(findings),
    clauseAndStandard: clauseAndStandardOf(leader, standardNames),
    observation: [plainObservation(orNothing(leader.finding)), extra].filter(Boolean).join(" "),
    // Order 139 part 2: the engineer's words if edited, else the file's
    // action line for a row of many clauses, else the finding's own.
    requiredAction: orNothing(leader.engineer_comment) || crsAction || orNothing(leader.required_action),
    status: statusOf(state, tier),
    priorState: state,
    tick: isTickFinding(leader),
    page: leader.contractor_page ?? null,
    grouping,
    crsGroup: server?.crs_group ?? null,
    crsOrder: server?.crs_order ?? null,
    crsAction,
    priority: server?.crs_priority ?? null,
    priorityLabel: server?.crs_priority_label ?? "",
    clauseCount: clauses.length,
    clauses: clauses.slice(0, MAX_CLAUSE_LINES),
  };
}

/** Order 139 part 2: the "Supporting clauses" lines under a row's required
 *  action - only on a row the file prints them for (one with an action line,
 *  i.e. a field row asking two or more things), with the file's cap and
 *  count: "and k more of these n". [] on any other row. */
export function supportingClauseLines(row: CrsRow): string[] {
  const n = row.clauseCount ?? 0;
  const listed = row.clauses ?? [];
  if (!row.crsAction || n < 1) return [];
  const more = n - listed.length;
  return [`Supporting clauses (${n}):`, ...listed, ...(more > 0 ? [`and ${more} more of these ${n}`] : [])];
}

/** The findings still on the sheet, and how many the engineer already
 *  rejected (approval_status "rejected"), which the footer states. */
export function splitRejected(findings: ReviewFinding[]): { findings: ReviewFinding[]; rejected: number } {
  const kept = findings.filter((f) => !isNotNeeded(f));
  return { findings: kept, rejected: findings.length - kept.length };
}

/** The once-said note when the sheet shows the server's grouping not at
 *  all; null when the rows are the file's (or there are none). */
export function groupingNote(rows: CrsRow[]): string | null {
  return rows.some((r) => r.grouping === "none") ? UNGROUPED_NOTE : null;
}

function byPageThenClause(a: ReviewFinding, b: ReviewFinding): number {
  return pageOf(a) - pageOf(b) || orNothing(a.standard_clause).localeCompare(orNothing(b.standard_clause), undefined, { numeric: true });
}

/** Every row of the sheet: the comments first (Tier B and C) - the server's
 *  rows in the file's order (`crs_order`), then any finding the server put
 *  on no row, by page - numbered 1..N; then the Tier A rows by page.
 *  Rejected findings are filtered out first. A chat note or a page-reading
 *  note is not a comment to the contractor and is not a row; the unread
 *  pages are the headline's and the footer's. Every other finding is on a
 *  row, so nothing is dropped quietly.
 *
 *  `server`: the run summary's tier per finding (#1111); when given it
 *  decides every tier, `facts` only fills in for a finding the server did
 *  not name. `groups` (order 139 part 2): the run summary's CRS row per
 *  finding (`serverGroupsOf`); null = no server grouping, and every finding
 *  is a row of its own (`groupingNote` then says so). A finding the file put
 *  in its Review notes (`crs_note`) is not a row (`serverNotesLine`). */
export function buildCrsRows(
  all: ReviewFinding[], facts: RunFacts, standardNames: Map<string, string>, server: ServerTiers | null = null,
  groups: ServerGroups | null = null,
): CrsRow[] {
  const { findings } = splitRejected(all);
  const grouping: CrsRow["grouping"] = groups ? "server" : "none";
  const byGroup = new Map<string, ReviewFinding[]>();
  const rows: CrsRow[] = [];
  for (const f of findings) {
    if (f.origin === "chat" || isPageNote(f) || isServerNote(f, groups)) continue;
    const group = groups?.get(f.id)?.crs_group;
    if (group) byGroup.set(group, [...(byGroup.get(group) ?? []), f]);
    else rows.push(rowOf(`one:${f.id}`, [f], f.confirmed_by ? "agreed" : "open", tierFor(f, facts, server), standardNames, grouping, null));
  }
  for (const [group, list] of byGroup) {
    const sorted = [...list].sort(byPageThenClause);
    const state: CardState = sorted.every(isAgreed) ? "agreed" : "open";
    rows.push(rowOf(`crs:${group}`, sorted, state, tierOfGroup(sorted, facts, server), standardNames, grouping,
      groups?.get(sorted[0].id) ?? null));
  }
  const order = (r: CrsRow): number => r.crsOrder ?? Number.MAX_SAFE_INTEGER;
  const comments = rows.filter((r) => r.tier.tier !== "A")
    .sort((a, b) => order(a) - order(b) || pageOf(a.findings[0]) - pageOf(b.findings[0]));
  const met = rows.filter((r) => r.tier.tier === "A").sort((a, b) => pageOf(a.findings[0]) - pageOf(b.findings[0]));
  comments.forEach((r, i) => { r.commentNo = i + 1; });
  return [...comments, ...met];
}

export function rowCounts(rows: CrsRow[]): TierCounts {
  return countTiers(rows.map((r) => r.tier));
}

/** A small, stable random number source: the same run id gives the same
 *  spot-check rows on every visit (mulberry32 over a string hash). */
function seeded(seed: string): () => number {
  let h = 1779033703 ^ seed.length;
  for (let i = 0; i < seed.length; i += 1) {
    h = Math.imul(h ^ seed.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  let a = h >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const SPOT_CHECK_SHARE = 0.05;

/** Spec 1.2: a 5% random sample of the Met rows, seeded by the run id so it
 *  is the same sample on every visit, plus every safety tick (#947), which
 *  is a Met the engineer must look at anyway. At least one when any Met
 *  row exists, so Tier A is never blindly trusted. */
export function spotCheckKeys(rows: CrsRow[], runId: string): Set<string> {
  const met = rows.filter((r) => r.tier.label === "Met");
  const keys = new Set(met.filter((r) => r.tick).map((r) => r.key));
  const pool = met.filter((r) => !r.tick);
  const want = Math.max(met.length > 0 ? 1 : 0, Math.ceil(met.length * SPOT_CHECK_SHARE)) - keys.size;
  const next = seeded(runId);
  const order = pool.map((r, i) => ({ r, i, k: next() })).sort((a, b) => a.k - b.k || a.i - b.i);
  for (const { r } of order.slice(0, Math.max(0, want))) keys.add(r.key);
  return keys;
}

/** The rows the depth selector shows, with Tier A behind its one line
 *  unless `showMet` or depth "everything"; the spot-check rows show at the
 *  Standard depth (Critical only is Needs you and clear failures, nothing else). */
export function visibleRows(rows: CrsRow[], depth: Depth, showMet: boolean, spot: Set<string>): CrsRow[] {
  return rows.filter((r) => {
    if (r.tier.tier === "C") return true;
    if (r.tier.tier === "B") return depth !== "critical" || r.findings[0].compliance_status === "NON_COMPLIANT";
    return depth === "everything" || showMet || (depth === "standard" && spot.has(r.key));
  });
}

/** "4, 9" -> "4 and 9"; "1-3, 7, 9" -> "1-3, 7 and 9". */
function spoken(list: string): string {
  const at = list.lastIndexOf(", ");
  return at < 0 ? list : `${list.slice(0, at)} and ${list.slice(at + 2)}`;
}

function plural(n: number, one: string, many: string): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

/** Order 127: the one phrase for the run's unread pages, shared by the
 *  header and the "Before you sign" box. `total` null = the page count is
 *  not known, and then no "of T" is claimed. "Not fully read": a page the
 *  AI reader did not read may still have values the code readers took from
 *  it, so "not read" alone would contradict a met value cited on that page.
 *  `unreadPhrase(11, 11)` -> "11 of 11 pages were not fully read";
 *  `unreadPhrase(1, 12)` -> "1 of 12 pages was not fully read";
 *  `unreadPhrase(2, null)` -> "2 pages were not fully read". */
export function unreadPhrase(n: number, total: number | null): string {
  return total !== null
    ? `${n} of ${total} ${total === 1 ? "page" : "pages"} ${n === 1 ? "was" : "were"} not fully read`
    : `${n} ${n === 1 ? "page was" : "pages were"} not fully read`;
}

/** The run's stored fields the headline reads: the clauses not applicable
 *  and the pages not read. */
export interface HeadlineFields {
  /** `requirement_split.does_not_apply`; null when the run does not hold it. */
  doesNotApply: number | null;
  /** Order 127: the run's unread pages, one definition (the server's
   *  `unread_pages`, the same list the issue gate asks ticks for, before any
   *  tick). Empty when none, or when the run does not hold the list. */
  unreadPages: number[];
  /** The submittal's page count as the run stored it; null when not known. */
  pagesTotal: number | null;
  /** Order 112: the seconds the run's stored trace adds up to, step by step;
   *  null when no trace was stored (then no read time is shown). */
  readSeconds: number | null;
}

/** From the run summary's "How this was reviewed" record (#1111) when the
 *  server sent one, else from the runs list's copy of the same stored fields. */
export function headlineFieldsOf(run: ReviewRunSummary, how: RunSummaryHowReviewed | null = null): HeadlineFields {
  if (how) {
    const steps = Object.values(how.stage_seconds ?? {});
    return {
      doesNotApply: how.requirement_split?.does_not_apply ?? null,
      unreadPages: sortedPages(how.unread_pages),
      pagesTotal: how.page_coverage?.pages_total ?? null,
      readSeconds: steps.length ? steps.reduce((a, b) => a + b, 0) : null,
    };
  }
  return {
    doesNotApply: run.requirement_split?.does_not_apply ?? null,
    unreadPages: sortedPages(run.unread_pages),
    pagesTotal: run.page_coverage?.pages_total ?? null,
    readSeconds: null,
  };
}

/** The server's list, once each, in order; null or absent (not known) is []. */
function sortedPages(pages: number[] | null | undefined): number[] {
  return [...new Set(pages ?? [])].sort((a, b) => a - b);
}

/** The one headline line (spec 1.2). The comment, needs-you and met counts
 *  are the run summary's (#1111) when the server sent it, else the rows'
 *  own (the same tier result the table, the met line and the footer show);
 *  the clauses not applicable and the unread pages are the run's stored
 *  fields (`headlineFieldsOf`), the read time `created_at` / `completed_at`.
 *  A field the run does not hold renders as nothing, never 0. */
export function crsHeadline(
  run: ReviewRunSummary, counts: TierCounts, fields: HeadlineFields = headlineFieldsOf(run), findingsInComments: number | null = null,
): string {
  // Order 112: COUNTS ARE ROWS, the rows the table shows. A row can stand on
  // many findings ("13 blanks, one comment"), so the findings behind the
  // comment rows come second, and only when they differ from the rows.
  const comments = counts.comment + counts.needsYou;
  const behind = findingsInComments !== null && findingsInComments !== comments
    ? ` (${plural(findingsInComments, "finding", "findings")})` : "";
  const first = `${plural(comments, "comment", "comments")}${behind}`
    + (counts.needsYou > 0 ? `, ${counts.needsYou.toLocaleString()} ${counts.needsYou === 1 ? "needs" : "need"} your judgement.` : ".");
  const notApplicable = fields.doesNotApply;
  const quiet = [
    counts.met > 0 ? plural(counts.met, "value met", "values met") : "",
    typeof notApplicable === "number" ? `${plural(notApplicable, "clause", "clauses")} not applicable` : "",
  ].filter(Boolean);
  const second = quiet.length ? ` ${quiet.join(", ")} (hidden).` : "";
  // Order 112: the read time is the stored trace's own total, step by step.
  // Without a trace nothing is said: the run row's created_at and
  // completed_at do not bracket the reading (a run that read for most of an
  // hour showed "under a minute" in the owner's app, order 112).
  const minutes = fields.readSeconds !== null ? Math.round(fields.readSeconds / 60) : null;
  const unread = fields.unreadPages;
  const reading = [
    minutes !== null ? `Read in ${minutes < 1 ? "under a minute" : `${minutes} min`}` : "",
    unread.length ? `${unreadPhrase(unread.length, fields.pagesTotal)} (${spoken(pageList(unread))})` : "",
  ].filter(Boolean);
  const third = reading.length ? ` ${reading.join("; ")}.` : "";
  return `${first}${second}${third}`;
}
