/**
 * The query list page, tidied (owner, 27 Nov 2026: the same pattern as a tidy product list): the mailbox in one chip with its details one
 * click away, a count line that is also a filter, one toolbar, and each query in one or two lines with short chips. Invented values only.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TechnicalQueriesView } from "./TechnicalQueriesView";
import { agoWords, countLine, mailboxChip, problemChips, queryTag, quickMatch, statusChip } from "./technicalQueryQuestion";

const base = { contractor_name: null, department: null, assignee_user_id: null, priority: "normal", received_at: "2026-01-01T00:00:00Z", due_at: null, can_review: true, messages: [], evidence: [] };
const rows = [
  { ...base, id: "q1", subject: "S1", ref_type: "CFC", ref_number: "7", discipline_code: "PRO", title_short: "Invented coating question", status: "awaiting_review", needs_person: 0 },
  { ...base, id: "q2", subject: "S2", ref_type: "TQ", ref_number: "00012", discipline_code: "PIP", title_short: "Invented valve question", status: "drafting", needs_person: 0, contractor_name: "Invented Builders", assignee_user_id: "u2", due_at: "2026-12-03T00:00:00Z" },
  { ...base, id: "q3", subject: "Please advise", ref_type: null, ref_number: null, discipline_code: null, title_short: null, status: "drafting", needs_person: 1 },
];
const ago = (min: number) => new Date(Date.now() - min * 60000).toISOString();
const mailbox = { id: "mb1", email: "queries@example.com", connection_state: "active", label_id: "L1", last_checked_at: ago(4),
  import_job: { id: "j1", kind: "import", state: "done", total: 77, done: 77, imported: 33, failed: 0, failures: [], error: null } };

const api = vi.hoisted(() => ({
  saveQuestion: vi.fn(), classifyEvidence: vi.fn(), decide: vi.fn(), list: vi.fn(), get: vi.fn(), metrics: vi.fn(), mailboxes: vi.fn(),
  assignees: vi.fn(), routingRules: vi.fn(), generateDraft: vi.fn(), createByHand: vi.fn(), completeGmail: vi.fn(), fileIntoLibrary: vi.fn(),
  gmailLabels: vi.fn(), activateGmailLabel: vi.fn(), checkNow: vi.fn(), importAgain: vi.fn(), prepareAllPlan: vi.fn(), prepareAllStart: vi.fn(),
}));
const cls = vi.hoisted(() => ({ ofDocument: vi.fn(), confirm: vi.fn() }));
vi.mock("../api/client", () => ({ technicalQueriesApi: api, classification: cls }));

describe("the query list page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.list.mockResolvedValue({ ok: true, data: { items: rows } });
    api.get.mockResolvedValue({ ok: true, data: rows[0] });
    api.metrics.mockResolvedValue({ ok: true, data: { total: 3 } });
    api.mailboxes.mockResolvedValue({ ok: true, data: { items: [mailbox] } });
    api.assignees.mockResolvedValue({ ok: true, data: { items: [{ id: "u2", display_name: "Invented Engineer" }] } });
    api.routingRules.mockResolvedValue({ ok: true, data: { items: [] } });
  });

  it("shows the mailbox as one small chip; the address, the counts and the import buttons only after a click", async () => {
    render(<TechnicalQueriesView />);
    const chip = await screen.findByTestId("mailbox-chip");
    expect(chip.textContent).toBe("Mailbox connected · checked 4 min ago");
    expect(screen.queryByText("queries@example.com", { exact: false })).toBeNull();
    expect(screen.queryByText("Check now")).toBeNull();
    expect(screen.queryByText(/77 messages/)).toBeNull();
    fireEvent.click(chip);
    const panel = screen.getByTestId("mailbox-panel");
    expect(panel.textContent).toContain("queries@example.com");
    expect(within(panel).getByText("Check now")).toBeTruthy();
    expect(within(panel).getByText("Import the label again")).toBeTruthy();
  });

  it("has a count line that is also a filter, with only the states that exist now", async () => {
    render(<TechnicalQueriesView />);
    const line = await screen.findByTestId("count-line");
    // the status parts add up to the total; the one needing a person is said "of them", never added (owner's live walk, 27 Nov 2026)
    expect(line.textContent).toBe("3 queries: 1 waiting for approval, 2 in progress. 1 of them needs a person");
    fireEvent.click(within(line).getByRole("button", { name: "1 waiting for approval" }));
    const list = screen.getByLabelText("Technical query list");
    expect(within(list).getAllByRole("button").length).toBe(1);
    expect(within(list).getByText("Invented coating question")).toBeTruthy();
    fireEvent.click(within(screen.getByTestId("count-line")).getByRole("button", { name: "show all" }));
    expect(within(list).getAllByRole("button").length).toBe(3);
  });

  it("puts New query, Filters and More in one toolbar, with finding the sources for all inside More", async () => {
    render(<TechnicalQueriesView />);
    const bar = await screen.findByRole("toolbar", { name: "Query actions" });
    await waitFor(() => expect(within(bar).getByTestId("more-menu")).toBeTruthy());
    expect(within(bar).getAllByRole("button").filter((b) => !b.closest('[data-testid="more-menu"]')).map((b) => b.textContent)).toEqual(["New query", "Filters"]);
    const more = within(bar).getByTestId("more-menu");
    expect(within(more).getByText("More")).toBeTruthy();
    expect(within(more).getByText("Find the sources for every query not prepared yet")).toBeTruthy();
    expect(within(more).getByText(/Rules for who it goes to/)).toBeTruthy();
  });

  it("gives each query one or two lines: tag, discipline, short title, a status chip, who has it, the due date and short problem chips", async () => {
    render(<TechnicalQueriesView />);
    const list = screen.getByLabelText("Technical query list");
    await waitFor(() => expect(within(list).getAllByRole("button").length).toBe(3));
    const [first, second, third] = within(list).getAllByRole("button");
    expect(within(first).getByTestId("query-tag").textContent).toBe("CFC-7");
    expect(within(first).getByTestId("status-chip").textContent).toBe("Waiting for approval");
    expect(within(second).getByTestId("query-tag").textContent).toBe("TQ-00012"); // the number as written (review of #1938)
    expect(second.textContent).toContain("Invented Builders · Invented Engineer");
    expect(second.textContent).toContain("due 3 Dec 2026");
    expect(within(second).queryAllByTestId("problem-chip")).toEqual([]);
    expect(within(third).queryByTestId("query-tag")).toBeNull();
    expect(within(third).getAllByTestId("problem-chip").map((c) => c.getAttribute("data-words"))).toEqual(["No query number", "No contractor"]);
    expect(within(third).getAllByTestId("problem-chip")[0].getAttribute("title")).toContain("no full TQ or CFC number");
    // the full sentence is in the row's own text for a screen reader and a keyboard user, not only on hover (review of #1938)
    expect(third.textContent).toContain("No query number: The subject has no full TQ or CFC number");
    for (const row of [first, second, third]) expect(row.textContent).not.toMatch(/_|awaiting_review|drafting/);
  });

  it("clicking 'approved' lists only rows chipped Approved", async () => {
    api.list.mockResolvedValue({ ok: true, data: { items: [{ ...rows[0], status: "approved" }, { ...rows[1], status: "sent" }] } });
    render(<TechnicalQueriesView />);
    const line = await screen.findByTestId("count-line");
    expect(line.textContent).toBe("2 queries: 1 approved, 1 sent");
    fireEvent.click(within(line).getByRole("button", { name: "1 approved" }));
    expect(within(screen.getByLabelText("Technical query list")).getAllByTestId("status-chip").map((c) => c.textContent)).toEqual(["Approved"]);
  });

  it("says a row's problems in full inside the query too", async () => {
    api.get.mockResolvedValue({ ok: true, data: rows[2] });
    api.list.mockResolvedValue({ ok: true, data: { items: [rows[2]] } });
    render(<TechnicalQueriesView />);
    const problems = await screen.findAllByTestId("query-problem");
    expect(problems.map((p) => p.textContent)).toEqual([
      "No query number. The subject has no full TQ or CFC number, so a person must check which query this is.",
      "No contractor. No contractor yet: add its code once under \u201cRules for who it goes to\u201d (in More) and every query with that code fills itself.",
    ]);
  });

  it("puts the count line's filter in the address and reads it back (F's walk, 27 Nov 2026)", async () => {
    window.history.replaceState(null, "", "/technicalQueries?show=person");
    render(<TechnicalQueriesView />);
    const list = screen.getByLabelText("Technical query list");
    await waitFor(() => expect(within(list).getAllByRole("button").length).toBe(1)); // read back: only the one needing a person
    fireEvent.click(within(await screen.findByTestId("count-line")).getByRole("button", { name: "show all" }));
    expect(window.location.search).toBe("");
    fireEvent.click(within(screen.getByTestId("count-line")).getByRole("button", { name: "1 waiting for approval" }));
    expect(window.location.search).toBe("?show=waiting");
    window.history.replaceState(null, "", "/");
  });

  it("opens the first match when the open query is not among a filter's matches (F's walk, 27 Nov 2026)", async () => {
    api.get.mockImplementation((id: string) => Promise.resolve({ ok: true, data: rows.find((r) => r.id === id) }));
    render(<TechnicalQueriesView />);
    expect(await screen.findByText(rows[0].subject, { selector: "h2" })).toBeTruthy(); // the first query opens on arrival
    fireEvent.click(within(await screen.findByTestId("count-line")).getByRole("button", { name: "1 of them needs a person" }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith("q3"));
    expect(await screen.findByText("Please advise", { selector: "h2" })).toBeTruthy();
  });

  it("says a stopped mailbox in red on the chip", async () => {
    api.mailboxes.mockResolvedValue({ ok: true, data: { items: [{ ...mailbox, connection_state: "error", status_note: "Gmail could not be read." }] } });
    render(<TechnicalQueriesView />);
    expect((await screen.findByTestId("mailbox-chip")).textContent).toBe("Mailbox problem");
  });
});

describe("the list page's words", () => {
  it("tags a query by its short number", () => {
    expect(queryTag({ ref_type: "TQ", ref_number: "00012" })).toBe("TQ-00012"); // kept as written: CFC-7 and CFC-007 are not one query
    expect(queryTag({ ref_type: "CFC", ref_number: "7" })).toBe("CFC-7");
    expect(queryTag({ ref_type: null, ref_number: null })).toBeNull();
  });
  it("puts every status in one of a few plain chips", () => {
    expect(statusChip("awaiting_review").words).toBe("Waiting for approval");
    for (const s of ["received", "triage", "drafting", "changes_requested", "some_new_state"]) expect(statusChip(s).words).toBe("In progress");
    expect(statusChip("approved").words).toBe("Approved");
    expect(statusChip("resolved").words).toBe("Closed");
  });
  it("says the problems short, the sentence kept for hover", () => {
    expect(problemChips({ needs_person: 0, ref_type: "TQ", contractor_name: "X" })).toEqual([]);
    expect(problemChips({ needs_person: 1, ref_type: "TQ", contractor_name: "X" }).map((p) => p.words)).toEqual(["No query number"]);
  });
  it("says how long ago the mailbox was checked", () => {
    const now = Date.parse("2026-11-27T10:00:00Z");
    expect(agoWords("2026-11-27T09:56:00Z", now)).toBe("4 min ago");
    expect(agoWords("2026-11-27T07:00:00Z", now)).toBe("3 h ago");
    expect(agoWords("2026-11-27T09:59:50Z", now)).toBe("just now");
    expect(agoWords(null, now)).toBeNull();
  });
  it("chooses the mailbox chip by its state", () => {
    expect(mailboxChip([], true)?.words).toBe("No mailbox connected");
    expect(mailboxChip([], false)).toBeNull();
    expect(mailboxChip([{ connection_state: "pending" }], true)?.words).toBe("Mailbox needs a label");
    expect(mailboxChip([{ connection_state: "active", import_job: { state: "running", kind: "import", done: 12, total: 77 } }], true)?.words).toBe("Mailbox: importing, 12 of 77 read");
    expect(mailboxChip([{ connection_state: "active", import_job: { state: "failed", kind: "import", done: 1, total: 77, error: "x" } }], true)?.tone).toBe("problem");
  });
  it("puts each row in the bucket whose word its chip says, never 'approved' for a sent one (review of #1938)", () => {
    const rows = ["approved", "send_pending", "sent", "awaiting_confirmation", "resolved", "duplicate", "cancelled", "drafting"].map((status) => ({ status, ref_type: "TQ" }));
    expect(countLine(rows).parts.map((p) => `${p.n} ${p.words}`)).toEqual(["1 in progress", "1 approved", "3 sent", "3 closed"]);
    for (const view of ["waiting", "progress", "approved", "sent", "closed"] as const) {
      const words = rows.filter((r) => quickMatch(view, r)).map((r) => statusChip(r.status).words);
      expect(new Set(words).size).toBeLessThanOrEqual(view === "closed" ? 3 : 1);
    }
    expect(rows.filter((r) => quickMatch("approved", r)).map((r) => statusChip(r.status).words)).toEqual(["Approved"]);
  });
  it("adds up: every status lands in exactly one part, and the parts sum to the total (owner's live walk, 27 Nov 2026)", () => {
    const statuses = ["received", "triage", "drafting", "awaiting_review", "changes_requested", "approved", "send_pending", "sent", "awaiting_confirmation", "resolved", "duplicate", "cancelled", "failed", "some_new_state"];
    const rows = statuses.flatMap((status) => [{ status, ref_type: "TQ", needs_person: 0 }, { status, ref_type: null, needs_person: 1 }]);
    const line = countLine(rows);
    expect(line.parts.reduce((sum, p) => sum + p.n, 0)).toBe(line.total);
    for (const r of rows) expect(line.parts.filter((p) => quickMatch(p.view, r)).length).toBe(1);
    expect(line.ofThem).toEqual({ view: "person", n: statuses.length, words: "need a person" });
  });
  it("counts only the states that exist", () => {
    expect(countLine([]).parts).toEqual([]);
    expect(countLine([{ status: "approved", ref_type: "TQ" }]).parts.map((p) => `${p.n} ${p.words}`)).toEqual(["1 approved"]);
    expect(quickMatch("person", { status: "drafting", needs_person: 0, ref_type: null })).toBe(true);
  });
});
