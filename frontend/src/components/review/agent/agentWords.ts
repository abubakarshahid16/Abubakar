/**
 * The closed vocabularies of the AI reviewer's screens (owner decision 2 of
 * 11 Nov 2026; contract contracts/generated/agent_review.ts). One place, so
 * no screen invents a word.
 *
 * Rule: "Pass" and "Fail" may be shown ONLY under the class "Proven by code".
 * `lineView` enforces it on the way in, even if the API sent otherwise.
 */
import type { AgentLeftOutReason, AgentRuleTier, AgentVerdictClass } from "../../../types/api";

export const NOT_REVIEWED_NOTE = "the AI gave no answer for these items";

export const PROVEN: AgentVerdictClass = "Proven by code";

/** Display order of the class blocks. */
export const CLASS_ORDER: readonly AgentVerdictClass[] = [
  "Proven by code",
  "AI opinion, engineer to confirm",
  "AI opinion, rule not yet approved",
  "Query for the engineer",
  "Not applicable",
  "Not reviewed",
];

/** Colour is never the only signal: each class has its own mark and border. */
export const CLASS_STYLE: Record<AgentVerdictClass, { mark: string; border: string }> = {
  "Proven by code": { mark: "■", border: "border-l-4 border-solid border-signal-400" },
  "AI opinion, engineer to confirm": { mark: "◆", border: "border-l-4 border-dashed border-warn-500" },
  "AI opinion, rule not yet approved": { mark: "◇", border: "border-l-4 border-dotted border-warn-500" },
  "Query for the engineer": { mark: "?", border: "border-l-4 border-double border-slateish-400" },
  "Not applicable": { mark: "–", border: "border-l-4 border-solid border-ink-600" },
  "Not reviewed": { mark: "○", border: "border-l-4 border-dashed border-slateish-500" },
};

export const LEFT_OUT_REASONS: readonly AgentLeftOutReason[] = [
  "needs another paper", "needs a human", "quote not found", "not labelled yet", "another equipment type",
  "rule book not held", "the paper names no equipment", "the paper names equipment the equipment list does not know",
  "the paper's equipment could not be read",
];
export const TIERS: readonly AgentRuleTier[] = ["AI approved", "Engineer", "Owner", "Not AI approved"];

/** What the rule-approval cell says. A null tier is a checklist item by the
 *  contract (every class except "rule not yet approved", which always has a
 *  tier); anywhere else a null tier is just "tier not given". */
export function tierWords(klass: string, tier: string | null): string {
  if (tier != null) return tier;
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
export function lineView(line: { verdict_class: string; word: string }): LineView {
  const klass = line.verdict_class;
  const known = isKnownClass(klass);
  const provenOnly = line.word === "Pass" || line.word === "Fail";
  if (!known) return { klass: null, word: provenOnly ? null : line.word, dataError: true };
  // Both ways: Pass/Fail only under "Proven by code", and that class only with them.
  if (provenOnly !== (klass === PROVEN)) return { klass, word: null, dataError: true };
  return { klass, word: line.word, dataError: false };
}

export const DATA_ERROR_NOTE =
  "Data error: this line's class and word do not belong together (a proven word needs the class Proven by code, and that class needs a proven word), so the word is not shown.";
