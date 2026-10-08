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
  answer_model_present: true,
  ingestion: {
    // /api/health is unauthenticated and carries only
    // these three. The full worker status is on /api/metrics.
    alive: true,
    stalled: false,
    busy: false,
  },
};

/** Enough of /api/metrics for the Ingestion screen to actually render. */
const ingestionMetrics = {
  refresh_seconds: 15,
  throughput: {
    extract: { unit: "pages/s", samples: 2, median: 277.6, best: 280.1,
               items_total: 1400 },
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
    // All four are built now. Ingestion was the last placeholder; the badge
    // machinery stays for the next unbuilt route, but nothing wears it.
    expect(screen.queryByText(/not built/i)).toBeNull();
  });

  it("renders the ingestion screen rather than a placeholder", async () => {
    // Route-aware, not one body for every endpoint. The previous fixture
    // answered /documents with the HEALTH object, and the screen only looked
    // healthy because a shape guard degraded it to a spinner - so this test
    // asserted "Reading the queue" and called that success. A fixture that
    // cannot produce the real screen is not testing the real screen.
    mockFetch((url) => {
      if (url.includes("/documents")) return json([]);
      if (url.includes("/metrics")) return json(ingestionMetrics);
      return json(healthOnline);
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: /Ingestion/ }));
    // The screen it replaced said "Not built yet. This screen is a placeholder
    // so the navigation is honest about what exists." Honest, and no longer
    // necessary.
    expect(await screen.findByText(/Throughput|Reading the queue/)).toBeInTheDocument();
    expect(screen.queryByText(/Not built yet/i)).toBeNull();
    expect(screen.queryByText(/placeholder/i)).toBeNull();
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

    // Connected first. The badge says a model is CONFIGURED, not which one -
    // /api/health is unauthenticated and the exact name and version is
    // fingerprinting material. The name is on the Dashboard, from the scoped
    // metrics route.
    expect(await screen.findByText(/answer model configured/i)).toBeInTheDocument();
    expect(screen.queryByText("qwen3.5:4b")).toBeNull();

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
    expect(await screen.findByText(/Queue not moving/i)).toBeInTheDocument();
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

describe("connection stability", () => {
  it("does not hand the screen to the outage banner for one failed poll", async () => {
    let polls = 0;
    let failOn = -1;
    mockFetch((url) => {
      if (!url.includes("/health")) return json([]);
      polls += 1;
      return polls === failOn ? Promise.reject(new TypeError("blip")) : json(healthOnline);
    });
    render(<App />);
    expect(await screen.findByText(/answer model configured/i)).toBeInTheDocument();

    failOn = polls + 1;
    // Wait until the poll AFTER the failed one has been sent: with a single
    // failure treated as an outage, the banner is on screen at this moment
    // and the view beneath it has been unmounted.
    await waitFor(() => expect(polls).toBeGreaterThan(failOn), { timeout: 9000 });
    expect(screen.queryByText(/backend is not running/i)).toBeNull();
    expect(screen.queryByText(/Backend offline/i)).toBeNull();
  }, 15000);

  it("does not say the backend is not running when health ANSWERS with an error", async () => {
    let polls = 0;
    let failing = false;
    mockFetch((url) => {
      if (!url.includes("/health")) return json([]);
      polls += 1;
      return failing
        ? new Response(JSON.stringify({ detail: "database is locked" }), {
            status: 500, headers: { "Content-Type": "application/json" },
          })
        : json(healthOnline);
    });
    render(<App />);
    expect(await screen.findByText(/answer model configured/i)).toBeInTheDocument();

    failing = true;
    const from = polls;
    await waitFor(() => expect(polls).toBeGreaterThan(from + 1), { timeout: 12000 });
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText(/backend is not running/i)).toBeNull();
  }, 20000);
});
