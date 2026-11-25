import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TechnicalQueriesView } from "./TechnicalQueriesView";

const query = {
  id: "q1",
  subject: "Coating question",
  contractor_name: null,
  department: null,
  assignee_user_id: null,
  extracted_question: "See attached.",
  proposed_question: "See attached.\n1. What is the minimum coating thickness?",
  proposed_questions: [{ question: "What is the minimum coating thickness?", filename: "query.pdf", page: 2 }],
  evidence_coverage: { searched: 19, of: 20, hits_in: 6, failed: 1, line: "Searched 19 of 20 contracts, hits in 6. 1 could not be searched." },
  status: "drafting",
  priority: "normal",
  received_at: "2026-01-01T00:00:00Z",
  due_at: null,
  can_review: true,
  messages: [],
  evidence: [],
};

const api = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  metrics: vi.fn(),
  mailboxes: vi.fn(),
  assignees: vi.fn(),
  routingRules: vi.fn(),
  generateDraft: vi.fn(),
  createByHand: vi.fn(),
  completeGmail: vi.fn(),
  fileIntoLibrary: vi.fn(),
}));

vi.mock("../api/client", () => ({ technicalQueriesApi: api }));

describe("Technical Queries screen", () => {
  beforeEach(() => {
    api.list.mockResolvedValue({ ok: true, data: { items: [query] } });
    api.get.mockResolvedValue({ ok: true, data: query });
    api.metrics.mockResolvedValue({ ok: true, data: { total: 1 } });
    api.mailboxes.mockResolvedValue({ ok: false, error: { message: "no" } });
    api.assignees.mockResolvedValue({ ok: false, error: { message: "no" } });
    api.routingRules.mockResolvedValue({ ok: false, error: { message: "no" } });
    api.generateDraft.mockResolvedValue({ ok: false, error: { message: "Claude for the draft is not enabled on this server." } });
  });

  it("states how many contracts the evidence search covered", async () => {
    render(<TechnicalQueriesView />);
    expect((await screen.findByTestId("evidence-coverage")).textContent).toBe("Searched 19 of 20 contracts, hits in 6. 1 could not be searched.");
  });

  it("offers each question the model found with its page, and adds only the ticked ones", async () => {
    render(<TechnicalQueriesView />);
    const box = await screen.findByRole("checkbox");
    expect(screen.getByText("query.pdf, page 2")).toBeTruthy();
    fireEvent.click(box);
    fireEvent.click(screen.getByText("Add ticked questions to the text"));
    const text = screen.getByLabelText("Question the draft will answer") as HTMLTextAreaElement;
    expect(text.value).toBe("See attached.\nWhat is the minimum coating thickness?");
  });

  it("shows the evidence job's progress, and which attachment pages were not read", async () => {
    api.get.mockResolvedValue({ ok: true, data: { ...query, attachment_reading: [{ filename: "query.pdf", pages_read: 5, page_count: 12, line: "query.pdf: pages 1 to 5 of 12 read; pages 6 to 12 were not read." }], evidence_job: { id: "j1", state: "running", progress_done: 3, progress_total: 20, label: "searching contract 4 of 20", error: null } } });
    render(<TechnicalQueriesView />);
    expect((await screen.findByTestId("evidence-progress")).textContent).toContain("searching contract 4 of 20 (3 of 20)");
    expect(screen.getByTestId("attachment-reading").textContent).toBe("query.pdf: pages 1 to 5 of 12 read; pages 6 to 12 were not read.");
  });

  it("has no send button, and Claude gets only the documents the engineer ticks", async () => {
    api.get.mockResolvedValue({ ok: true, data: { ...query, status: "approved", confirmed_question: "What applies?", evidence: [{ id: "e1", document_id: "contract-1", page_start: 1, exact_quote: "x", evidence_state: "verified", supersession_state: "current" }] } });
    api.generateDraft.mockResolvedValue({ ok: true, data: query });
    render(<TechnicalQueriesView />);
    await screen.findByText("Coating question", { selector: "h2" });
    expect(screen.queryByText("Send approved response")).toBeNull();
    expect(screen.getByText(/Sending is not approved by the owner/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Written by"), { target: { value: "claude" } });
    fireEvent.click(screen.getByLabelText("contract-1"));
    fireEvent.click(screen.getByText("Generate draft"));
    await waitFor(() => expect(api.generateDraft).toHaveBeenCalledWith("q1", "claude", ["contract-1"]));
  });

  it("shows the server's refusal when Claude is chosen for the draft", async () => {
    api.get.mockResolvedValue({ ok: true, data: { ...query, confirmed_question: "What applies?" } });
    render(<TechnicalQueriesView />);
    await screen.findByText("Coating question", { selector: "h2" });
    fireEvent.change(screen.getByLabelText("Written by"), { target: { value: "claude" } });
    fireEvent.click(screen.getByText("Generate draft"));
    await waitFor(() => expect(api.generateDraft).toHaveBeenCalledWith("q1", "claude", []));
    expect((await screen.findByRole("alert")).textContent).toContain("not enabled on this server");
  });

  it("finishes the Gmail connection from the app's own return page, clears the address bar and says the admin line", async () => {
    api.completeGmail.mockResolvedValue({ ok: true, data: { result: "admin_must_allow", mailbox_id: null } });
    window.history.replaceState(null, "", "/technicalQueries/gmail-return?code=one-time&state=abc");
    render(<TechnicalQueriesView queryId="gmail-return" />);
    await waitFor(() => expect(api.completeGmail).toHaveBeenCalledWith({ code: "one-time", state: "abc", error: null }));
    expect(window.location.search).toBe("");
    expect(window.location.pathname).toBe("/technicalQueries");
    expect((await screen.findByRole("alert")).textContent).toBe("Your company's Google admin must allow this app.");
  });

  it("posts the Gmail return once even when the effect runs twice (React StrictMode, as on the dev build)", async () => {
    api.completeGmail.mockClear();
    api.completeGmail.mockResolvedValue({ ok: true, data: { result: "connected", mailbox_id: "mb" } });
    window.history.replaceState(null, "", "/technicalQueries/gmail-return?code=one-time&state=abc");
    render(<StrictMode><TechnicalQueriesView queryId="gmail-return" /></StrictMode>);
    await waitFor(() => expect(api.completeGmail).toHaveBeenCalled());
    expect(api.completeGmail).toHaveBeenCalledTimes(1);
    expect(api.completeGmail).toHaveBeenCalledWith({ code: "one-time", state: "abc", error: null });
    await screen.findByText("Gmail is connected. Choose the label to import below.");
    expect(screen.queryByText(/requires code and state/)).toBeNull();
  });

  it("says an unfiled mailbox attachment is kept out of the library and files it only when the engineer chooses a role", async () => {
    const withFile = { ...query, messages: [{ id: "m1", from_address: "a@b.example", to_addresses: [], cc_addresses: [], sent_at: null, received_at: "x", subject: "s", body: "b", raw_message_hash: null, attachments: [{ id: "a1", filename: "query.pdf", size_bytes: 10, document_id: "d1", filed_at: null, scan_status: "static_check_clean", parse_status: "ready" }] }] };
    api.get.mockResolvedValue({ ok: true, data: withFile });
    api.fileIntoLibrary.mockResolvedValue({ ok: true, data: { ...withFile, messages: [{ ...withFile.messages[0], attachments: [{ ...withFile.messages[0].attachments[0], filed_at: "2026-11-26T00:00:00Z" }] }] } });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<TechnicalQueriesView />);
    expect((await screen.findByTestId("attachment-unfiled")).textContent).toContain("kept out of the library");
    fireEvent.change(screen.getByLabelText("Role to file this attachment under"), { target: { value: "SPECIFICATION" } });
    fireEvent.click(screen.getByText("File into the library"));
    await waitFor(() => expect(api.fileIntoLibrary).toHaveBeenCalledWith("q1", "a1", "SPECIFICATION"));
    await waitFor(() => expect(screen.queryByTestId("attachment-unfiled")).toBeNull());
  });

  it("creates a query by hand with its papers, with no mailbox", async () => {
    api.createByHand.mockResolvedValue({ ok: true, data: { item: { ...query, id: "q2", subject: "By hand" }, uploaded: 1 } });
    render(<TechnicalQueriesView />);
    fireEvent.click(await screen.findByText("New query by hand / upload"));
    fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "By hand" } });
    fireEvent.change(screen.getByLabelText("The question, as asked"), { target: { value: "Is it allowed?" } });
    fireEvent.click(screen.getByText("Create query"));
    await waitFor(() => expect(api.createByHand).toHaveBeenCalledTimes(1));
    const form = api.createByHand.mock.calls[0][0] as FormData;
    expect(form.get("subject")).toBe("By hand");
    expect(form.get("body")).toBe("Is it allowed?");
  });
});
