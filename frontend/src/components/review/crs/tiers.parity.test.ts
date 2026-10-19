import { readFileSync } from "node:fs";
import { resolve } from "node:path";
/**
 * Order 133 (117a item 4): the screen's side of the shared tier cases.
 *
 * `contracts/fixtures/review_tier_cases.json` is run by BOTH engines: the
 * server's `backend/app/review_tiers.py` (pytest: test_133_one_truth_tiers.py)
 * and this file's `tiers.ts`. A rule changed on one side only fails one of
 * the two runs; a rule changed in `review_tiers.json` (regenerated into
 * `contracts/generated/review_tiers.ts`) moves both at once.
 *
 * There are no known disagreements (order 135 fixed D1, D2 and D3): the
 * former pins are ordinary `cases` ("D1: ...", "D2: ..."), the characters
 * behind them are `text_cases` (the fold and the phrases), and the reader
 * record behind D3 is `run_facts` (what `runFactsOf` gathers).
 *
 * MUTATION PROOF (by hand, order 135): compiling the phrases with
 * `word_edge.python` (JavaScript's ASCII-only \w) in place of
 * `word_edge.javascript` fails "D1: ..." and the cases glued to a letter or
 * digit outside ASCII; folding with the old [\s_-]+ fails the text cases
 * for U+0085, U+001F, U+200B, U+2060, the trim and the mixed run; putting
 * the page-note regex back into `runFactsOf` fails every run_facts case.
 *
 * MUTATION PROOF (by hand, order 133): re-adding
 * `const TIER_C = new Set(["NEEDS_ENGINEER_REVIEW", "CONDITIONAL"])` to
 * tiers.ts fails the source fence; swapping two entries of `unsettled_order`
 * in the generated rules fails "the page comes before ..." cases.
 */
import { describe, expect, it } from "vitest";

import { TIER_RULES } from "../../../../../contracts/generated/review_tiers";
import type { ReviewFinding } from "../../../types/api";
import { splitRejected } from "./crsRows";
import {
  PHRASE_PATTERNS, type RunFacts, fold, runFactsOf, type Tier, type TierCounts, type TierLabel, type TierReason, type TierResult,
  UNSETTLED_RULES, countTiers, tierOf,
} from "./tiers";

interface FactsJson {
  pages_not_read: number[];
  reader_timed_out_pages: number[];
  missing_standards: string[];
  library_standard_ids: string[] | null;
}
type Over = Record<string, unknown>;
interface CaseTable {
  facts: Record<string, FactsJson>;
  base_finding: Over;
  cases: { name: string; finding: Over; facts: string; expected: TierResult }[];
  removed: { name: string; finding: Over; removed: boolean }[];
  counts: { name: string; facts: string; findings: Over[]; expected: Record<string, number> }[];
  text_cases: { name: string; text: string; folded: string; phrases: string[] }[];
  run_facts: {
    name: string;
    run: Over;
    expected: { pages_not_read: number[]; reader_timed_out_pages: number[] };
  }[];
}

const TABLE: CaseTable = JSON.parse(
  readFileSync(resolve(__dirname, "../../../../../contracts/fixtures/review_tier_cases.json"), "utf8"),
);

function factsOf(name: string): RunFacts {
  const f = TABLE.facts[name];
  if (!f) throw new Error(`no facts set named ${name}`);
  return {
    pagesNotRead: f.pages_not_read, readerTimedOutPages: f.reader_timed_out_pages,
    missingStandards: f.missing_standards, libraryStandardIds: f.library_standard_ids,
  };
}

/** `base_finding` with the case's fields laid over it (a null overrides). */
function findingOf(over: Over): ReviewFinding {
  return { ...TABLE.base_finding, ...over } as unknown as ReviewFinding;
}

/** The screen's counts in the server's (snake_case) names; written out by
 *  hand on purpose, so this check does not lean on `count_keys`. */
function snakeCounts(c: TierCounts): Record<string, number> {
  return {
    met: c.met, not_applicable: c.notApplicable, another_document: c.anotherDocument, comment: c.comment,
    needs_you: c.needsYou,
  };
}

describe("the shared case table, as the screen answers it", () => {
  it.each(TABLE.cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(tierOf(findingOf(c.finding), factsOf(c.facts))).toEqual(c.expected);
  });
});

const PHRASE_WORDS = Object.keys(TIER_RULES.phrases) as (keyof typeof PHRASE_PATTERNS)[];

describe("the shared character cases: the fold and the phrases (order 135, D1 and D2)", () => {
  it.each(TABLE.text_cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(fold(c.text)).toBe(c.folded);
    for (const word of PHRASE_WORDS) {
      expect(PHRASE_PATTERNS[word].test(fold(c.text)), word).toBe(c.phrases.includes(word));
    }
  });
});

describe("the shared run facts: what runFactsOf gathers from a stored run (order 135, D3)", () => {
  it.each(TABLE.run_facts.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    const facts = runFactsOf(c.run as never, null, []);
    expect(facts.pagesNotRead).toEqual(c.expected.pages_not_read);
    expect([...facts.readerTimedOutPages].sort((a, b) => a - b)).toEqual(c.expected.reader_timed_out_pages);
  });
});

describe("the fold class holds every white space this engine knows", () => {
  // A guard against a narrower future class, not a proof of the D2 fix: the
  // old [\s_-]+ passed this too (JavaScript's \s is inside it). The D2 fix
  // is proven by the text cases above.
  it("every code point /^\\s$/u matches is folded", () => {
    const foldClass = new RegExp(`^(?:${TIER_RULES.fold.pattern})$`);
    const spaceLike = /^\s$/u;
    const missed: string[] = [];
    let seen = 0;
    for (let cp = 0; cp <= 0x10ffff; cp += 1) {
      if (cp >= 0xd800 && cp <= 0xdfff) continue;
      const ch = String.fromCodePoint(cp);
      if (!spaceLike.test(ch)) continue;
      seen += 1;
      if (!foldClass.test(ch)) missed.push(cp.toString(16));
    }
    expect(seen).toBeGreaterThan(20);
    expect(missed).toEqual([]);
  });
});

describe("removed and counts", () => {
  it.each(TABLE.removed.map((r) => [r.name, r] as const))("%s", (_name, r) => {
    expect(splitRejected([findingOf(r.finding)]).rejected).toBe(r.removed ? 1 : 0);
  });
  it.each(TABLE.counts.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    const facts = factsOf(c.facts);
    expect(snakeCounts(countTiers(c.findings.map((over) => tierOf(findingOf(over), facts))))).toEqual(c.expected);
  });
});

/** A value as JSON with its object keys sorted, so equal inputs give equal text. */
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([x], [y]) => (x < y ? -1 : x > y ? 1 : 0));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

describe("the table is not vacuous", () => {
  it("holds at least 30 distinct cases, one per reason word and per tiered status, and the D1, D2 and D3 cases", () => {
    const unique = new Set(TABLE.cases.map((c) => canonical([c.finding, c.facts, c.expected])));
    expect(unique.size).toBeGreaterThanOrEqual(30);
    // a case that repeats another's input and answer adds nothing
    expect(unique.size).toBe(TABLE.cases.length);
    const reasons = new Set(TABLE.cases.map((c) => c.expected.reason));
    for (const word of TIER_RULES.reasons) expect(reasons, word).toContain(word);
    const statuses = new Set(TABLE.cases.map((c) => findingOf(c.finding).compliance_status));
    for (const status of [
      ...Object.keys(TIER_RULES.status_tiers), ...TIER_RULES.tier_c_statuses, TIER_RULES.missing_information.status,
    ]) expect(statuses, status).toContain(status);
    // order 135: no disagreement is left; D1 and D2 are ordinary cases, D3 a run_facts case
    expect("disagreements" in TABLE).toBe(false);
    expect(TABLE.cases.some((c) => c.name.startsWith("D1:"))).toBe(true);
    expect(TABLE.cases.some((c) => c.name.startsWith("D2:"))).toBe(true);
    expect(TABLE.run_facts.some((c) => c.name.startsWith("D3:"))).toBe(true);
    expect(TABLE.text_cases.length).toBeGreaterThanOrEqual(20);
    expect(TABLE.text_cases.some((c) => c.phrases.length > 0)).toBe(true);
    expect(TABLE.text_cases.some((c) => c.phrases.length === 0)).toBe(true);
    expect(TABLE.text_cases.some((c) => c.folded !== c.text)).toBe(true);
    expect(TABLE.run_facts.length).toBeGreaterThanOrEqual(3);
    expect(TABLE.run_facts.some((c) => c.expected.reader_timed_out_pages.length > 0)).toBe(true);
    expect(TABLE.run_facts.some((c) => c.expected.reader_timed_out_pages.length === 0)).toBe(true);
    expect(TABLE.removed.some((r) => r.removed) && TABLE.removed.some((r) => !r.removed)).toBe(true);
    expect(TABLE.counts.length).toBeGreaterThan(0);
  });
});

// Type-level wiring: the generated rule words and the server's TierRow
// unions name exactly the same words. tsc fails on any drift.
type Same<X, Y> = [X] extends [Y] ? ([Y] extends [X] ? true : false) : false;
const _reasonsMatch: Same<(typeof TIER_RULES.reasons)[number], TierReason> = true;
const _labelsMatch: Same<(typeof TIER_RULES.labels)[number], TierLabel> = true;
const _tiersMatch: Same<(typeof TIER_RULES.tiers)[number], Tier> = true;

describe("tiers.ts reads its rules from the generated data", () => {
  it("the word lists agree with the server's TierRow (checked by tsc)", () => {
    expect([_reasonsMatch, _labelsMatch, _tiersMatch]).toEqual([true, true, true]);
  });
  it("compiles every phrase from the data, with the data's word edge and flags", () => {
    const edge = TIER_RULES.word_edge;
    expect(Object.keys(PHRASE_PATTERNS).sort()).toEqual(Object.keys(TIER_RULES.phrases).sort());
    for (const [word, source] of Object.entries(TIER_RULES.phrases)) {
      const compiled = PHRASE_PATTERNS[word as keyof typeof PHRASE_PATTERNS];
      expect(source, word).toContain(edge.token);
      expect(source, word).not.toContain("\\b");
      expect(compiled.source).toBe(new RegExp(source.replaceAll(edge.token, edge.javascript), edge.javascript_flags).source);
      expect(compiled.source, word).not.toContain(edge.token);
      expect(compiled.flags).toBe(edge.javascript_flags);
    }
  });
  it("has one predicate per reason word of unsettled_order: none missing, none extra", () => {
    expect(Object.keys(UNSETTLED_RULES).sort()).toEqual([...TIER_RULES.unsettled_order].sort());
  });
});

describe("source fence: tiers.ts keeps no rule literal of its own", () => {
  const source = readFileSync(resolve(__dirname, "tiers.ts"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  const quoted = (word: string) => new RegExp(`["'\`]${word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}["'\`]`);

  it("names no status, label or matching value", () => {
    const words = [
      ...Object.keys(TIER_RULES.status_tiers), ...TIER_RULES.tier_c_statuses, TIER_RULES.missing_information.status,
      ...TIER_RULES.labels, ...TIER_RULES.pairing_guess.always, TIER_RULES.pairing_guess.held.match_method,
      TIER_RULES.rule_not_proven_trust_label, TIER_RULES.removed.approval_status,
    ];
    for (const word of new Set(words)) expect(source, word).not.toMatch(quoted(word));
  });
  it("uses a reason word only as a key of UNSETTLED_RULES, never as a value", () => {
    for (const word of TIER_RULES.reasons) {
      const uses = source.match(new RegExp(`${quoted(word).source}(\\s*:)?`, "g")) ?? [];
      for (const use of uses) expect(use, word).toMatch(/:$/);
    }
  });
  it("holds no phrase, word edge, fold pattern or page-note guess", () => {
    for (const text of [
      "conflicting values", "unit unknown|", TIER_RULES.word_edge.token, "\\p{L}", "\\u205f", "\\ufeff", "[\\s_-]",
    ]) expect(source, text).not.toContain(text);
    expect(source).not.toMatch(/timed\? \?out/);
  });
});
