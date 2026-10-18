/**
 * The CRS-first Sheet's rows (order 95 piece 2, spec 1.2; Part of #967).
 *
 * ONE ROW PER COMMENT, in the client's seven columns: comment no., page or
 * section, item, clause and standard, observation, required action, status.
 * A row is the same group of findings the card view shows as one card
 * (`buildCards`: "13 blanks, one comment"), so the two screens never
 * disagree about what one comment is. Every other finding that is not a
 * note is one row of its own, whatever its status: Met and not-applicable
 * rows hide behind one line by default; anything else needs the engineer.
 * A finding the engineer already rejected is not on the sheet at all; the
 * footer counts it.
 *
 * Display only. Stored statuses do not change here.
 */
import type { ReviewFinding, ReviewRunSummary, RunSummaryHowReviewed } from "../../../types/api";
import { orNothing, pageList } from "../reviewFormat";
import {
  type CardState, type SheetCard, buildCards, fieldOf, groupLine, isNotNeeded, isPageNote, isTickFinding,
} from "../sheet/sheetCards";
import { type RunFacts, type ServerTiers, type TierCounts, type TierResult, countTiers, tierFor, tierOfGroup } from "./tiers";

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
 *  the colon are already plain; the code itself is not for the engineer. */
export function plainObservation(text: string): string {
  return text.replace(/^[a-z]+(?:_[a-z]+)+:\s*/, "");
}

function rowOf(key: string, findings: ReviewFinding[], state: CardState, tier: TierResult, standardNames: Map<string, string>): CrsRow {
  const leader = findings[0];
  const extra = findings.length > 1 ? groupLine({ key, findings, state, page: null, pages: [] }) : "";
  return {
    key, findings, tier, commentNo: null,
    pageOrSection: pageOrSectionOf(findings),
    item: itemOf(findings),
    clauseAndStandard: clauseAndStandardOf(leader, standardNames),
    observation: [plainObservation(orNothing(leader.finding)), extra].filter(Boolean).join(" "),
    requiredAction: orNothing(leader.engineer_comment) || orNothing(leader.required_action),
    status: statusOf(state, tier),
    priorState: state,
    tick: isTickFinding(leader),
    page: leader.contractor_page ?? null,
  };
}

function cardRow(card: SheetCard, facts: RunFacts, standardNames: Map<string, string>, server: ServerTiers | null): CrsRow {
  return rowOf(card.key, card.findings, card.state, tierOfGroup(card.findings, facts, server), standardNames);
}

/** The findings still on the sheet, and how many the engineer already
 *  rejected (approval_status "rejected"), which the footer states. */
export function splitRejected(findings: ReviewFinding[]): { findings: ReviewFinding[]; rejected: number } {
  const kept = findings.filter((f) => !isNotNeeded(f));
  return { findings: kept, rejected: findings.length - kept.length };
}

/** Every row of the sheet, comments first (Tier B and C, in page order,
 *  numbered), then the Tier A rows in page order. Rejected findings are
 *  filtered out first. A chat note or a page-reading note is not a comment
 *  to the contractor and is not a row; the unread pages are the headline's
 *  and the footer's. Every other finding is a row: one the card view does
 *  not group (a met value, a null or unknown status) takes its own tier,
 *  so nothing is dropped quietly. `server`: the run summary's tier per
 *  finding (#1111); when given it decides every tier, `facts` only fills
 *  in for a finding the server did not name. */
export function buildCrsRows(
  all: ReviewFinding[], facts: RunFacts, standardNames: Map<string, string>, server: ServerTiers | null = null,
): CrsRow[] {
  const { findings } = splitRejected(all);
  const cards = buildCards(findings);
  const onCards = new Set(cards.flatMap((c) => c.findings.map((f) => f.id)));
  const rows = cards.map((c) => cardRow(c, facts, standardNames, server));
  for (const f of findings) {
    if (onCards.has(f.id) || f.origin === "chat" || isPageNote(f)) continue;
    rows.push(rowOf(`one:${f.id}`, [f], f.confirmed_by ? "agreed" : "open", tierFor(f, facts, server), standardNames));
  }
  const comments = rows.filter((r) => r.tier.tier !== "A").sort((a, b) => pageOf(a.findings[0]) - pageOf(b.findings[0]));
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

/** The run's stored fields the headline reads: the clauses not applicable
 *  and the pages the reader did not read. */
export interface HeadlineFields {
  /** `requirement_split.does_not_apply`; null when the run does not hold it. */
  doesNotApply: number | null;
  /** Pages not read into fields, and (from the server) pages the AI reader
   *  timed out on; both make a finding "page not read". */
  unreadPages: number[];
  /** Order 112: the seconds the run's stored trace adds up to, step by step;
   *  null when no trace was stored (then no read time is shown). */
  readSeconds: number | null;
}

/** From the run summary's "How this was reviewed" record (#1111) when the
 *  server sent one, else from the runs list's copy of the same stored fields. */
export function headlineFieldsOf(run: ReviewRunSummary, how: RunSummaryHowReviewed | null = null): HeadlineFields {
  if (how) {
    const pages = [...(how.page_coverage?.pages_not_read_into_fields ?? []), ...(how.timed_out_pages ?? [])];
    const steps = Object.values(how.stage_seconds ?? {});
    return {
      doesNotApply: how.requirement_split?.does_not_apply ?? null,
      unreadPages: [...new Set(pages)].sort((a, b) => a - b),
      readSeconds: steps.length ? steps.reduce((a, b) => a + b, 0) : null,
    };
  }
  return {
    doesNotApply: run.requirement_split?.does_not_apply ?? null,
    unreadPages: run.page_coverage?.pages_not_read_into_fields ?? [],
    readSeconds: null,
  };
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
    unread.length ? `the reader gave up on ${unread.length === 1 ? "page" : "pages"} ${spoken(pageList(unread))}` : "",
  ].filter(Boolean);
  const third = reading.length ? ` ${reading.join("; ").replace(/^the/, "The")}.` : "";
  return `${first}${second}${third}`;
}
