/**
 * ONE home for the plain words of the AI review screens (rule 8): how a line
 * is NAMED, how its reason is WORDED, how the counts are SAID, and which
 * words may never reach a reader. Nothing here decides a verdict: a line
 * already carries its class and word (agentWords.ts keeps those). A reason
 * is reworded only into what the code saw; a reason this file does not know
 * and that carries a code word is shown as `UNKNOWN_WHY`, never raw.
 *
 * The phrase table mirrors the one the CRS file uses (backend/app/crs_ai_words.py);
 * the keys are the backend's own sentences.
 */
import type { AgentLine, AgentRunSummary } from "../../../types/api";

export const UNKNOWN_WHY = "It could not be confirmed.";

/** Words a reader must not see in the main columns. */
export const BANNED_ON_SCREEN: readonly RegExp[] = [
  /\bGREEN\b/, /\bRED\b/, /\bYELLOW\b/, /first verdict/i, /second opinion/i, /\bS-[A-Z]{1,6}-\d+\b/,
  /\bR-[0-9a-f]{8}(?:-[0-9a-f]{4}){0,4}[0-9a-f]*\b/i,
  /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i,
  /\b[a-z0-9]+(?:_[a-z0-9]+)+\b/,
  /\b(?:claude|sonnet|opus|haiku|gpt|qwen|llama|ollama|gemma|mistral)[\w.:-]*/i,
];

export function hasBannedWord(text: string): boolean {
  return BANNED_ON_SCREEN.some((re) => re.test(text));
}

/** "pressure_relief" -> "pressure relief": an internal word in words a reader knows. */
export function humanizeCode(text: string): string {
  return text.replace(/\b([A-Za-z0-9]+(?:_[A-Za-z0-9]+)+)\b/g, (m) => m.replace(/_/g, " "));
}

// ---------------------------------------------------------------- reasons

/** The backend's own sentences (exact start) -> plain words. */
const KNOWN: ReadonlyArray<readonly [string, string]> = [
  ["the paper is silent on this; a missing statement is not a failure",
    "The AI found no line for this on the pages it read; code cannot prove that something is absent"],
  ["the rule is conditional; code cannot prove the condition holds",
    "The rule holds only under a condition, and code cannot prove the condition holds"],
  ["the rule is a table row or a note; its conditions may lie outside the quote",
    "The rule is a table row or a note whose conditions may lie outside the quoted text"],
  ["the quoted paper text defers or leaves open this value", "The paper leaves this value open"],
  ["the quoted paper text could not be verified by code", "The quoted text could not be found on the page"],
  ["the quoted clause text could not be verified by code", "The quoted rule text could not be found in the rule book"],
  ["the reviewer's code found words", "The AI's own words say the paper leaves this out, so it stays an opinion"],
  ["the AI reader quoted only the field's name", "Only the name of the field was quoted, with no value after it"],
  ["two AI readers disagree on this line", "The second AI reader disagreed with the first"],
  ["not a held rule: code cannot tell the item is required", "This is not a held rule, so code cannot tell the item is required"],
  ["the rule's stored requirement row was not found", "The stored requirement for this rule was not found, so code cannot tell it binds"],
  ["the rule is advice, not a requirement", "The rule is advice, not a requirement, so something missing is not a failure"],
  ["the requirement does not say shall or must", "The rule does not say shall or must, so something missing is not a failure"],
  ["the requirement holds only under a condition", "The rule holds only under a condition, and code cannot prove it applies"],
  ["the rule has a stored exception", "The rule has an exception that may apply"],
  ["the rule names no field of the field registry", "The rule names no field code knows, so code cannot prove something is absent"],
  ["the requirement names several registry fields", "The rule names several fields, so code cannot tell which one is absent"],
  ["this paper kind has no field list", "This kind of paper has no fixed field list, so code cannot prove something is absent"],
  ["this paper kind's field list does not carry the field", "This item may belong in another paper"],
  ["a page has no readable text", "A page has no readable text, so code cannot prove something is absent"],
  ["a field read from the paper names this item", "The paper names this item, so it may be stated"],
  ["the field's registry words stand on a page of the paper", "The field's words stand on a page of the paper, so it may be stated"],
  ["the sheet marks this value as not final", "The paper marks this value as not final"],
  ["clause quote not verified or too short", "The quoted rule text is too short or could not be found, so an absence cannot be confirmed"],
  ["no second opinion on the absence", "No second AI reader confirmed that this is absent"],
  ["the second opinion did not agree the item is absent", "The second AI reader did not agree that this is absent"],
  ["second opinion model is the same or unknown",
    "The second check was not done by a different model, so this stays an opinion"],
  ["second opinion disagreed", "The second AI reader disagreed with the first"],
  ["no second opinion", "No second AI reader checked this, so it stays an opinion"],
  ["the AI did not give pass or fail", "The AI did not decide"],
  ["no figure with its unit inside both quotes", "The value and its unit were not found together in the quoted text"],
  ["code could not compare the figures", "Code could not compare the figures"],
  ["paper quote not verified by code", "The quoted text could not be found on the page"],
  ["clause quote not verified by code", "The quoted rule text could not be found in the rule book"],
  ["clause quote is too short or is the clause heading", "The quoted rule text is too short to rely on"],
  ["not mentioned is never a pass", "The paper does not mention this, and not mentioned is never counted as met"],
  ["AI call failed", "The AI gave no answer"],
  ["no answer from the AI", "The AI gave no answer"],
  ["answer cut off", "The AI's answer was cut off"],
  ["sweep finding", "A later look at the whole paper raised this, so it is left to the engineer"],
];
const ENDS = /[\s.;:]+$/;

/** One reason in plain words, never raw when it carries a code word. */
export function plainReason(raw: string | null | undefined): string {
  const text = (raw ?? "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  const out: string[] = [];
  let rest = text;
  while (rest) {
    const lower = rest.toLowerCase();
    const hit = KNOWN.find(([k]) => lower.startsWith(k.toLowerCase()));
    if (hit) {
      out.push(hit[1]);
      // A known sentence ends at its next ";" (a colour or an error text may follow it).
      const cut = rest.indexOf(";", hit[0].length);
      rest = cut < 0 ? "" : rest.slice(cut + 1).trim();
      // "...; first verdict RED" is a part of the same thought: dropped here.
      if (/^first verdict/i.test(rest)) rest = "";
      continue;
    }
    const cut = rest.indexOf(";");
    const piece = (cut < 0 ? rest : rest.slice(0, cut)).replace(ENDS, "");
    rest = cut < 0 ? "" : rest.slice(cut + 1).trim();
    if (!piece) continue;
    out.push(hasBannedWord(piece) ? UNKNOWN_WHY.replace(/\.$/, "") : piece);
  }
  const unique = out.filter((p, i) => out.indexOf(p) === i);
  const joined = unique.join("; ");
  return /[.!?]$/.test(joined) ? joined : `${joined}.`;
}

// ---------------------------------------------------------------- line names

export interface LineName {
  /** what a reader sees first */
  title: string;
  /** the internal id, for a tooltip or a small grey column */
  id: string;
}

const CHECK = /^S-[A-Za-z]{1,6}-0*(\d+)$/;
const CHECK_PLAIN = /^S-0*(\d+)$/;

/** A line is named by what it is, not by its id. */
export function lineName(line: Pick<AgentLine, "item_id" | "rule_book" | "clause">): LineName {
  const where = [line.rule_book, line.clause].map((s) => (s ?? "").trim()).filter(Boolean).join(" ");
  const check = CHECK.exec(line.item_id) ?? CHECK_PLAIN.exec(line.item_id);
  if (check) {
    return { title: `Checklist point ${check[1]}${where ? ` (${where})` : ""}`, id: line.item_id };
  }
  if (/^R-/.test(line.item_id)) {
    return { title: where ? `Rule: ${where}` : "Rule (no rule book or clause named)", id: line.item_id };
  }
  return { title: where ? `Point: ${where}` : "Point", id: line.item_id };
}

// ---------------------------------------------------------------- open points and counts

const isOpen = (l: Pick<AgentLine, "verdict_class" | "word">) =>
  l.verdict_class !== "Not applicable" && l.word !== "Pass";

/** Lines a reader still has to look at: everything except Pass and not applicable. */
export function openPoints(lines: readonly Pick<AgentLine, "verdict_class" | "word">[]): number {
  return lines.filter(isOpen).length;
}

const plural = (n: number, one: string, many: string) => `${n.toLocaleString()} ${n === 1 ? one : many}`;

/** The counts of one AI review in plain words, over the lines of this review
 *  only. A class with no line is left out (a zero that matters, "proven by
 *  code", is always said). */
export function countsSentence(lines: readonly AgentLine[]): string {
  const n = (f: (l: AgentLine) => boolean) => lines.filter(f).length;
  const klass = (c: string) => (l: AgentLine) => l.verdict_class === c;
  const opinion = (l: AgentLine) => l.verdict_class === "AI opinion, engineer to confirm" || l.verdict_class === "AI opinion, rule not yet approved";
  const parts: string[] = [];
  const notMet = n((l) => (opinion(l) || klass("AI verdict, two readers agree")(l)) && /not met/.test(l.word));
  const met = n((l) => (opinion(l) || klass("AI verdict, two readers agree")(l)) && /: met$/.test(l.word));
  const stated = n((l) => klass("AI verdict, two readers agree")(l) && /not stated/.test(l.word));
  const proven = n(klass("Proven by code"));
  if (notMet) parts.push(plural(notMet, "point the AI thinks is not met", "points the AI thinks are not met"));
  if (met) parts.push(plural(met, "point the AI thinks is met", "points the AI thinks are met"));
  if (stated) parts.push(plural(stated, "point the AI says the paper does not state", "points the AI says the paper does not state"));
  const q = n(klass("Query for the engineer"));
  if (q) parts.push(plural(q, "question for the engineer", "questions for the engineer"));
  const needs = n(klass("Not checked on this paper"));
  if (needs) parts.push(plural(needs, "point that needs a drawing or a calculation", "points that need a drawing or a calculation"));
  const na = n(klass("Not applicable"));
  if (na) parts.push(plural(na, "rule that does not apply", "rules that do not apply"));
  const nr = n(klass("Not reviewed"));
  if (nr) parts.push(plural(nr, "line the AI gave no answer for", "lines the AI gave no answer for"));
  const held = n(klass("Not checked: rule book not held"));
  if (held) parts.push(plural(held, "line not checked because we do not hold its rule book", "lines not checked because we do not hold their rule book"));
  const notes = n(klass("AI note, no rule book"));
  if (notes) parts.push(plural(notes, "AI note", "AI notes"));
  parts.push(`${proven.toLocaleString()} proven by code`);
  return parts.join(", ");
}

/** The same in the words of the class counts the summary route sends, for the
 *  moment the lines are not all loaded: no opinion is split into met / not met. */
export function classCountsSentence(counts: AgentRunSummary["counts_by_class"]): string {
  const c = (k: string) => counts[k] ?? 0;
  const parts: string[] = [];
  const opinions = c("AI opinion, engineer to confirm") + c("AI opinion, rule not yet approved");
  if (opinions) parts.push(plural(opinions, "AI opinion to confirm", "AI opinions to confirm"));
  if (c("AI verdict, two readers agree")) parts.push(plural(c("AI verdict, two readers agree"), "AI verdict agreed by two readers", "AI verdicts agreed by two readers"));
  if (c("Query for the engineer")) parts.push(plural(c("Query for the engineer"), "question for the engineer", "questions for the engineer"));
  if (c("Not applicable")) parts.push(plural(c("Not applicable"), "rule that does not apply", "rules that do not apply"));
  parts.push(`${c("Proven by code").toLocaleString()} proven by code`);
  return parts.join(", ");
}

// ---------------------------------------------------------------- the two reviewers, named once

export const RULE_CHECK_NAME = "Rule check (on this computer, no AI cost)";
/** No cost figure is known to the app before a run, so none is written. */
export const AI_REVIEW_NAME = "AI review (Claude, costs money)";

export const AI_PANEL_TITLE = "AI review of this document";
export const AI_PANEL_WHAT =
  "An AI reviewer read this document against the rules of the rule books we hold. Nothing here is final until an engineer confirms it.";
export const INTERNAL_CRS_LINE = "For your own team: every point the AI raised, with its reason. Not for the contractor.";
export const CONTRACTOR_CRS_LINE = "For the contractor: only the failures the code proved.";
export const CONTRACTOR_EMPTY_LINE =
  "The contractor copy holds only failures the code proved. This review has none, so that file has no rows.";
export const RULE_CHECK_STEPS_TITLE = "Steps of the rule check";

/** The page's headline while the AI review has open points: its state and the next step. */
export function aiHeadline(open: number | null): { headline: string; next: string } {
  return open == null
    ? { headline: "AI review: its open points could not be counted here.", next: "Next: read the AI review's points, then download the internal CRS." }
    : {
      headline: `AI review: ${open.toLocaleString()} ${open === 1 ? "point is" : "points are"} still open.`,
      next: "Next: read the AI review's points, then download the internal CRS.",
    };
}

// ---------------------------------------------------------------- missing rule books, apart

export interface MissingSplit { cited: number; other: number }

/** The rule books we do not hold, in the two kinds the record keeps apart:
 *  those the paper names, and those its equipment type needs. */
export function missingSplit(books: readonly { why: string }[]): MissingSplit {
  const cited = books.filter((b) => /^cited by the paper/i.test(b.why)).length;
  return { cited, other: books.length - cited };
}

export function missingWords(m: MissingSplit): string {
  return `${m.cited.toLocaleString()} rule ${m.cited === 1 ? "book" : "books"} the paper names that we do not hold; `
    + `${m.other.toLocaleString()} more that this equipment type needs.`;
}

/** The page record's source, when it was copied from an earlier review (never as if this run read the pages). */
export function pagesTakenWords(cov: { carried_from_run?: string | null; carried_from_at?: string | null } | null | undefined): string | null {
  if (!cov || !cov.carried_from_run) return null;
  const d = cov.carried_from_at ? new Date(cov.carried_from_at) : null;
  const day = d && !Number.isNaN(d.getTime()) ? `, ${d.toISOString().slice(0, 10)}` : "";
  return `Pages read: taken from an earlier review of this paper${day}`;
}
