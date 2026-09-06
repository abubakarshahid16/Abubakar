/**
 * The Chat screen is the demo, and its job is to be impossible to misread.
 *
 * These tests hold the properties that make it trustworthy rather than merely
 * pretty: a quotation is labelled as the document's words, generated prose is
 * labelled as the model's, a refusal reads as a refusal, a follow-up shows
 * what it carried, and Explain warns about its cost before it is pressed.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import type { Health } from "../api/client";
import type { AnswerPassage, AskResult, Conversation, Message } from "../types/api";

const health: Health = {
  ok: true,
  embed_model_present: true,
  answer_model_present: true,
  ingestion: {
    // /api/health is unauthenticated and carries only
    // these three. The full worker status is on /api/metrics.
    alive: true,
    stalled: false,
    busy: false,
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
  match_span: [0, 70],
  chunks_joined: 1,
  text_source: "extracted",
  ocr_min_conf: null,
  ocr_alphabet_violations: 0,
  ocr_alphabet_sample: null,
  kind: "prose",
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

/** A1, but read off a page image instead of out of the text layer. */
const OCR_PASSAGE: AnswerPassage = {
  ...A1,
  text_source: "recognised",
  ocr_min_conf: 0.87,
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
  report?: unknown;
}

function mockApi(routes: Routes = {}) {
  const calls: { url: string; body: unknown }[] = [];
  const spy = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
    const body = (() => {
      if (url.includes("/health")) return health;
      if (url.endsWith("/reports")) {
        return routes.report ?? {
          id: "report_abc",
          title: "Evidence report",
          question: "what is the NDFT for coating system no. 1",
          created_at: "2026-09-04T00:00:00Z",
          owner_username: null,
          file_size_bytes: 1234,
          page_count: 2,
          passage_count: 1,
          documents: [],
          not_implemented_sections: [],
          suppressed_reason: null,
        };
      }
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
    expect(screen.getByText(/quoted directly, no AI rewriting/i)).toBeInTheDocument();
    expect(screen.getByText(A1.text)).toBeInTheDocument();
  });

  // The defect this test exists for: 92 recognised chunks were retrievable
  // while AnswerCard rendered "Quoted verbatim from the document"
  // unconditionally. Provenance was stored, carried through retrieval, and
  // made REQUIRED in the contract - and the screen ignored it. The assertion
  // that matters is the ABSENCE of the verbatim label; asserting only that the
  // OCR label appears would have passed while both were on screen.
  it("never calls OCR text a verbatim quotation", async () => {
    mockApi({
      ask: askResult({
        passage: OCR_PASSAGE,
        supporting: [],
        assistant_message: extractMessage({
          payload: { passage: OCR_PASSAGE, supporting: [], passages: [],
                     cited: [], rejected_citations: [], seconds: 1.255 },
        }),
      }),
    });
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "what is the NDFT");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(
      await screen.findByText(/Read by OCR from a scanned page/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/not the document's own text — check it against the page below/i),
    ).toBeInTheDocument();

    // THE ASSERTION THAT WOULD HAVE CAUGHT IT.
    expect(screen.queryByText(/Quoted verbatim from the document/i)).toBeNull();
    expect(screen.queryByText(/quoted directly, no AI rewriting/i)).toBeNull();
  });

  it("shows the page image without being asked, for a recognised passage", async () => {
    // A label that says "check it against the page" while the page sits behind
    // a click is a label that expects to be ignored.
    mockApi({
      ask: askResult({
        passage: OCR_PASSAGE,
        supporting: [],
        assistant_message: extractMessage({
          payload: { passage: OCR_PASSAGE, supporting: [], passages: [],
                     cited: [], rejected_citations: [], seconds: 1.255 },
        }),
      }),
    });
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "what is the NDFT");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    await screen.findByText(/Read by OCR from a scanned page/i);
    expect(await screen.findByRole("img", { name: /page 17/i })).toBeInTheDocument();
  });

  it("still labels EXTRACTED text as a verbatim quotation", async () => {
    // The other half: the weaker label must not leak onto text that earned the
    // stronger one.
    mockApi();
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "what is the NDFT");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(/Quoted verbatim from the document/i)).toBeInTheDocument();
    expect(screen.queryByText(/Read by OCR from a scanned page/i)).toBeNull();
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

    // The citation is now set as a citation rather than a row of chips, so
    // assert on the whole line: it has to be quotable straight into an email.
    const chip = await screen.findByRole("button", { name: "Show source 1" });
    const cite = chip.parentElement!.querySelector("cite")!;
    expect(cite.textContent).toContain("NORSOKM501Rev5.pdf");
    expect(cite.textContent).toContain("page 17");
    // THE CLAUSE IS NO LONGER PART OF THE CITATION. `chunks.section` does not
    // reset at chapter or appendix boundaries, so the heading it names is
    // wrong far more often than it is right, while the page is reliable. See
    // `clauseLabel` in components/chat/Provenance.tsx.
    expect(cite.textContent).not.toContain("clause");
    expect(cite.textContent).not.toContain("A.1");
  });

  // WAS: "says so plainly when a document has no clause numbering". That
  // statement is gone with the label it explained. No clause is printed for
  // any document now, so singling one out as unnumbered would imply the
  // others had a number the reader could see - and the reader cannot.
  it("cites a passage with no section exactly as it cites one with a section", async () => {
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

    const chip = await screen.findByRole("button", { name: "Show source 1" });
    const cite = chip.parentElement!.querySelector("cite")!;
    expect(cite.textContent).toBe("NORSOKM501Rev5.pdf, page 17");
    // Nothing stands in for the absent clause. Not "unknown", not a dash.
    expect(cite.textContent).not.toMatch(/clause|unknown|n\/a|[—–]/i);
  });

  it("opens the evidence panel with the passage and the rendered page", async () => {
    mockApi();
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "q");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await userEvent.click(await screen.findByRole("button", { name: "Show source 1" }));

    const panel = await screen.findByRole("complementary", { name: "Evidence" });
    expect(within(panel).getByText(/Quoted passage/i)).toBeInTheDocument();
    // The passage carries a highlight and the question is known, so the panel
    // asks for the page with the answer BOXED rather than the plain render.
    const img = within(panel).getByRole("img", { name: /Page 17 of NORSOKM501Rev5\.pdf/ });
    expect(img.getAttribute("src") ?? "").toContain(
      "/api/documents/doc_norsok/pages/17/image?",
    );
    expect(within(panel).getByText(/Page 17 as printed/i)).toBeInTheDocument();
  });

  /** A passage whose answering span is a real fraction of it, and the ask
   *  response shaped so it actually reaches the screen: ChatView renders
   *  r.data.assistant_message, not the top-level answer/passage, so those are
   *  the fields a fixture has to override. */
  function answering(passage: AnswerPassage) {
    const base = extractMessage();
    return askResult({
      answer: passage.text,
      passage,
      supporting: [],
      assistant_message: {
        ...base,
        text: passage.text,
        payload: { ...base.payload, passage, supporting: [] },
      },
    });
  }

  const PARTIAL: AnswerPassage = {
    ...A1,
    text:
      "Cleanliness shall be ISO 8501-1 Sa 2 1/2. " +
      "The nominal dry film thickness is 280 um. " +
      "Adhesion shall be tested on each batch.",
    highlight: [42, 83],
  };

  async function ask() {
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "q");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
  }

  it("marks the answering span inside the quoted passage", async () => {
    // A1's own highlight spans its ENTIRE text, which is deliberately not
    // marked - emphasising everything leaves the eye nowhere to land, the same
    // reason the page-image path refuses a box covering most of a page. So the
    // property is asserted with a partial span, and on the mark itself rather
    // than only on the words being present.
    mockApi({ ask: answering(PARTIAL) });
    await ask();
    await userEvent.click(await screen.findByRole("button", { name: "Show source 1" }));

    const panel = await screen.findByRole("complementary", { name: "Evidence" });
    const mark = within(panel).getByText("The nominal dry film thickness is 280 um.");
    expect(mark.tagName).toBe("MARK");
    expect(panel.textContent).toContain(PARTIAL.text);
  });

  it("marks the answering sentence inside the answer itself, not only the panel", async () => {
    // The reader looks at the quotation first. The mark lived only in the side
    // panel, so on a passage of standards prose the answering fragment arrived
    // in the same weight as everything around it.
    mockApi({ ask: answering(PARTIAL) });
    await ask();

    const quote = await screen.findByText("The nominal dry film thickness is 280 um.");
    expect(quote.tagName).toBe("MARK");
    // partial, not the whole passage
    expect((quote.textContent ?? "").length).toBeLessThan(PARTIAL.text.length);
    // and the passage is still quoted in full around it
    expect(document.querySelector("blockquote")?.textContent).toBe(PARTIAL.text);
  });

  it("leaves the quotation plain when no span could be located", async () => {
    // Nothing emphasised, rather than something emphasised wrongly - the rule
    // the page-image path already follows when it cannot locate an answer.
    mockApi({ ask: answering({ ...PARTIAL, highlight: null }) });
    await ask();
    await screen.findByText(PARTIAL.text);
    expect(document.querySelector("blockquote mark")).toBeNull();
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

  it("offers report generation on a generated explanation", async () => {
    const calls = mockApi({
      conversation: {
        conversation,
        messages: [
          userMessage(),
          extractMessage(),
          extractMessage({
            id: "msg_a2",
            ordinal: 3,
            text: "The service responsibilities continue across two cited passages [S1] [S2].",
            answer_type: "generated",
            explains_id: "msg_a1",
            payload: {
              passages: [A1, A4],
              cited: [1, 2],
              rejected_citations: [],
              model: "qwen3.5:4b",
              seconds: 52,
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

    const buttons = await screen.findAllByRole("button", { name: "Save as report" });
    await userEvent.click(buttons.at(-1)!);

    await waitFor(() => {
      expect(calls.some((c) => c.url.endsWith("/reports") && c.body && (c.body as { message_id?: string }).message_id === "msg_a2")).toBe(true);
    });
    expect(await screen.findByText(/Saved as report_abc/i)).toBeInTheDocument();
  });

  it("warns that an extract report does not merge other matched passages into the answer", async () => {
    mockApi();
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "what is the NDFT");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(/Other matched passages stay in the evidence section/i)).toBeInTheDocument();
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
    // Named by document and page - the two things that are reliable. The
    // clause label is not printed; see `clauseLabel` in chat/Provenance.tsx.
    const considered = screen.getByText(/What was considered/i).parentElement!;
    expect(considered.textContent).toContain("NORSOKM501Rev5.pdf");
    expect(considered.textContent).toMatch(/pages? 19/);
    expect(screen.queryByText(/A.4 Coating system no. 4/)).toBeNull();
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
    const cites = document.querySelectorAll("cite");
    expect(cites.length).toBeGreaterThan(0);
    expect(
      Array.from(cites).some((c) =>
        (c.textContent ?? "").includes("NORSOKM501Rev5.pdf, page 17"),
      ),
    ).toBe(true);
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

// ------------------------------------------------------ the answer, boxed

describe("the answer outlined on the rendered page", () => {
  const withQuestion = () =>
    mockApi({
      conversation: {
        conversation,
        messages: [
          userMessage({ text: "what is the NDFT", resolved_question: "what is the NDFT" }),
          extractMessage(),
        ],
      },
      conversations: {
        total: 1,
        limit: 20,
        offset: 0,
        conversations: [{ ...conversation, first_question: "q" }],
      },
    });

  it("requests the boxed render, passing the chunk and the question", async () => {
    withQuestion();
    await openChat();
    await userEvent.click(await screen.findByRole("button", { name: /^what is the NDFT/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Show source 1" }));

    const img = await screen.findByRole("img", { name: /with the answer outlined/i });
    const src = img.getAttribute("src") ?? "";
    expect(src).toContain("/pages/17/image?");
    expect(src).toContain(`chunk_id=${encodeURIComponent(A1.chunk_id)}`);
    expect(src).toContain("q=what+is+the+NDFT");
  });

  it("tells the reader the answer is outlined", async () => {
    withQuestion();
    await openChat();
    await userEvent.click(await screen.findByRole("button", { name: /^what is the NDFT/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Show source 1" }));

    expect(await screen.findByText("answer outlined")).toBeInTheDocument();
    expect(
      screen.getByText(/The answering sentence is outlined on the real page/i),
    ).toBeInTheDocument();
  });

  it("says the location could not be confirmed rather than boxing nothing silently", async () => {
    mockApi({
      conversation: {
        conversation,
        messages: [
          userMessage({ text: "what is the NDFT", resolved_question: "what is the NDFT" }),
          extractMessage({
            payload: {
              // no highlight: no answering sentence was identified
              passage: { ...A1, highlight: null },
              supporting: [],
              seconds: 1.2,
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
    await userEvent.click(await screen.findByRole("button", { name: "Show source 1" }));

    expect(
      await screen.findByText(/location of the answer on this page could not be confirmed/i),
    ).toBeInTheDocument();
    // and the plain page is shown, never a box somewhere plausible
    const img = screen.getByRole("img", { name: /^Page 17 of NORSOKM501Rev5\.pdf$/ });
    expect(img.getAttribute("src") ?? "").not.toContain("chunk_id");
    expect(screen.queryByText("answer outlined")).toBeNull();
  });
});

// ------------------------------------------------------- request ownership

/**
 * Tier 2 runs 20-50 seconds and is not streamed, which is exactly the window
 * in which an impatient reader clicks something else. Three handlers apply
 * their result with `setMessages(m => [...m, ...])` against whatever transcript
 * is on screen when the response resolves, not the one it was asked against.
 *
 * These tests hold the reader's mental model rather than the code's: an
 * explanation appears under the answer it explains or not at all, a question
 * appears once however many times its transcript was reloaded, and the
 * transcript on screen belongs to the conversation whose name is highlighted.
 */
describe("a response belongs to the request that asked for it", () => {
  const convA: Conversation = { ...conversation, id: "conv_a", title: "Coating systems" };
  const convB: Conversation = { ...conversation, id: "conv_b", title: "Welding procedures" };

  /** A fetch mock whose responses can be held open, one route at a time. */
  function holdableApi(handler: (url: string, body: any) => unknown | "HOLD") {
    const held: ((v: unknown) => void)[] = [];
    const spy = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      if (url.includes("/health")) return json(health);
      const r = handler(url, body);
      if (r === "HOLD") {
        return new Promise((resolve) => {
          held.push((v) => resolve(json(v)));
        });
      }
      return Promise.resolve(json(r));
    });
    vi.stubGlobal("fetch", spy);
    return {
      release: async (i: number, value: unknown) => {
        held[i](value);
        // let the awaiting handler and its re-render run
        await waitFor(() => expect(true).toBe(true));
      },
      heldCount: () => held.length,
    };
  }

  function json(body: unknown) {
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  const listOf = (...cs: Conversation[]) => ({
    total: cs.length,
    limit: 20,
    offset: 0,
    conversations: cs.map((c) => ({ ...c, message_count: 2 })),
  });

  it("drops an explanation whose transcript has moved on", async () => {
    // Reproduced by hand in the UI: press Explain, get impatient, ask
    // something else. The explanation lands under the new question's refusal,
    // and AnswerCard labels it "An explanation of the quoted answer above" -
    // which is then a false statement about the answer directly above it.
    const q1 = userMessage({ id: "u1", text: "what is the NDFT for coating system no. 1" });
    const a1 = extractMessage({ id: "a1" });
    const api = holdableApi((url, body) => {
      if (url.endsWith("/ask")) {
        if (body?.explain_of) return "HOLD";
        return askResult({
          answer_type: "insufficient_evidence",
          answer: null,
          reason: "The documents do not cover welding preheat.",
          passage: null,
          supporting: [],
          passages: [],
          user_message: userMessage({ id: "u2", text: "what preheat is required" }),
          assistant_message: extractMessage({
            id: "a2",
            text: null,
            answer_type: "insufficient_evidence",
            reason: "The documents do not cover welding preheat.",
            payload: { passages: [], seconds: 1.2 },
          }),
        });
      }
      if (url.includes("/conversations/")) return { conversation: convA, messages: [q1, a1] };
      return listOf(convA);
    });

    await openChat();
    await userEvent.click(await screen.findByRole("button", { name: /^Coating systems/ }));
    await userEvent.click(await screen.findByRole("button", { name: /Explain in plain/i }));

    // the reader gets impatient and asks something else
    await userEvent.type(screen.getByLabelText("Your question"), "what preheat is required");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText(/do not cover welding preheat/);

    // ...and only now does the explanation come back
    await api.release(
      0,
      askResult({
        answer_type: "generated",
        answer: "In plain terms, the coating must be 280 micrometres thick.",
        assistant_message: extractMessage({
          id: "a3",
          answer_type: "generated",
          text: "In plain terms, the coating must be 280 micrometres thick.",
          explains_id: "a1",
        }),
      }),
    );

    expect(screen.queryByText(/In plain terms/)).toBeNull();
  });

  it("shows a question once even if the transcript was reloaded while it ran", async () => {
    // The user turn is committed server-side BEFORE the answer is generated
    // (chat.ask), so any reload during those 20-50 seconds already contains
    // it. send() then appends its own copy of the same turn.
    let reloaded = false;
    const q1 = userMessage({ id: "u1", text: "what is the NDFT for coating system no. 1" });
    const api = holdableApi((url) => {
      if (url.endsWith("/ask")) return "HOLD";
      if (url.includes("/conversations/"))
        return { conversation: convA, messages: reloaded ? [q1] : [] };
      return listOf(convA);
    });

    await openChat();
    await userEvent.click(await screen.findByRole("button", { name: /^Coating systems/ }));
    await userEvent.type(
      screen.getByLabelText("Your question"),
      "what is the NDFT for coating system no. 1",
    );
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    // the reader clicks the conversation again while the answer is running
    reloaded = true;
    await userEvent.click(screen.getByRole("button", { name: /^Coating systems/ }));
    await waitFor(() => expect(screen.getByText(q1.text!)).toBeInTheDocument());

    await api.release(0, askResult({ user_message: q1, assistant_message: extractMessage({ id: "a1" }) }));

    expect(screen.getAllByText(q1.text!)).toHaveLength(1);
  });

  it("keeps the transcript of the conversation the reader ended on", async () => {
    // The reverse race: two quick clicks between conversations, where the
    // slower response wins and paints the wrong transcript under the
    // highlighted name.
    const api = holdableApi((url) => {
      if (url.includes("/conversations/conv_a")) return "HOLD";
      if (url.includes("/conversations/conv_b"))
        return {
          conversation: convB,
          messages: [userMessage({ id: "u9", text: "which welding procedure applies" })],
        };
      return listOf(convA, convB);
    });

    await openChat();
    await userEvent.click(await screen.findByRole("button", { name: /^Coating systems/ }));
    await userEvent.click(screen.getByRole("button", { name: /^Welding procedures/ }));
    await screen.findByText(/which welding procedure applies/);

    await api.release(0, {
      conversation: convA,
      messages: [userMessage({ id: "u1", text: "what is the NDFT for coating system no. 1" })],
    });

    expect(screen.getByText(/which welding procedure applies/)).toBeInTheDocument();
    expect(screen.queryByText(/what is the NDFT/)).toBeNull();
  });

  it("asks once when the Ask button is pressed twice in a fresh chat", async () => {
    // The `asking` flag is only set AFTER the conversation has been created,
    // and the button stays enabled across that await. A double-click there
    // created two conversations and spent two answers on one question.
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        urls.push(`${init?.method ?? "GET"} ${url}`);
        if (url.includes("/health")) return Promise.resolve(json(health));
        if (url.endsWith("/ask")) return new Promise<Response>(() => {}); // never resolves
        if (init?.method === "POST") return Promise.resolve(json(convA));
        return Promise.resolve(json(listOf()));
      }),
    );

    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "what is the NDFT");
    const form = screen.getByLabelText("Your question").closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitFor(() => expect(urls.some((u) => u.endsWith("/ask"))).toBe(true));

    expect(urls.filter((u) => u.endsWith("/ask"))).toHaveLength(1);
    expect(urls.filter((u) => u === "POST /api/conversations")).toHaveLength(1);
  });
});

// ------------------------------------------------- evidence that did not fit

describe("evidence dropped to fit the context window", () => {
  /**
   * The other end of the pipe from `truncated`. Output truncation has been on
   * screen since the token cap was raised; INPUT truncation was invisible, and
   * it is the worse of the two - the model answers from evidence it was never
   * given, and cites sources it never saw.
   *
   * A numeric table costs about one token per character, so three table
   * passages need ~3,645 tokens against a 1,536-token window.
   */
  it("names each source that was dropped or shortened", async () => {
    mockApi({
      ask: askResult({
        answer_type: "generated",
        answer: "The amplitude falls from 39.0 to 31.9 [S1].",
        passage: null,
        supporting: [],
        passages: [A1],
        cited: [1],
        assistant_message: extractMessage({
          text: "The amplitude falls from 39.0 to 31.9 [S1].",
          answer_type: "generated",
          payload: {
            passages: [A1],
            cited: [1],
            seconds: 40,
            evidence_removed: [
              { index: 2, filename: "book2-Differential-Equations.pdf",
                page_start: 597, action: "trimmed",
                characters_kept: 387, characters_dropped: 1006 },
              { index: 3, filename: "book2-Differential-Equations.pdf",
                page_start: 598, action: "dropped",
                characters_kept: 0, characters_dropped: 1383 },
            ],
          },
        }),
      }),
    });
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "amplitude at t=4");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(
      await screen.findByText(/2 sources did not fit the model's context window/i),
    ).toBeInTheDocument();
    // The page is the actionable part. "Some evidence was dropped" is not
    // something a reader can do anything about; "page 598 was dropped" is.
    expect(screen.getByText(/not used at all/)).toBeInTheDocument();
    expect(screen.getByText(/1,006 characters left out/)).toBeInTheDocument();
    expect(screen.getAllByText(/p59[78]/).length).toBeGreaterThan(0);
  });

  it("says nothing at all when every source fitted", async () => {
    mockApi();
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "what is the NDFT");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText(A1.text);
    expect(screen.queryByText(/did not fit the model/i)).toBeNull();
  });
});

// ------------------------------------------------ a refused Tier 2 upgrade
//
// THE DEFECT. Press "Explain in plain language" on a quoted answer. The model
// writes prose citing no supplied source, and `answer.py` refuses it — right,
// and not weakened here. But `chat.ask(explain_of=…)` persists that refusal as
// its own assistant turn, and the transcript drew it as a PEER of the extract:
// the screen said "here is your answer, quoted from page 17" and "The
// documents do not answer this" at the same time, about the same question.
//
// The fixtures below reproduce that exact stack — extract, then a message with
// `explains_id` pointing at it and `answer_type: "insufficient_evidence"`.

describe("a refused plain-language upgrade", () => {
  const REFUSAL_REASON = "the generated answer cited no supplied source";

  /** The refused upgrade, as chat.ask persists it. `over` lets a test change
   *  one field — notably `explains_id` — without losing the shape. */
  const refusedUpgrade = (over: Partial<Message> = {}): Message =>
    extractMessage({
      id: "msg_a2",
      ordinal: 3,
      text: null,
      answer_type: "insufficient_evidence",
      reason: REFUSAL_REASON,
      explains_id: "msg_a1",
      payload: { passages: [A4], cited: [], rejected_citations: [], seconds: 51.2 },
      ...over,
    });

  const transcript = (...ms: Message[]) => ({
    conversation: { conversation, messages: ms },
    conversations: {
      total: 1,
      limit: 20,
      offset: 0,
      conversations: [{ ...conversation, first_question: "q" }],
    },
  });

  async function openTranscript(...ms: Message[]) {
    mockApi(transcript(...ms));
    await openChat();
    await userEvent.click(await screen.findByRole("button", { name: /^what is the NDFT/ }));
  }

  // FIXTURE HONESTY. This project has five recorded instances of a fixture
  // that could not produce the condition its test claimed to cover. The same
  // payload, on a turn that is NOT an upgrade of anything, must still raise
  // the page-level refusal — which proves this fixture really is one that
  // reaches that branch, and that the refusal has not been suppressed
  // globally by the fix.
  it("still reads as a page-level refusal when it is not an upgrade of anything", async () => {
    await openTranscript(userMessage(), refusedUpgrade({ explains_id: null }));

    expect(await screen.findByText(/The documents do not answer this/i)).toBeInTheDocument();
    expect(screen.getByText(/Nothing was made up to fill the gap/i)).toBeInTheDocument();
  });

  it("never shows a quoted answer and a page-level refusal for the same question", async () => {
    await openTranscript(userMessage(), extractMessage(), refusedUpgrade());

    // the extract survives, whole
    expect(await screen.findByText(A1.text)).toBeInTheDocument();
    expect(screen.getByText(/Quoted verbatim from the document/i)).toBeInTheDocument();

    // THE ASSERTION THAT WOULD HAVE CAUGHT IT. Both of these were on screen
    // together, stacked, each contradicting the other.
    expect(screen.queryByText(/The documents do not answer this/i)).toBeNull();
    expect(screen.queryByText(/Nothing was made up to fill the gap/i)).toBeNull();
    expect(screen.queryByText(/What was considered, so you can judge/i)).toBeNull();
  });

  it("reports the failure as a failed upgrade, in the model's own reason", async () => {
    await openTranscript(userMessage(), extractMessage(), refusedUpgrade());

    expect(
      await screen.findByText(/The plain-language version could not be produced/i),
    ).toBeInTheDocument();
    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent(REFUSAL_REASON);
    expect(notice).toHaveTextContent(/nothing is shown rather than prose you could not check/i);
  });

  it("never shows the uncited prose the model actually wrote", async () => {
    // The refusal exists to keep this text off the screen. Scoping it must
    // not have quietly turned it back on.
    await openTranscript(
      userMessage(),
      extractMessage(),
      refusedUpgrade({ text: "Coatings are generally about 280 micrometres thick." }),
    );

    await screen.findByText(/The plain-language version could not be produced/i);
    expect(screen.queryByText(/Coatings are generally about 280/)).toBeNull();
    expect(screen.queryByText(/Written by the model/i)).toBeNull();
  });

  it("still lets the reader see what the model was given, with document and page", async () => {
    await openTranscript(userMessage(), extractMessage(), refusedUpgrade());

    await screen.findByText(/What the model was given/i);
    const notice = screen.getByRole("status");
    expect(within(notice).getByText("NORSOKM501Rev5.pdf")).toBeInTheDocument();
    expect(within(notice).getByText(/pages? 19/)).toBeInTheDocument();
    expect(within(notice).queryByText(/A.4 Coating system no. 4/)).toBeNull();
  });

  it("opens the FAILED ATTEMPT's evidence, not the extract's", async () => {
    // The two passage sets are different. Addressing the considered passages
    // by the extract's id would open A1 while the row said page 19.
    await openTranscript(userMessage(), extractMessage(), refusedUpgrade());

    const notice = await screen.findByRole("status");
    await userEvent.click(within(notice).getByText(/pages? 19/));

    const panel = await screen.findByRole("complementary", { name: "Evidence" });
    expect(within(panel).getByText(A4.text)).toBeInTheDocument();
    expect(within(panel).queryByText(A1.text)).toBeNull();
  });

  it("offers the upgrade again, labelled as a retry rather than as a first go", async () => {
    // A refused upgrade put nothing on screen, so the "already explained"
    // guard does not apply — but the button must not pretend nothing happened.
    await openTranscript(userMessage(), extractMessage(), refusedUpgrade());

    expect(
      await screen.findByRole("button", { name: /Try the plain-language version again/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Explain in plain language$/i })).toBeNull();
  });

  it("keeps hiding the button when the upgrade SUCCEEDED", async () => {
    await openTranscript(
      userMessage(),
      extractMessage(),
      extractMessage({
        id: "msg_a2",
        ordinal: 3,
        text: "The thickness is 280 um [S1].",
        answer_type: "generated",
        explains_id: "msg_a1",
        payload: { passages: [A1], cited: [1], model: "qwen3.5:4b", seconds: 51.8 },
      }),
    );

    await screen.findByText(/Written by the model/i);
    expect(screen.queryByRole("button", { name: /plain-language version again/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Explain in plain/i })).toBeNull();
  });

  it("does not swallow a failed upgrade whose answer is not on screen", async () => {
    // Nothing to attach it to. Reporting it nowhere would be the other half
    // of this defect: an attempt that silently looks like it never ran.
    await openTranscript(userMessage(), refusedUpgrade({ explains_id: "msg_gone" }));

    expect(await screen.findByText(/The documents do not answer this/i)).toBeInTheDocument();
  });

  it("scopes the failure when it arrives live, from pressing the button", async () => {
    mockApi({
      ask: (() => {
        let n = 0;
        return () => {
          n += 1;
          if (n === 1) return askResult();
          return askResult({
            answer_type: "insufficient_evidence",
            answer: null,
            reason: REFUSAL_REASON,
            passage: null,
            supporting: [],
            passages: [A4],
            assistant_message: refusedUpgrade(),
          });
        };
      })(),
    });
    await openChat();
    await userEvent.type(screen.getByLabelText("Your question"), "what is the NDFT");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await userEvent.click(await screen.findByRole("button", { name: /Explain in plain/i }));

    expect(
      await screen.findByText(/The plain-language version could not be produced/i),
    ).toBeInTheDocument();
    expect(screen.getByText(A1.text)).toBeInTheDocument();
    expect(screen.queryByText(/The documents do not answer this/i)).toBeNull();
  });

  // Rule: "backend offline" and "that request failed" must never look the
  // same. A refused upgrade and an upgrade that never ran are both failures
  // of the same button, and only one of them has anything the reader can do.
  it("distinguishes the model being down from the model being refused", async () => {
    await openTranscript(
      userMessage(),
      extractMessage(),
      refusedUpgrade({
        answer_type: "model_unavailable",
        reason: "the local answer model could not be reached (ConnectError)",
        payload: { passages: [A1], seconds: 0.1 },
      }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/local answer model is not running/i);
    expect(alert).toHaveTextContent("ollama serve");
    expect(alert).toHaveTextContent(/This is the machine, not your question/i);

    // not the refusal wording, and not the page-level one either
    expect(screen.queryByText(/cited no supplied source/i)).toBeNull();
    expect(screen.queryByText(/The documents do not answer this/i)).toBeNull();
    expect(screen.getByText(A1.text)).toBeInTheDocument();
  });
});
