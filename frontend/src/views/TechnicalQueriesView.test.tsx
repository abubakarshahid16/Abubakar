import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { attachmentsRead, notReadWhy, peopleLine, proposalNoteWords } from "../api/technicalQueries";
import { formatWhen } from "../format/when";
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
  gmailLabels: vi.fn(),
  activateGmailLabel: vi.fn(),
  checkNow: vi.fn(), importAgain: vi.fn(), prepareAllPlan: vi.fn(), prepareAllStart: vi.fn(),
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

  it("shows the clause locator, the key-term count (information only) and the best passage's reranker score, and never says 'not covered'", async () => {
    api.get.mockResolvedValue({ ok: true, data: { ...query,
      evidence_coverage: { searched: 20, of: 20, hits_in: 5, failed: 0, line: "Searched 20 of 20 contracts, hits in 5.", matching_passages: 0, key_terms: 5, top_rerank_score: 0.412 },
      evidence: [{ id: "e1", document_id: "c1", page_start: 4, locator: "6.1 Painting", match_count: 1, match_terms: 5, match_ok: 0, rank_score: 0.412, exact_quote: "x", evidence_state: "proposed", supersession_state: "current" }] } });
    const { container } = render(<TechnicalQueriesView />);
    expect((await screen.findByTestId("evidence-top-score")).textContent).toContain("relevance score");
    expect(screen.getByTestId("evidence-top-score").textContent).toContain("0.412");
    expect(screen.getByText(/Open source, 6\.1 Painting, page 4/)).toBeTruthy();
    expect(screen.getByTestId("evidence-match").textContent).toBe("1 of 5 key terms");
    expect(container.textContent).not.toMatch(/not covered|weak match/i);
  });

  it("says which source each passage comes from: the contract document or the standard, by name (owner, 26 Nov 2026)", async () => {
    api.get.mockResolvedValue({ ok: true, data: { ...query,
      evidence: [
        { id: "e1", document_id: "c1", page_start: 4, locator: "Schedule B, 4.2.1 Invented Lining", source_kind: "contract document", source_name: "ZQ-INVENTED-SCHEDULE-B", exact_quote: "x", evidence_state: "proposed", supersession_state: "current" },
        { id: "e2", document_id: "s1", page_start: 9, locator: "6.1 Invented Coating", source_kind: "company standard", source_name: "ZQ-STD-001", exact_quote: "y", evidence_state: "proposed", supersession_state: "current" },
      ] } });
    render(<TechnicalQueriesView />);
    const sources = (await screen.findAllByTestId("evidence-source")).map((node) => node.textContent);
    expect(sources).toEqual(["ZQ-INVENTED-SCHEDULE-B (contract document) · ", "ZQ-STD-001 (company standard) · "]);
    expect(screen.getByText(/Open source, 6\.1 Invented Coating, page 9/)).toBeTruthy();
  });

  it("tells the engineer that a kept passage counts once its source document is confirmed (F's live check, 26 Nov 2026)", async () => {
    api.get.mockResolvedValue({ ok: true, data: { ...query,
      evidence: [
        { id: "e1", document_id: "c1", page_start: 4, exact_quote: "x", evidence_state: "verified", supersession_state: "unknown" },
        { id: "e2", document_id: "c2", page_start: 5, exact_quote: "y", evidence_state: "verified", supersession_state: "current" },
        { id: "e3", document_id: "c3", page_start: 6, exact_quote: "z", evidence_state: "proposed", supersession_state: "unknown" },
      ] } });
    render(<TechnicalQueriesView />);
    const notes = await screen.findAllByTestId("evidence-needs-confirm");
    expect(notes).toHaveLength(1);  // only the kept passage whose source is not confirmed
    expect(notes[0].textContent).toContain("source document is confirmed");
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
    expect((await screen.findByTestId("import-progress")).textContent).toContain("read 12 of 35 messages, 12 imported, 1 failed");
    expect(screen.getByTestId("import-failures").textContent).toContain("Invented subject one");
    expect(screen.getByTestId("last-checked").textContent).toMatch(/26 Nov 2026, \d{2}:\d{2}( \S+)?/);
  });

  it("says the finished import with every count's boundary: messages, queries, imported, our replies kept apart (first live import said 'imported 77 of 77' for 36)", async () => {
    const job = { id: "j", kind: "import", state: "done", total: 7, done: 7, failed: 0, error: null, failures: [], imported: 3, queries: 2,
      skipped: { "our replies, added to their query (sent by us)": 3, "sent from this mailbox, with no query of its thread or number yet": 1 } };
    api.mailboxes.mockResolvedValue({ ok: true, data: { items: [{ id: "mb", email: "box@example.test", connection_state: "active", label_id: "L1", last_checked_at: null, import_job: job }] } });
    render(<TechnicalQueriesView />);
    expect((await screen.findByTestId("import-done")).textContent).toBe(
      "Import finished: 7 messages in 2 queries: 3 imported, 3 our replies, added to their query (sent by us), 1 sent from this mailbox, with no query of its thread or number yet.",
    );
  });

  it("never says 'imported 77 of 77' for an import that ran before the reasons were counted: it says what is stored", async () => {
    const old = { id: "j", kind: "import", state: "done", total: 77, done: 77, failed: 0, error: null, failures: [], imported: 77, skipped: {}, queries: 33, messages: 36, reasons_recorded: false };
    api.mailboxes.mockResolvedValue({ ok: true, data: { items: [{ id: "mb", email: "box@example.test", connection_state: "active", label_id: "L1", last_checked_at: null, import_job: old }] } });
    render(<TechnicalQueriesView />);
    const said = (await screen.findByTestId("import-done")).textContent;
    expect(said).toBe("Import finished: processed 77 messages; 36 stored as messages of 33 queries; the reason the other 41 were not stored was not recorded for this import (it ran before this was counted).");
    expect(said).not.toMatch(/imported 77/);
  });

  it("hides 'Gmail is connected. Choose the label...' once a label is active (owner's screenshot during the import)", async () => {
    api.completeGmail.mockResolvedValue({ ok: true, data: { result: "connected", mailbox_id: "mb" } });
    api.mailboxes.mockResolvedValue({ ok: true, data: { items: [{ id: "mb", email: "box@example.test", connection_state: "active", label_id: "L1", last_checked_at: null, import_job: null }] } });
    window.history.replaceState(null, "", "/technicalQueries/gmail-return?code=one-time&state=abc");
    render(<TechnicalQueriesView queryId="gmail-return" />);
    await waitFor(() => expect(api.completeGmail).toHaveBeenCalled());
    await screen.findByTestId("mailbox-status");
    expect(screen.queryByText("Gmail is connected. Choose the label to import below.")).toBeNull();
  });

  it("fills the list while the import runs, and never says nothing was imported then", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const running = { id: "mb", email: "box@example.test", connection_state: "active", label_id: "L1", last_checked_at: null,
        import_job: { id: "j", kind: "import", state: "running", total: 77, done: 12, failed: 0, error: null, failures: [], imported: 12 } };
      api.mailboxes.mockResolvedValue({ ok: true, data: { items: [running] } });
      api.list.mockResolvedValue({ ok: true, data: { items: [] } });
      render(<TechnicalQueriesView />);
      expect(await screen.findByText("The import is running: queries appear here as their messages arrive.")).toBeTruthy();
      expect(screen.queryByText("No technical queries have been imported.")).toBeNull();
      api.list.mockClear();
      api.list.mockResolvedValue({ ok: true, data: { items: [{ ...query, id: "q-new", subject: "Arrived during the import" }] } });
      await vi.advanceTimersByTimeAsync(3100);
      await waitFor(() => expect(api.list).toHaveBeenCalled());
      expect(await screen.findByText("Arrived during the import")).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it("folds a long To/Cc list to one count line and says when the question is in the attachment, not the email text (lead-4, 26 Nov 2026)", async () => {
    const people = Array.from({ length: 43 }, (_, n) => `person${n}@invented.example`);
    const message = { id: "m", from_address: "x@example.test", to_addresses: people.slice(0, 3), cc_addresses: people.slice(3), sent_at: null, received_at: "x", subject: "s", body: "b", raw_message_hash: null, attachments: [] };
    const note = "No question in the email text. The question is in the attachment: form.docx; the proposed question below comes from it.";
    api.get.mockResolvedValue({ ok: true, data: { ...query, extracted_question: "From: someone", extracted_question_main: "", email_question_note: note, messages: [message] } });
    render(<TechnicalQueriesView />);
    expect(await screen.findByText(note)).toBeTruthy();
    expect(screen.getAllByTestId("mail-people").map((p) => p.textContent)).toEqual(["To/Cc: 43 people"]);
    expect(screen.queryByText("From: someone")).toBeNull();
    expect(peopleLine(["a@x.example"], ["b@x.example"]).lines).toEqual(["To: a@x.example", "CC: b@x.example"]);
  });

  it("says how many of the query's attachments were read and names each one not read with why (nothing silently missing)", async () => {
    const att = (filename: string, media_type: string, read: boolean) => ({ id: filename, filename, media_type, size_bytes: 1, document_id: read ? "d" : null, scan_status: read ? "static_check_clean" : "pending", parse_status: read ? "ready" : "pending" });
    const message = { id: "m", from_address: "x@example.test", to_addresses: [], cc_addresses: [], sent_at: null, received_at: "x", subject: "s", body: "b", raw_message_hash: null,
      attachments: [att("query.pdf", "application/pdf", true), att("logo.png", "image/png", false), att("answer.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", false), att("calc.xlsm", "application/vnd.ms-excel.sheet.macroenabled.12", false)] };
    api.get.mockResolvedValue({ ok: true, data: { ...query, messages: [message] } });
    render(<TechnicalQueriesView />);
    const box = await screen.findByTestId("attachments-read");
    expect(box.textContent).toContain("1 of 4 attachments read.");
    expect(box.textContent).toContain("logo.png: picture, not read");
    expect(box.textContent).toContain("answer.docx: Word, not read yet");
    expect(box.textContent).toContain("calc.xlsm: macro file, not opened");
    expect(box.textContent).not.toContain("query.pdf");
    expect(attachmentsRead([{ attachments: [att("query.pdf", "application/pdf", true), { ...att("logo1.png", "image/png", false), inline_picture: 1 }, { ...att("logo2.gif", "image/gif", false), inline_picture: 1 }] }])?.line)
      .toBe("1 of 1 attachment read; 2 signature pictures, not attachments");
    expect(notReadWhy({ filename: "old.doc", document_id: null, parse_status: "pending", scan_status: "pending" })).toBe("older Word format (.doc), not read: save it as .docx");
    expect(notReadWhy({ filename: "x.docx", document_id: null, parse_status: "pending", scan_status: "static_check_flagged" })).toBe("Word with active content, its text is not used");
  });

  it("folds a mail's signature and notices behind 'show', and says each attachment's true state (never 'pending upload' for a picture)", async () => {
    const message = { id: "m", from_address: "x@example.test", to_addresses: [], cc_addresses: [], sent_at: null, received_at: "x", subject: "s", raw_message_hash: null,
      body: "Invented question?\n\nBest regards,\nInvented notice", body_main: "Invented question?", body_folded: "Best regards,\nInvented notice",
      attachments: [{ id: "a", filename: "logo.png", media_type: "image/png", size_bytes: 1, document_id: null, scan_status: "pending", parse_status: "pending" }] };
    api.get.mockResolvedValue({ ok: true, data: { ...query, messages: [message] } });
    render(<TechnicalQueriesView />);
    const folded = await screen.findByTestId("mail-folded");
    expect(folded.tagName).toBe("DETAILS");
    expect(folded.hasAttribute("open")).toBe(false);
    expect(folded.textContent).toContain("Invented notice");
    expect(screen.getByTestId("attachment-state").textContent).toBe("not read: picture, not read");
    expect(document.body.textContent).not.toContain("pending upload");
  });

  it("keeps the detail inside the window and brings it into view on a narrow screen when a query is clicked", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const narrow = vi.fn().mockReturnValue({ matches: true });
    Object.defineProperty(window, "matchMedia", { configurable: true, value: narrow });
    api.list.mockResolvedValue({ ok: true, data: { items: [{ ...query, id: "q1", subject: "First" }, { ...query, id: "q2", subject: "Second" }] } });
    render(<TechnicalQueriesView />);
    fireEvent.click(await screen.findByText("Second"));
    await waitFor(() => expect(narrow).toHaveBeenCalledWith("(max-width: 1023px)"));
    expect(scroll.mock.calls.length).toBeGreaterThanOrEqual(2); // the page top on arrival, then the detail
    const region = screen.getByRole("region", { name: "Technical Queries and CFCs" });
    expect(region.className).toContain("minmax(0,1fr)");
  });

  it("marks our own reply in a query's thread 'Sent by us'", async () => {
    const message = (id: string, inbound: number) => ({ id, is_inbound: inbound, from_address: "x@example.test", to_addresses: [], cc_addresses: [], sent_at: null, received_at: "x", subject: "s", body: "b", raw_message_hash: null, attachments: [] });
    api.get.mockResolvedValue({ ok: true, data: { ...query, messages: [message("in", 1), message("ours", 0)] } });
    render(<TechnicalQueriesView />);
    expect((await screen.findAllByTestId("sent-by-us")).length).toBe(1);
  });

  it("imports the label again only after saying what it will do, in the page", async () => {
    const active = { id: "mb", email: "box@example.test", connection_state: "active", label_id: "L1", last_checked_at: null, import_job: { id: "j", kind: "import", state: "done", total: 77, done: 77, failed: 0, error: null, failures: [] } };
    api.mailboxes.mockResolvedValue({ ok: true, data: { items: [active] } });
    api.importAgain.mockResolvedValue({ ok: true, data: { import_job: "j2" } });
    render(<TechnicalQueriesView />);
    fireEvent.click(await screen.findByText("Import the label again"));
    expect(api.importAgain).not.toHaveBeenCalled();
    expect(screen.getByTestId("confirm-import-again").textContent).toContain("reads all 77 messages of the label again and adds only what is not stored yet");
    fireEvent.click(screen.getByText("Yes, read the label again"));
    await waitFor(() => expect(api.importAgain).toHaveBeenCalledWith("mb"));
  });

  it("offers the contractor code in the number first and says 'contractor not set' instead of 'Unknown'", async () => {
    api.routingRules.mockResolvedValue({ ok: true, data: { items: [] } });
    api.list.mockResolvedValue({ ok: true, data: { items: [{ ...query, id: "q1", subject: "Unmapped", contractor_name: null }] } });
    render(<TechnicalQueriesView />);
    expect(await screen.findByText(/contractor not set: add its code under Rules for who it goes to/)).toBeTruthy();
    expect(screen.queryByText(/Unknown contractor/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Filters" }));
    const options = Array.from((screen.getByLabelText("Rule type") as HTMLSelectElement).options).map((o) => o.textContent);
    expect(options[0]).toBe("Contractor code in the number");
    expect(options).toContain("Discipline code");
  });

  it("prepares every unprepared query only after saying how many and how long, then shows how many are left", async () => {
    api.mailboxes.mockResolvedValue({ ok: true, data: { items: [] } });
    api.prepareAllPlan.mockResolvedValue({ ok: true, data: { unprepared: 33, minutes_each: 5, waiting_or_running: 0 } });
    api.prepareAllStart.mockResolvedValue({ ok: true, data: { unprepared: 0, minutes_each: 5, waiting_or_running: 33, queued_now: 33 } });
    render(<TechnicalQueriesView />);
    fireEvent.click(await screen.findByText("Prepare evidence for all unprepared queries"));
    expect((await screen.findByTestId("confirm-prepare-all")).textContent).toContain(
      "33 queries are not prepared yet, or were prepared by older question rules with no confirmed question (their question is proposed again from the attached form): about 5 min each (measured on the last prepared queries), one at a time in the background. Prepared queries and confirmed questions are kept.",
    );
    expect(api.prepareAllStart).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Yes, prepare them"));
    expect((await screen.findByTestId("prepare-all-progress")).textContent).toContain("33 still waiting or running");
  });

  it("has a Check now button that queues one poll", async () => {
    const active = { id: "mb", email: "box@example.test", connection_state: "active", label_id: "L1", last_checked_at: null, import_job: { id: "j", kind: "import", state: "done", total: 3, done: 3, failed: 0, error: null, failures: [] } };
    api.mailboxes.mockResolvedValue({ ok: true, data: { items: [active] } });
    api.checkNow.mockResolvedValue({ ok: true, data: { import_job: "j2" } });
    render(<TechnicalQueriesView />);
    expect((await screen.findByTestId("import-done")).textContent).toBe("Import finished: 3 messages: 3 imported.");
    fireEvent.click(await screen.findByText("Check now"));
    await waitFor(() => expect(api.checkNow).toHaveBeenCalledWith("mb"));
  });

  it("says a waiting import will try again by itself and keeps Check now usable", async () => {
    const waiting = { id: "mb", email: "box@example.test", connection_state: "active", label_id: "L1", last_checked_at: null,
      import_job: { id: "j", kind: "import", state: "queued", total: 0, done: 0, failed: 0, error: "Gmail could not be read just now. It will try again by itself, or use Check now.", failures: [] } };
    api.mailboxes.mockResolvedValue({ ok: true, data: { items: [waiting] } });
    api.checkNow.mockResolvedValue({ ok: true, data: { import_job: "j" } });
    render(<TechnicalQueriesView />);
    expect((await screen.findByRole("alert")).textContent).toContain("try again by itself");
    expect(screen.queryByTestId("import-progress")).toBeNull();
    fireEvent.click(await screen.findByText("Check now"));
    await waitFor(() => expect(api.checkNow).toHaveBeenCalledWith("mb"));
  });

  it("says why a stopped mailbox is not checked, and offers Check now (error) or Connect Gmail again", async () => {
    const stopped = { id: "mb", email: "box@example.test", connection_state: "error", label_id: "L1", last_checked_at: null, status_note: "Gmail could not be read after several tries, so the checking stopped.", import_job: null };
    api.mailboxes.mockResolvedValue({ ok: true, data: { items: [stopped] } });
    api.checkNow.mockResolvedValue({ ok: true, data: { import_job: "j" } });
    render(<TechnicalQueriesView />);
    expect((await screen.findByTestId("mailbox-stopped")).textContent).toContain("is not being checked. Gmail could not be read after several tries");
    fireEvent.click(await screen.findByText("Check now"));
    await waitFor(() => expect(api.checkNow).toHaveBeenCalledWith("mb"));
    expect(screen.getByText("Connect Gmail again")).toBeTruthy();
  });

  it("lists type, discipline, number and title, flags a subject with no number, and filters by them", async () => {
    const withRef = { ...query, id: "q1", subject: "PRJ-CON-CO-TQ-12 - PIPING_a_Coating question", ref_type: "TQ", ref_number: "12", discipline_code: "PIPING", title_short: "Coating question", needs_person: 0 };
    const noRef = { ...query, id: "q2", subject: "Please advise", needs_person: 1 };
    api.list.mockResolvedValue({ ok: true, data: { items: [withRef, noRef] } });
    render(<TechnicalQueriesView />);
    expect(await screen.findByText("TQ-12 · PIPING · Coating question")).toBeTruthy();
    expect((await screen.findByTestId("needs-person")).textContent).toContain("no full TQ or CFC number");
    fireEvent.click(screen.getByRole("button", { name: "Filters" }));
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "CFC" } });
    fireEvent.change(screen.getByLabelText("Discipline code"), { target: { value: "civil" } });
    fireEvent.change(screen.getByLabelText("Running number"), { target: { value: "7" } });
    fireEvent.click(screen.getByLabelText(/Needs a person/));
    api.list.mockClear();
    fireEvent.click(screen.getByText("Refresh and apply filters"));
    await waitFor(() => expect(api.list).toHaveBeenCalledWith(expect.objectContaining({ ref_type: "CFC", discipline: "civil", number: "7", needs_person: true })));
    expect(screen.getByRole("button", { name: "Filters (4 active)" })).toBeTruthy();
  });

  it("folds the filters behind one button, closed on arrival, with no send-only status, and puts the mailbox and the list first", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    api.list.mockResolvedValue({ ok: true, data: { items: [{ ...query, id: "q1", subject: "First query" }] } });
    api.mailboxes.mockResolvedValue({ ok: true, data: { items: [] } });
    render(<TechnicalQueriesView />);
    expect(await screen.findByText("First query")).toBeTruthy();
    expect(scroll).toHaveBeenCalled(); // the page opens at its top
    expect(screen.queryByLabelText("Status")).toBeNull(); // folded: none of the fields shows
    expect(screen.queryByLabelText("Contractor", { selector: "#query-contractor-filter" })).toBeNull();
    const toggle = screen.getByRole("button", { name: "Filters" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    const connect = await screen.findByText("Connect Gmail");
    const list = screen.getByLabelText("Technical query list");
    expect(connect.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy(); // Connect Gmail comes before the list
    expect(toggle.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const options = Array.from((screen.getByLabelText("Status") as HTMLSelectElement).options).map((option) => option.textContent);
    expect(options).toContain("Awaiting review");
    expect(options).not.toContain("Sent");
  });

  it("answer first (E5, 26 Nov 2026): the question, the proposed response and the decisions come first; the email, attachments and evidence are folded", async () => {
    render(<TechnicalQueriesView />);
    const question = await screen.findByRole("heading", { name: "Question for the draft" });
    const response = screen.getByRole("heading", { name: /^Proposed response/ });
    const generate = screen.getByRole("button", { name: "Generate draft" });
    const email = screen.getByTestId("tq-folded-email-question");
    const mail = screen.getByTestId("tq-folded-mail");
    const evidence = screen.getByTestId("tq-folded-evidence");
    const before = (a: Node, b: Node) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    expect([before(question, response), before(response, generate), before(generate, email), before(email, mail), before(mail, evidence)]).toEqual([true, true, true, true, true]);
    for (const part of [email, mail, evidence]) {
      expect(part.tagName).toBe("DETAILS");
      expect((part as HTMLDetailsElement).open).toBe(false);  // folded on arrival
    }
    expect(within(evidence).getByTestId("evidence-coverage")).toBeTruthy();  // the same parts, only folded
  });

  it("says why no question was proposed from the attachment, never silently (lead-4, 26 Nov 2026)", () => {
    expect(proposalNoteWords("none_found", true)).toBe("The AI on this computer found no separate question in the attachment. The proposed question below is the form's own question section, as printed. Check it before you confirm it.");
    expect(proposalNoteWords("not_on_page", false)).toMatch(/not word for word on the page, so none was kept\. Read the attachment text below and write the question\./);
    expect(proposalNoteWords("model_unavailable", false)).toMatch(/^The AI on this computer was not available/);
    expect(proposalNoteWords(null, true)).toBeNull();
  });

  it("shows the mail's received time and the confirmation time with their zone, never the stored UTC text (lead-4, 26 Nov 2026)", async () => {
    const at = "2026-11-20T08:30:00Z";
    const mail = { id: "m1", received_at: at, from_address: "contractor@example.test", to_addresses: [], cc_addresses: [], subject: "Invented", body: "Invented.", attachments: [] };
    api.get.mockResolvedValue({ ok: true, data: { ...query, confirmed_question: "Invented?", confirmed_question_at: at, messages: [mail] } });
    render(<TechnicalQueriesView />);
    expect(await screen.findByText(`Received: ${formatWhen(at)}`)).toBeTruthy();
    expect(screen.getByText(new RegExp(`Confirmed by an engineer on ${formatWhen(at).replace(/[+]/g, "\\+")}`))).toBeTruthy();
    expect(screen.queryByText(new RegExp(at))).toBeNull();
  });
});
