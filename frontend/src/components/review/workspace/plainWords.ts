/**
 * OWNER: builder C. THE ONE PLAIN-WORDS TABLE (review workspace v2).
 *
 * Every code the review stores (engine reason codes, compliance statuses,
 * rule ids, trust labels, removal reasons...) has ONE place where its plain
 * words live: here. The workspace never shows a raw code on its own; it shows
 * the words, with the code folded under "Details" (`<PlainTerm>`).
 *
 * GATHERED, NOT REWRITTEN. The maps that existed before were scattered, and
 * their words are kept byte for byte:
 *   - reason   : the Tier C reason words (were in CrsEvidenceDrawer; that
 *                file now reads them from here, `REASON_WORDS`)
 *   - tier     : the tier labels (crs/tiers.ts), already plain
 *   - removal  : evidenceNav REMOVAL_REASON_WORDS (read from there)
 *   - trust    : reviewFormat TRUST_WORDS (read from there)
 *   - code     : the review code sentences (were in sheet/DecisionCard; that
 *                file now reads them from here, `CODE_WORDS`)
 *   - status   : reviewFormat STATUS_LABEL (read from there)
 *   - runStatus: reviewFormat RUN_STATUS_LABEL (read from there)
 *   - engine   : the reason codes a finding's text may open with
 *                ("no_field_matched: ..."): reasonWords REASON_CODE_WORDS
 *                itself, plus ENGINE_EXTRA_WORDS for codes it does not name
 *   - rule     : rule ids shown in finding text (the datasheet checks'
 *                "DS-M1"... and short labels such as "p4"), new words
 *
 * Pure functions; display only. Nothing here changes a stored value.
 */
// Types only from the contract: importing its values would pull every
// workspace component into the old screens (CrsEvidenceDrawer and
// DecisionCard read their words from this file) and close an import loop.
import type { PlainEntry, PlainKind } from "./contract";
import type { CrsRow } from "../crs/crsRows";
import { REMOVAL_REASON_WORDS } from "../crs/evidenceNav";
import { REASON_CODE_WORDS } from "../reasonWords";
import type { TierReason } from "../crs/tiers";
import { RUN_STATUS_LABEL, STATUS_LABEL, TRUST_WORDS } from "../reviewFormat";

/** Why a Tier C row needs the engineer, in full sentences (order 95 piece 4).
 *  Moved here unchanged from CrsEvidenceDrawer, which imports it. */
export const REASON_WORDS: Record<TierReason, string> = {
  "page not read": "The reader did not read this page into fields, so the value may still be on the page. Read the page yourself.",
  "standard not in library": "The standard this comment rests on is not in the library, so the clause could not be checked. Upload it, or decide from the datasheet.",
  "no standard linked": "This is a blank value with no standard behind it, so there was no clause to check. Decide from the datasheet.",
  "standard outside this review": "The standard this comment rests on was not part of this review (it may be in the library). An engineer can add it with \"Add a standard\" under \"Engineer: change the standards\", or you can decide from the datasheet.",
  "AI guess": "The datasheet field was paired with this clause by an AI guess that nobody has confirmed. Check that the field is the one the clause means.",
  "rule not proven": "The rule behind this comment has not been proven yet, so its answer is not trusted on its own. Check it against the standard.",
  "safety field": "This is a safety field. It meets the standard, but it is shown for your own tick before it goes on the record.",
  "condition unsettled": "The rule has a condition the computer could not settle. Decide whether it applies here.",
  "value conflict": "The datasheet gives two values for this field. Decide which one counts.",
  "unit unknown": "The unit of the value could not be read, so it was not compared. Check the unit on the page.",
};

/** One sentence per default review code. A configured code with no sentence
 *  here shows its own name only - never an invented explanation. Moved here
 *  unchanged from sheet/DecisionCard, which imports it. */
export const CODE_WORDS: Record<string, string> = {
  "Approved": "Everything checked meets the standard; the contractor may go ahead.",
  "Approved with Comments": "The contractor may go ahead and must answer our comments.",
  "Rejected / Revise and Resubmit": "The contractor must fix the comments and send it again.",
  "Manual Review Required": "Not decided here; it needs a fuller engineering review.",
};

/** The tier labels (crs/tiers.ts). They are already the words the screen
 *  uses, so each maps to itself and carries no "Details". */
const TIER_WORDS: Record<string, string> = {
  "Met": "Met",
  "Not applicable": "Not applicable",
  "Another document": "Another document",
  "Comment": "Comment",
  "Needs you": "Needs you",
};

/** The reason codes a finding's text or rationale may open with (backend
 *  comparison.py) are main's approved table, `reasonWords.REASON_CODE_WORDS`,
 *  used as it is (the same object, never a copy), so the workspace and the
 *  old screens always say the same words for a code. Codes that table does
 *  not name, and only those, get words here; plainWords.test.ts fails if a
 *  code appears in both. */
export const ENGINE_EXTRA_WORDS: Readonly<Record<string, string>> = {
  refused_by_rule: "A possible match was turned down by a checking rule.",
};

/** Rule ids that reach finding text (backend datasheet_checks.py writes
 *  "Datasheet check DS-M1: ..."). A short label such as "p4" is handled by
 *  `ruleWords` below, since its number varies. */
const RULE_WORDS: Record<string, string> = {
  "DS-M1": "Datasheet check (a required field is missing)",
  "DS-M2": "Datasheet check (a required field is left blank)",
  "DS-U1": "Datasheet check (a value has no unit)",
  "DS-U2": "Datasheet check (a value is in the wrong kind of unit)",
  "DS-R1": "Datasheet check (the revision block)",
};

export const PLAIN_WORDS: Record<Exclude<PlainKind, "any">, Readonly<Record<string, string>>> = {
  reason: REASON_WORDS,
  tier: TIER_WORDS,
  removal: REMOVAL_REASON_WORDS,
  trust: TRUST_WORDS,
  code: CODE_WORDS,
  status: STATUS_LABEL,
  runStatus: RUN_STATUS_LABEL,
  engine: REASON_CODE_WORDS,
  rule: RULE_WORDS,
};

/** The tables in lookup order for kind "any": contract.PLAIN_KINDS, repeated
 *  here for the reason above (plainWords.test.ts checks the two agree). */
export const LOOKUP_ORDER: readonly Exclude<PlainKind, "any">[] = [
  "reason", "tier", "removal", "trust", "code", "status", "runStatus", "engine", "rule",
];

const SHORT_RULE = /^[pP](\d+)$/;
const DATASHEET_RULE = /^DS-[A-Z]+\d+$/;

/** Words for a rule label the table does not list by name. */
function ruleWords(code: string): string | null {
  const short = SHORT_RULE.exec(code);
  if (short) return `Review rule ${short[1]}`;
  if (DATASHEET_RULE.test(code)) return "Datasheet check";
  return null;
}

function has(table: Readonly<Record<string, string>>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(table, key);
}

/** The words a table gives a code (engine: main's table, then the
 *  workspace-only extras); null when the table does not list it. */
function tableWords(kind: Exclude<PlainKind, "any">, code: string): string | null {
  const table = PLAIN_WORDS[kind];
  if (has(table, code)) return table[code];
  if (kind === "engine" && has(ENGINE_EXTRA_WORDS, code)) return ENGINE_EXTRA_WORDS[code];
  return null;
}

/** True when the text is a stored code, not words a person wrote:
 *  one token with an underscore, a digit, or four or more capitals only
 *  ("no_field_matched", "NON_COMPLIANT", "DS-M1", "p4", "COMPLIANT").
 *  "Met", "AI guess" and "Approved" are words. */
export function looksLikeCode(text: string): boolean {
  if (/\s/.test(text)) return false;
  return text.includes("_") || /\d/.test(text) || /^[A-Z][A-Z-]{3,}$/.test(text);
}

/** "value_conflict" -> "Value conflict"; "NON_COMPLIANT" -> "Non compliant". */
function humanise(code: string): string {
  const words = code.replace(/[_-]+/g, " ").trim().toLowerCase();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "";
}

/** A code in plain words. Known code: its words, the code as `detail`.
 *  Unknown code: a humanised version, the code as `detail`. Words already
 *  (or a known code whose words are itself): `detail` null. A non-empty
 *  code never comes back as empty words. */
export function plainWords(code: string | null | undefined, kind: PlainKind = "any"): PlainEntry {
  const raw = (code ?? "").trim();
  if (!raw) return { words: "", detail: null };
  const kinds = kind === "any" ? LOOKUP_ORDER : [kind];
  for (const k of kinds) {
    const words = tableWords(k, raw);
    if (words !== null) {
      const shown = words || raw;
      return { words: shown, detail: shown === raw ? null : raw };
    }
    if (k === "rule") {
      const words = ruleWords(raw);
      if (words) return { words, detail: raw };
    }
  }
  if (!looksLikeCode(raw)) return { words: raw, detail: null };
  return { words: humanise(raw) || raw, detail: raw };
}

/** One code found in free text, and the table it belongs to. */
export interface FoundCode {
  code: string;
  kind: Exclude<PlainKind, "any">;
}

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** The coded keys free text may carry as a bare word, longest first so
 *  "NON_COMPLIANT" is matched before "COMPLIANT". Keys that are words
 *  ("Approved", "queued", "Met") are left alone in prose. */
const TEXT_KINDS: Exclude<PlainKind, "any">[] = ["engine", "status", "trust", "removal", "rule"];
const TEXT_CODES: FoundCode[] = TEXT_KINDS
  .flatMap((kind) => [...Object.keys(PLAIN_WORDS[kind]), ...(kind === "engine" ? Object.keys(ENGINE_EXTRA_WORDS) : [])]
    .filter(looksLikeCode).map((code) => ({ code, kind })))
  .sort((a, b) => b.code.length - a.code.length);
const TEXT_CODE_RE = new RegExp(`(?<![\\w-])(${TEXT_CODES.map((c) => escape(c.code)).join("|")})(?![\\w-])`, "g");
/** A reason code opening a clause: "no_field_matched: ...", "UNREAD_PAGES: ...". */
const PREFIX_RE = /(^|[\s(;.,])([A-Za-z]+(?:_[A-Za-z]+)+):\s*/g;
/** A short rule label where it can only be a rule: "rule p4", "(p4)", "p4: ...". */
const RULE_AFTER_WORD_RE = /\b([Rr])ule\s+[pP](\d+)\b/g;
const RULE_IN_BRACKETS_RE = /\(([pP]\d+)\)/g;
const RULE_LEADING_RE = /^([pP]\d+):/;
const OTHER_DATASHEET_RULE_RE = /(?<![\w-])(DS-[A-Z]+\d+)(?![\w-])/g;
/** "Datasheet check DS-M1": the rule's words already say "Datasheet check". */
const LABELLED_DATASHEET_RULE_RE = /\bDatasheet check (DS-[A-Z]+\d+)(?![\w-])/g;

function lowerFirst(words: string): string {
  return words.charAt(0).toLowerCase() + words.slice(1);
}

/** Every code inside a free text, in order of appearance, each once. */
export function codesIn(text: string | null | undefined): FoundCode[] {
  const t = text ?? "";
  if (!t) return [];
  const found: { at: number; code: FoundCode }[] = [];
  for (const m of t.matchAll(PREFIX_RE)) {
    const code = m[2];
    found.push({ at: m.index + m[1].length, code: { code, kind: "engine" } });
  }
  for (const m of t.matchAll(TEXT_CODE_RE)) {
    const hit = TEXT_CODES.find((c) => c.code === m[1]);
    if (hit) found.push({ at: m.index, code: hit });
  }
  for (const m of t.matchAll(OTHER_DATASHEET_RULE_RE)) found.push({ at: m.index, code: { code: m[1], kind: "rule" } });
  for (const m of t.matchAll(RULE_AFTER_WORD_RE)) found.push({ at: m.index, code: { code: `p${m[2]}`, kind: "rule" } });
  for (const m of t.matchAll(RULE_IN_BRACKETS_RE)) found.push({ at: m.index, code: { code: m[1].toLowerCase(), kind: "rule" } });
  const leading = RULE_LEADING_RE.exec(t);
  if (leading) found.push({ at: 0, code: { code: leading[1].toLowerCase(), kind: "rule" } });
  const seen = new Set<string>();
  return found
    .sort((a, b) => a.at - b.at)
    .map((f) => f.code)
    .filter((c) => (seen.has(c.code) ? false : (seen.add(c.code), true)));
}

/** Free text with the codes inside it rewritten as words. A reason code that
 *  opens a clause is dropped (the words after its colon already say it, as
 *  crsRows.plainObservation does); a bare known code is replaced by its
 *  words; a short rule label becomes "review rule N". Text with no code
 *  comes back unchanged. */
export function plainText(text: string): string {
  if (!text) return text;
  let out = text.replace(LABELLED_DATASHEET_RULE_RE, "$1");
  let strippedAtStart = false;
  out = out.replace(PREFIX_RE, (_m, before: string, _code: string, at: number) => {
    if (at === 0 && before === "") strippedAtStart = true;
    return before;
  });
  out = out.replace(RULE_LEADING_RE, (_m, label: string) => `${plainWords(label, "rule").words}:`);
  out = out.replace(RULE_AFTER_WORD_RE, (_m, r: string, n: string) => `${r === "R" ? "Review" : "review"} rule ${n}`);
  out = out.replace(RULE_IN_BRACKETS_RE, (_m, label: string) => `(${lowerFirst(plainWords(label, "rule").words)})`);
  out = out.replace(TEXT_CODE_RE, (code: string, _g: string, at: number) => {
    const hit = TEXT_CODES.find((c) => c.code === code);
    // Inside a sentence the code's words stand in for one word, so a full
    // sentence's closing full stop is left off.
    const words = (hit ? tableWords(hit.kind, code) ?? code : code).replace(/\.$/, "");
    return at === 0 ? words : lowerFirst(words);
  });
  out = out.replace(OTHER_DATASHEET_RULE_RE, (code: string) => plainWords(code, "rule").words);
  if (strippedAtStart && out) out = out.charAt(0).toUpperCase() + out.slice(1);
  return out;
}

/** A COPY of the row with plain words in the observation, required action
 *  and status. The key, tier and findings are the same values (not copies),
 *  so decisions, counts and history still line up with the original row. */
export function plainRow(row: CrsRow): CrsRow {
  return {
    ...row,
    observation: plainText(row.observation),
    requiredAction: plainText(row.requiredAction),
    status: plainText(row.status),
  };
}
