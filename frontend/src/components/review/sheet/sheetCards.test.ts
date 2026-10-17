/**
 * #967 PR 2: the Sheet screen's card model.
 *
 * MUTATION PROOF: key cards by finding id and "collapses 13 blanks" fails;
 * drop the engineer-wording branch of the key and "keeps an engineer's own
 * wording apart" fails; let `isAgreed` ignore a rejection and "a rejected
 * finding is not agreed" fails; claim "proven" in `trustLine` and the trust
 * test fails; drop the gate items not on a card and "never says everything
 * checked out" fails.
 */
import { describe, expect, it } from "vitest";

import type { CrsIssueGate, ReviewFinding } from "../../../types/api";
import { CARD_CHUNK, type SheetCard, visibleCards } from "./sheetCards";
import {
  buildCards, cardTitle, commentTemplate, groupLine, headline, isAskFinding, passedCount, progress, trustLine,
} from "./sheetCards";

let n = 0;
function f(over: Partial<ReviewFinding> = {}): ReviewFinding {
  n += 1;
  return {
    id: `f${n}`, compliance_status: "MISSING_INFORMATION", matched_phrase: `Field ${n}`,
    required_action: `Contractor to state Field ${n}.`, finding: `Field ${n} is blank.`,
    contractor_page: 2, approval_status: "pending", confirmed_by: null, origin: null,
    ...over,
  } as ReviewFinding;
}

function gate(over: Partial<CrsIssueGate> = {}): CrsIssueGate {
  return {
    review_run_id: "run-1", issuable: false, final_code_recorded: false, blockers: [],
    unread_pages: [], open_findings: [], ...over,
  };
}

describe("cards", () => {
  it("collapses 13 blanks with the same comment template into one card", () => {
    const blanks = Array.from({ length: 13 }, () => f());
    const cards = buildCards(blanks);
    expect(cards).toHaveLength(1);
    expect(cards[0].findings).toHaveLength(13);
    expect(groupLine(cards[0])).toBe("13 blanks, one answer");
  });

  it("keeps different outcomes and different templates apart", () => {
    const cards = buildCards([
      f(), f({ compliance_status: "NON_COMPLIANT" }),
      f({ required_action: "Contractor to confirm the material grade." }),
    ]);
    expect(cards).toHaveLength(3);
  });

  it("keeps an engineer's own wording apart, as the sheet does", () => {
    const cards = buildCards([f(), f({ engineer_comment: "My words." })]);
    expect(cards).toHaveLength(2);
  });

  it("takes the field name and numbers out of the template", () => {
    expect(commentTemplate(f({ matched_phrase: "Set pressure", required_action: "Set pressure 12.5 barg is missing" })))
      .toBe("<field> # barg is missing");
  });

  it("makes no card for a pass, a page-reading note or another document's point", () => {
    expect(isAskFinding(f({ compliance_status: "COMPLIANT" }))).toBe(false);
    expect(isAskFinding(f({ compliance_status: "NEEDS_ENGINEER_REVIEW", ai_rationale: "UNREAD_PAGES: page 4" }))).toBe(false);
    expect(isAskFinding(f({ compliance_status: "NOT_IN_DOCUMENT_SCOPE" }))).toBe(false);
    expect(isAskFinding(f({ compliance_status: null, origin: "ai_engineering_check" }))).toBe(true);
  });

  it("orders cards and their findings by datasheet page", () => {
    const cards = buildCards([f({ contractor_page: 5, compliance_status: "NON_COMPLIANT" }), f({ contractor_page: 1 })]);
    expect(cards.map((c) => c.page)).toEqual([1, 5]);
  });
});

describe("answered", () => {
  it("is open until every finding of the card is answered", () => {
    const [card] = buildCards([f({ confirmed_by: "eng" }), f()]);
    expect(card.state).toBe("open");
    expect(progress([card])).toEqual({ answered: 0, total: 1 });
  });

  it("knows agreed, not needed and mixed", () => {
    expect(buildCards([f({ confirmed_by: "eng" })])[0].state).toBe("agreed");
    expect(buildCards([f({ approval_status: "rejected" })])[0].state).toBe("not_needed");
    expect(buildCards([f({ confirmed_by: "eng" }), f({ approval_status: "rejected" })])[0].state).toBe("mixed");
  });

  it("a rejected finding is not agreed, even when it was confirmed earlier", () => {
    expect(buildCards([f({ confirmed_by: "eng", approval_status: "rejected" })])[0].state).toBe("not_needed");
  });
});

describe("words", () => {
  it("titles a card in plain English, with no clause number", () => {
    const title = cardTitle(buildCards([f({ matched_phrase: "Orifice", standard_clause: "5.2.1" })])[0]);
    expect(title).toBe("Orifice is not given");
    expect(title).not.toMatch(/5\.2\.1/);
    expect(cardTitle(buildCards([f({ matched_phrase: "Capacity" }), f({ matched_phrase: "Orifice" })])[0]))
      .toBe("Capacity and Orifice are not given");
  });

  it("never claims a rule is proven before rule_trust is wired", () => {
    expect(trustLine(buildCards([f({ match_method: "containment" })])[0])).toBe("Rule not yet proven, so you decide");
    expect(trustLine(buildCards([f({ compliance_status: null, origin: "ai_engineering_check" })])[0]))
      .toBe("Flagged by the computer's plausibility check");
  });

  it("counts the passes of this run", () => {
    expect(passedCount([f({ compliance_status: "COMPLIANT" }), f()])).toBe(1);
  });

  it("rule_trust (#947): the trust line is the finding's own label, in the owner's words", () => {
    expect(trustLine(buildCards([f({ trust_label: "AUTO_PROVEN" })])[0])).toBe("Checked by a proven rule");
    expect(trustLine(buildCards([f({ trust_label: "ENGINEER_CONFIRMED" })])[0])).toBe("Rule approved by an engineer");
    expect(trustLine(buildCards([f({ compliance_status: "NEEDS_ENGINEER_REVIEW", trust_label: "UNPROVEN", rule_said: "NON_COMPLIANT" })])[0]))
      .toBe('Rule not yet proven, so you decide. The rule said "does not meet"; held for you.');
  });
});

describe("the safety tick (rule_trust #947 step 8)", () => {
  const tick = (over: Partial<ReviewFinding> = {}) =>
    f({ compliance_status: "COMPLIANT", show_for_engineer_tick: true, trust_label: "AUTO_PROVEN", tier: "SAFETY",
        matched_phrase: "Set pressure", finding: "Set pressure 9 barg meets the standard.", ...over });

  it("a flagged safety meets is a card, one per value, never grouped and never a pass", () => {
    expect(isAskFinding(tick())).toBe(true);
    expect(isAskFinding(f({ compliance_status: "COMPLIANT", show_for_engineer_tick: false }))).toBe(false);
    const cards = buildCards([tick(), tick({ matched_phrase: "Set pressure" })]);
    expect(cards).toHaveLength(2);
    expect(cardTitle(cards[0])).toBe("Set pressure meets the standard: a safety field, please check it");
    expect(passedCount([tick()])).toBe(1); // still a pass in the count; the tick is the engineer's check of it
  });

  it("is open until ticked, and ticked or 'something is off' like any answer", () => {
    expect(buildCards([tick()])[0].state).toBe("open");
    expect(buildCards([tick({ confirmed_by: "eng" })])[0].state).toBe("agreed");
    expect(buildCards([tick({ approval_status: "rejected" })])[0].state).toBe("not_needed");
    expect(headline(buildCards([tick()]), gate(), null)).toBe("1 thing needs your answer. Everything else checked out.");
  });
});

describe("headline", () => {
  it("says how many things need an answer", () => {
    const cards = buildCards([f(), f({ compliance_status: "NON_COMPLIANT" })]);
    expect(headline(cards, gate(), null)).toBe("2 things need your answer. Everything else checked out.");
  });

  it("never says everything checked out while a page is unread or the sheet has other open items", () => {
    const cards = buildCards([f()]);
    const text = headline(cards, gate({
      unread_pages: [{ page: 4, reason: null }], open_findings: [{ finding_id: "row-key", row_kind: null, item: 3 }],
    }), null);
    expect(text).toBe("1 thing needs your answer. Page 4 still needs a look. 1 more item on the sheet needs a decision.");
    expect(text).not.toMatch(/checked out/);
  });

  it("asks for the overall decision once every card is answered", () => {
    expect(headline(buildCards([f({ confirmed_by: "eng" })]), gate(), null))
      .toBe("All answered. Choose your overall decision.");
  });

  it("says ready only when the server's gate says issuable", () => {
    const cards = buildCards([f({ confirmed_by: "eng" })]);
    expect(headline(cards, gate({ issuable: true }), "Approved with Comments"))
      .toBe("All answered and decided. Ready to send to the contractor.");
    expect(headline(cards, gate({ blockers: ["no page coverage is recorded for this run, so no page can be called read"] }), "Approved"))
      .toMatch(/^Not ready to send yet: no page coverage/);
  });
});

describe("#603: visibleCards", () => {
  const many = Array.from({ length: 70 }, (_, i) => ({ key: `k${i}`, findings: [], state: "open", page: 1, pages: [1] })) as unknown as SheetCard[];
  it("shows the first chunk and extends it to reach the selected card", () => {
    expect(visibleCards(many, CARD_CHUNK, null)).toHaveLength(CARD_CHUNK);
    expect(visibleCards(many, CARD_CHUNK, many[65])).toHaveLength(66);
    expect(visibleCards(many, 200, many[3])).toHaveLength(70);
  });
});
