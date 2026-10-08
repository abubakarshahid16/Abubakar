/**
 * Chat redesign PR 5 (owner order 2026-09-26): what a reader does with an answer.
 *
 *  - "Was this right?" is sent, shown as chosen, and put back if not saved.
 *  - "Add to comment sheet" files the text on screen, says where it went,
 *    and offers Undo only while the server allows it. A draft naming no
 *    document offers no button at all.
 *  - "@ a document" sends exactly the documents picked, and nothing when
 *    none are.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import type { Health } from "../api/client";
import type { Conversation, Message } from "../types/api";

const health: Health = {
  ok: true, embed_model_present: true, answer_model_present: true,
  ingestion: { alive: true, stalled: false, busy: false },
};

const conversation: Conversation = {
  id: "conv_1", title: "Hydrotest requirements", document_id: null, message_count: 2,
  created_at: "2026-09-26T00:00:00Z", updated_at: "2026-09-26T00:00:00Z",
};

const question: Message = {
  id: "u_1", conversation_id: "conv_1", ordinal: 1, role: "user", text: "write that as a comment",
  resolved_question: "write that as a comment", carried_terms: [], answer_type: null, reason: null,
  explains_id: null, payload: null, created_at: "2026-09-26T00:00:00Z",
};

function draft(over: Partial<Message> = {}): Message {
  return {
    id: "a_1", conversation_id: "conv_1", ordinal: 2, role: "assistant",
    text: "Please state the chloride limit.", resolved_question: null, carried_terms: [],
    answer_type: "general", reason: null, explains_id: null, payload: { passages: [] },
    created_at: "2026-09-26T00:00:00Z", answer_kind: "action",
    used_line: "Drafted from the previous answer · 2 s", verification: null, steps: [], sources: [],
    suggestions: [], notices: [],
    draft: { type: "comment", text: "Please state the chloride limit.", status: "draft", source_ids: ["doc_ds"] },
    ...over,
  };
}

function general(over: Partial<Message> = {}): Message {
  return draft({
    id: "a_2", answer_kind: "general", draft: null, text: "Sulfidation is sulfur attack on steel.",
    used_line: "General knowledge, not from your documents · Claude · 3 s", ...over,
  });
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

interface Call { url: string; method: string; body: any }

function mockApi({
  messages = [question, draft()],
  filed = {
    finding_id: "f_1", message_id: "a_1", document_id: "doc_ds", document_name: "Sample datasheet",
    review_run_id: "run_1", chat_comments_on_sheet: 1,
    undo_until: new Date(Date.now() + 300_000).toISOString(),
  } as unknown,
  feedbackStatus = 200,
  stream,
}: {
  messages?: Message[];
  filed?: unknown;
  feedbackStatus?: number;
  stream?: string;
} = {}) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const call = { url, method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : null };
    calls.push(call);
    if (url.includes("/health")) return Promise.resolve(json(health));
    if (url.includes("/chat/models")) {
      return Promise.resolve(json({ default: "claude", models: [
        { id: "claude", label: "Claude", model: "m", available: true, reason: null },
        { id: "local", label: "Local model", model: "l", available: true, reason: null }] }));
    }
    if (url.includes("/feedback")) {
      return Promise.resolve(json(feedbackStatus === 200
        ? { message_id: "a_1", helpful: call.body.helpful, note: null }
        : { code: "internal", message: "no" }, feedbackStatus));
    }
    if (url.includes("/comment") && call.method === "POST") return Promise.resolve(json(filed));
    if (url.includes("/comment/") && call.method === "DELETE") return Promise.resolve(json({ finding_id: "f_1", withdrawn: true }));
    if (url.includes("/documents?limit=50")) {
      return Promise.resolve(json([
        { id: "doc_ds", filename: "sample-datasheet.pdf" },
        { id: "doc_std", filename: "sample-standard.pdf" },
      ]));
    }
    if (url.endsWith("/ask/stream")) {
      return Promise.resolve(new Response(stream ?? "", { status: 200, headers: { "Content-Type": "text/event-stream" } }));
    }
    if (url.includes("/conversations/")) return Promise.resolve(json({ conversation, messages }));
    if (url.includes("/conversations")) {
      if (call.method === "POST") return Promise.resolve(json(conversation));
      return Promise.resolve(json({ total: 1, limit: 50, offset: 0, conversations: [conversation] }));
    }
    return Promise.resolve(json([]));
  }));
  return calls;
}

async function openConversation() {
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: /^Chat/ }));
  const recent = await screen.findByRole("region", { name: "Recent chats" });
  await userEvent.click(within(recent).getByRole("button", { name: "Hydrotest requirements" }));
}

afterEach(() => vi.unstubAllGlobals());

// ---------------------------------------------------------------- feedback

describe("was this right?", () => {
  it("sends the reader's answer and shows it as chosen", async () => {
    const calls = mockApi({ messages: [question, general()] });
    await openConversation();
    const group = await screen.findByRole("group", { name: "Was this right?" });
    await userEvent.click(within(group).getByRole("button", { name: "No" }));
    await waitFor(() =>
      expect(calls.find((c) => c.url.endsWith("/conversations/conv_1/messages/a_2/feedback"))?.body)
        .toEqual({ helpful: false }));
    expect(within(group).getByRole("button", { name: "No" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows a reopened chat's earlier answer", async () => {
    mockApi({ messages: [question, general({ feedback: true })] });
    await openConversation();
    const group = await screen.findByRole("group", { name: "Was this right?" });
    expect(within(group).getByRole("button", { name: "Yes" })).toHaveAttribute("aria-pressed", "true");
  });

  it("puts the choice back and says so when it was not saved", async () => {
    mockApi({ messages: [question, general()], feedbackStatus: 500 });
    await openConversation();
    const group = await screen.findByRole("group", { name: "Was this right?" });
    await userEvent.click(within(group).getByRole("button", { name: "Yes" }));
    expect(await screen.findByText("That was not saved. Try again.")).toBeInTheDocument();
    expect(within(group).getByRole("button", { name: "Yes" })).toHaveAttribute("aria-pressed", "false");
  });
});

// ------------------------------------------------------ add to comment sheet

describe("add to comment sheet", () => {
  it("files the text on screen, says where it went, and can be undone", async () => {
    const calls = mockApi();
    await openConversation();
    const card = await screen.findByRole("region", { name: "Draft comment" });
    await userEvent.click(within(card).getByRole("button", { name: "Edit" }));
    const box = within(card).getByLabelText("Draft comment text");
    await userEvent.type(box, " Thanks.");
    await userEvent.click(within(card).getByRole("button", { name: "Add to comment sheet" }));

    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/messages/a_1/comment"))?.body)
        .toEqual({ text: "Please state the chloride limit. Thanks." }));
    expect(await within(card).findByText(/Added to the comment sheet for Sample datasheet, under your name\./)).toBeInTheDocument();
    // filed: no second button, no more editing
    expect(within(card).queryByRole("button", { name: "Add to comment sheet" })).toBeNull();
    expect(within(card).queryByRole("button", { name: "Edit" })).toBeNull();

    await userEvent.click(within(card).getByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "DELETE" && c.url.endsWith("/messages/a_1/comment/f_1"))).toBe(true));
    expect(await within(card).findByText(/Withdrawn\. It is no longer on the comment sheet\./)).toBeInTheDocument();
  });

  it("says plainly when the document has no review run, so no sheet yet", async () => {
    mockApi({ filed: {
      finding_id: "f_1", message_id: "a_1", document_id: "doc_ds", document_name: "Sample datasheet",
      review_run_id: null, chat_comments_on_sheet: 0, undo_until: new Date(Date.now() + 300_000).toISOString(),
    } });
    await openConversation();
    const card = await screen.findByRole("region", { name: "Draft comment" });
    await userEvent.click(within(card).getByRole("button", { name: "Add to comment sheet" }));
    expect(await within(card).findByText(/it is on no comment sheet until one is run/)).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Open review" })).toBeNull();
  });

  it("offers no Undo once the server's window has closed", async () => {
    mockApi({ filed: {
      finding_id: "f_1", message_id: "a_1", document_id: "doc_ds", document_name: "Sample datasheet",
      review_run_id: "run_1", chat_comments_on_sheet: 1, undo_until: new Date(Date.now() - 1000).toISOString(),
    } });
    await openConversation();
    const card = await screen.findByRole("region", { name: "Draft comment" });
    await userEvent.click(within(card).getByRole("button", { name: "Add to comment sheet" }));
    await within(card).findByText(/Added to the comment sheet/);
    expect(within(card).queryByRole("button", { name: "Undo" })).toBeNull();
  });

  it("offers no button for a draft that names no document", async () => {
    mockApi({ messages: [question, draft({ draft: { type: "comment", text: "x", status: "draft", source_ids: [] } })] });
    await openConversation();
    const card = await screen.findByRole("region", { name: "Draft comment" });
    expect(within(card).queryByRole("button", { name: "Add to comment sheet" })).toBeNull();
    expect(within(card).getByText(/names no document it could be filed on/)).toBeInTheDocument();
  });

  it("does not offer to file again what a reopened chat already filed", async () => {
    mockApi({ messages: [question, draft({ filed_comment: { finding_id: "f_1", document_id: "doc_ds", filed_at: "2026-09-26T00:00:00Z" } })] });
    await openConversation();
    const card = await screen.findByRole("region", { name: "Draft comment" });
    expect(within(card).getByText(/Added to the comment sheet earlier/)).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Add to comment sheet" })).toBeNull();
  });
});

// ------------------------------------------------------------ @ a document

describe("@ a document", () => {
  it("sends exactly the documents picked, and none once they are removed", async () => {
    const calls = mockApi({ messages: [question, general()] });
    await openConversation();
    await userEvent.click(await screen.findByRole("button", { name: /^@ a document/ }));
    const dialog = await screen.findByRole("dialog", { name: "Choose documents" });
    await userEvent.click(await within(dialog).findByRole("checkbox", { name: "sample-datasheet.pdf" }));
    expect(within(dialog).getByText("Answers come from this document only.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Done" }));

    expect(screen.getByRole("list", { name: "Answering from" })).toHaveTextContent("@sample-datasheet.pdf");
    expect(screen.getByText("Answering from:")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Your question"), "what is the test pressure");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() =>
      expect(calls.filter((c) => c.url.endsWith("/ask/stream")).at(-1)?.body.document_ids).toEqual(["doc_ds"]));

    await userEvent.click(screen.getByRole("button", { name: "Stop answering from sample-datasheet.pdf" }));
    await userEvent.type(screen.getByLabelText("Your question"), "and the standard?");
    await waitFor(() => expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith("/ask/stream"))).toHaveLength(2));
    expect(calls.filter((c) => c.url.endsWith("/ask/stream")).at(-1)?.body).not.toHaveProperty("document_ids");
  });
});
