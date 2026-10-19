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
 * `disagreements` are inputs the two sides answer differently TODAY. Each
 * side pins its own answer, and the answers must DIFFER: fixing one side
 * fails here until the case moves into `cases`.
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
  PHRASE_PATTERNS, type RunFacts, type Tier, type TierCounts, type TierLabel, type TierReason, type TierResult,
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
  disagreements: { id: string; name: string; finding: Over; facts: string; python: TierResult; screen: TierResult }[];
  removed: { name: string; finding: Over; removed: boolean }[];
  counts: { name: string; facts: string; findings: Over[]; expected: Record<string, number> }[];
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

describe("known disagreements stay pinned until fixed on purpose", () => {
  it.each(TABLE.disagreements.map((d) => [`${d.id}: ${d.name}`, d] as const))("%s", (_name, d) => {
    const screen = tierOf(findingOf(d.finding), factsOf(d.facts));
    expect(screen).toEqual(d.screen);
    // If this fails, the two sides now agree: move the case into `cases`.
    expect(screen).not.toEqual(d.python);
    expect(d.screen).not.toEqual(d.python);
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

describe("the table is not vacuous", () => {
  it("holds at least 30 cases, one per reason word and per tiered status, and both D1 and D2", () => {
    expect(TABLE.cases.length).toBeGreaterThanOrEqual(30);
    const reasons = new Set(TABLE.cases.map((c) => c.expected.reason));
    for (const word of TIER_RULES.reasons) expect(reasons, word).toContain(word);
    const statuses = new Set(TABLE.cases.map((c) => findingOf(c.finding).compliance_status));
    for (const status of [
      ...Object.keys(TIER_RULES.status_tiers), ...TIER_RULES.tier_c_statuses, TIER_RULES.missing_information.status,
    ]) expect(statuses, status).toContain(status);
    expect(TABLE.disagreements.map((d) => d.id)).toEqual(expect.arrayContaining(["D1", "D2"]));
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
  it("compiles every phrase from the data, with the same source and no flags", () => {
    expect(Object.keys(PHRASE_PATTERNS).sort()).toEqual(Object.keys(TIER_RULES.phrases).sort());
    for (const [word, source] of Object.entries(TIER_RULES.phrases)) {
      const compiled = PHRASE_PATTERNS[word as keyof typeof PHRASE_PATTERNS];
      expect(compiled.source).toBe(new RegExp(source).source);
      expect(compiled.flags).toBe("");
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
  it("holds no phrase or fold pattern", () => {
    expect(source).not.toMatch(/\\bvalue conflict/);
    expect(source).not.toMatch(/\\bunit unknown/);
    expect(source).not.toContain("[\\s_-]");
  });
});
