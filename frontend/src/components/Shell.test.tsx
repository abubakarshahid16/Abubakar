/**
 * Shell behaviour that must not regress.
 *
 * The rule under test throughout: when the backend is unreachable the UI says
 * so plainly, rather than spinning or presenting the last numbers it saw as
 * though they were live.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import type { Health } from "../api/client";

const healthOnline: Health = {
  ok: true,
  embed_model_present: true,
  answer_model: "qwen3.5:4b",
  ingestion: {
    alive: true,
    current_document: null,
    seconds_since_heartbeat: 0.4,
    seconds_since_progress: 12,
    documents_completed: 5,
    pending_count: 0,
    oldest_pending_age_seconds: null,
    stalled: false,
    stalled_reasons: [],
    last_error: null,
  },
};

function mockFetch(impl: (url: string) => Promise<Response> | Response) {
  const spy = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    return Promise.resolve(impl(url));
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => vi.useRealTimers());
afterEach(() => vi.unstubAllGlobals());

describe("shell navigation", () => {
  it("lists all four views and marks the unbuilt ones", async () => {
    mockFetch(() => json(healthOnline));
    render(<App />);

    for (const label of ["Documents", "Chat", "Ingestion", "Dashboard"]) {
      expect(screen.getByRole("button", { name: new RegExp(label) })).toBeInTheDocument();
    }
    // Documents and Chat are built; the remaining two must be visibly marked
    expect(screen.getAllByText(/not built/i)).toHaveLength(2);
  });

  it("navigates to an unbuilt view and says it is not built rather than faking it", async () => {
    mockFetch(() => json(healthOnline));
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: /Ingestion/ }));
    expect(await screen.findByText(/Not built yet/i)).toBeInTheDocument();
  });

  it("marks the current view for assistive technology", async () => {
    mockFetch(() => json(healthOnline));
    render(<App />);
    const documents = screen.getByRole("button", { name: /Documents/ });
    expect(documents).toHaveAttribute("aria-current", "page");
  });

  it("is reachable by keyboard, with a skip link first", async () => {
    mockFetch(() => json(healthOnline));
    const user = userEvent.setup();
    render(<App />);
    await user.tab();
    expect(screen.getByRole("link", { name: /skip to content/i })).toHaveFocus();
  });
});

describe("connection state", () => {
  it("says the backend is not running when health cannot be reached", async () => {
    mockFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    render(<App />);

    expect(await screen.findByText(/backend is not running/i)).toBeInTheDocument();
    expect(screen.getByText(/Backend offline/i)).toBeInTheDocument();
  });

  it("does not present stale numbers as live after the backend goes away", async () => {
    let online = true;
    mockFetch(() => (online ? json(healthOnline) : Promise.reject(new TypeError("down"))));
    render(<App />);

    // connected first, so the model name is on screen
    expect(await screen.findByText("qwen3.5:4b")).toBeInTheDocument();

    online = false;
    // the poller re-checks; the badge must flip and the warning must appear
    await waitFor(
      () => expect(screen.getByText(/backend is not running/i)).toBeInTheDocument(),
      { timeout: 8000 },
    );
    expect(screen.getByText(/may be out of date/i)).toBeInTheDocument();
  }, 15000);

  it("surfaces a stalled worker even while the API itself is reachable", async () => {
    mockFetch(() =>
      json({
        ...healthOnline,
        ingestion: {
          ...healthOnline.ingestion,
          stalled: true,
          pending_count: 6,
          stalled_reasons: ["6_pending_but_no_progress_for_240s"],
        },
      }),
    );
    render(<App />);
    expect(await screen.findByText(/Worker stalled/i)).toBeInTheDocument();
  });

  it("offers a retry that re-attempts the connection", async () => {
    let attempts = 0;
    mockFetch(() => {
      attempts += 1;
      return Promise.reject(new TypeError("down"));
    });
    const user = userEvent.setup();
    render(<App />);

    await screen.findByText(/backend is not running/i);
    const before = attempts;
    await user.click(screen.getByRole("button", { name: /retry connection/i }));
    await waitFor(() => expect(attempts).toBeGreaterThan(before));
  });
});
