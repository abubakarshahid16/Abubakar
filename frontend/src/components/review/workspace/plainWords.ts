/**
 * OWNER: builder C. THE ONE PLAIN-WORDS TABLE (PLACEHOLDER - planner team).
 *
 * There is no glossary.ts on main (#1149 is not merged; src/glossary.test.ts
 * is the banned-words test, not a mapping). The mappings that exist today
 * are scattered, and builder C gathers them here WITHOUT changing their
 * words: CrsEvidenceDrawer REASON_WORDS (tier C reasons), evidenceNav
 * REMOVAL_REASON_WORDS, reviewFormat TRUST_WORDS / STATUS_LABEL /
 * RUN_STATUS_LABEL, DecisionCard CODE_WORDS, crsRows plainObservation
 * (engine reason-code prefixes such as "no_field_matched:").
 */
import type { PlainEntry, PlainKind } from "./contract";
import type { CrsRow } from "../crs/crsRows";

/** PLACEHOLDER: empty tables. Builder C fills them. */
export const PLAIN_WORDS: Record<Exclude<PlainKind, "any">, Readonly<Record<string, string>>> = {
  reason: {}, tier: {}, removal: {}, trust: {}, code: {}, status: {}, runStatus: {}, engine: {}, rule: {},
};

/** PLACEHOLDER: the code as its own words. */
export function plainWords(code: string | null | undefined, _kind: PlainKind = "any"): PlainEntry {
  return { words: code ?? "", detail: null };
}

/** PLACEHOLDER: the text unchanged. Builder C replaces engine codes inside free text. */
export function plainText(text: string): string {
  return text;
}

/** PLACEHOLDER: the row unchanged. Builder C returns a copy with plain words
 *  in observation / requiredAction / status (never changes key, tier, findings). */
export function plainRow(row: CrsRow): CrsRow {
  return row;
}
