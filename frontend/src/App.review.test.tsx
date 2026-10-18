/**
 * Order 95 piece 2 (Part of #967), with `CRS_SHEET_IS_DEFAULT = false` (the
 * value it ships with): `/review/<run>` is the current card view, also at
 * `/review/<run>/cards`; the new comment sheet is at `/review/<run>/crs-sheet`;
 * the behind-the-scenes pages (the old "crs" page among them) keep their
 * addresses. `App.review.crsDefault.test.tsx` covers the value `true`.
 *
 * MUTATION PROOF: route `/review/<run>` to the new sheet and the first test
 * fails; drop "crs-sheet" from `PANELS.review` and the second is refused as
 * an unknown address; drop "cards" and the third is.
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { setToken } from "./api/client";

vi.mock("./views/CrsSheetView", () => ({
  CrsSheetView: ({ runId }: { runId: string }) => <p>{`crs sheet for ${runId}`}</p>,
}));
vi.mock("./views/ReviewSheetView", () => ({
  ReviewSheetView: ({ runId, panel }: { runId: string; panel?: string }) => <p>{`cards for ${runId}${panel ? ` panel ${panel}` : ""}`}</p>,
}));
vi.mock("./views/SubmittalsLandingView", () => ({
  SubmittalsLandingView: () => <p>landing</p>,
}));

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function mockApi() {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/auth/me")) return Promise.resolve(json({ required: false, user: null }));
    if (url.includes("/documents")) return Promise.resolve(json([]));
    if (url.includes("/metrics")) return Promise.resolve(json({ refresh_seconds: 15 }));
    return Promise.resolve(json({ ok: true, embed_model_present: true, answer_model_configured: true, ingestion: { alive: true, stalled: false, busy: false } }));
  }));
}

async function goTo(path: string) {
  await act(async () => {
    window.history.pushState({}, "", path);
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  setToken(null);
  window.history.pushState({}, "", "/");
});

describe("the review routes (the card view is the default)", () => {
  it("/review/<run> opens the current card view", async () => {
    mockApi();
    render(<App initialView="review" />);
    expect(await screen.findByText("landing")).toBeInTheDocument();
    await goTo("/review/run-1");
    expect(await screen.findByText("cards for run-1")).toBeInTheDocument();
  });

  it("/review/<run>/crs-sheet opens the new comment sheet", async () => {
    mockApi();
    render(<App initialView="review" />);
    await goTo("/review/run-1/crs-sheet");
    expect(await screen.findByText("crs sheet for run-1")).toBeInTheDocument();
  });

  it("/review/<run>/cards still opens the card view, and its pages keep their addresses", async () => {
    mockApi();
    render(<App initialView="review" />);
    await goTo("/review/run-1/cards");
    expect(await screen.findByText("cards for run-1")).toBeInTheDocument();
    await goTo("/review/run-1/findings");
    expect(await screen.findByText("cards for run-1 panel findings")).toBeInTheDocument();
    await goTo("/review/run-1/crs");
    expect(await screen.findByText("cards for run-1 panel crs")).toBeInTheDocument();
    await goTo("/review/run-1/secret");
    expect(await screen.findByRole("heading", { name: "This address cannot be opened" })).toBeInTheDocument();
  });
});
