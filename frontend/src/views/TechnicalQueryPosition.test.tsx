/** COMPANY's usual cost / schedule sentence, OFFERED beside the draft (lead-4's final design, 27 Nov 2026). Invented values. */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TechnicalQueriesView } from "./TechnicalQueriesView";
import { TechnicalQueryPosition, withPositionLine } from "./TechnicalQueryPosition";

const LINE = "On the information given, COMPANY finds no basis for a change to cost or schedule from this item.";

describe("the offered sentence", () => {
  it("is added once, as the last paragraph", () => {
    const once = withPositionLine("1. Class 300 applies [S1].", LINE);
    expect(once).toBe(`1. Class 300 applies [S1].\n\n${LINE}`);
    expect(withPositionLine(once, LINE)).toBe(once); // a second press changes nothing
    expect(withPositionLine("", LINE)).toBe(LINE);
  });

  it("shows the quiet hint only when the request mentions money or time, and says where it can be added when the reply is not editable", () => {
    const { rerender } = render(<TechnicalQueryPosition position={{ line: LINE, hint: null }} canEdit onAdd={() => {}} />);
    expect(screen.queryByTestId("position-hint")).toBeNull();
    expect(screen.getByRole("button", { name: "Add COMPANY’s usual cost/schedule sentence" })).toBeTruthy();
    rerender(<TechnicalQueryPosition position={{ line: LINE, hint: "This request mentions money or time: state COMPANY's position yourself." }} canEdit={false} onAdd={() => {}} />);
    expect(screen.getByTestId("position-hint")).toHaveTextContent("This request mentions money or time");
    expect(screen.queryByTestId("position-add")).toBeNull();
    expect(screen.getByText(/while the reply can still be changed/)).toBeTruthy();
  });
});

const query = {
  id: "q1", subject: "Invented query", contractor_name: null, department: null, assignee_user_id: null, extracted_question: "Which class?",
  proposed_question: "Which class?", proposed_questions: [], evidence_coverage: null, status: "awaiting_review", priority: "normal",
  received_at: "2026-01-01T00:00:00Z", due_at: null, can_review: true, messages: [], evidence: [],
  drafts: [{ id: "dr1", version: 1, answer: "1. Class 300 applies [S1].", citations_json: "[]", model: "local-model", system: true }],
  ready: { question: "Which class?", question_source: "proposed", evidence: "ready", evidence_fresh: true, draft: "ready", draft_fresh: true, marks: [], position: { line: LINE, hint: null } },
};
const api = vi.hoisted(() => ({
  saveQuestion: vi.fn(), classifyEvidence: vi.fn(), list: vi.fn(), get: vi.fn(), metrics: vi.fn(), mailboxes: vi.fn(), assignees: vi.fn(),
  routingRules: vi.fn(), generateDraft: vi.fn(), createByHand: vi.fn(), completeGmail: vi.fn(), fileIntoLibrary: vi.fn(), gmailLabels: vi.fn(),
  activateGmailLabel: vi.fn(), checkNow: vi.fn(), importAgain: vi.fn(), prepareAllPlan: vi.fn(), prepareAllStart: vi.fn(), startGmail: vi.fn(),
  testSend: vi.fn(), decide: vi.fn(), createDraft: vi.fn(),
}));
vi.mock("../api/client", () => ({ technicalQueriesApi: api, classification: { ofDocument: vi.fn(), confirm: vi.fn() } }));

describe("on the query page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.list.mockResolvedValue({ ok: true, data: { items: [query] } });
    api.get.mockResolvedValue({ ok: true, data: query });
    api.metrics.mockResolvedValue({ ok: true, data: { total: 1 } });
    for (const f of [api.mailboxes, api.assignees, api.routingRules, api.prepareAllPlan]) f.mockResolvedValue({ ok: false, error: { message: "no" } });
  });

  it("on a reply awaiting approval, one press puts the sentence in the engineer's own reply, opened for them to save (the model's draft is untouched)", async () => {
    render(<TechnicalQueriesView isAdmin />);
    const add = await screen.findByTestId("position-add");
    expect(screen.getByTestId("more-actions")).not.toHaveAttribute("open");
    fireEvent.click(add);
    fireEvent.click(add);
    const editor = screen.getByLabelText("Write the reply yourself") as HTMLTextAreaElement;
    expect(editor.value).toBe(`1. Class 300 applies [S1].\n\n${LINE}`); // added once
    expect((screen.getByTestId("more-actions") as HTMLDetailsElement).open).toBe(true);
    expect(api.createDraft).not.toHaveBeenCalled(); // nothing is saved until the engineer saves it
  });
});
