/**
 * rule_trust (#947): a labelled finding says who stands behind its rule, in
 * the owner's words; an unlabelled one says nothing.
 *
 * MUTATION PROOF: drop the `trust_label` block in FindingDetail and the first
 * two tests fail; print words for a null label and the third fails.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ReviewFinding } from "../../types/api";
import { FindingDetail } from "./FindingDetail";

vi.mock("../../api/client", () => ({
  api: { document: vi.fn(async () => ({ ok: false, error: { message: "nf" } })) },
  reviews: { update: vi.fn(), confirm: vi.fn(), rejectPairing: vi.fn() },
}));

const finding = (over: Partial<ReviewFinding>): ReviewFinding => ({
  id: "f1", document_id: "doc-sub", standard_document_id: null, finding: "f", requirement: "r",
  requirement_source_text: "text", contractor_evidence_text: "9 barg", contractor_page: 1,
  standard_page: null, standard_clause: null, compliance_status: "COMPLIANT", confirmed_by: null,
  confirmed_at: null, engineer_comment: null, approval_status: "pending", requirement_id: "req",
  fact_id: "fact", ...over,
}) as unknown as ReviewFinding;

describe("the trust line", () => {
  it("names a proven rule and asks for the safety tick", () => {
    render(<FindingDetail finding={finding({ trust_label: "AUTO_PROVEN", tier: "SAFETY", show_for_engineer_tick: true })}
      documents={[]} onChanged={vi.fn()} />);
    expect(screen.getByTestId("rule-trust")).toHaveTextContent(
      "Checked by a proven rule · safety field: read the clause and the value on the page, then confirm it or reject it");
  });

  it("says what an unproven rule said and that the engineer decides", () => {
    render(<FindingDetail finding={finding({ compliance_status: "NEEDS_ENGINEER_REVIEW", trust_label: "UNPROVEN", rule_said: "COMPLIANT" })}
      documents={[]} onChanged={vi.fn()} />);
    expect(screen.getByTestId("rule-trust")).toHaveTextContent(
      'Rule not yet proven, so you decide · the rule said "Compliant"; held for you until the rule is proven');
  });

  it("prints nothing for a finding the run did not label", () => {
    render(<FindingDetail finding={finding({ trust_label: null })} documents={[]} onChanged={vi.fn()} />);
    expect(screen.queryByTestId("rule-trust")).toBeNull();
  });
});
