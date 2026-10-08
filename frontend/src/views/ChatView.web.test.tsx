/**
 * Chat redesign PR 6 (owner order 2026-09-26): the web lane on screen.
 *
 *  - "Web" is offered only when the system allows it, and says why not.
 *  - A web question shows the exact phrase and SENDS NOTHING until "Search
 *    once"; that request carries no text at all. Cancel sends nothing.
 *  - Web sources open the site, carry "web · unverified", and are never
 *    document chips.
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
  id: "conv_1", title: "Newer edition", document_id: null, message_count: 2,
  created_at: "2026-09-26T00:00:00Z", updated_at: "2026-09-26T00:00:00Z",
};

const question: Message = {
  id: "u_1", conversation_id: "conv_1", ordinal: 1, role: "user",
  text: "is there a newer edition of ISO 12944 online", resolved_question: null, carried_terms: [],
  answer_type: null, reason: null, explains_id: null, payload: null, created_at: "2026-09-26T00:00:00Z",
};

function consent(over: Partial<Message["payload"]> = {}): Message {
  return {
    id: "a_1", conversation_id: "conv_1", ordinal: 2, role: "assistant",
    text: 'I can search the web for "newer edition iso 12944 online". Only this phrase is sent. Search once?',
    resolved_question: null, carried_terms: [], answer_type: "web_consent", reason: null, explains_id: null,
    payload: { passages: [], web_phrase: "newer edition iso 12944 online", web_available: true, ...over },
    created_at: "2026-09-26T00:00:00Z", answer_kind: "web", used_line: "Nothing has been sent",
    sources: [], steps: [], suggestions: [], notices: [], verification: null, draft: null,
  };
}

const webAnswer: Message = {
  ...consent(), id: "a_2", ordinal: 3, answer_type: "web",
  text: 'What a public web search for "newer edition iso 12944 online" returned. These are web pages, not your documents:\n\n1. ISO 12944 revision notice (Example Journal)',
  used_line: 'Searched the web for "newer edition iso 12944 online" · only this phrase was sent · 2 s',
  sources: [{
    n: 1, kind: "web", document_id: null, display_name: "Example Journal", document_number: null,
    page: null, page_end: null, clause: "2025-01-01", text_source: null, ocr_min_conf: null,
    url: "https://example.org/iso-12944", cited: true, quotes: [], rows: [],
  }],
  notices: ["Web results are unverified. Your contract baseline is the edition it names, whatever a website says."],
  payload: { passages: [] },
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

interface Call { url: string; method: string; body: unknown }

function mockApi({ messages = [question, consent()], webAvailable = true, afterSearch }: {
  messages?: Message[]; webAvailable?: boolean; afterSearch?: Message[];
} = {}) {
  const calls: Call[] = [];
  let current = messages;
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const call = { url, method: init?.method ?? "GET", body: init?.body ?? null };
    calls.push(call);
    if (url.includes("/health")) return Promise.resolve(json(health));
    if (url.includes("/chat/models")) {
      return Promise.resolve(json({
        default: "claude",
        models: [{ id: "claude", label: "Claude", model: "m", available: true, reason: null },
                 { id: "local", label: "Local model", model: "l", available: true, reason: null }],
        web_available: webAvailable,
        web_reason: webAvailable ? null : "web search is switched off for chat on this system",
      }));
    }
    if (url.endsWith("/web-search")) {
      current = afterSearch ?? [...messages, webAnswer];
      return Promise.resolve(json(webAnswer));
    }
    if (url.endsWith("/ask/stream")) {
      return Promise.resolve(new Response("", { status: 200, headers: { "Content-Type": "text/event-stream" } }));
    }
    if (url.includes("/conversations/")) return Promise.resolve(json({ conversation, messages: current }));
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
  await userEvent.click(within(recent).getByRole("button", { name: "Newer edition" }));
}

afterEach(() => vi.unstubAllGlobals());

describe("the Web switch", () => {
  it("is not offered when the system does not allow it, and says why", async () => {
    mockApi({ webAvailable: false });
    await openConversation();
    const web = await screen.findByRole("button", { name: "Web off" });
    expect(web).toBeDisabled();
    expect(web).toHaveAttribute("title", "web search is switched off for chat on this system");
  });

  it("sends web: true only while it is on", async () => {
    const calls = mockApi();
    await openConversation();
    await userEvent.click(await screen.findByRole("button", { name: "Web off" }));
    await userEvent.type(screen.getByLabelText("Your question"), "any newer edition online?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/ask/stream"))).toBe(true));
    expect(JSON.parse(String(calls.find((c) => c.url.endsWith("/ask/stream"))!.body))).toMatchObject({ web: true });
  });
});

describe("ask first, then search once", () => {
  it("shows the exact phrase and sends nothing until Search once, which sends no text", async () => {
    const calls = mockApi();
    await openConversation();
    const offer = await screen.findByRole("group", { name: "Web search" });
    expect(within(offer).getByText('"newer edition iso 12944 online"')).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/web-search"))).toBe(false);

    await userEvent.click(within(offer).getByRole("button", { name: "Search once" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/messages/a_1/web-search"))).toBe(true));
    expect(calls.find((c) => c.url.endsWith("/web-search"))!.body).toBeNull();

    const link = await screen.findByRole("link", { name: "Example Journal" });
    expect(link).toHaveAttribute("href", "https://example.org/iso-12944");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(screen.getByText("web · unverified")).toBeInTheDocument();
    expect(screen.getByText(/only this phrase was sent/)).toBeInTheDocument();
    // a web source is never a document chip
    expect(screen.queryByRole("button", { name: /^Source 1/ })).toBeNull();
  });

  it("sends nothing when cancelled", async () => {
    const calls = mockApi();
    await openConversation();
    const offer = await screen.findByRole("group", { name: "Web search" });
    await userEvent.click(within(offer).getByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("Not searched. Nothing was sent.")).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/web-search"))).toBe(false);
  });

  it("offers no search when nothing was safe to send", async () => {
    mockApi({ messages: [question, consent({ web_phrase: null })] });
    await openConversation();
    await screen.findByText(/I can search the web/);
    expect(screen.queryByRole("button", { name: "Search once" })).toBeNull();
  });

  it("offers no second search once it has run", async () => {
    mockApi({ messages: [question, consent({ web_searched: true })] });
    await openConversation();
    await screen.findByText(/This search has been run/);
    expect(screen.queryByRole("button", { name: "Search once" })).toBeNull();
  });
});
