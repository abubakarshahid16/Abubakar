/**
 * The comparison-scope notice, at the level of the screen rather than the card.
 *
 * `AnswerCard` can only say "answered from one document" if something hands it
 * the question the reader actually asked. THE DEFECT LIVED IN THE WIRING: the
 * composer sends every question as `tier: "extract"`, there is no mode
 * selector on Chat, and the transcript rendered the answer with no notion of
 * what had been asked — so "compare the mechanical requirements from all
 * documents" came back as one passage from one document with nothing said
 * about the comparison that never happened.
 *
 * comparisonScope.test.tsx holds the matcher and the card. This holds the join
 * between them: the question travels from the user turn to the answer beneath
 * it, and only the answer beneath it.
 */
import { render, screen } from "@testing-library/react";
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

const DOC13: AnswerPassage = {
  chunk_id: "doc13:p00204:c00311:aa11",
  document_id: "doc13",
  filename: "MechanicalSpecification.pdf",
  page_start: 204,
  page_end: 205,
  section: "10.1 General Procedure",
  text: "The mechanical completion procedure shall be carried out in accordance with clause 10.",
  highlight: null,
  match_span: null,
  chunks_joined: 1,
  kind: "prose",
  score: 6.1,
  identifier_hits: [],
  text_source: "extracted",
  ocr_min_conf: null,
  ocr_alphabet_violations: 0,
  ocr_alphabet_sample: null,
};

/** The two passages the original transcript collapsed into "2 other passages
 *  matched" — from OTHER documents, which is precisely why the answer needed
 *  to say it had not compared them. */
const DOC15: AnswerPassage = {
  ...DOC13,
  chunk_id: "doc15:p00042:c00099:bb22",
  document_id: "doc15",
  filename: "PipingSpecification.pdf",
  page_start: 42,
  page_end: 42,
  section: "4.2 Mechanical requirements",
  text: "Mechanical requirements for piping supports are given in table 4.",
};

const DOC16: AnswerPassage = {
  ...DOC13,
  chunk_id: "doc16:p00007:c00012:cc33",
  document_id: "doc16",
  filename: "StructuralSpecification.pdf",
  page_start: 7,
  page_end: 7,
  section: "2.1 Scope",
  text: "Mechanical requirements for structural steelwork are given in annex B.",
};

const conversation: Conversation = {
  id: "conv_cmp",
  title: "compare the mechanical requirements",
  document_id: null,
  message_count: 2,
  created_at: "2026-09-04T00:00:00Z",
  updated_at: "2026-09-04T00:00:00Z",
};

function userMessage(text: string): Message {
  return {
    id: "msg_u1",
    conversation_id: conversation.id,
    ordinal: 1,
    role: "user",
    text,
    resolved_question: text,
    carried_terms: [],
    answer_type: null,
    reason: null,
    explains_id: null,
    payload: null,
    created_at: "2026-09-04T00:00:00Z",
  };
}

function assistantMessage(): Message {
  return {
    id: "msg_a1",
    conversation_id: conversation.id,
    ordinal: 2,
    role: "assistant",
    text: DOC13.text,
    resolved_question: null,
    carried_terms: [],
    answer_type: "extract",
    reason: null,
    explains_id: null,
    payload: {
      passage: DOC13,
      supporting: [DOC15, DOC16],
      passages: [],
      cited: [],
      rejected_citations: [],
      seconds: 1.4,
    },
    created_at: "2026-09-04T00:00:00Z",
  };
}

function mockApi(question: string) {
  const spy = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const body = (() => {
      if (url.includes("/health")) return health;
      if (url.endsWith("/ask")) {
        return {
          question,
          answer_type: "extract",
          answer: DOC13.text,
          reason: null,
          passage: DOC13,
          supporting: [DOC15, DOC16],
          passages: [],
          cited: [],
          rejected_citations: [],
          retrieval_mode: "hybrid",
          reranked: true,
          candidates_considered: 20,
          model: null,
          prompt_tokens: null,
          output_tokens: null,
          seconds: 1.4,
          timings: {},
          conversation,
          user_message: userMessage(question),
          assistant_message: assistantMessage(),
          resolved_question: question,
          carried_terms: [],
        };
      }
      if (url.includes("/conversations/")) return { conversation, messages: [] };
      if (url.includes("/conversations")) {
        if (init?.method === "POST") return conversation;
        return { total: 0, limit: 20, offset: 0, conversations: [] };
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
}

async function ask(question: string) {
  mockApi(question);
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: /Document Q&A/ }));
  await userEvent.type(screen.getByLabelText("Your question"), question);
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));
  // The quoted answer is on screen before anything is asserted about the
  // notice beside it; an absent notice under an absent answer proves nothing.
  expect(await screen.findByText(DOC13.text)).toBeInTheDocument();
}

afterEach(() => vi.unstubAllGlobals());

describe("a comparison asked in Chat is answered with its scope stated", () => {
  it("says the answer came from one document, and that Chat does not compare", async () => {
    await ask("please compare the mechanical requirements from all documents");
    const notice = await screen.findByRole("note");
    expect(notice.textContent).toMatch(/Answered from 1 document\b/);
    expect(notice.textContent).toMatch(/comparison across the corpus is not performed in Chat/i);
  });

  it("still shows the passages it did match, unchanged", async () => {
    // The notice ADDS a statement. It must not quietly remove the evidence the
    // reader already had, or it trades one omission for another.
    await ask("please compare the mechanical requirements from all documents");
    expect(screen.getByText(/2 other passages matched/i)).toBeInTheDocument();
  });

  it("says nothing of the kind for an ordinary question", async () => {
    await ask("what does clause 10.1 require for mechanical completion");
    expect(screen.queryByRole("note")).toBeNull();
  });
});
