/**
 * The closed vocabularies of the AI reviewer's screens (owner decision 2 of
 * 11 Nov 2026; contract contracts/generated/agent_review.ts). One place, so
 * no screen invents a word.
 *
 * Rule: "Pass" and "Fail" may be shown ONLY under the class "Proven by code".
 * `lineView` enforces it on the way in, even if the API sent otherwise.
 */
import type { AgentLeftOutReason, AgentMode, AgentPart, AgentRuleTier, AgentVerdictClass } from "../../../types/api";

export const NOT_REVIEWED_NOTE = "the AI gave no answer for these items";

export const PROVEN: AgentVerdictClass = "Proven by code";

/** Display order of the class blocks. */
export const CLASS_ORDER: readonly AgentVerdictClass[] = [
  "Proven by code",
  "AI verdict, two readers agree",
  "Not checked on this paper",
  "AI opinion, engineer to confirm",
  "AI opinion, rule not yet approved",
  "Query for the engineer",
  "Not applicable",
  "Not reviewed",
  "Not checked: rule book not held",
  "AI note, no rule book",
];

/** Display order of the blocks of a general review: nothing is proven there. */
export const GENERAL_CLASS_ORDER: readonly AgentVerdictClass[] = [
  "Not checked: rule book not held",
  "AI note, no rule book",
  "Query for the engineer",
  "Not reviewed",
  "Not applicable",
  "Proven by code",
  "AI verdict, two readers agree",
  "Not checked on this paper",
  "AI opinion, engineer to confirm",
  "AI opinion, rule not yet approved",
];

/** The one word each class may carry (exhaustive against the generated type:
 *  tsc fails here when the contract gains a class). */
export const CLASS_WORDS: Record<AgentVerdictClass, readonly string[]> = {
  "Proven by code": ["Pass", "Fail"],
  "AI verdict, two readers agree": ["AI verdict: met", "AI verdict: not met", "AI verdict: not stated"],
  "Not checked on this paper": ["Needs a drawing or a calculation"],
  "AI opinion, engineer to confirm": ["AI thinks: met", "AI thinks: not met"],
  "AI opinion, rule not yet approved": ["AI thinks: met", "AI thinks: not met"],
  "Query for the engineer": ["Query"],
  "Not applicable": ["Not applicable"],
  "Not reviewed": ["Not reviewed"],
  "Not checked: rule book not held": ["Not checked"],
  "AI note, no rule book": ["AI note"],
};

/** Plain words of a general-review part. */
export const PART_WORDS: Record<AgentPart, string> = {
  "not held": "Rule book not held",
  checklist: "Checklist",
  "paper against itself": "Paper checked against itself",
  "against project papers": "Checked against project papers",
  "engineering comment": "Engineering comment",
};
export const PART_ORDER: readonly AgentPart[] = [
  "not held", "paper against itself", "against project papers", "engineering comment", "checklist",
];

export const MODEL_WORDS_MARK = "the model's words, not a quote";

export function modeWords(mode: AgentMode): string {
  return mode === "general review"
    ? "General review: no rule book held; AI notes and queries only, internal"
    : "Rule review";
}

/** Colour is never the only signal: each class has its own mark and border. */
export const CLASS_STYLE: Record<AgentVerdictClass, { mark: string; border: string }> = {
  "Proven by code": { mark: "■", border: "border-l-4 border-solid border-signal-400" },
  "AI verdict, two readers agree": { mark: "◈", border: "border-l-4 border-solid border-info-500" },
  "Not checked on this paper": { mark: "▣", border: "border-l-4 border-dashed border-ink-500" },
  "AI opinion, engineer to confirm": { mark: "◆", border: "border-l-4 border-dashed border-warn-500" },
  "AI opinion, rule not yet approved": { mark: "◇", border: "border-l-4 border-dotted border-warn-500" },
  "Query for the engineer": { mark: "?", border: "border-l-4 border-double border-slateish-400" },
  "Not applicable": { mark: "–", border: "border-l-4 border-solid border-ink-600" },
  "Not reviewed": { mark: "○", border: "border-l-4 border-dashed border-slateish-500" },
  "Not checked: rule book not held": { mark: "⊘", border: "border-l-4 border-dashed border-slateish-300" },
  "AI note, no rule book": { mark: "✎", border: "border-l-4 border-double border-signal-300" },
};

export const LEFT_OUT_REASONS: readonly AgentLeftOutReason[] = [
  "needs another paper", "needs a human", "quote not found", "not labelled yet", "another equipment type",
  "rule book not held", "the paper names no equipment", "the paper names equipment the equipment list does not know",
  "the paper's equipment could not be read", "a part excluded by a value the paper states",
  "both labelling readers named other equipment",
];
export const TIERS: readonly AgentRuleTier[] = ["AI approved", "Engineer", "Owner", "Not AI approved"];

/** What the rule-approval cell says. A null tier is a checklist item by the
 *  contract (every class except "rule not yet approved", which always has a
 *  tier); anywhere else a null tier is just "tier not given". */
export function tierWords(klass: string, tier: string | null): string {
  if (tier != null) return tier;
  if (klass === "Not checked: rule book not held" || klass === "AI note, no rule book") return "no rule book";
  return klass === "AI opinion, rule not yet approved" ? "tier not given" : "Checklist item";
}

export function isKnownClass(value: string): value is AgentVerdictClass {
  return (CLASS_ORDER as readonly string[]).includes(value);
}

export interface LineView {
  /** the class block the line belongs to; null when the class is not in the vocabulary */
  klass: AgentVerdictClass | null;
  /** the word to show; null when the word may not be shown for this line */
  word: string | null;
  dataError: boolean;
}

/** What may be shown for one line. A "Pass"/"Fail" word on a class other
 *  than "Proven by code" is NOT shown; the line shows its class and a visible
 *  data-error note. An unknown class is a data error too. */
/** The owner's words (12 Nov 2026) for the two stored words of the class "AI verdict, two readers agree"; every other word shows as stored. */
export function displayWord(word: string): string {
  if (word === "AI verdict: met") return "Met (AI, two readers agree, quotes verified)";
  if (word === "AI verdict: not met") return "Not met (AI, two readers agree, quotes verified)";
  return word;
}

export function lineView(line: { verdict_class: string; word: string }, mode: AgentMode = "rule review"): LineView {
  const klass = line.verdict_class;
  // A class the screen does not know: shown as "unknown class", never a word.
  if (!isKnownClass(klass)) return { klass: null, word: null, dataError: true };
  // Each class carries only its own words; a general review never shows a
  // proven word at all (nothing in it is proven).
  const allowed = CLASS_WORDS[klass].includes(line.word);
  const proven = line.word === "Pass" || line.word === "Fail";
  if (!allowed || (mode === "general review" && proven)) return { klass, word: null, dataError: true };
  return { klass, word: line.word, dataError: false };
}

export const DATA_ERROR_NOTE =
  "Data error: this line's class and word do not belong together, so the word is not shown.";
