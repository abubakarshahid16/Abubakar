/**
 * The owner's written order (19 Oct 2026): the new review workspace replaces
 * the old review design permanently. No old review screen can be reached:
 * every old review address opens the workspace (on the tab that holds the
 * same thing) and the address bar shows where it now leads, so old bookmarks
 * and links keep working. The map itself is unit-tested in
 * `components/review/workspace/workspaceRoute.test.ts`.
 *
 * MUTATION PROOF: let App render the old card view / comment sheet / How
 * page again for their addresses and "never shows an old screen" fails;
 * drop the address replacement effect and the address assertions fail;
 * route /review/inbox to the inbox and the inbox test fails.
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { setToken } from "./api/client";
import type { ReviewWorkspaceProps } from "./components/review/workspace/contract";

vi.mock("./views/CrsSheetView", () => ({
  CrsSheetView: ({ runId }: { runId: string }) => <p>{`old crs sheet for ${runId}`}</p>,
}));
vi.mock("./views/HowReviewedView", () => ({
  HowReviewedView: ({ runId }: { runId: string }) => <p>{`old how page for ${runId}`}</p>,
}));
vi.mock("./views/ReviewSheetView", () => ({
  ReviewSheetView: ({ runId }: { runId: string }) => <p>{`old cards for ${runId}`}</p>,
}));
vi.mock("./views/SubmittalsLandingView", () => ({
  SubmittalsLandingView: ({ workspace, inbox }: { workspace?: boolean; inbox?: boolean }) => (
    <p>{`landing${inbox ? " inbox" : ""} workspace=${String(Boolean(workspace))}`}</p>
  ),
}));
vi.mock("./components/review/workspace/ReviewWorkspace", () => ({
  ReviewWorkspace: ({ location }: ReviewWorkspaceProps) => (
    <p data-testid="ws-location">{`workspace for ${location.runId} on ${location.tab}`}</p>
  ),
}));
vi.mock("./components/review/workspace/FinishedReviewNotice", () => ({ FinishedReviewNotice: () => null }));

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

function noOldScreen() {
  expect(screen.queryByText(/^old /)).toBeNull();
  expect(screen.queryByRole("switch", { name: "Try new design" })).toBeNull();
}

describe("old review addresses open the workspace (owner, 19 Oct 2026)", () => {
  it("/review is the workspace's first page, with no design switch", async () => {
    mockApi();
    render(<App initialView="review" />);
    expect(await screen.findByText("landing workspace=true")).toBeInTheDocument();
    noOldScreen();
  });

  it("/review/inbox leads to the workspace's first page, and the address says /review", async () => {
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    await goTo("/review/inbox");
    expect(await screen.findByText("landing workspace=true")).toBeInTheDocument();
    expect(screen.queryByText(/landing inbox/)).toBeNull();
    expect(window.location.pathname).toBe("/review");
  });

  it("/review/<run> opens the workspace", async () => {
    mockApi();
    render(<App initialView="review" />);
    await goTo("/review/run-1");
    expect(await screen.findByText("workspace for run-1 on sheet")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/review/run-1");
    noOldScreen();
  });

  it("/review/<run>/workspace keeps working at its own address", async () => {
    mockApi();
    render(<App initialView="review" />);
    await goTo("/review/run-1/workspace?tab=numbers");
    expect(await screen.findByText("workspace for run-1 on numbers")).toBeInTheDocument();
    expect(window.location.pathname + window.location.search).toBe("/review/run-1/workspace?tab=numbers");
  });

  it.each([
    ["cards", "sheet", "/review/run-1"],
    ["crs-sheet", "sheet", "/review/run-1"],
    ["findings", "findings", "/review/run-1?tab=findings"],
    ["standards", "standards", "/review/run-1?tab=standards"],
    ["steps", "steps", "/review/run-1?tab=steps"],
    ["numbers", "numbers", "/review/run-1?tab=numbers"],
    ["how", "how", "/review/run-1?tab=how"],
    ["crs", "crs", "/review/run-1?tab=crs"],
  ])("/review/<run>/%s never shows an old screen: workspace on the %s tab, address %s", async (panel, tab, address) => {
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    await goTo(`/review/run-1/${panel}`);
    expect(await screen.findByText(`workspace for run-1 on ${tab}`)).toBeInTheDocument();
    noOldScreen();
    expect(window.location.pathname + window.location.search).toBe(address);
  });

  it("an unknown review address is still refused", async () => {
    mockApi();
    render(<App initialView="review" />);
    await goTo("/review/run-1/secret");
    expect(await screen.findByRole("heading", { name: "This address cannot be opened" })).toBeInTheDocument();
  });
});
