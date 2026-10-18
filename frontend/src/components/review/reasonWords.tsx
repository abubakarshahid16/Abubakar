/**
 * Order 120 item 3: the review's internal reason codes in plain words.
 *
 * A finding's text and its "why" open with the code the comparison wrote
 * ("no_field_matched: no field read from this datasheet ..."). The words
 * after the colon are already plain; the code is not for the engineer. This
 * is the one table of every code, each with a sentence, and the one place
 * that splits a code off; the code stays in a tooltip for whoever debugs.
 * `backend/tests/test_order120_reason_words.py` fails when the backend gains
 * a code this table does not name.
 */
import type { ReviewFinding } from "../../types/api";
import { AI_ENGINEERING_CHECK } from "./reviewFormat";

export const REASON_CODE_WORDS: Record<string, string> = {
  no_field_matched: "No field read from this datasheet answers this requirement.",
  requires_other_document: "This requirement asks for its own document (a certificate, procedure or drawing), not a datasheet value.",
  condition_not_met: "This requirement applies only under a condition the datasheet shows is not met.",
  outside_the_range: "The value is outside the range the clause allows.",
  not_the_stated_value: "The clause states one value and the datasheet another. A stated value is not a limit, so this is yours to judge.",
  stated_as_asked: "The clause only asks for this to be stated, and the datasheet states it.",
  named_value: "The clause names the values allowed; the datasheet's value was checked against them.",
  table_row: "This number is a row of a lookup table in the standard, not a limit, so it was not compared.",
  relative_limit: "The clause sets a difference from another quantity, not a value, so it was not compared.",
  range_against_exact_value: "The datasheet gives a range where the clause asks for one exact value, so they were not compared.",
  unit_mismatch: "The clause and the datasheet use units that could not be converted to each other.",
  ambiguous_match: "More than one datasheet field could be the one this clause means, so no value was chosen.",
  conflicting_values: "The datasheet gives more than one value for this field.",
  pairing_not_checked: "The pairing of this field with the clause could not be checked; the value may still be on the sheet.",
  LOW_TRUST_VALUE: "The value as read is not trusted enough for a verdict until you check it on the page.",
  UNREAD_PAGES: "Pages of this submittal were not read, so the value may be on a page nobody read.",
  PAGE_READER_ONLY: "Only the page reader looked for this value, and it did not find it.",
  RULE_EVALUATED: "Worked out by an approved rule.",
};

// A code: snake_case words, all lower or all upper case, then a colon or the
// end. A plain word ("PSV: ...", "Note: ...") is never taken for a code.
const LEAD = /^([a-z]+(?:_[a-z]+)+|[A-Z]+(?:_[A-Z]+)+)(?::\s*|$)/;

export interface SplitReason {
  /** The internal code the text opened with, or null. */
  code: string | null;
  /** The code's plain sentence; empty for a code the table does not name. */
  words: string;
  /** The text after the code. */
  rest: string;
}

export function splitReason(text: string | null | undefined): SplitReason {
  const value = text ?? "";
  const lead = LEAD.exec(value);
  if (!lead) return { code: null, words: "", rest: value };
  return { code: lead[1], words: REASON_CODE_WORDS[lead[1]] ?? "", rest: value.slice(lead[0].length) };
}

/** A text that may open with a reason code: the code's sentence, then the
 *  rest; the code itself only in the tooltip. */
export function ReasonText({ text }: { text: string }) {
  const { code, words, rest } = splitReason(text);
  if (code === null) return <>{text}</>;
  return (
    <span title={`Internal reason code: ${code}`} data-reason-code={code}>
      {[words, rest].filter(Boolean).join(" ")}
    </span>
  );
}

/** Order 120 item 3: an AI engineering check that names no standard is the
 *  computer's own sense check; its "rule" is that, not the model's topic. */
export const SENSE_CHECK_RULE = "No standard clause - this is the computer's sense check.";

export function isSenseCheck(f: Pick<ReviewFinding, "origin" | "standard_document_id" | "standard_clause">): boolean {
  return f.origin === AI_ENGINEERING_CHECK && !f.standard_document_id && !f.standard_clause;
}
