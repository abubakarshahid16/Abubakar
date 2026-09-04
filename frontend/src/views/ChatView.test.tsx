/**
 * The Chat screen is the demo, and its job is to be impossible to misread.
 *
 * These tests hold the properties that make it trustworthy rather than merely
 * pretty: a quotation is labelled as the document's words, generated prose is
 * labelled as the model's, a refusal reads as a refusal, a follow-up shows
 * what it carried, and Explain warns about its cost before it is pressed.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import type { Health } from "../api/client";
import type { AnswerPassage, AskResult, Conversation, Message } from "../types/api";

const health: Health = {
  ok: true,
  embed_model_present: true,
  answer_model: "qwen3.5:4b",
  ingestion: {
    alive: true,
    current_document: null,
    seconds_since_heartbeat: 0.5,
    seconds_since_progress: 20,
    documents_completed: 4,
    pending_count: 0,
    oldest_pending_age_seconds: null,
    stalled: false,
    stalled_reasons: [],
    last_error: null,
  },
};

const A1: AnswerPassage = {
  chunk_id: "norsok:p00017:c00042:aa11",
  document_id: "doc_norsok",
  filename: "NORSOKM501Rev5.pdf",
  page_start: 17,
  page_end: 17,
  section: "A.1 Coating system no. 1 (shall be pre-qualified)",
  text: "Coating system no. 1 shall have a nominal dry film thickness of 280 um.",
  highlight: [0, 70],
  score: 6.538,
  identifier_hits: ["system 1"],
};

const A4: AnswerPassage = {
  ...A1,
  chunk_id: "norsok:p00019:c00051:bb22",
  page_start: 19,
  section: "A.4 Coating system no. 4 (shall be pre-qualified)",
  text: "Coating system no. 4 shall have a nominal dry film thickness of 450 um.",
  highlight: null,
  score: 5.1,
  identifier_hits: ["system 4"],
};

const conversation: Conversation = {
  id: "conv_abc",
  title: "what is the NDFT for coating system no. 1",
  document_id: null,
  message_count: 2,
  created_at: "2026-09-04T00:00:00Z",
  updated_at: "2026-09-04T00:00:00Z",
};

function userMessage(over: Partial<Message> = {}): Message {
  return {
    id: "msg_u1",
    conversation_id: "conv_abc",
    ordinal: 1,
    role: "user",
    text: "what is the NDFT for coating system no. 1",
    resolved_question: "what is the NDFT for coating system no. 1",
    carried_terms: [],
    answer_type: null,
    reason: null,
    explains_id: null,
    payload: null,
    created_at: "2026-09-04T00:00:00Z",
    ...over,
  };
}

function extractMessage(over: Partial<Message> = {}): Message {
  return {
    id: "msg_a1",
    conversation_id: "conv_abc",
    ordinal: 2,
    role: "assistant",
    text: A1.text,
    resolved_question: null,
    carried_terms: [],
    answer_type: "extract",
    reason: null,
    explains_id: null,
    payload: {
      passage: A1,
      supporting: [A4],
      passages: [],
      cited: [],
      rejected_citations: [],
      retrieval_mode: "hybrid",
      reranked: true,
      candidates_considered: 20,
      model: null,
      seconds: 1.255,
      timings: {},
    },
    created_at: "2026-09-04T00:00:00Z",
    ...over,
  };
}

function askResult(over: Partial<AskResult> = {}): Partial<AskResult> {
  return {
    question: "what is the NDFT for coating system no. 1",
    answer_type: "extract",
    answer: A1.text,
    reason: null,
    passage: A1,
    supporting: [A4],
    passages: [],
    cited: [],
    rejected_citations: [],
    retrieval_mode: "hybrid",
    reranked: true,
    candidates_considered: 20,
    model: null,
    prompt_tokens: null,
    output_tokens: null,
    seconds: 1.255,
    timings: {},
    conversation,
    user_message: userMessage(),
    assistant_message: extractMessage(),
    resolved_question: "what is the NDFT for coating system no. 1",
    carried_terms: [],
    ...over,
  };
}

interface Routes {
  conversations?: unknown;
  conversation?: unknown;
  ask?: unknown | (() => unknown);
  newConversation?: unknown;
}

function mockApi(routes: Routes = {}) {
  const calls: { url: string; body: unknown }[] = [];
  const spy = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
    const body = (() => {
      if (url.includes("/health")) return health;
      if (url.endsWith("/ask")) {
        const r = routes.ask ?? askResult();
        return typeof r === "function" ? (r as () => unknown)() : r;
      }
      if (url.includes("/conversations/")) return routes.conversation ?? { conversation, messages: [] };
      if (url.includes("/conversations")) {
        if (init?.method === "POST") return routes.newConversation ?? conversation;
        return (
          routes.conversations ?? { total: 0, limit: 20, offset: 0, conversations: [] }
        );
      }
      return [];
    })();
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", spy);
  return calls;
}

async function openChat() {
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: /Chat/ }));
}

afterEach(() => vi.unstubAllGlobals());

// --------------------------------------------------------------- navigation

describe("chat navigation", () => {
  it("is no longer marked as not built", async () => {
    mockApi();
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Main" });
    const chat = within(nav).getByRole("button", { name: /Chat/ });
    expect(within(chat).queryByText("not built")).toBeNull();
  });
});

// --------------------------------------------------- quotation vs generated

describe("a quotation is never mistaken for generated prose", () => {
  it("labels a Tier 1 answer as the document's own words", async () => {
    mockApi();
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "what is the NDFT");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(/Quoted verbatim from the document/i)).toBeInTheDocument();
    expect(screen.getByText(/no model involved/i)).toBeInTheDocument();
    expect(screen.getByText(A1.text)).toBeInTheDocument();
  });

  it("labels a Tier 2 answer as the model's words, not the document's", async () => {
    mockApi({
      conversation: {
        conversation,
        messages: [
          userMessage(),
          extractMessage(),
          extractMessage({
            id: "msg_a2",
            ordinal: 3,
            text: "The thickness is 280 um [S1].",
            answer_type: "generated",
            explains_id: "msg_a1",
            payload: {
              passages: [A1],
              cited: [1],
              rejected_citations: [],
              model: "qwen3.5:4b",
              seconds: 51.8,
            },
          }),
        ],
      },
      conversations: {
        total: 1,
        limit: 20,
        offset: 0,
        conversations: [{ ...conversation, first_question: "q" }],
      },
    });
    await openChat();
    await userEvent.click(await screen.findByRole("button", { name: /^what is the NDFT/ }));

    // the model name also appears in the sidebar, so assert on the label itself
    expect(
      await screen.findByText(/Written by the model · qwen3\.5:4b — not the document's words/i),
    ).toBeInTheDocument();
    // and the quotation is still on screen, still labelled as a quotation
    expect(screen.getByText(/Quoted verbatim/i)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------- citations

describe("citations", () => {
  it("shows the document, page and clause beside a quoted answer", async () => {
    mockApi();
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "q");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    // the filename appears on the citation line and again in the supporting
    // list, so scope to the citation line beside the quotation
    const chip = await screen.findByRole("button", { name: "Show source 1" });
    const citation = within(chip.parentElement!);
    expect(citation.getByText("NORSOKM501Rev5.pdf")).toBeInTheDocument();
    expect(citation.getByText("page 17")).toBeInTheDocument();
    expect(
      citation.getByText("A.1 Coating system no. 1 (shall be pre-qualified)"),
    ).toBeInTheDocument();
  });

  it("says so plainly when a document has no clause numbering", async () => {
    mockApi({
      ask: askResult({
        passage: { ...A1, section: null },
        supporting: [],
        assistant_message: extractMessage({
          payload: { passage: { ...A1, section: null }, supporting: [], seconds: 1 },
        }),
      }),
    });
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "q");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(/no clause numbering/i)).toBeInTheDocument();
  });

  it("opens the evidence panel with the passage and the rendered page", async () => {
    mockApi();
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "q");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await userEvent.click(await screen.findByRole("button", { name: "Show source 1" }));

    const panel = await screen.findByRole("complementary", { name: "Evidence" });
    expect(within(panel).getByText(/Quoted passage/i)).toBeInTheDocument();
    expect(
      within(panel).getByRole("img", { name: /Page 17 of NORSOKM501Rev5.pdf/ }),
    ).toHaveAttribute("src", "/api/documents/doc_norsok/pages/17/image");
    expect(within(panel).getByText(/Page 17 as printed/i)).toBeInTheDocument();
  });

  it("marks the answering span inside the quoted passage", async () => {
    mockApi();
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "q");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await userEvent.click(await screen.findByRole("button", { name: "Show source 1" }));

    const panel = await screen.findByRole("complementary", { name: "Evidence" });
    expect(within(panel).getByText(A1.text.slice(0, 70))).toBeInTheDocument();
  });

  it("reports a citation the model invented rather than hiding it", async () => {
    mockApi({
      conversation: {
        conversation,
        messages: [
          userMessage(),
          extractMessage({
            id: "msg_g",
            text: "Claim [S1].",
            answer_type: "generated",
            payload: {
              passages: [A1],
              cited: [1],
              rejected_citations: [9],
              model: "qwen3.5:4b",
              seconds: 50,
            },
          }),
        ],
      },
      conversations: {
        total: 1,
        limit: 20,
        offset: 0,
        conversations: [{ ...conversation, first_question: "q" }],
      },
    });
    await openChat();
    await userEvent.click(await screen.findByRole("button", { name: /^what is the NDFT/ }));

    expect(await screen.findByText(/\[S9\]/)).toBeInTheDocument();
    expect(screen.getByText(/not among the sources supplied/i)).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------ explain

describe("explain", () => {
  it("warns how long it takes before it is pressed", async () => {
    mockApi();
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "q");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(
      await screen.findByRole("button", { name: /Explain in plain language/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/about 50 seconds on this hardware/i)).toBeInTheDocument();
    expect(screen.getByText(/the quotation above is already the answer/i)).toBeInTheDocument();
  });

  it("sends explain_of rather than re-asking the question", async () => {
    const calls = mockApi();
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "q");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await userEvent.click(await screen.findByRole("button", { name: /Explain in plain/i }));

    await waitFor(() => {
      const explain = calls.filter((c) => c.url.endsWith("/ask")).at(-1);
      expect(explain?.body).toMatchObject({ tier: "generated", explain_of: "msg_a1" });
    });
  });

  it("is not offered on an answer that already has an explanation", async () => {
    mockApi({
      conversation: {
        conversation,
        messages: [
          userMessage(),
          extractMessage(),
          extractMessage({
            id: "msg_a2",
            ordinal: 3,
            text: "Explained [S1].",
            answer_type: "generated",
            explains_id: "msg_a1",
            payload: { passages: [A1], cited: [1], model: "qwen3.5:4b", seconds: 50 },
          }),
        ],
      },
      conversations: {
        total: 1,
        limit: 20,
        offset: 0,
        conversations: [{ ...conversation, first_question: "q" }],
      },
    });
    await openChat();
    await userEvent.click(await screen.findByRole("button", { name: /^what is the NDFT/ }));
    await screen.findByText(/Written by the model/i);

    expect(screen.queryByRole("button", { name: /Explain in plain/i })).toBeNull();
  });

  it("is not offered when there is no evidence to explain", async () => {
    mockApi({
      ask: askResult({
        answer_type: "insufficient_evidence",
        answer: null,
        reason: "no indexed passage matched this question",
        passage: null,
        supporting: [],
        assistant_message: extractMessage({
          text: null,
          answer_type: "insufficient_evidence",
          reason: "no indexed passage matched this question",
          payload: { passages: [], seconds: 1 },
        }),
      }),
    });
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "q");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    await screen.findByText(/The documents do not answer this/i);
    expect(screen.queryByRole("button", { name: /Explain in plain/i })).toBeNull();
  });
});

// ------------------------------------------------------- insufficient evidence

describe("insufficient evidence", () => {
  it("says there is no answer rather than showing a weak one", async () => {
    mockApi({
      ask: askResult({
        answer_type: "insufficient_evidence",
        answer: null,
        reason: "the closest passages were not a credible match",
        passage: null,
        supporting: [],
        passages: [A4],
        assistant_message: extractMessage({
          text: null,
          answer_type: "insufficient_evidence",
          reason: "the closest passages were not a credible match",
          payload: { passages: [A4], seconds: 1.4 },
        }),
      }),
    });
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "q");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(/The documents do not answer this/i)).toBeInTheDocument();
    expect(screen.getByText(/Nothing was made up to fill the gap/i)).toBeInTheDocument();
    // what was considered is still offered, so the reader can judge
    expect(screen.getByText(/What was considered/i)).toBeInTheDocument();
    expect(screen.getByText(/A.4 Coating system no. 4/)).toBeInTheDocument();
  });

  it("distinguishes the model being down from there being no evidence", async () => {
    mockApi({
      conversation: {
        conversation,
        messages: [
          userMessage(),
          extractMessage({
            text: null,
            answer_type: "model_unavailable",
            reason: "the local answer model could not be reached (ConnectError)",
            payload: { passages: [A1], seconds: 0.1 },
          }),
        ],
      },
      conversations: {
        total: 1,
        limit: 20,
        offset: 0,
        conversations: [{ ...conversation, first_question: "q" }],
      },
    });
    await openChat();
    await userEvent.click(await screen.findByRole("button", { name: /^what is the NDFT/ }));

    expect(
      await screen.findByText(/The local answer model is not running/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/The documents do not answer this/i)).toBeNull();
  });
});

// ----------------------------------------------------------------- follow-ups

describe("follow-ups", () => {
  it("shows what a follow-up carried in, rather than rewriting silently", async () => {
    mockApi({
      ask: askResult({
        question: "what is its curing time",
        resolved_question: "what is its curing time system 1 ndft coating",
        carried_terms: ["system 1", "ndft", "coating"],
        user_message: userMessage({
          id: "msg_u2",
          ordinal: 3,
          text: "what is its curing time",
          resolved_question: "what is its curing time system 1 ndft coating",
          carried_terms: ["system 1", "ndft", "coating"],
        }),
      }),
    });
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "what is its curing time");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(/Read as a follow-up/i)).toBeInTheDocument();
    expect(screen.getByText("system 1")).toBeInTheDocument();
    // the question as typed is what is shown as the question
    expect(screen.getByText("what is its curing time")).toBeInTheDocument();
  });

  it("says nothing about follow-ups when nothing was carried", async () => {
    mockApi();
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "q");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    await screen.findByText(/Quoted verbatim/i);
    expect(screen.queryByText(/Read as a follow-up/i)).toBeNull();
  });
});

// -------------------------------------------------------------- conversations

describe("conversations", () => {
  it("lists recent conversations and reopens one", async () => {
    mockApi({
      conversations: {
        total: 1,
        limit: 20,
        offset: 0,
        conversations: [{ ...conversation, first_question: "what is the NDFT" }],
      },
      conversation: { conversation, messages: [userMessage(), extractMessage()] },
    });
    await openChat();

    await userEvent.click(await screen.findByRole("button", { name: /^what is the NDFT/ }));
    expect(await screen.findByText(A1.text)).toBeInTheDocument();
    // a reopened conversation still carries its citation, not bare text
    expect(
      screen.getByText("A.1 Coating system no. 1 (shall be pre-qualified)"),
    ).toBeInTheDocument();
  });

  it("keeps the question when the request fails, rather than losing it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.includes("/health")) {
          return Promise.resolve(
            new Response(JSON.stringify(health), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        if (url.endsWith("/ask")) return Promise.reject(new TypeError("Failed to fetch"));
        if (url.includes("/conversations") && init?.method === "POST") {
          return Promise.resolve(
            new Response(JSON.stringify(conversation), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        return Promise.resolve(
          new Response(JSON.stringify({ total: 0, limit: 20, offset: 0, conversations: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );
    await openChat();
    const input = screen.getByLabelText("Your question") as HTMLInputElement;
    await userEvent.type(input, "a question worth not losing");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Cannot reach the backend/i);
    await waitFor(() => expect(input.value).toBe("a question worth not losing"));
  });
});

// ------------------------------------------------------------------ guidance

describe("inputs that are not document questions", () => {
  const guidanceMessage = (over = {}) =>
    extractMessage({
      id: "msg_g1",
      text: "Hello. I answer questions about your documents, quoting the source with its page and clause.",
      answer_type: "guidance",
      reason: null,
      payload: {
        passages: [],
        cited: [],
        rejected_citations: [],
        input_kind: "greeting",
        examples: [
          "What does NORSOKM501Rev5.pdf say about Coating system no. 1?",
          "What does book1-professionalpractices.pdf say about Self-Driving Vehicles?",
        ],
        seconds: 0.002,
      },
      ...over,
    });

  it("greets rather than refusing, and shows no search results", async () => {
    mockApi({
      ask: askResult({
        answer_type: "guidance",
        answer: "Hello. I answer questions about your documents, quoting the source with its page and clause.",
        reason: null,
        passage: null,
        supporting: [],
        passages: [],
        assistant_message: guidanceMessage(),
      }),
    });
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "hi");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(/I answer questions about your documents/i)).toBeInTheDocument();
    // never a refusal, and never evidence for a search that did not happen
    expect(screen.queryByText(/The documents do not answer this/i)).toBeNull();
    expect(screen.queryByText(/What was considered/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /Show source/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Explain in plain/i })).toBeNull();
  });

  it("offers real example questions drawn from the loaded documents", async () => {
    mockApi({
      ask: askResult({
        answer_type: "guidance",
        answer: "Hello.",
        passage: null,
        supporting: [],
        passages: [],
        assistant_message: guidanceMessage(),
      }),
    });
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "hi");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(/Questions your documents can answer/i)).toBeInTheDocument();
    expect(
      screen.getByText("What does NORSOKM501Rev5.pdf say about Coating system no. 1?"),
    ).toBeInTheDocument();
  });
});

// ------------------------------------------------------------- prose defects

describe("refusal wording", () => {
  it("does not run two sentences together without a full stop", async () => {
    mockApi({
      ask: askResult({
        answer_type: "insufficient_evidence",
        answer: null,
        reason: "the closest passages were not a credible match",
        passage: null,
        supporting: [],
        passages: [],
        assistant_message: extractMessage({
          text: null,
          answer_type: "insufficient_evidence",
          reason: "the closest passages were not a credible match",
          payload: { passages: [], seconds: 1.4 },
        }),
      }),
    });
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "q");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    const text = (await screen.findByText(/not a credible match/i)).textContent ?? "";
    expect(text).toContain("credible match. Nothing was made up");
    expect(text).not.toContain("credible match Nothing");
  });

  it("leaves a reason that already ends in a full stop alone", async () => {
    mockApi({
      ask: askResult({
        answer_type: "insufficient_evidence",
        answer: null,
        reason: "No indexed passage matched this question.",
        passage: null,
        supporting: [],
        passages: [],
        assistant_message: extractMessage({
          text: null,
          answer_type: "insufficient_evidence",
          reason: "No indexed passage matched this question.",
          payload: { passages: [], seconds: 1 },
        }),
      }),
    });
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "q");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    const text = (await screen.findByText(/No indexed passage/i)).textContent ?? "";
    expect(text).toContain("this question. Nothing");
    expect(text).not.toContain("question.. Nothing");
  });
});
