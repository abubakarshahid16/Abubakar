/**
 * #645: the AI's proposed checks, shown as proposals with the clause words
 * beside them; only an administrator may accept or reject one.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ClauseCheckDrafts } from "./ClauseCheckDrafts";
import type { ClauseCheckDraft } from "../../types/api";

const draft: ClauseCheckDraft = {
  id: "d1", requirement_id: "r1", standard_document_id: "std", clause: "5.1", page: 3,
  source_text: "The cold differential test pressure shall not exceed 12 barg.",
  field: "cold differential test pressure", operator: "<=", value: "12", unit: "barg",
  condition: null, quote: "cold differential test pressure shall not exceed 12 barg",
  model: "m", status: "draft", decided_at: null, new_requirement_id: null,
};

function mockFetch(rows: ClauseCheckDraft[], posts: { url: string; body: unknown }[] = []) {
  let current = rows;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const json = (b: unknown) => new Response(JSON.stringify(b),
      { status: 200, headers: { "Content-Type": "application/json" } });
    if (init?.method === "POST") {
      posts.push({ url, body: JSON.parse(String(init.body)) });
      current = [];
      return json({ id: "d1", decision: "accept", status: "accepted", new_requirement_id: "r2" });
    }
    return json(current);
  }));
}

afterEach(() => vi.unstubAllGlobals());

describe("ClauseCheckDrafts", () => {
  it("shows a draft as a proposal with the clause sentence and the quoted words", async () => {
    mockFetch([draft]);
    render(<ClauseCheckDrafts />);
    const row = await screen.findByTestId("clause-check-d1");
    expect(row).toHaveTextContent("Proposed check: cold differential test pressure <= 12 barg");
    expect(row).toHaveTextContent("Clause 5.1, page 3: The cold differential test pressure");
    expect(row).toHaveTextContent("Stands on the words:");
  });

  it("offers no decision to a reader who is not an administrator", async () => {
    mockFetch([draft]);
    render(<ClauseCheckDrafts />);
    await screen.findByTestId("clause-check-d1");
    expect(screen.queryByRole("button", { name: "Accept as a requirement" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
  });

  it("lets an administrator accept, then shows the list without it", async () => {
    const posts: { url: string; body: unknown }[] = [];
    mockFetch([draft], posts);
    render(<ClauseCheckDrafts isAdmin />);
    fireEvent.click(await screen.findByRole("button", { name: "Accept as a requirement" }));
    await waitFor(() => expect(screen.getByText("No proposals are waiting.")).toBeInTheDocument());
    expect(posts).toEqual([{ url: expect.stringContaining("/standards/clause-checks/d1/decision"),
                             body: { decision: "accept" } }]);
  });

  it("names the condition a limit holds under", async () => {
    mockFetch([{ ...draft, condition: "For sour service" }]);
    render(<ClauseCheckDrafts />);
    expect(await screen.findByTestId("clause-check-d1")).toHaveTextContent("only For sour service");
  });
});
