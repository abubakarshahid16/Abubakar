/** The owner's TEST copy of a query's draft (owner, 26 Nov 2026 23:14 PKT): "Allow test sending" on a connected mailbox while the switch is
 *  on, and "Send me a test copy" on a query whose own mailbox may receive it. The server decides the address; the page never asks for one. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TechnicalQueriesView } from "./TechnicalQueriesView";

const draft = { id: "dr1", version: 1, answer: "Class 300 applies [S1].", citations_json: "[]", model: "local-model", system: true };
const query = {
  id: "q1", subject: "Flange question", contractor_name: null, department: null, assignee_user_id: null, extracted_question: "Which class?",
  proposed_question: "Which class?", proposed_questions: [], evidence_coverage: null, status: "awaiting_review", priority: "normal",
  received_at: "2026-01-01T00:00:00Z", due_at: null, can_review: true, messages: [], evidence: [], drafts: [draft],
  test_send: { ready: true, to: "queries@example.test", why: null },
};
const mailbox = { id: "mb", email: "queries@example.test", connection_state: "active", label_id: "L1", last_checked_at: null, import_job: null };

const api = vi.hoisted(() => ({
  saveQuestion: vi.fn(), classifyEvidence: vi.fn(), list: vi.fn(), get: vi.fn(), metrics: vi.fn(), mailboxes: vi.fn(), assignees: vi.fn(),
  routingRules: vi.fn(), generateDraft: vi.fn(), createByHand: vi.fn(), completeGmail: vi.fn(), fileIntoLibrary: vi.fn(), gmailLabels: vi.fn(),
  activateGmailLabel: vi.fn(), checkNow: vi.fn(), importAgain: vi.fn(), prepareAllPlan: vi.fn(), prepareAllStart: vi.fn(), startGmail: vi.fn(),
  testSend: vi.fn(), decide: vi.fn(),
}));
const cls = vi.hoisted(() => ({ ofDocument: vi.fn(), confirm: vi.fn() }));
vi.mock("../api/client", () => ({ technicalQueriesApi: api, classification: cls }));

describe("the owner's test copy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.list.mockResolvedValue({ ok: true, data: { items: [query] } });
    api.get.mockResolvedValue({ ok: true, data: query });
    api.metrics.mockResolvedValue({ ok: true, data: { total: 1 } });
    api.mailboxes.mockResolvedValue({ ok: false, error: { message: "no" } });
    api.assignees.mockResolvedValue({ ok: false, error: { message: "no" } });
    api.routingRules.mockResolvedValue({ ok: false, error: { message: "no" } });
    api.prepareAllPlan.mockResolvedValue({ ok: false, error: { message: "no" } });
  });

  it("sends a test copy of the latest draft and says it went only to the query's own mailbox", async () => {
    api.testSend.mockResolvedValue({ ok: true, data: { sent_to: "queries@example.test", at: "2026-11-26T18:30:00Z" } });
    render(<TechnicalQueriesView />);
    fireEvent.click(await screen.findByTestId("test-send"));
    await waitFor(() => expect(api.testSend).toHaveBeenCalledWith("q1", "dr1"));  // no address: the server decides it
    expect((await screen.findByTestId("test-sent")).textContent).toBe("A test copy was sent to queries@example.test only. Nothing went to the contractor.");
  });

  it("shows no test-copy button while the query's mailbox may not receive one", async () => {
    api.get.mockResolvedValue({ ok: true, data: { ...query, test_send: { ready: false, to: null, why: "test sending is switched off" } } });
    api.list.mockResolvedValue({ ok: true, data: { items: [{ ...query, test_send: { ready: false, to: null, why: "x" } }] } });
    render(<TechnicalQueriesView />);
    await screen.findAllByText("Flange question");
    expect(screen.queryByTestId("test-send")).toBeNull();
  });

  it("offers 'Allow test sending' on a connected mailbox only while the switch is on, and says when it is allowed", async () => {
    api.mailboxes.mockResolvedValue({ ok: true, data: { items: [{ ...mailbox, test_send_enabled: true, test_send_granted_at: null }] } });
    api.startGmail.mockResolvedValue({ ok: false, error: { message: "stop here" } });
    const first = render(<TechnicalQueriesView />);
    fireEvent.click(await screen.findByTestId("allow-test-send"));
    await waitFor(() => expect(api.startGmail).toHaveBeenCalledWith("test_send"));
    first.unmount();
    api.mailboxes.mockResolvedValue({ ok: true, data: { items: [{ ...mailbox, test_send_enabled: true, test_send_granted_at: "2026-11-26T18:00:00Z" }] } });
    const second = render(<TechnicalQueriesView />);
    expect((await screen.findByTestId("test-send-allowed")).textContent).toContain("queries@example.test), and only to it");
    second.unmount();
    api.mailboxes.mockResolvedValue({ ok: true, data: { items: [{ ...mailbox, test_send_enabled: false }] } });
    render(<TechnicalQueriesView />);
    await screen.findByTestId("mailbox-status");
    expect(screen.queryByTestId("allow-test-send")).toBeNull();
  });
});
