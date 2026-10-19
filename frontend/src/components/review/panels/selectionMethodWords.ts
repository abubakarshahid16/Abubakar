/**
 * v2.1 (gap T2): how a standard was chosen for a review, in plain words.
 *
 * The codes are the server's `review_applicable_standards.selection_method`
 * values (backend applicability.py METHOD_*, claude_selection.py "model").
 * Each answer keeps the raw code as `detail`, for the "Details" fold, so an
 * engineer can still see exactly what was stored. An unknown code is
 * humanised, never hidden; a missing one says it was not recorded.
 *
 * A guess is said as a guess (CLAUDE.md rule 4): "similar wording" and "the
 * AI suggested it" are not citations, and the words say so.
 */
import type { PlainEntry } from "../workspace/contract";

export const SELECTION_METHOD_WORDS: Record<string, string> = {
  referenced: "Named in the document",
  possible_citation: "Looks like a standard the document mentions (not confirmed)",
  equipment_type: "Chosen for this kind of equipment",
  governing_standard: "Governs this kind of equipment",
  discipline: "Matches the discipline",
  service: "Matches the service or operating conditions",
  semantic: "Found by similar wording (a guess, not named in the document)",
  project: "Required by the contract or project",
  manual: "Added by an engineer",
  model: "Suggested by the AI (a guess until an engineer confirms it)",
  scope: "Its scope covers this document",
};

export const SELECTION_METHOD_UNRECORDED = "How it was chosen was not recorded";

/** "value_conflict" -> "Value conflict". */
function humanise(code: string): string {
  const words = code.replace(/[_-]+/g, " ").trim().toLowerCase();
  return words ? words[0].toUpperCase() + words.slice(1) : code;
}

export function selectionMethodWords(method: string | null | undefined): PlainEntry {
  const code = (method ?? "").trim();
  if (!code) return { words: SELECTION_METHOD_UNRECORDED, detail: null };
  return { words: SELECTION_METHOD_WORDS[code] ?? humanise(code), detail: code };
}
