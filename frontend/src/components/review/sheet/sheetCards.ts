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
import { AI_ENGINEERING_CHECK, PAGE_READER_ONLY, UNREAD_PAGES, WEB_STANDARD_CHECK, pageList } from "../reviewFormat";

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
function isPageNote(f: ReviewFinding): boolean {
  const why = f.ai_rationale ?? "";
  return why.startsWith(UNREAD_PAGES) || why.startsWith(PAGE_READER_ONLY);
}

/** A finding the engineer must answer: a comment the sheet would carry. */
export function isAskFinding(f: ReviewFinding): boolean {
  if (f.origin === "chat" || isPageNote(f)) return false;
  if (CHECK_ORIGINS.has(f.origin ?? "")) return true;
  return ASK_STATUSES.has(f.compliance_status ?? "");
}

function fieldOf(f: ReviewFinding): string {
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

function cardKey(f: ReviewFinding): string {
  if (f.engineer_comment) return `own:${f.id}`;
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
  const noun = card.findings[0].compliance_status === "MISSING_INFORMATION" ? "blanks" : "places";
  return `${n} ${noun}, one answer`;
}

/** The trust line. Until rule_trust (#947) is wired, no rule is claimed as
 *  proven: a guess is shown as a guess (CLAUDE.md rule 4). */
export function trustLine(card: SheetCard): string {
  const leader = card.findings[0];
  if (CHECK_ORIGINS.has(leader.origin ?? "")) return "Flagged by the computer's plausibility check";
  return "Rule not yet proven, so you decide";
}

/** #603: how many cards the Sheet shows before "show the next". */
export const CARD_CHUNK = 60;

/** #603: the first `shown` cards, extended so the selected card is always
 *  among them - the keyboard walks every card, not only the shown ones. */
export function visibleCards(cards: SheetCard[], shown: number, selected: SheetCard | null): SheetCard[] {
  const at = selected ? cards.findIndex((c) => c.key === selected.key) : -1;
  return cards.slice(0, Math.max(shown, at + 1));
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
