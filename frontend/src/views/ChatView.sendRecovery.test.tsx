/**
 * One rejected request must not kill sending until a reload.
 *
 * Two causes are covered: a 200 whose body is not JSON (a proxy's page), and
 * a call that rejects outright. After either, the next question is sent.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { api } from "../api/client";
import type { Health } from "../api/client";

const health: Health = {
  ok: true, embed_model_present: true, answer_model_configured: true,
  ingestion: { alive: true, stalled: false, busy: false },
};
const conv = {
  id: "conv_1", title: "t", document_id: null, message_count: 0,
  created_at: "2026-09-26T00:00:00Z", updated_at: "2026-09-26T00:00:00Z",
};
const json = (body: unknown) =>
  new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

function stub(onCreate: () => Response) {
  const created: string[] = [];
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/health")) return Promise.resolve(json(health));
    if (url.endsWith("/ask") || url.endsWith("/ask/stream")) return new Promise<Response>(() => {});
    if (url.includes("/conversations") && init?.method === "POST") {
      created.push(url);
      return Promise.resolve(onCreate());
    }
    if (url.includes("/conversations")) {
      return Promise.resolve(json({ total: 0, limit: 20, offset: 0, conversations: [] }));
    }
    return Promise.resolve(json([]));
  }));
  return created;
}

async function openChat() {
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: /^Chat/ }));
}

async function submit() {
  const box = screen.getByLabelText("Your question") as HTMLTextAreaElement;
  if (!box.value) await userEvent.type(box, "what is the NDFT");
  fireEvent.submit(box.closest("form")!);
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("sending recovers after a failure", () => {
  it("a non-JSON 200 shows a failure and the next question is still sent", async () => {
    let n = 0;
    const created = stub(() => (n++ === 0
      ? new Response("<html>proxy</html>", { status: 200, headers: { "Content-Type": "text/html" } })
      : json(conv)));
    await openChat();
    await submit();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await submit();
    await waitFor(() => expect(created).toHaveLength(2));
  });

  it("a rejected call is shown as a failure and does not block the next question", async () => {
    const created = stub(() => json(conv));
    vi.spyOn(api, "newConversation").mockRejectedValueOnce(new Error("boom"));
    await openChat();
    await submit();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await submit();
    await waitFor(() => expect(created).toHaveLength(1));
  });
});
