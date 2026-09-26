/**
 * The Chat screen in a real browser (owner order 2026-09-26, PR 7).
 *
 * Every /api call is answered here, so nothing reaches a backend, a model
 * or a document - see playwright.chat.config.ts. Sample data only.
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const conv = {
  id: "conv_1", title: "Hydrotest requirements", document_id: null, message_count: 0,
  created_at: "2026-09-26T00:00:00Z", updated_at: "2026-09-26T00:00:00Z",
};

const PASSAGE = {
  chunk_id: "c1", document_id: "d1", filename: "sample-datasheet.pdf", page_start: 5, page_end: 5,
  section: "Sheet 5", text: "Row 9 Hydrostatic test pressure basis per project pressure standard.",
  highlight: null, match_span: null, chunks_joined: 1, text_source: "extracted", ocr_min_conf: null,
  ocr_alphabet_violations: 0, ocr_alphabet_sample: null, kind: "prose", score: 3, identifier_hits: [],
};

function message(id: string, role: "user" | "assistant", text: string, over: Record<string, unknown> = {}) {
  return {
    id, conversation_id: "conv_1", ordinal: 1, role, text, resolved_question: role === "user" ? text : null,
    carried_terms: [], answer_type: role === "assistant" ? "general" : null, reason: null, explains_id: null,
    payload: role === "assistant" ? { passages: [] } : null, created_at: "2026-09-26T00:00:00Z", notices: [],
    ...over,
  };
}

const documentAnswer = message("a1", "assistant", "**Partly.** The test pressure is covered [S1].", {
  answer_type: "generated", answer_kind: "document",
  payload: { passages: [PASSAGE], cited: [1], rejected_citations: [], model: "claude", seconds: 6 },
  used_line: "Checked your submittal · Claude · 6 s",
  verification: { verified: 1, total: 1, method: "quote found on the page" },
  steps: [{ label: "Searched your documents", count: 20, done: true }],
  sources: [{ n: 1, kind: "document", document_id: "d1", display_name: "Sample datasheet", document_number: "DS-1",
              page: 5, page_end: 5, clause: "Sheet 5", text_source: "extracted", ocr_min_conf: null, url: null,
              cited: true, quotes: ["Hydrostatic test pressure basis"], rows: [] }],
  suggestions: ["Write that as a comment"],
});

const generalAnswer = message("a2", "assistant", "Sulfidation is sulfur attack on hot steel.", {
  answer_kind: "general", used_line: "General knowledge, not from your documents · Claude · 3 s",
});

function sse(events: [string, unknown][]): string {
  return events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");
}

function done(question: string, answer: Record<string, unknown>) {
  return {
    question, answer_type: answer.answer_type, answer: answer.text, reason: null, passage: null,
    supporting: [], passages: [], cited: [], rejected_citations: [], conversation: conv,
    user_message: message("u_" + String(answer.id), "user", question), assistant_message: answer,
    resolved_question: question, carried_terms: [],
  };
}

interface Api {
  calls: { url: string; method: string; body: string | null }[];
  stream: (body: Record<string, unknown>, route: Route) => Promise<void>;
  messages: unknown[];
  conversations: unknown[];
}

async function mockApi(page: Page, api: Partial<Api> = {}): Promise<Api> {
  const state: Api = {
    calls: [],
    messages: [],
    conversations: [],
    stream: async (_body, route) => {
      await route.fulfill({ status: 200, contentType: "text/event-stream",
                            body: sse([["turn", { turn_id: "t1" }], ["done", done("q", documentAnswer)]]) });
    },
    ...api,
  };
  await page.route(/^http:\/\/127\.0\.0\.1:5173\/api\//, async (route) => {
    const req = route.request();
    const url = req.url();
    state.calls.push({ url, method: req.method(), body: req.postData() });
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(b) });
    if (url.includes("/health")) return json({ ok: true, embed_model_present: true, answer_model_present: true, ingestion: { alive: true, stalled: false, busy: false } });
    if (url.includes("/auth/me")) return json({ required: false, user: null });
    if (url.includes("/chat/models")) return json({ default: "claude", web_available: true, web_reason: null, models: [
      { id: "claude", label: "Claude", model: "m", available: true, reason: null },
      { id: "local", label: "Local model", model: "l", available: true, reason: null }] });
    if (url.endsWith("/ask/stream")) return state.stream(JSON.parse(req.postData() ?? "{}"), route);
    if (url.includes("/cancel")) return json({ turn_id: "t1", cancelled: true });
    if (url.includes("/comment") && req.method() === "POST") return json({
      finding_id: "f1", message_id: "a3", document_id: "d1", document_name: "Sample datasheet",
      review_run_id: "run_1", chat_comments_on_sheet: 1, undo_until: new Date(Date.now() + 300_000).toISOString() });
    if (url.includes("/comment/") && req.method() === "DELETE") return json({ finding_id: "f1", withdrawn: true });
    if (url.includes("/conversations/") && req.method() === "DELETE") return json({ id: "conv_1", deleted: true });
    if (url.includes("/conversations/")) return json({ conversation: conv, messages: state.messages });
    if (url.includes("/conversations")) {
      if (req.method() === "POST") return json(conv);
      return json({ total: state.conversations.length, limit: 50, offset: 0, conversations: state.conversations });
    }
    return json([]);
  });
  return state;
}

async function openChat(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /^Chat/ }).click();
  await expect(page.getByRole("heading", { name: "What can I help with?" })).toBeVisible();
}

test("a question streams in, shows how many points were found, and opens its source", async ({ page }) => {
  const api = await mockApi(page);
  await openChat(page);
  await page.getByLabel("Your question").fill("does the datasheet meet the hydrotest requirement");
  await page.keyboard.press("Enter");

  await expect(page.getByTestId("used-line")).toHaveText("Checked your submittal · Claude · 6 s");
  await expect(page.getByText("1 of 1 point found on the page")).toBeVisible();
  await expect(page.getByText("Written by the model · claude — not the document's words")).toBeVisible();

  await page.getByRole("button", { name: "Source 1" }).first().click();
  const preview = page.getByRole("region", { name: "Source 1 preview" });
  await expect(preview.getByText("Sample datasheet")).toBeVisible();
  await expect(preview.locator("mark")).toHaveText("Hydrostatic test pressure basis");

  const body = JSON.parse(api.calls.find((c) => c.url.endsWith("/ask/stream"))!.body!);
  expect(body).toMatchObject({ question: "does the datasheet meet the hydrotest requirement", tier: "generated", model: "claude" });
});

test("Stop ends an answer that has not started, and the chat reloads", async ({ page }) => {
  let release: (() => void) | null = null;
  const api = await mockApi(page, {
    stream: (_body, route) => new Promise<void>((resolve) => {
      release = () => { void route.abort().catch(() => undefined); resolve(); };
    }),
  });
  await openChat(page);
  await page.getByLabel("Your question").fill("a long question");
  await page.keyboard.press("Enter");
  const stop = page.getByRole("button", { name: /Stop/ });
  await expect(stop).toBeVisible();
  await stop.click();
  await expect(stop).toBeHidden();
  await expect.poll(() => api.calls.filter((c) => c.method === "GET" && c.url.includes("/conversations/conv_1")).length)
    .toBeGreaterThan(0);
  (release as (() => void) | null)?.();
});

test("general knowledge is labelled, cites nothing, and can be rewritten", async ({ page }) => {
  const api = await mockApi(page, {
    stream: async (body, route) => {
      const answer = String(body.question).startsWith("Give me") ? { ...generalAnswer, id: "a2b" } : generalAnswer;
      await route.fulfill({ status: 200, contentType: "text/event-stream",
                            body: sse([["done", done(String(body.question), answer)]]) });
    },
  });
  await openChat(page);
  await page.getByLabel("Your question").fill("what is sulfidation");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("used-line")).toContainText("General knowledge, not from your documents");
  await expect(page.getByRole("button", { name: /^Source \d/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Points", exact: true }).click();
  await expect.poll(() => api.calls.filter((c) => c.url.endsWith("/ask/stream")).length).toBe(2);
  expect(JSON.parse(api.calls.filter((c) => c.url.endsWith("/ask/stream"))[1].body!).question).toBe("Give me that in points");
});

test("a drafted comment is filed only when pressed, and can be undone", async ({ page }) => {
  const draft = message("a3", "assistant", "Please state the chloride limit.", {
    answer_kind: "action", used_line: "Drafted from the previous answer · 2 s",
    draft: { type: "comment", text: "Please state the chloride limit.", status: "draft", source_ids: ["d1"] },
  });
  const api = await mockApi(page, {
    conversations: [conv],
    messages: [message("u1", "user", "write that as a comment"), { ...draft, ordinal: 2 }],
  });
  await openChat(page);
  await page.getByRole("region", { name: "Recent chats" }).getByRole("button", { name: "Hydrotest requirements", exact: true }).click();
  const card = page.getByRole("region", { name: "Draft comment" });
  await expect(card.getByText("Needs an engineer")).toBeVisible();
  expect(api.calls.some((c) => c.url.includes("/comment"))).toBe(false);

  await card.getByRole("button", { name: "Add to comment sheet" }).click();
  await expect(card.getByText(/Added to the comment sheet for Sample datasheet, under your name\./)).toBeVisible();
  await card.getByRole("button", { name: "Undo" }).click();
  await expect(card.getByText(/Withdrawn\./)).toBeVisible();
  expect(api.calls.some((c) => c.method === "DELETE" && c.url.endsWith("/comment/f1"))).toBe(true);
});

test("a web question asks first and sends nothing until Search once", async ({ page }) => {
  const consent = message("a4", "assistant", 'I can search the web for "newer edition iso 12944". Search once?', {
    answer_type: "web_consent", answer_kind: "web", used_line: "Nothing has been sent",
    payload: { passages: [], web_phrase: "newer edition iso 12944", web_available: true },
  });
  const api = await mockApi(page, { conversations: [conv], messages: [message("u1", "user", "newer edition online?"), { ...consent, ordinal: 2 }] });
  await openChat(page);
  await page.getByRole("region", { name: "Recent chats" }).getByRole("button", { name: "Hydrotest requirements", exact: true }).click();
  const offer = page.getByRole("group", { name: "Web search" });
  await expect(offer.getByText('"newer edition iso 12944"')).toBeVisible();
  await offer.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByText("Not searched. Nothing was sent.")).toBeVisible();
  expect(api.calls.some((c) => c.url.endsWith("/web-search"))).toBe(false);
});

test("a recent chat is deleted only after asking, and Undo keeps it", async ({ page }) => {
  const api = await mockApi(page, { conversations: [conv] });
  await openChat(page);
  const recent = page.getByRole("region", { name: "Recent chats" });
  await recent.getByRole("button", { name: "Hydrotest requirements", exact: true }).hover();
  await recent.getByRole("button", { name: "Delete conversation Hydrotest requirements" }).click();
  await recent.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(recent.getByRole("button", { name: "Hydrotest requirements", exact: true })).toHaveCount(0);
  await recent.getByRole("button", { name: "Undo" }).click();
  await expect(recent.getByRole("button", { name: "Hydrotest requirements", exact: true })).toBeVisible();
  expect(api.calls.some((c) => c.method === "DELETE")).toBe(false);
});
