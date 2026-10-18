/**
 * The Sheet screen's cards (#967 PR 2): one card per POINT, not per finding.
 *
 * Findings with the same outcome, the same reason code and the same comment
 * template collapse into one card ("13 blanks, one comment"). An engineer's
 * own wording is theirs for that finding and is never merged.
 *
 * Display only. Stored statuses do not change, and whether the run may be
 * issued is still the server's issue gate, never this file.
 */
import type { CrsIssueGate, ReviewFinding } from "../../../types/api";
import { AI_ENGINEERING_CHECK, PAGE_READER_ONLY, UNREAD_PAGES, WEB_STANDARD_CHECK, pageList, trustWords } from "../reviewFormat";

const ASK_STATUSES = new Set(["NON_COMPLIANT", "MISSING_INFORMATION", "NEEDS_ENGINEER_REVIEW", "CONDITIONAL"]);
const CHECK_ORIGINS = new Set([AI_ENGINEERING_CHECK, WEB_STANDARD_CHECK]);

export type CardState = "open" | "agreed" | "not_needed" | "mixed";

export interface SheetCard {
  key: string;
  /** Leader first: the lowest page, so the document opens where the point starts. */
  findings: ReviewFinding[];
  state: CardState;
  page: number | null;
  /** Every datasheet page the card's findings sit on. */
  pages: number[];
}

/** The plain words of the owner's spec. Stored statuses are untouched. */
export const PLAIN_OUTCOME: Record<string, string> = {
  COMPLIANT: "meets the standard",
  NON_COMPLIANT: "does not meet",
  MISSING_INFORMATION: "needs you",
  NEEDS_ENGINEER_REVIEW: "needs you",
  CONDITIONAL: "needs you",
  NOT_IN_DOCUMENT_SCOPE: "belongs to another document",
};

function fold(text: string | null | undefined): string {
  return (text ?? "").toLowerCase().split(/\s+/).filter(Boolean).join(" ");
}

/** A page-reading question is a Review note, not a comment to the contractor. */
export function isPageNote(f: ReviewFinding): boolean {
  const why = f.ai_rationale ?? "";
  return why.startsWith(UNREAD_PAGES) || why.startsWith(PAGE_READER_ONLY);
}

/** rule_trust (#947 step 8): a "meets" from a SAFETY-tier rule is shown
 *  for the engineer's own tick. It is never a comment to the contractor:
 *  the engineer checks the value on the page, then ticks it or says
 *  something is off. */
export function isTickFinding(f: ReviewFinding): boolean {
  return Boolean(f.show_for_engineer_tick) && f.compliance_status === "COMPLIANT";
}

/** A finding the engineer must answer: a comment the sheet would carry, or a
 *  safety tick. */
export function isAskFinding(f: ReviewFinding): boolean {
  if (f.origin === "chat" || isPageNote(f)) return false;
  if (isTickFinding(f)) return true;
  if (CHECK_ORIGINS.has(f.origin ?? "")) return true;
  return ASK_STATUSES.has(f.compliance_status ?? "");
}

/** The datasheet field a finding is about, in the datasheet's own words.
 *  Shared with the CRS-first Sheet (order 95 piece 2). */
export function fieldOf(f: ReviewFinding): string {
  return f.matched_phrase || f.contractor_section || f.equipment_tag || "";
}

function reasonCode(f: ReviewFinding): string {
  const lead = /^[A-Z][A-Z_]{2,}\b/.exec(f.ai_rationale ?? "");
  return lead?.[0] ?? f.scope_decision?.reason_code ?? "";
}

/** The comment's template: its words with the field's name and every number
 *  taken out, so "Set pressure is blank" and "Orifice is blank" match. */
export function commentTemplate(f: ReviewFinding): string {
  let text = fold(f.required_action || f.finding);
  const field = fold(fieldOf(f));
  if (field) text = text.split(field).join("<field>");
  return text.replace(/\d+(?:[.,]\d+)?/g, "#");
}

/** #1062 (owner click-through, #1061 check 2): a requirement row with no
 *  clause id is a row of a standard's TABLE (a material grade, `· p142`
 *  only). Hundreds of them, each worded for its own grade, made hundreds of
 *  cards; one table is one point for the engineer. */
export function isTableRow(f: ReviewFinding): boolean {
  return !f.standard_clause && Boolean(f.standard_document_id) && typeof f.standard_page === "number"
    && !CHECK_ORIGINS.has(f.origin ?? "");
}

function cardKey(f: ReviewFinding): string {
  if (f.engineer_comment) return `own:${f.id}`;
  // A safety tick is one value, checked by one person: never grouped.
  if (isTickFinding(f)) return `tick:${f.id}`;
  // One card per table page of a standard, whatever each row's wording.
  if (isTableRow(f)) return ["table", f.standard_document_id, f.standard_page, f.compliance_status ?? ""].join("\u001f");
  return [f.origin ?? "", f.compliance_status ?? "", reasonCode(f), commentTemplate(f)].join("\u001f");
}

export function isAgreed(f: ReviewFinding): boolean {
  return Boolean(f.confirmed_by) && f.approval_status !== "rejected";
}

export function isNotNeeded(f: ReviewFinding): boolean {
  return f.approval_status === "rejected";
}

function stateOf(findings: ReviewFinding[]): CardState {
  const agreed = findings.filter(isAgreed).length;
  const dropped = findings.filter(isNotNeeded).length;
  if (agreed + dropped < findings.length) return "open";
  if (agreed === findings.length) return "agreed";
  if (dropped === findings.length) return "not_needed";
  return "mixed";
}

function pageOf(f: ReviewFinding): number {
  return typeof f.contractor_page === "number" ? f.contractor_page : Number.MAX_SAFE_INTEGER;
}

export function buildCards(findings: ReviewFinding[]): SheetCard[] {
  const groups = new Map<string, ReviewFinding[]>();
  for (const f of findings) {
    if (!isAskFinding(f)) continue;
    const key = cardKey(f);
    groups.set(key, [...(groups.get(key) ?? []), f]);
  }
  return [...groups.entries()]
    .map(([key, list]) => {
      const sorted = [...list].sort((a, b) => pageOf(a) - pageOf(b));
      const page = sorted[0].contractor_page ?? null;
      const pages = [...new Set(sorted.map((f) => f.contractor_page).filter((p): p is number => typeof p === "number"))];
      return { key, findings: sorted, state: stateOf(sorted), page, pages };
    })
    .sort((a, b) => pageOf(a.findings[0]) - pageOf(b.findings[0]));
}

const TITLE_TAIL: Record<string, string> = {
  NON_COMPLIANT: "does not meet the standard",
  MISSING_INFORMATION: "is not given",
  NEEDS_ENGINEER_REVIEW: "needs your judgement",
  CONDITIONAL: "needs your judgement",
};
const TITLE_TAIL_PLURAL: Record<string, string> = {
  NON_COMPLIANT: "do not meet the standard",
  MISSING_INFORMATION: "are not given",
  NEEDS_ENGINEER_REVIEW: "need your judgement",
  CONDITIONAL: "need your judgement",
};

function capital(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

/** The card's title in plain English: what it is about, never a clause number. */
export function cardTitle(card: SheetCard): string {
  const leader = card.findings[0];
  const fields = [...new Set(card.findings.map(fieldOf).filter(Boolean))];
  const subject = fields.length === 0 ? "This point"
    : fields.length === 1 ? fields[0]
    : fields.length === 2 ? `${fields[0]} and ${fields[1]}`
    : `${fields[0]}, ${fields[1]} and ${fields.length - 2} more`;
  if (isTickFinding(leader)) return capital(`${subject} meets the standard: a safety field, please check it`);
  if (isTableRow(leader) && card.findings.length > 1) {
    // #1062: the table, not its rows; the page is the standard's (where the table is).
    const tail = TITLE_TAIL_PLURAL[leader.compliance_status ?? ""] ?? "need your answer";
    return `${card.findings.length} rows of a table on page ${leader.standard_page} of the standard ${tail}`;
  }
  if (CHECK_ORIGINS.has(leader.origin ?? "")) {
    return capital(`${subject}: the computer's plausibility check raised it`);
  }
  const plural = fields.length > 1 && leader.compliance_status === "MISSING_INFORMATION";
  const tail = TITLE_TAIL[leader.compliance_status ?? ""] ?? "needs your answer";
  return capital(`${subject} ${plural ? "are not given" : tail}`);
}

/** "13 blanks, one comment" for a group; nothing for a single finding. */
export function groupLine(card: SheetCard): string {
  const n = card.findings.length;
  if (n < 2) return "";
  if (isTableRow(card.findings[0])) return `${n} rows of one table, one answer`;
  return `${n} ${findingNoun(card)}, one answer`;
}

/** #1094: one distinct (standard, clause) a card's findings cite, with what
 *  it raised. A placeholder card groups blanks by outcome and wording, not
 *  by requirement, so one card may cite many clauses; the card must never
 *  show one of them as THE rule for all its blanks. */
export interface ClauseGroup {
  /** The first finding citing it (lowest page): what "open the rule" opens. */
  leader: ReviewFinding;
  standardId: string;
  clause: string;
  /** How many of the card's findings this clause raised. */
  count: number;
  /** The fields (labels) it covers, distinct, in page order. */
  fields: string[];
}

/** True when the finding names no rule at all: no standard and no clause. */
export function hasNoClause(f: ReviewFinding): boolean {
  return !f.standard_document_id && !f.standard_clause;
}

/** The card's distinct (standard, clause) pairs in page order; findings that
 *  name no clause share one group with an empty standard and clause. */
export function clauseGroups(card: SheetCard): ClauseGroup[] {
  const groups = new Map<string, ClauseGroup>();
  for (const f of card.findings) {
    const standardId = f.standard_document_id ?? "";
    const clause = f.standard_clause ?? "";
    const key = `${standardId}\u001f${clause}`;
    const group = groups.get(key) ?? { leader: f, standardId, clause, count: 0, fields: [] };
    group.count += 1;
    const field = fieldOf(f);
    if (field && !group.fields.includes(field)) group.fields.push(field);
    groups.set(key, group);
  }
  return [...groups.values()];
}

/** "4 clauses across 3 standards" - the headline of a card whose blanks
 *  cite more than one rule. Counts only what names a clause; the findings
 *  no clause names are counted separately so the words stay true. */
export function clauseSummary(groups: ClauseGroup[], noun: string): string {
  const named = groups.filter((g) => !(g.standardId === "" && g.clause === ""));
  const standards = new Set(named.map((g) => g.standardId).filter(Boolean)).size;
  const unnamed = groups.find((g) => g.standardId === "" && g.clause === "")?.count ?? 0;
  const parts: string[] = [];
  if (named.length > 0) {
    const across = standards > 1 ? ` across ${standards} standards` : standards === 1 ? " of one standard" : "";
    parts.push(`${named.length} ${named.length === 1 ? "clause" : "clauses"}${across}`);
  }
  if (unnamed > 0) parts.push(`${unnamed} ${unnamed === 1 ? noun.replace(/s$/, "") : noun} no clause names`);
  return parts.join(", and ");
}

/** The noun a card counts its findings in: blanks for "not given", places otherwise. */
export function findingNoun(card: SheetCard): string {
  return card.findings[0].compliance_status === "MISSING_INFORMATION" ? "blanks" : "places";
}

/** The trust line: who stands behind the rule, in the owner's words
 *  (rule_trust, #947), from the finding's own label. A finding the run did
 *  not label claims nothing: a guess is shown as a guess (CLAUDE.md rule
 *  4). A verdict held for the engineer says what the rule said. */
export function trustLine(card: SheetCard): string {
  const leader = card.findings[0];
  if (CHECK_ORIGINS.has(leader.origin ?? "")) return "Flagged by the computer's plausibility check";
  const words = trustWords(leader.trust_label) || "Rule not yet proven, so you decide";
  if (!leader.rule_said) return words;
  return `${words}. The rule said "${PLAIN_OUTCOME[leader.rule_said] ?? leader.rule_said}"; held for you.`;
}

/** "Not needed" leaves a comment off the Comment Resolution Sheet, so every
 *  place that offers it asks why, with the same floor (#925, #1037). */
export const MIN_REASON = 10;

/** #967 item 5: one value to underline on the page, by its finding and its
 *  card's state. Ids only; the value itself never leaves the finding. */
export interface PageMark {
  findingId: string;
  /** open: amber, needs you; tick: green, a safety tick to check (#1003);
   *  answered: grey. The same three the list under the page uses. */
  state: "open" | "tick" | "answered";
}

/** Every value on `page` that has a card, with its card's state - the marks
 *  the server draws on the page image. */
export function marksOn(cards: SheetCard[], page: number | null): PageMark[] {
  return cards.flatMap((c) =>
    c.findings
      .filter((f) => page !== null && f.contractor_page === page)
      .map((f) => ({
        findingId: f.id,
        state: c.state !== "open" ? "answered" as const : isTickFinding(c.findings[0]) ? "tick" as const : "open" as const,
      })),
  );
}

/** #967 item 5: what the page image shows, in words with the denominator (CLAUDE.md rule 4). */
export function marksSentence(located: number | null, total: number | null): string {
  if (located === null || total === null) return "The page is shown; whether its values are marked could not be read.";
  if (total === 0) return "No value on this page has a card.";
  if (located === total) {
    return total === 1 ? "The 1 value with a card is underlined on the page." : `All ${total} values with a card are underlined on the page.`;
  }
  if (located === 0) {
    return `None of the ${total} value${total === 1 ? "" : "s"} with a card could be placed on this page - read the page itself.`;
  }
  const missing = total - located;
  return `${located} of ${total} values with a card are underlined on the page; ${missing} could not be placed - read the page for ${missing === 1 ? "that one" : "those"}.`;
}

/** #603: how many cards the Sheet shows before "show the next". */
export const CARD_CHUNK = 60;

/** #603: a window of at most `shown` cards that always holds the selected
 *  card. The first `shown` cards while the selection is among them; when the
 *  keyboard (J / K wrap) or the default selection lands further down, a
 *  window of the same size around it - never every card up to it (a mostly
 *  answered sheet can put the first open card thousands of cards down). */
export function visibleCards(cards: SheetCard[], shown: number, selected: SheetCard | null): SheetCard[] {
  const at = selected ? cards.findIndex((c) => c.key === selected.key) : -1;
  if (at < shown) return cards.slice(0, shown);
  const from = Math.max(0, Math.min(at - Math.floor(shown / 2), cards.length - shown));
  return cards.slice(from, from + shown);
}

export interface SheetProgress {
  answered: number;
  total: number;
}

export function progress(cards: SheetCard[]): SheetProgress {
  return { answered: cards.filter((c) => c.state !== "open").length, total: cards.length };
}

/** The one headline sentence. The server's gate decides; this words it. */
export function headline(cards: SheetCard[], gate: CrsIssueGate | null, finalCode: string | null): string {
  const open = cards.length - progress(cards).answered;
  const unread = gate?.unread_pages.map((p) => p.page) ?? [];
  const onCards = new Set(cards.flatMap((c) => c.findings.map((f) => f.id)));
  const elsewhere = (gate?.open_findings ?? []).filter((o) => !onCards.has(o.finding_id)).length;
  const notes = [
    unread.length > 0
      ? `Page${unread.length === 1 ? "" : "s"} ${pageList(unread)} still need${unread.length === 1 ? "s" : ""} a look.`
      : "",
    gate?.blockers.some((b) => b.startsWith("no page coverage")) ? "No page can be called read yet." : "",
    elsewhere > 0 ? `${elsewhere} more ${elsewhere === 1 ? "item" : "items"} on the sheet ${elsewhere === 1 ? "needs" : "need"} a decision.` : "",
  ].filter(Boolean);
  const tail = notes.length > 0 ? ` ${notes.join(" ")}` : "";
  if (open > 0) {
    const lead = `${open} ${open === 1 ? "thing needs" : "things need"} your answer.`;
    return `${lead}${tail || " Everything else checked out."}`;
  }
  if (!finalCode) return `All answered. Choose your overall decision.${tail}`;
  if (gate?.issuable) return "All answered and decided. Ready to send to the contractor.";
  const first = gate?.blockers.find((b) => !b.includes("final code"));
  return first ? `Not ready to send yet: ${first}.` : "Checking whether it can be sent…";
}

/** Plain words for the passed findings, with their boundary (this run). */
export function passedCount(findings: ReviewFinding[]): number {
  return findings.filter((f) => f.compliance_status === "COMPLIANT").length;
}
