/**
 * The query page's lower half (owner, 27 Nov 2026 00:02: "it is difficult to understand these buttons"): the decision is the one coloured
 * button, re-writing is quiet and says it replaces the reply, one form and one Save for who handles it, a short quote with the ask's words
 * marked, the Word file says why it waits, and the history speaks plainly. Invented values only.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TechnicalQueriesView } from "./TechnicalQueriesView";
import { askWords, decisionFor, fromSubjectHint, historyWords, markedPieces, shortQuote, wordReplyWhyNot } from "./technicalQueryQuestion";

const LONG = "The coating system shall have a minimum dry film thickness of 250 microns on every external surface of the vessel, measured "
  + "after curing, and the contractor shall record each reading in the inspection sheet together with the batch number and the date. "
  + "A reading below the minimum is repaired and measured again before the next coat, and the repair is written in the same sheet.";
const draft = { id: "d1", version: 1, answer: "Yes. The minimum dry film thickness is 250 microns.", assumptions_json: "[]", unresolved_json: "[]",
  citations_json: JSON.stringify([{ label: "S1", document_id: "doc-1", page: 4, exact_quote: LONG, evidence_id: "e1" }]), model: "invented-small:9b", system: true };
const query = {
  id: "q1", subject: "TQ-0099-PRO Coating thickness", contractor_name: null, department: null, assignee_user_id: null,
  contractor_code: "ABC", discipline_code: "PRO",
  proposed_question: "1. What is the minimum coating thickness?", proposed_questions: [], status: "awaiting_review", priority: "normal",
  received_at: "2026-01-01T00:00:00Z", due_at: null, can_review: true, messages: [], decisions: [],
  evidence: [{ id: "e1", document_id: "doc-1", page_start: 4, exact_quote: LONG, evidence_state: "candidate", supersession_state: "current", for_current_question: true }],
  drafts: [draft],
};

const api = vi.hoisted(() => ({
  saveQuestion: vi.fn(), classifyEvidence: vi.fn(), decide: vi.fn(), list: vi.fn(), get: vi.fn(), metrics: vi.fn(), mailboxes: vi.fn(),
  assignees: vi.fn(), routingRules: vi.fn(), generateDraft: vi.fn(), createByHand: vi.fn(), completeGmail: vi.fn(), fileIntoLibrary: vi.fn(),
  gmailLabels: vi.fn(), activateGmailLabel: vi.fn(), checkNow: vi.fn(), importAgain: vi.fn(), prepareAllPlan: vi.fn(), prepareAllStart: vi.fn(),
  triage: vi.fn(), assign: vi.fn(), prepareEvidence: vi.fn(),
}));
const cls = vi.hoisted(() => ({ ofDocument: vi.fn(), confirm: vi.fn() }));
vi.mock("../api/client", () => ({ technicalQueriesApi: api, classification: cls }));

function open(data: Record<string, unknown> = {}) {
  const q = { ...query, ...data };
  api.list.mockResolvedValue({ ok: true, data: { items: [q] } });
  api.get.mockResolvedValue({ ok: true, data: q });
  render(<TechnicalQueriesView />);
  return screen.findByText(q.subject as string, { selector: "h2" });
}

describe("the query page's lower half", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.metrics.mockResolvedValue({ ok: true, data: { total: 1 } });
    api.mailboxes.mockResolvedValue({ ok: false, error: { message: "no" } });
    api.assignees.mockResolvedValue({ ok: true, data: { items: [{ id: "u2", display_name: "Invented Engineer" }] } });
    api.routingRules.mockResolvedValue({ ok: false, error: { message: "no" } });
    api.classifyEvidence.mockResolvedValue({ ok: true, data: query });
    api.decide.mockResolvedValue({ ok: true, data: query });
    api.triage.mockResolvedValue({ ok: true, data: query });
    api.assign.mockResolvedValue({ ok: true, data: query });
  });

  it("the one coloured button under the reply is the decision; re-writing is quiet and folded", async () => {
    await open();
    const decision = screen.getByTestId("approve-once");
    const filled = within(decision).getAllByRole("button").filter((b) => b.className.includes("bg-signal-500"));
    expect(filled.map((b) => b.textContent)).toEqual(["Approve the reply"]);
    expect(within(decision).getByRole("button", { name: "Send back with a note" })).toBeTruthy();
    expect(screen.getByTestId("decision-hint").textContent).toMatch(/Nothing is sent/);
    const redo = screen.getByTestId("more-actions");
    expect(within(redo).getByText("Redo: change the reply or write it again")).toBeTruthy();
    for (const b of within(redo).getAllByRole("button")) expect(b.className).not.toContain("bg-signal-500");
    expect(within(redo).getByRole("button", { name: "Write the reply again" })).toBeTruthy();
    expect(within(redo).getAllByText(/replaces the reply above/).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Generate draft" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Approve latest draft" })).toBeNull();
  });

  it("send back asks for a note and sends it with the decision", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Send back with a note" }));
    const box = screen.getByTestId("send-back");
    const send = within(box).getByRole("button", { name: "Send back" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.change(within(box).getByLabelText("What should change in the reply?"), { target: { value: "Cite the inspection clause too." } });
    fireEvent.click(send);
    await waitFor(() => expect(api.decide).toHaveBeenCalledWith("q1", "request_changes", "d1", "Cite the inspection clause too."));
  });

  it("without the reviewer role the page says who can approve instead of a button", async () => {
    await open({ can_review: false });
    expect(screen.queryByRole("button", { name: "Approve the reply" })).toBeNull();
    expect(screen.getByTestId("decision-no-role").textContent).toMatch(/technical-query reviewer role/);
  });

  it("who writes the reply is a choice, and Claude says why it cannot be used now", async () => {
    await open({ draft_engines: { claude: { available: false, why: "the Claude account has no credit" } } });
    const local = screen.getByLabelText("The AI on this computer (free)") as HTMLInputElement;
    const claude = screen.getByLabelText(/^Claude \(paid, better/) as HTMLInputElement;
    expect(local.checked).toBe(true);
    expect(claude.disabled).toBe(true);
    expect(screen.getByTestId("claude-why").textContent).toContain("the Claude account has no credit");
  });

  it("one form and one Save for who handles it: the routing fields, then the person", async () => {
    await open();
    const who = screen.getByLabelText("Who handles it");
    expect(within(who).getAllByRole("button").map((b) => b.textContent)).toEqual(["Save who handles it"]);
    expect(screen.getByTestId("from-subject").textContent).toContain("contractor code ABC, discipline PRO");
    fireEvent.change(within(who).getByLabelText("Responsible person"), { target: { value: "u2" } });
    fireEvent.click(within(who).getByRole("button", { name: "Save who handles it" }));
    await waitFor(() => expect(api.assign).toHaveBeenCalledWith("q1", "u2"));
    expect(api.triage).toHaveBeenCalledWith("q1", { contractor_name: null, department: null, priority: "normal", due_at: null });
  });

  it("a long source passage shows a few lines with the ask's words marked, and the whole passage one click away", async () => {
    await open();
    const sources = screen.getByTestId("reply-sources");
    expect(within(sources).getByTestId("quote-short").textContent).toContain("…");
    // the ask's words are marked once the ask is on the page (it is filled one render after the query opens)
    expect((await within(sources).findAllByTestId("quote-mark")).map((m) => m.textContent?.toLowerCase())).toContain("coating");
    expect(within(sources).getByText("Show the whole quote")).toBeTruthy();
    expect(within(sources).getByTestId("quote-full").textContent).toContain("written in the same sheet.");
  });

  it("the Word file waits for the approval and says so; the history says nobody has approved yet", async () => {
    await open();
    const word = screen.getByTestId("word-reply");
    expect((within(word).getByRole("button", { name: "Download the reply as a Word file" }) as HTMLButtonElement).disabled).toBe(true);
    expect(word.textContent).toContain("Available once the reply is approved.");
    expect(within(screen.getByTestId("review-history")).getByText("Nobody has approved this yet.")).toBeTruthy();
  });

  it("once approved the Word file is a link and Mark as answered follows", async () => {
    await open({ status: "approved" });
    const word = screen.getByTestId("word-reply");
    expect(within(word).getByRole("link", { name: "Download the reply as a Word file" }).getAttribute("href")).toBe("/api/technical-queries/q1/response.docx");
    expect(within(word).getByRole("button", { name: "Mark as answered" })).toBeTruthy();
  });
});

describe("what the contractor's form cites", () => {
  beforeEach(() => {
    api.metrics.mockResolvedValue({ ok: true, data: { total: 1 } });
    api.mailboxes.mockResolvedValue({ ok: false, error: { message: "no" } });
    api.assignees.mockResolvedValue({ ok: false, error: { message: "no" } });
    api.routingRules.mockResolvedValue({ ok: false, error: { message: "no" } });
  });
  it("is listed near the top, a not-held one marked; nothing when the form cites nothing", async () => {
    await open({ ready: { question: "1. What is the minimum coating thickness?", question_source: "proposed", evidence: "ready", evidence_fresh: true, draft: "ready", draft_fresh: true,
      cited: [{ line: "Invented standard 12, clause 4: held", held: true }, { line: "Invented standard 99: not held among the standards you may read", held: false }] } });
    const box = screen.getByTestId("contractor-cites");
    expect([...box.querySelectorAll("li")].map((li) => [li.textContent, li.className.includes("text-warn-500")])).toEqual([
      ["\u2713Invented standard 12, clause 4: held", false], ["!Invented standard 99: not held among the standards you may read", true]]);
  });
  it("is absent when the form cites nothing", async () => {
    await open();
    expect(screen.queryByTestId("contractor-cites")).toBeNull();
  });
});

describe("the lower half's words", () => {
  it("cuts a long passage at a word and says it was cut; a short one is whole", () => {
    expect(shortQuote("short text")).toEqual({ short: "short text", cut: false });
    const { short, cut } = shortQuote(LONG, 60);
    expect(cut).toBe(true);
    expect(short.length).toBeLessThanOrEqual(60);
    expect(LONG.startsWith(short)).toBe(true);
  });
  it("marks whole words of the ask only, never common words", () => {
    const words = askWords("Please confirm the minimum coating thickness required");
    expect(words).toEqual(["minimum", "coating", "thickness"]);
    expect(markedPieces("Coatings and coating.", ["coating"]).filter((p) => p.hit).map((p) => p.text)).toEqual(["coating"]);
  });
  it("decides the decision and the Word file's wait from the status", () => {
    expect(decisionFor({ status: "drafting", drafts: [{}], can_review: true }).kind).toBe("none");
    expect(decisionFor({ status: "awaiting_review", drafts: [], can_review: true }).kind).toBe("none");
    expect(decisionFor({ status: "awaiting_review", drafts: [{}], can_review: false }).kind).toBe("no_role");
    expect(wordReplyWhyNot({ status: "awaiting_review", drafts: [{}] })).toBe("Available once the reply is approved.");
    expect(wordReplyWhyNot({ status: "approved", drafts: [{}] })).toBeNull();
  });
  it("says what the subject holds, and plain history", () => {
    expect(fromSubjectHint({})).toBeNull();
    expect(fromSubjectHint({ discipline_code: "PRO" })).toContain("discipline PRO");
    expect(historyWords([])).toEqual(["Nobody has approved this yet."]);
    expect(historyWords([{ decision: "request_changes", comment: "Cite the clause." }])).toEqual(["Sent back: Cite the clause."]);
  });
});
