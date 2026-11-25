import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  mailboxes: vi.fn(),
  gmailLabels: vi.fn(),
  activateGmailLabel: vi.fn(),
  checkNow: vi.fn(),
}));

vi.mock("../api/client", () => ({ technicalQueriesApi: api }));

describe("Technical Queries screen", () => {
  beforeEach(() => {
    api.list.mockResolvedValue({ ok: true, data: { items: [query] } });
    api.get.mockResolvedValue({ ok: true, data: query });
    api.metrics.mockResolvedValue({ ok: true, data: { total: 1 } });
    api.mailboxes.mockResolvedValue({ ok: false, error: { message: "no" } });
    window.confirm = () => { throw new Error("the browser's own confirm box must never be used"); };
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
    const box = within(await screen.findByLabelText("Questions found in the attachment")).getByRole("checkbox");
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
    render(<TechnicalQueriesView />);
    expect((await screen.findByTestId("attachment-unfiled")).textContent).toContain("kept out of the library");
    // the paper opens by the query's own route (the general document route says 404 for an unfiled attachment)
    expect(screen.getByRole("link", { name: "query.pdf" }).getAttribute("href")).toBe("/api/technical-queries/q1/attachments/a1/original");
    fireEvent.change(screen.getByLabelText("Role to file this attachment under"), { target: { value: "SPECIFICATION" } });
    fireEvent.click(screen.getByText("File into the library"));
    expect(api.fileIntoLibrary).not.toHaveBeenCalled(); // asked in the page first
    fireEvent.click(await screen.findByText("Yes, file it"));
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

  it("activates the label with an in-page confirm, saves first, and shows the import progress, the failures by subject and the last check", async () => {
    const pending = { id: "mb", email: "box@example.test", connection_state: "needs_label", label_id: null };
    api.mailboxes.mockResolvedValueOnce({ ok: true, data: { items: [pending] } });
    api.gmailLabels.mockResolvedValue({ ok: true, data: { items: [{ id: "L1", name: "Technical queries", type: "user" }] } });
    api.activateGmailLabel.mockResolvedValue({ ok: true, data: { imported: 0, connection_state: "active", import_job: "j1" } });
    const running = { id: "mb", email: "box@example.test", connection_state: "active", label_id: "L1", last_checked_at: "2026-11-26T01:20:00Z",
      import_job: { id: "j1", kind: "import", state: "running", total: 35, done: 12, failed: 1, error: null, failures: [{ subject: "Invented subject one", reason: "the message could not be imported (ValueError)" }] } };
    api.mailboxes.mockResolvedValue({ ok: true, data: { items: [running] } });
    render(<TechnicalQueriesView />);
    fireEvent.click(await screen.findByText("Choose label"));
    fireEvent.click(await screen.findByText("Activate selected label"));
    expect(api.activateGmailLabel).not.toHaveBeenCalled(); // an in-page question first, never the browser's box
    fireEvent.click(await screen.findByText("Yes, save and start the import"));
    await waitFor(() => expect(api.activateGmailLabel).toHaveBeenCalledWith("mb", "L1"));
    expect((await screen.findByTestId("import-progress")).textContent).toContain("imported 12 of 35, 1 failed");
    expect(screen.getByTestId("import-failures").textContent).toContain("Invented subject one");
    expect(screen.getByTestId("last-checked").textContent).toMatch(/26 Nov 2026, \d{2}:\d{2}( \S+)?/);
  });

  it("has a Check now button that queues one poll", async () => {
    const active = { id: "mb", email: "box@example.test", connection_state: "active", label_id: "L1", last_checked_at: null, import_job: { id: "j", kind: "import", state: "done", total: 3, done: 3, failed: 0, error: null, failures: [] } };
    api.mailboxes.mockResolvedValue({ ok: true, data: { items: [active] } });
    api.checkNow.mockResolvedValue({ ok: true, data: { import_job: "j2" } });
    render(<TechnicalQueriesView />);
    expect((await screen.findByTestId("import-done")).textContent).toContain("imported 3 of 3");
    fireEvent.click(await screen.findByText("Check now"));
    await waitFor(() => expect(api.checkNow).toHaveBeenCalledWith("mb"));
  });

  it("lists type, discipline, number and title, flags a subject with no number, and filters by them", async () => {
    const withRef = { ...query, id: "q1", subject: "PRJ-CON-CO-TQ-12 - PIPING_a_Coating question", ref_type: "TQ", ref_number: "12", discipline_code: "PIPING", title_short: "Coating question", needs_person: 0 };
    const noRef = { ...query, id: "q2", subject: "Please advise", needs_person: 1 };
    api.list.mockResolvedValue({ ok: true, data: { items: [withRef, noRef] } });
    render(<TechnicalQueriesView />);
    expect(await screen.findByText("TQ-12 · PIPING · Coating question")).toBeTruthy();
    expect((await screen.findByTestId("needs-person")).textContent).toContain("no TQ or CFC number");
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "CFC" } });
    fireEvent.change(screen.getByLabelText("Discipline code"), { target: { value: "civil" } });
    fireEvent.change(screen.getByLabelText("Running number"), { target: { value: "7" } });
    fireEvent.click(screen.getByLabelText(/Needs a person/));
    api.list.mockClear();
    fireEvent.click(screen.getByText("Refresh and apply filters"));
    await waitFor(() => expect(api.list).toHaveBeenCalledWith(expect.objectContaining({ ref_type: "CFC", discipline: "civil", number: "7", needs_person: true })));
  });
});
