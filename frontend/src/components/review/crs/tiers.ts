/**
 * The CRS-first Sheet's tiers (order 95 piece 2, spec section 2; Part of #967).
 *
 * ONE PLACE DECIDES what the engineer sees first. Every row of the Sheet,
 * the collapsed "met" line, the footer counts and the keyboard flow read
 * the result of `tierOf`, never a status of their own.
 *
 *   Tier A  "Met" / "Not applicable"   COMPLIANT ("Met"), NOT_APPLICABLE
 *           / "Another document"       (does-not-apply), NOT_IN_DOCUMENT_SCOPE
 *                                      (the clause names another document).
 *   Tier B  "Comment"                  NON_COMPLIANT; MISSING_INFORMATION
 *                                      when the page WAS read into fields and
 *                                      the standard IS in the library.
 *   Tier C  "Needs you" + a reason     NEEDS_ENGINEER_REVIEW, CONDITIONAL, a
 *                                      page not read into fields or timed out
 *                                      ("page not read"), a standard the
 *                                      library does not hold ("standard not
 *                                      in library"), a pairing an AI guessed
 *                                      and nobody confirmed ("AI guess",
 *                                      mirrors comparison._pairing_unconfirmed),
 *                                      a rule not yet proven ("rule not
 *                                      proven"), an unconfirmed safety tick
 *                                      ("safety field"), a value conflict, an
 *                                      unknown unit, else "condition
 *                                      unsettled". These apply whatever the
 *                                      status: a "met" nobody can stand behind
 *                                      is shown to the engineer.
 *
 * DISPLAY ONLY. No stored status changes here, and the run's verdicts are
 * untouched (rule 3 of #805: display, no verdict change). The inputs are
 * data-shaped on purpose: piece 1 of order 95 (the run summary endpoint)
 * will hand the same facts from the server, and this signature stays.
 */
import type { PageCoverage, ReviewFinding, ReviewRunMissingReference, ReviewRunStandard, ReviewRunSummary } from "../../../types/api";

export type Tier = "A" | "B" | "C";

/** The words on the row. Never a percentage (spec 1.2). */
export type TierLabel = "Met" | "Not applicable" | "Another document" | "Comment" | "Needs you";

/** The closed list of reason words for a Tier C row (spec 1.2). */
export type TierReason =
  | "page not read"
  | "standard not in library"
  | "AI guess"
  | "rule not proven"
  | "safety field"
  | "condition unsettled"
  | "value conflict"
  | "unit unknown";

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

const TIER_C = new Set(["NEEDS_ENGINEER_REVIEW", "CONDITIONAL"]);

function fold(text: string | null | undefined): string {
  return (text ?? "").toLowerCase().replace(/[\s_-]+/g, " ").trim();
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

/** Mirrors `_pairing_unconfirmed` in backend/app/comparison.py (#921): a
 *  field paired by its name alone (METHOD_FIELD_NAME, always held), or a
 *  model's pairing held for review (METHOD_MODEL_CHOICE with
 *  NEEDS_ENGINEER_REVIEW), is a guess waiting for an engineer. */
export function pairingUnconfirmed(finding: ReviewFinding): boolean {
  if (finding.match_method === "field_name") return true;
  return finding.match_method === "model" && finding.compliance_status === "NEEDS_ENGINEER_REVIEW";
}

/** rule_trust (#947): the rule behind the finding has not been proven yet. */
export function ruleUnproven(finding: ReviewFinding): boolean {
  return finding.trust_label === "UNPROVEN";
}

/** rule_trust (#947): a safety field shown for the engineer's own tick,
 *  which no engineer has ticked yet. */
export function safetyTickOpen(finding: ReviewFinding): boolean {
  return Boolean(finding.show_for_engineer_tick) && finding.compliance_status === "COMPLIANT" && !finding.confirmed_by;
}

function conflictWord(finding: ReviewFinding): TierReason | null {
  const why = fold(finding.ai_rationale);
  if (/\bvalue conflict\b|\bconflicting values?\b|\bvalues? conflict\b/.test(why)) return "value conflict";
  if (/\bunit unknown\b|\bunknown unit\b|\bunit (?:not|could not be) (?:read|recognised|recognized|parsed)\b/.test(why)) return "unit unknown";
  return null;
}

/** The fact, other than the status, that makes this finding Tier C, in the
 *  order the reason is told. The page comes first: nothing about an unread
 *  page is settled. Null when no such fact holds. */
function unsettledReason(finding: ReviewFinding, facts: RunFacts): TierReason | null {
  if (pageNotRead(finding, facts)) return "page not read";
  if (citesMissingStandard(finding, facts)) return "standard not in library";
  if (pairingUnconfirmed(finding)) return "AI guess";
  if (ruleUnproven(finding)) return "rule not proven";
  if (safetyTickOpen(finding)) return "safety field";
  return conflictWord(finding);
}

/** Why a Tier C row needs the engineer, in the spec's reason words. */
function needsYouReason(finding: ReviewFinding, facts: RunFacts): TierReason {
  const unsettled = unsettledReason(finding, facts);
  if (unsettled) return unsettled;
  if (finding.compliance_status === "MISSING_INFORMATION" && !standardInLibrary(finding, facts)) return "standard not in library";
  return "condition unsettled";
}

/** Spec section 2, in order: the facts that make any finding Tier C come
 *  first, so a "met" value on an unread page is still shown to the engineer. */
export function tierOf(finding: ReviewFinding, facts: RunFacts = EMPTY_FACTS): TierResult {
  const status = finding.compliance_status ?? "";
  if (TIER_C.has(status) || unsettledReason(finding, facts) !== null) {
    return { tier: "C", label: "Needs you", reason: needsYouReason(finding, facts) };
  }
  if (status === "COMPLIANT") return { tier: "A", label: "Met", reason: null };
  if (status === "NOT_APPLICABLE") return { tier: "A", label: "Not applicable", reason: null };
  if (status === "NOT_IN_DOCUMENT_SCOPE") return { tier: "A", label: "Another document", reason: null };
  if (status === "NON_COMPLIANT") return { tier: "B", label: "Comment", reason: null };
  if (status === "MISSING_INFORMATION") {
    if (standardInLibrary(finding, facts)) return { tier: "B", label: "Comment", reason: null };
    return { tier: "C", label: "Needs you", reason: "standard not in library" };
  }
  // A status this table does not know is never swept quietly: it needs a person.
  return { tier: "C", label: "Needs you", reason: "condition unsettled" };
}

/** The facts from the run and its standards list, as the screen has them
 *  today. Piece 1 of order 95 replaces this with the server's own summary. */
export function runFactsOf(
  run: Pick<ReviewRunSummary, "page_coverage"> | null,
  standards: ReviewRunStandard[] | null,
  missing: ReviewRunMissingReference[],
): RunFacts {
  const coverage: PageCoverage | null | undefined = run?.page_coverage;
  const timedOut = Object.entries(coverage?.not_read_reasons ?? {})
    .filter(([, reason]) => /timed? ?out/i.test(reason ?? ""))
    .map(([page]) => Number(page))
    .filter((p) => Number.isFinite(p));
  return {
    pagesNotRead: coverage?.pages_not_read_into_fields ?? [],
    readerTimedOutPages: timedOut,
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

export function countTiers(results: TierResult[]): TierCounts {
  const counts: TierCounts = { met: 0, notApplicable: 0, anotherDocument: 0, comment: 0, needsYou: 0 };
  for (const r of results) {
    if (r.tier === "B") counts.comment += 1;
    else if (r.tier === "C") counts.needsYou += 1;
    else if (r.label === "Met") counts.met += 1;
    else if (r.label === "Another document") counts.anotherDocument += 1;
    else counts.notApplicable += 1;
  }
  return counts;
}

/** A group of findings shown as one row takes the most demanding tier of
 *  its members: C over B over A. */
export function tierOfGroup(findings: ReviewFinding[], facts: RunFacts): TierResult {
  const results = findings.map((f) => tierOf(f, facts));
  return results.find((r) => r.tier === "C") ?? results.find((r) => r.tier === "B") ?? results[0]
    ?? { tier: "C", label: "Needs you", reason: "condition unsettled" };
}
