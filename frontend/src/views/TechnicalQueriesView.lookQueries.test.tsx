/** H's audit of the query page (27 Nov 2026): #52 the "AI, to be checked" mark was a hand-made box beside the kit's chips (two chip shapes);
 *  #53 "Confirm source document" stood under every passage of the same source. Invented values. */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TechnicalQueriesView } from "./TechnicalQueriesView";

const passage = (id: string, doc: string) => ({ id, document_id: doc, page_start: 3, exact_quote: `quote ${id}`, evidence_state: "proposed", supersession_state: "unknown", for_current_question: true });
const query = {
  id: "q1", subject: "Invented query", contractor_name: null, department: null, assignee_user_id: null, extracted_question: "Which class?",
  proposed_question: "Which class?", proposed_questions: [], evidence_coverage: null, status: "awaiting_review", priority: "normal",
  received_at: "2026-01-01T00:00:00Z", due_at: null, can_review: true, messages: [],
  evidence: [passage("e1", "doc-a"), passage("e2", "doc-a"), passage("e3", "doc-b")],
  drafts: [{ id: "dr1", version: 1, answer: "Class 300 applies [S1].", citations_json: "[]", model: "local-model", system: true }],
};

const api = vi.hoisted(() => ({
  saveQuestion: vi.fn(), classifyEvidence: vi.fn(), list: vi.fn(), get: vi.fn(), metrics: vi.fn(), mailboxes: vi.fn(), assignees: vi.fn(),
  routingRules: vi.fn(), generateDraft: vi.fn(), createByHand: vi.fn(), completeGmail: vi.fn(), fileIntoLibrary: vi.fn(), gmailLabels: vi.fn(),
  activateGmailLabel: vi.fn(), checkNow: vi.fn(), importAgain: vi.fn(), prepareAllPlan: vi.fn(), prepareAllStart: vi.fn(), startGmail: vi.fn(),
  testSend: vi.fn(), decide: vi.fn(),
}));
const cls = vi.hoisted(() => ({ ofDocument: vi.fn(), confirm: vi.fn() }));
vi.mock("../api/client", () => ({ technicalQueriesApi: api, classification: cls }));

describe("the query page in one kit", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.list.mockResolvedValue({ ok: true, data: { items: [query] } });
    api.get.mockResolvedValue({ ok: true, data: query });
    api.metrics.mockResolvedValue({ ok: true, data: { total: 1 } });
    for (const f of [api.mailboxes, api.assignees, api.routingRules, api.prepareAllPlan]) f.mockResolvedValue({ ok: false, error: { message: "no" } });
  });

  it("asks to confirm each unconfirmed source document once, not under every one of its passages (#53)", async () => {
    render(<TechnicalQueriesView isAdmin />);
    await screen.findAllByText("quote e1");
    expect(screen.getAllByTestId("confirm-source")).toHaveLength(2); // doc-a once, doc-b once
    expect(screen.getAllByTestId("evidence-needs-confirm-again")).toHaveLength(1); // doc-a's second passage: one short line
  });

  it("marks the proposed reply with the kit's own chip (#52)", async () => {
    render(<TechnicalQueriesView isAdmin />);
    const chip = await screen.findByTestId("ai-to-check");
    expect(chip.className).toContain("kit-chip");
    expect(chip.getAttribute("data-word")).toBe("AI, to be checked");
    expect(chip.className).toContain("kit-chip--check"); // amber, as every "needs a person's look" word
  });
});
