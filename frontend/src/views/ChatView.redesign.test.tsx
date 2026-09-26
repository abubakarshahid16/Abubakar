/**
 * The Chat redesign (owner order 2026-09-26): what the new screen promises.
 *
 *  - Answers stream: real steps, the text as it is written, then the answer.
 *  - Stop stops: the server is told, by turn id, and the turn ends "stopped".
 *  - General knowledge says so and cites nothing, whatever the model wrote.
 *  - A document answer shows how many points were found on the page, and each
 *    superscript opens its source with the exact words marked.
 *  - A draft comment is a draft: an engineer edits it; nothing is filed.
 *  - Model text is never HTML.
 *  - Recent chats live in the navigation; delete asks, then offers Undo.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import type { Health } from "../api/client";
import type { AnswerPassage, Conversation, Message } from "../types/api";

const health: Health = {
  ok: true,
  embed_model_present: true,
  answer_model_present: true,
  ingestion: { alive: true, stalled: false, busy: false },
};

const PASSAGE: AnswerPassage = {
  chunk_id: "doc1:p00005:c00009:aa",
  document_id: "doc_ds",
  filename: "datasheet-sample.pdf",
  page_start: 5,
  page_end: 5,
  section: "Sheet 5",
  text: "Row 9 Hydrostatic test pressure basis per the project pressure standard.",
  highlight: null,
  match_span: null,
  chunks_joined: 1,
  text_source: "extracted",
  ocr_min_conf: null,
  ocr_alphabet_violations: 0,
  ocr_alphabet_sample: null,
  kind: "prose",
  score: 3.2,
  identifier_hits: [],
};

const conversation: Conversation = {
  id: "conv_1",
  title: "Hydrotest requirements",
  document_id: null,
  message_count: 0,
  created_at: "2026-09-26T00:00:00Z",
  updated_at: "2026-09-26T00:00:00Z",
};

function user(text: string, over: Partial<Message> = {}): Message {
  return {
    id: `u_${text.length}`,
    conversation_id: "conv_1",
    ordinal: 1,
    role: "user",
    text,
    resolved_question: text,
    carried_terms: [],
    answer_type: null,
    reason: null,
    explains_id: null,
    payload: null,
    created_at: "2026-09-26T00:00:00Z",
    ...over,
  };
}

function assistant(over: Partial<Message> = {}): Message {
  return {
    id: "a_1",
    conversation_id: "conv_1",
    ordinal: 2,
    role: "assistant",
    text: "**Partly.** The test pressure is covered [S1].",
    resolved_question: null,
    carried_terms: [],
    answer_type: "generated",
    reason: null,
    explains_id: null,
    payload: { passages: [PASSAGE], cited: [1], rejected_citations: [], model: "claude-x", seconds: 6 },
    created_at: "2026-09-26T00:00:00Z",
    answer_kind: "document",
    used_line: "Checked your submittal · Claude · 6 s",
    verification: { verified: 1, total: 1, method: "quote found on the page" },
    steps: [
      { label: "Searched your documents", count: 20, done: true },
      { label: "Read the best sources", count: 1, done: true },
    ],
    sources: [
      {
        n: 1, kind: "document", document_id: "doc_ds", display_name: "Sour water drum datasheet",
        document_number: "DS-0003", page: 5, page_end: 5, clause: "Sheet 5", text_source: "extracted",
        ocr_min_conf: null, url: null, cited: true, quotes: ["Hydrostatic test pressure basis"], rows: [],
      },
    ],
    suggestions: ["Write that as a comment", "What else is missing?"],
    draft: null,
    notices: [],
    ...over,
  };
}

function done(q: string, answer: Message) {
  return {
    question: q,
    answer_type: answer.answer_type,
    answer: answer.text,
    reason: null,
    passage: null,
    supporting: [],
    passages: [PASSAGE],
    cited: [1],
    rejected_citations: [],
    conversation,
    user_message: user(q),
    assistant_message: answer,
    resolved_question: q,
    carried_terms: [],
  };
}

function sse(events: [string, unknown][]): string {
  return events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const eventStream = (body: string | ReadableStream<Uint8Array>) =>
  new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });

interface Call {
  url: string;
  method: string;
  body: any;
  headers: Headers;
  signal?: AbortSignal | null;
}

function mockApi({
  stream,
  conversations = [],
  messages = [],
  models = {
    default: "claude",
    models: [
      { id: "claude", label: "Claude", model: "m", available: true, reason: null },
      { id: "local", label: "Local model", model: "l", available: true, reason: null },
    ],
  },
}: {
  stream?: (body: any, call: Call) => Response | Promise<Response>;
  conversations?: Conversation[];
  messages?: Message[];
  models?: unknown;
} = {}) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const call: Call = {
      url,
      method: init?.method ?? "GET",
      body: init?.body ? JSON.parse(String(init.body)) : null,
      headers: new Headers(init?.headers),
      signal: init?.signal,
    };
    calls.push(call);
    if (url.includes("/health")) return Promise.resolve(json(health));
    if (url.includes("/chat/models")) return Promise.resolve(json(models));
    if (url.endsWith("/ask/stream")) {
      return Promise.resolve(stream ? stream(call.body, call) : eventStream(""));
    }
    if (url.includes("/cancel")) return Promise.resolve(json({ turn_id: "t", cancelled: true }));
    if (url.includes("/conversations/") && call.method === "DELETE") {
      return Promise.resolve(json({ id: "conv_1", deleted: true }));
    }
    if (url.includes("/conversations/")) return Promise.resolve(json({ conversation, messages }));
    if (url.includes("/conversations")) {
      if (call.method === "POST") return Promise.resolve(json(conversation));
      return Promise.resolve(json({ total: conversations.length, limit: 50, offset: 0, conversations }));
    }
    return Promise.resolve(json([]));
  }));
  return calls;
}

async function openChat() {
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: /^Chat/ }));
}

async function ask(text: string) {
  await userEvent.type(screen.getByLabelText("Your question"), text);
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));
}

afterEach(() => vi.unstubAllGlobals());

// ---------------------------------------------------------------- first open

describe("the first screen", () => {
  it("asks what it can help with, and the nav says Chat", async () => {
    mockApi();
    await openChat();
    expect(await screen.findByText("What can I help with?")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("button", { name: /^Chat\s*Ask anything, with sources/ })).toBeInTheDocument();
    expect(screen.getByText(/AI can be wrong\. Open a source to check the page it came from\./)).toBeInTheDocument();
    // the conversation column is gone from the chat itself
    expect(screen.queryByRole("complementary", { name: "Recent conversations" })).toBeNull();
  });

  it("says honestly that Claude receives the question when Claude answers", async () => {
    mockApi();
    await openChat();
    expect(await screen.findByText(/your question and the passages it needs are sent to it/i)).toBeInTheDocument();
    expect(screen.queryByText(/nothing you type leaves this machine/i)).toBeNull();
  });
});

// ------------------------------------------------------------------ streaming

describe("an answer is written as it streams", () => {
  it("shows the real steps and the text, then the finished answer", async () => {
    const answer = assistant();
    let push: ((s: string) => void) | null = null;
    let end: (() => void) | null = null;
    const calls = mockApi({
      stream: () =>
        eventStream(
          new ReadableStream<Uint8Array>({
            start(controller) {
              const enc = new TextEncoder();
              push = (s) => controller.enqueue(enc.encode(s));
              end = () => controller.close();
            },
          }),
        ),
    });
    await openChat();
    await ask("does it meet the hydrotest requirement");

    await waitFor(() => expect(push).not.toBeNull());
    push!(sse([["turn", { turn_id: "turn_1" }], ["step", { label: "Searching your documents", count: 20, done: false }]]));
    expect(await screen.findByText("Searching your documents")).toBeInTheDocument();
    push!(sse([["delta", { text: "The test pressure is covered. " }]]));
    expect(await screen.findByText(/The test pressure is covered\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Stop/ })).toBeInTheDocument();

    push!(sse([["done", done("does it meet the hydrotest requirement", answer)]]));
    end!();
    expect(await screen.findByTestId("used-line")).toHaveTextContent("Checked your submittal · Claude · 6 s");
    expect(screen.queryByRole("button", { name: /Stop/ })).toBeNull();

    const streamCall = calls.find((c) => c.url.endsWith("/ask/stream"))!;
    expect(streamCall.headers.get("Accept")).toBe("text/event-stream");
    // one request answered it: the plain route was never also asked
    expect(calls.some((c) => c.url.endsWith("/ask"))).toBe(false);
  });

  it("stops by turn id, and shows the turn as stopped", async () => {
    let push: ((s: string) => void) | null = null;
    const calls = mockApi({
      stream: () =>
        eventStream(
          new ReadableStream<Uint8Array>({
            start(controller) {
              const enc = new TextEncoder();
              push = (s) => controller.enqueue(enc.encode(s));
            },
          }),
        ),
    });
    await openChat();
    await ask("explain sulfidation");
    await waitFor(() => expect(push).not.toBeNull());
    push!(sse([["turn", { turn_id: "turn_42" }], ["delta", { text: "Sulfidation is a kind of corrosion. " }]]));
    await screen.findByText(/Sulfidation is a kind of corrosion\./);

    await userEvent.click(screen.getByRole("button", { name: /Stop/ }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/conversations/conv_1/ask/turn_42/cancel"))).toBe(true),
    );

    push!(sse([["done", done("explain sulfidation", assistant({
      answer_type: "cancelled", answer_kind: "general", text: "Sulfidation is a kind of corrosion.",
      used_line: "Stopped · 2 s", verification: null, sources: [], steps: [], suggestions: [],
      payload: { passages: [] },
    }))]]));
    expect(await screen.findByText(/You stopped this answer/)).toBeInTheDocument();
    expect(screen.getByTestId("used-line")).toHaveTextContent("Stopped");
  });

  it("closes the connection when Stop is pressed before the server named the turn", async () => {
    const calls = mockApi({
      stream: (_body, call) =>
        eventStream(
          new ReadableStream<Uint8Array>({
            start(controller) {
              call.signal?.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")));
            },
          }),
        ),
    });
    await openChat();
    await ask("anything at all");
    await userEvent.click(await screen.findByRole("button", { name: /Stop/ }));
    await waitFor(() => expect(calls.find((c) => c.url.endsWith("/ask/stream"))?.signal?.aborted).toBe(true));
    // no cancel route without a turn id; the closed connection IS the stop
    expect(calls.some((c) => c.url.includes("/cancel"))).toBe(false);
  });

  it("reports a stream error and gives the question back", async () => {
    mockApi({
      stream: () => eventStream(sse([["turn", { turn_id: "t" }], ["error", { code: "internal", message: "the answer could not be completed" }]])),
    });
    await openChat();
    await ask("a question worth keeping");
    expect(await screen.findByRole("alert")).toHaveTextContent("the answer could not be completed");
    await waitFor(() =>
      expect((screen.getByLabelText("Your question") as HTMLTextAreaElement).value).toBe("a question worth keeping"),
    );
  });
});

// ---------------------------------------------------------- general knowledge

describe("general knowledge", () => {
  const general = assistant({
    answer_type: "general",
    answer_kind: "general",
    text: "Think of sulfidation as rust's hot cousin [S1].",
    used_line: "General knowledge, not from your documents · Claude · 3 s",
    verification: null,
    sources: [],
    steps: [],
    suggestions: ["Give me that in points"],
    payload: { passages: [] },
  });

  it("says it is not from your documents and cites nothing, even a marker the model wrote", async () => {
    mockApi({ stream: () => eventStream(sse([["done", done("what is sulfidation", general)]])) });
    await openChat();
    await ask("what is sulfidation");
    expect(await screen.findByTestId("used-line")).toHaveTextContent("General knowledge, not from your documents");
    expect(screen.getByText(/rust's hot cousin\./)).toBeInTheDocument();
    expect(screen.queryByText(/\[S1\]/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Source 1/ })).toBeNull();
    expect(screen.queryByText(/points? found on the page/)).toBeNull();
  });

  it("rewrites on request, as the reader's own follow-up", async () => {
    const calls = mockApi({ stream: () => eventStream(sse([["done", done("what is sulfidation", general)]])) });
    await openChat();
    await ask("what is sulfidation");
    const rewrite = await screen.findByText("Rewrite as:");
    await userEvent.click(within(rewrite.parentElement!).getByRole("button", { name: "Points" }));
    await waitFor(() =>
      expect(calls.filter((c) => c.url.endsWith("/ask/stream")).at(-1)?.body).toMatchObject({
        question: "Give me that in points",
      }),
    );
  });

  it("never renders model text as HTML", async () => {
    const hostile = assistant({
      ...general,
      text: 'Here: <img src=x onerror="window.__pwned=1"> **bold** done.',
    });
    mockApi({ stream: () => eventStream(sse([["done", done("q", hostile)]])) });
    await openChat();
    await ask("q");
    expect(await screen.findByText(/<img src=x onerror=/)).toBeInTheDocument();
    expect(document.querySelector("article img")).toBeNull();
    expect(screen.getByText("bold").tagName).toBe("STRONG");
  });
});

// ------------------------------------------------------------ document answers

describe("a document answer", () => {
  it("counts the points found on the page and opens each source with its words marked", async () => {
    const calls = mockApi({ stream: () => eventStream(sse([["done", done("does it meet", assistant())]])) });
    await openChat();
    await ask("does it meet");

    expect(await screen.findByText("1 of 1 point found on the page")).toBeInTheDocument();
    expect(screen.getByText(/Written by the model · claude-x — not the document's words/)).toBeInTheDocument();
    expect(screen.getByText("Partly.").tagName).toBe("STRONG");

    await userEvent.click(screen.getByRole("button", { name: "Source 1" }));
    const preview = screen.getByRole("region", { name: "Source 1 preview" });
    expect(within(preview).getByText("Sour water drum datasheet")).toBeInTheDocument();
    expect(within(preview).getByText(/DS-0003 · page 5 · Sheet 5/)).toBeInTheDocument();
    expect(within(preview).getByText("Hydrostatic test pressure basis").tagName).toBe("MARK");

    await userEvent.click(within(preview).getByRole("button", { name: "Open page" }));
    expect(await screen.findByRole("complementary", { name: "Evidence" })).toBeInTheDocument();
    await waitFor(() => expect(calls.some((c) => c.url.includes("/documents/doc_ds/pages/5"))).toBe(true));
  });

  it("explains how it got there only when asked", async () => {
    mockApi({ stream: () => eventStream(sse([["done", done("does it meet", assistant())]])) });
    await openChat();
    await ask("does it meet");
    const how = await screen.findByRole("button", { name: /How I got this/ });
    expect(screen.queryByText("Searched your documents")).toBeNull();
    await userEvent.click(how);
    expect(screen.getByText("Searched your documents")).toBeInTheDocument();
    expect(screen.getByText(/looked up on the page it cites/)).toBeInTheDocument();
  });

  it("asks for the exact wording of the same question", async () => {
    const calls = mockApi({ stream: () => eventStream(sse([["done", done("does it meet", assistant())]])) });
    await openChat();
    await ask("does it meet");
    await userEvent.click(await screen.findByRole("button", { name: "Exact wording" }));
    await waitFor(() =>
      expect(calls.filter((c) => c.url.endsWith("/ask/stream")).at(-1)?.body).toMatchObject({
        question: "/quote does it meet",
      }),
    );
  });

  it("shows the engineer notice the server attached", async () => {
    const withNotice = assistant({
      notices: ["This needs an engineer's judgement - the passages are evidence, not a verdict"],
    });
    mockApi({ stream: () => eventStream(sse([["done", done("is it compliant", withNotice)]])) });
    await openChat();
    await ask("is it compliant");
    expect(await screen.findByText(/This needs an engineer's judgement/)).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------- drafts

describe("a draft comment", () => {
  it("is a draft an engineer edits, and nothing is filed", async () => {
    const draft = assistant({
      answer_type: "general",
      answer_kind: "action",
      text: "Please state the hydrotest water chloride limit.",
      used_line: "Drafted from the previous answer · 2 s",
      draft: { type: "comment", text: "Please state the hydrotest water chloride limit.", status: "draft", source_ids: [] },
      verification: null,
      sources: [],
      suggestions: [],
      payload: { passages: [] },
    });
    const calls = mockApi({ stream: () => eventStream(sse([["done", done("write that as a comment", draft)]])) });
    await openChat();
    await ask("write that as a comment");
    const card = await screen.findByRole("region", { name: "Draft comment" });
    expect(within(card).getByText("Needs an engineer")).toBeInTheDocument();
    expect(within(card).getByText(/Not added to any review yet/)).toBeInTheDocument();
    await userEvent.click(within(card).getByRole("button", { name: "Edit" }));
    const box = within(card).getByLabelText("Draft comment text");
    await userEvent.type(box, " Thanks.");
    expect((box as HTMLTextAreaElement).value).toMatch(/limit\. Thanks\.$/);
    // no rewrite chips on a draft, and no write anywhere
    expect(screen.queryByText("Rewrite as:")).toBeNull();
    expect(calls.some((c) => /\/reviews|\/findings/.test(c.url))).toBe(false);
  });
});

// ---------------------------------------------------------------- composer

describe("the composer", () => {
  it("sends on Enter and starts a new line on Shift+Enter", async () => {
    const calls = mockApi({ stream: () => eventStream(sse([["done", done("x", assistant())]])) });
    await openChat();
    const box = screen.getByLabelText("Your question") as HTMLTextAreaElement;
    await userEvent.type(box, "first line{Shift>}{Enter}{/Shift}second line");
    expect(box.value).toBe("first line\nsecond line");
    expect(calls.some((c) => c.url.endsWith("/ask/stream"))).toBe(false);
    await userEvent.type(box, "{Enter}");
    await waitFor(() =>
      expect(calls.find((c) => c.url.endsWith("/ask/stream"))?.body).toMatchObject({ question: "first line\nsecond line" }),
    );
  });

  it("counts toward the limit and will not send a question that would be cut", async () => {
    mockApi();
    await openChat();
    const box = screen.getByLabelText("Your question");
    fireEvent.change(box, { target: { value: "x".repeat(501) } });
    expect(screen.getByText(/501\/500 - too long to send/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    fireEvent.change(box, { target: { value: "x".repeat(500) } });
    expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled();
  });
});

// ------------------------------------------------------------ recent chats

describe("recent chats in the navigation", () => {
  const older: Conversation = { ...conversation, id: "conv_1", title: "PSV bolting" };

  it("opens a chat from the navigation", async () => {
    mockApi({ conversations: [older], messages: [user("which bolts"), assistant()] });
    await openChat();
    const recent = await screen.findByRole("region", { name: "Recent chats" });
    await userEvent.click(within(recent).getByRole("button", { name: "PSV bolting" }));
    expect(await screen.findByText("which bolts")).toBeInTheDocument();
  });

  it("asks before deleting, and Undo means nothing is deleted", async () => {
    const calls = mockApi({ conversations: [older] });
    await openChat();
    const recent = await screen.findByRole("region", { name: "Recent chats" });
    await userEvent.click(within(recent).getByRole("button", { name: "Delete conversation PSV bolting" }));
    // asked, not done
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.click(within(recent).getByRole("button", { name: "Delete" }));
    expect(within(recent).queryByRole("button", { name: "PSV bolting" })).toBeNull();
    await userEvent.click(within(recent).getByRole("button", { name: "Undo" }));
    expect(within(recent).getByRole("button", { name: "PSV bolting" })).toBeInTheDocument();
    window.dispatchEvent(new Event("pagehide"));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  });

  it("deletes for real when the reader leaves inside the Undo window", async () => {
    const calls = mockApi({ conversations: [older] });
    await openChat();
    const recent = await screen.findByRole("region", { name: "Recent chats" });
    await userEvent.click(within(recent).getByRole("button", { name: "Delete conversation PSV bolting" }));
    await userEvent.click(within(recent).getByRole("button", { name: "Delete" }));
    window.dispatchEvent(new Event("pagehide"));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "DELETE" && c.url.includes("/conversations/conv_1?confirm=true"))).toBe(true),
    );
  });
});
