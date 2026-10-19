/**
 * The CRS-first Sheet's tiers (order 95 piece 2, spec section 2; Part of #967).
 *
 * ONE PLACE DECIDES what the engineer sees first. Every row of the Sheet,
 * the collapsed "met" line, the footer counts and the keyboard flow read
 * the result of `tierOf`, never a status of their own.
 *
 * THE RULES ARE DATA (order 133): every status, label, reason word, the
 * order the reasons are told in, the phrases and the pairing-guess rule
 * live in `backend/app/reference/review_tiers.json`, generated for the
 * screen into `contracts/generated/review_tiers.ts` (`TIER_RULES`). The
 * server's `backend/app/review_tiers.py` reads the same file, and both run
 * the same cases (`contracts/fixtures/review_tier_cases.json`; here
 * `tiers.parity.test.ts`). This file keeps only the logic:
 *
 *   Tier C (`needs_you`) + a reason: a status in `tier_c_statuses`, or any
 *           fact of `unsettled_order` that holds (unread or timed-out page,
 *           a standard the library does not hold, an AI pairing guess -
 *           mirrors comparison._pairing_unconfirmed -, a rule not proven,
 *           an unconfirmed safety tick, a value conflict, an unknown unit),
 *           whatever the status: a "met" nobody can stand behind is shown
 *           to the engineer. The first fact in `unsettled_order` names it.
 *   Else    `status_tiers[status]` (Tier A "Met" / "Not applicable" /
 *           "Another document", Tier B "Comment").
 *   Else    `missing_information`: Tier B when the standard IS in the
 *           library, else Tier C "standard not in library".
 *   Else    a status the table does not know: Tier C `fallback_reason`.
 *
 * DISPLAY ONLY. No stored status changes here, and the run's verdicts are
 * untouched (rule 3 of #805: display, no verdict change). The inputs are
 * data-shaped on purpose: the run summary endpoint hands the same facts
 * from the server, and this signature stays.
 */
import type {
  ReviewFinding, ReviewRunMissingReference, ReviewRunStandard, ReviewRunSummary, RunSummaryTier,
  RunSummaryTierCounts, RunSummaryTierLabel, RunSummaryTierReason, RunSummaryTierRow,
} from "../../../types/api";
import { TIER_RULES } from "../../../../../contracts/generated/review_tiers";

/** The tier words are the server's (`backend/app/api/run_summary.py`
 *  `TierRow`, generated into contracts/generated/run_summary.ts, order
 *  119.1): one list, so the screen cannot name a tier the server never sends. */
export type Tier = RunSummaryTier;

/** The words on the row. Never a percentage (spec 1.2). */
export type TierLabel = RunSummaryTierLabel;

/** The closed list of reason words for a Tier C row (spec 1.2). */
export type TierReason = RunSummaryTierReason;

export interface TierResult {
  tier: Tier;
  label: TierLabel;
  /** Only a Tier C row carries a reason. */
  reason: TierReason | null;
}

/** What is known about the run, as data. Every list may be empty. */
export interface RunFacts {
  /** `page_coverage.pages_not_read_into_fields` as stored on the run. */
  pagesNotRead: number[];
  /** Pages the AI reader gave up on (`reader.timed_out`), when recorded per page. */
  readerTimedOutPages: number[];
  /** Identifiers of standards the submittal cites that the library does not
   *  hold (MISSING_LOCALLY), e.g. "API 526". */
  missingStandards: string[];
  /** Ids of the standards the run compared against (the library). Null when
   *  the list could not be loaded: then nothing is called "not in library"
   *  on that ground alone - a failed list is not an empty one. */
  libraryStandardIds: string[] | null;
}

export const EMPTY_FACTS: RunFacts = {
  pagesNotRead: [], readerTimedOutPages: [], missingStandards: [], libraryStandardIds: null,
};

type Placed = Pick<TierResult, "tier" | "label">;
type Predicate = (finding: ReviewFinding, facts: RunFacts) => boolean;
/** A reason word of `unsettled_order`: a fact, other than the status, that makes a finding Tier C. */
type UnsettledWord = (typeof TIER_RULES.unsettled_order)[number];
type PhraseWord = keyof typeof TIER_RULES.phrases;

const NEEDS_YOU: Placed = TIER_RULES.needs_you;
const MISSING_INFORMATION = TIER_RULES.missing_information;
const FALLBACK_REASON: TierReason = TIER_RULES.fallback_reason;
const TIER_C_STATUSES: ReadonlySet<string> = new Set(TIER_RULES.tier_c_statuses);
/** A Map, not an object: a status named like an Object.prototype key must not find a tier. */
const STATUS_TIERS: ReadonlyMap<string, Placed> = new Map(Object.entries(TIER_RULES.status_tiers));
const PAIRING_ALWAYS: ReadonlySet<string> = new Set(TIER_RULES.pairing_guess.always);
const PAIRING_HELD = TIER_RULES.pairing_guess.held;
const FOLD = new RegExp(TIER_RULES.fold.pattern, "g");

const WORD_EDGE = TIER_RULES.word_edge;

/** The phrase rules, compiled once from the data with the data's word edge
 *  and flags (order 135, D1): the data's token becomes this engine's
 *  spelling of one class (a Unicode letter, number or underscore), compiled
 *  with the flag that spelling needs. The server puts its own spelling of the
 *  same class in place of the same token. */
export const PHRASE_PATTERNS: Readonly<Record<PhraseWord, RegExp>> = Object.fromEntries(
  Object.entries(TIER_RULES.phrases).map(([word, source]) => [
    word, new RegExp(source.replaceAll(WORD_EDGE.token, WORD_EDGE.javascript), WORD_EDGE.javascript_flags),
  ]),
) as Record<PhraseWord, RegExp>;

/** Lower case, every run of the data's separators (order 135, D2: an
 *  explicit class, never this engine's own \s) as one space, ends trimmed.
 *  The server folds with the same class. */
export function fold(text: string | null | undefined): string {
  return (text ?? "").toLowerCase().replace(FOLD, TIER_RULES.fold.replace).trim();
}

/** The finding's page is one the reader did not read into fields, or gave up on. */
export function pageNotRead(finding: ReviewFinding, facts: RunFacts): boolean {
  const page = finding.contractor_page;
  if (typeof page !== "number") return false;
  return facts.pagesNotRead.includes(page) || facts.readerTimedOutPages.includes(page);
}

/** The finding cites a standard the library does not hold. A finding with
 *  no library standard behind it that names a missing one, in its sources,
 *  its requirement or its rationale, is such a finding. */
export function citesMissingStandard(finding: ReviewFinding, facts: RunFacts): boolean {
  if (facts.missingStandards.length === 0) return false;
  const text = fold([
    ...(finding.governing_sources ?? []), finding.requirement, finding.ai_rationale, finding.standard_clause,
  ].filter(Boolean).join(" \n "));
  return facts.missingStandards.some((id) => {
    const needle = fold(id);
    return needle.length > 0 && text.includes(needle);
  });
}

/** The finding rests on a standard the library holds. */
export function standardInLibrary(finding: ReviewFinding, facts: RunFacts): boolean {
  if (!finding.standard_document_id) return false;
  if (facts.libraryStandardIds === null) return true;
  return facts.libraryStandardIds.includes(finding.standard_document_id);
}

/** Mirrors `_pairing_unconfirmed` in backend/app/comparison.py (#921), from
 *  `pairing_guess`: a field paired by its name alone (`always`), or a
 *  model's pairing held for review (`held`), is a guess waiting for an
 *  engineer. */
export function pairingUnconfirmed(finding: ReviewFinding): boolean {
  if (PAIRING_ALWAYS.has(finding.match_method ?? "")) return true;
  return finding.match_method === PAIRING_HELD.match_method && finding.compliance_status === PAIRING_HELD.compliance_status;
}

/** rule_trust (#947): the rule behind the finding has not been proven yet. */
export function ruleUnproven(finding: ReviewFinding): boolean {
  return finding.trust_label === TIER_RULES.rule_not_proven_trust_label;
}

/** rule_trust (#947): a safety field shown for the engineer's own tick,
 *  which no engineer has ticked yet. */
export function safetyTickOpen(finding: ReviewFinding): boolean {
  return Boolean(finding.show_for_engineer_tick) && finding.compliance_status === TIER_RULES.safety_tick_status
    && !finding.confirmed_by;
}

function phrase(word: PhraseWord): Predicate {
  return (finding) => PHRASE_PATTERNS[word].test(fold(finding.ai_rationale));
}

/** One predicate per reason word of `unsettled_order`, keyed by the word.
 *  The keys are type-checked against the data (none missing, none extra);
 *  the ORDER they are tried in is the data's, never this object's. */
export const UNSETTLED_RULES: Readonly<Record<UnsettledWord, Predicate>> = {
  "page not read": pageNotRead,
  [MISSING_INFORMATION.not_in_library_reason]: citesMissingStandard,
  "AI guess": pairingUnconfirmed,
  "rule not proven": ruleUnproven,
  "safety field": safetyTickOpen,
  ...(Object.fromEntries(
    (Object.keys(TIER_RULES.phrases) as PhraseWord[]).map((word) => [word, phrase(word)]),
  ) as Record<PhraseWord, Predicate>),
};

/** The fact, other than the status, that makes this finding Tier C, in the
 *  order the reason is told (`unsettled_order`: the page comes first, since
 *  nothing about an unread page is settled). Null when no such fact holds. */
function unsettledReason(finding: ReviewFinding, facts: RunFacts): TierReason | null {
  return TIER_RULES.unsettled_order.find((word) => UNSETTLED_RULES[word](finding, facts)) ?? null;
}

function needsYou(reason: TierReason): TierResult {
  return { tier: NEEDS_YOU.tier, label: NEEDS_YOU.label, reason };
}

/** Why a Tier C row needs the engineer, in the spec's reason words. */
function needsYouReason(finding: ReviewFinding, facts: RunFacts): TierReason {
  const unsettled = unsettledReason(finding, facts);
  if (unsettled) return unsettled;
  if (finding.compliance_status === MISSING_INFORMATION.status && !standardInLibrary(finding, facts)) {
    return MISSING_INFORMATION.not_in_library_reason;
  }
  return FALLBACK_REASON;
}

/** Spec section 2, in order: the facts that make any finding Tier C come
 *  first, so a "met" value on an unread page is still shown to the engineer. */
export function tierOf(finding: ReviewFinding, facts: RunFacts = EMPTY_FACTS): TierResult {
  const status = finding.compliance_status ?? "";
  if (TIER_C_STATUSES.has(status) || unsettledReason(finding, facts) !== null) {
    return needsYou(needsYouReason(finding, facts));
  }
  const placed = STATUS_TIERS.get(status);
  if (placed) return { tier: placed.tier, label: placed.label, reason: null };
  if (status === MISSING_INFORMATION.status) {
    if (standardInLibrary(finding, facts)) return { ...MISSING_INFORMATION.in_library, reason: null };
    return needsYou(MISSING_INFORMATION.not_in_library_reason);
  }
  // A status this table does not know is never swept quietly: it needs a person.
  return needsYou(FALLBACK_REASON);
}

/** The facts from the run and its standards list: the same stored fields
 *  the server's `run_summary._facts` reads, `page_coverage.pages_not_read_into_fields`
 *  and the reader record's `requirement_split.reader.timed_out` (order 135,
 *  D3: never a guess from a page note's words). No reader record gives no
 *  timed-out page, as on the server: an empty list makes no claim. */
export function runFactsOf(
  run: Pick<ReviewRunSummary, "page_coverage" | "requirement_split"> | null,
  standards: ReviewRunStandard[] | null,
  missing: ReviewRunMissingReference[],
): RunFacts {
  return {
    pagesNotRead: run?.page_coverage?.pages_not_read_into_fields ?? [],
    readerTimedOutPages: run?.requirement_split?.reader?.timed_out ?? [],
    missingStandards: missing.filter((m) => m.status === "MISSING_LOCALLY" || !m.status).map((m) => m.identifier),
    libraryStandardIds: standards ? standards.filter((s) => s.included).map((s) => s.standard_document_id) : null,
  };
}

export interface TierCounts {
  met: number;
  notApplicable: number;
  /** NOT_IN_DOCUMENT_SCOPE: the clause names another document. */
  anotherDocument: number;
  comment: number;
  needsYou: number;
}

/** `count_keys` (the server's snake_case count names) in the screen's camelCase. */
function countKey(label: string): keyof TierCounts | undefined {
  const key = (TIER_RULES.count_keys as Readonly<Record<string, string>>)[label];
  return key === undefined ? undefined : key.replace(/_(\w)/g, (_m, c: string) => c.toUpperCase()) as keyof TierCounts;
}

/** Every label each tier can carry, from the rule data. */
const LABELS_OF_TIER: ReadonlyMap<Tier, ReadonlySet<string>> = (() => {
  const placed: Placed[] = [...STATUS_TIERS.values(), MISSING_INFORMATION.in_library, NEEDS_YOU];
  const byTier = new Map<Tier, Set<string>>();
  for (const p of placed) byTier.set(p.tier, (byTier.get(p.tier) ?? new Set()).add(p.label));
  return byTier;
})();

/** A tier with one label only (Comment, Needs you) is counted by its tier
 *  whatever the label says; a tier with several (Met, Not applicable,
 *  Another document) by its label, and a label that tier does not carry
 *  counts as not applicable. */
function countKeyOf(r: TierResult): keyof TierCounts {
  const labels = LABELS_OF_TIER.get(r.tier);
  if (labels?.size === 1) return countKey([...labels][0]) ?? "notApplicable";
  return (labels?.has(r.label) ? countKey(r.label) : undefined) ?? "notApplicable";
}

export function countTiers(results: TierResult[]): TierCounts {
  const counts: TierCounts = { met: 0, notApplicable: 0, anotherDocument: 0, comment: 0, needsYou: 0 };
  for (const r of results) counts[countKeyOf(r)] += 1;
  return counts;
}

/** The server's tier per finding (order 95 piece 1, #1111:
 *  `GET /api/reviews/runs/{id}/summary`, `backend/app/review_tiers.py`),
 *  keyed by finding id. When the screen has it, it is THE answer (spec
 *  section 2: one place decides); `tierOf` above is the fallback for a
 *  server without the route. */
export type ServerTiers = ReadonlyMap<string, TierResult>;

export function serverTiersOf(rows: RunSummaryTierRow[]): ServerTiers {
  return new Map(rows.map((r) => [r.finding_id, {
    tier: r.tier, label: r.label, reason: r.tier === NEEDS_YOU.tier ? (r.reason ?? FALLBACK_REASON) : null,
  }]));
}

/** One finding's tier: the server's when it sent one for this finding,
 *  else the screen's own rules. A finding the server's rows do not name
 *  (it arrived after the summary was read) keeps the screen's answer
 *  rather than vanishing. */
export function tierFor(finding: ReviewFinding, facts: RunFacts, server: ServerTiers | null = null): TierResult {
  return server?.get(finding.id) ?? tierOf(finding, facts);
}

/** The server's headline counts in the screen's shape. */
export function countsOfServer(counts: RunSummaryTierCounts): TierCounts {
  return {
    met: counts.met, notApplicable: counts.not_applicable, anotherDocument: counts.another_document,
    comment: counts.comment, needsYou: counts.needs_you,
  };
}

/** A group of findings shown as one row takes the most demanding tier of
 *  its members: C (Needs you) over B (Comment) over A. */
export function tierOfGroup(findings: ReviewFinding[], facts: RunFacts, server: ServerTiers | null = null): TierResult {
  const results = findings.map((f) => tierFor(f, facts, server));
  return results.find((r) => r.tier === NEEDS_YOU.tier)
    ?? results.find((r) => r.tier === MISSING_INFORMATION.in_library.tier)
    ?? results[0]
    ?? needsYou(FALLBACK_REASON);
}
