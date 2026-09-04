/**
 * One connection-level error at a time, and never a raw code on screen.
 *
 * With the backend down the shell rendered its amber "backend is not running"
 * banner AND let the view render its own red card reading "Request failed /
 * HTTP 502 / code: internal". Two errors for one condition, one of them in
 * language a reader cannot act on.
 */
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { ErrorState } from "./components/states";
import type { ApiError } from "./types/api";

function mockAllFailing(status?: number) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      status === undefined
        ? Promise.reject(new TypeError("Failed to fetch"))
        : Promise.resolve(
            new Response(JSON.stringify({ detail: "gateway" }), {
              status,
              headers: { "Content-Type": "application/json" },
            }),
          ),
    ),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("one connection error at a time", () => {
  it("shows only the disconnected banner when the backend is unreachable", async () => {
    mockAllFailing();
    render(<App />);
    expect(await screen.findByText(/The backend is not running/i)).toBeInTheDocument();
    // and NOT a second card for the same condition
    expect(screen.queryByText(/Request failed/i)).toBeNull();
    expect(screen.queryByText(/Something went wrong/i)).toBeNull();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("treats a gateway status as the backend being unreachable, not as an API error", async () => {
    mockAllFailing(502);
    render(<App />);
    expect(await screen.findByText(/The backend is not running/i)).toBeInTheDocument();
    expect(screen.queryByText(/502/)).toBeNull();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("does not render the view at all while the shell owns the error", async () => {
    mockAllFailing();
    render(<App />);
    await screen.findByText(/The backend is not running/i);
    // the Documents view's own headings must be absent
    expect(screen.queryByText(/Upload a PDF/i)).toBeNull();
    expect(screen.queryByText("Corpus")).toBeNull();
  });
});

describe("no raw codes or statuses on a client-facing screen", () => {
  it("titles an error in words rather than printing its code", () => {
    render(
      <ErrorState
        error={{ code: "internal", message: "The backend hit an unexpected error." }}
      />,
    );
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.queryByText(/code:/i)).toBeNull();
    expect(screen.queryByText(/internal/)).toBeNull();
  });

  it("uses the right title for a known code", () => {
    render(<ErrorState error={{ code: "not_found", message: "No document with that id" }} />);
    expect(screen.getByText("Not found")).toBeInTheDocument();
  });

  it("falls back to a human title for an unrecognised code", () => {
    // The cast is the point of the test. `code` is a closed union, so the
    // type system says this cannot happen - but the union is a CONTRACT with
    // the backend, and the screen has to survive the backend adding a code
    // before the frontend knows about it. Without a fallback the title would
    // render as undefined.
    const rogue = { code: "something_new", message: "Unexpected." } as unknown as ApiError;
    render(<ErrorState error={rogue} />);
    expect(screen.getByText("That did not work")).toBeInTheDocument();
    expect(screen.queryByText(/something_new/)).toBeNull();
  });

  it("never shows a bare HTTP status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        // health succeeds so the shell is online; the documents call 500s
        const ok = url.includes("/health");
        return Promise.resolve(
          new Response(
            JSON.stringify(
              ok
                ? {
                    ok: true,
                    embed_model_present: true,
                    answer_model: "qwen3.5:4b",
                    ingestion: {
                      alive: true,
                      current_document: null,
                      seconds_since_heartbeat: 0.1,
                      seconds_since_progress: 1,
                      documents_completed: 0,
                      pending_count: 0,
                      oldest_pending_age_seconds: null,
                      stalled: false,
                      stalled_reasons: [],
                      last_error: null,
                    },
                  }
                : { detail: "boom" },
            ),
            { status: ok ? 200 : 500, headers: { "Content-Type": "application/json" } },
          ),
        );
      }),
    );
    render(<App />);
    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText(/details are in its log/i)).toBeInTheDocument();
    expect(screen.queryByText(/HTTP 500/)).toBeNull();
    expect(screen.queryByText(/500/)).toBeNull();
  });
});
