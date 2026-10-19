/**
 * Workspace v2 (builder A): the switch, the routes and the address.
 *
 * With the switch off and no opt-in nothing changes (`/review/<run>` is the
 * comment sheet, App.review.test.tsx stays green unchanged); the workspace's
 * own address always works; "Try new design" turns `/review/<run>` into the
 * workspace; a blocked storage falls back to the old screen; the query
 * string keeps the reader's place.
 *
 * MUTATION PROOF: make isWorkspaceScreen ignore the switch and the first
 * test fails; drop "workspace" from PANELS.review and the second is refused
 * as an unknown address; stop reading window.location.search on popstate and
 * the restore test fails; use pushState for tab changes and the history test
 * fails.
 */
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { setToken } from "./api/client";
import { WORKSPACE_OPT_IN_KEY } from "./components/review/workspace/workspaceRoute";
import type { ReviewWorkspaceProps } from "./components/review/workspace/contract";

vi.mock("./views/CrsSheetView", () => ({
  CrsSheetView: ({ runId }: { runId: string }) => <p>{`crs sheet for ${runId}`}</p>,
}));
vi.mock("./views/HowReviewedView", () => ({
  HowReviewedView: ({ runId }: { runId: string }) => <p>{`how page for ${runId}`}</p>,
}));
vi.mock("./views/ReviewSheetView", () => ({
  ReviewSheetView: ({ runId, panel }: { runId: string; panel?: string }) => <p>{`cards for ${runId}${panel ? ` panel ${panel}` : ""}`}</p>,
}));
vi.mock("./views/SubmittalsLandingView", () => ({
  SubmittalsLandingView: ({ workspace, inbox }: { workspace?: boolean; inbox?: boolean }) => (
    <p>{`landing${inbox ? " inbox" : ""} workspace=${String(Boolean(workspace))}`}</p>
  ),
}));
vi.mock("./components/review/workspace/ReviewWorkspace", () => ({
  ReviewWorkspace: ({ location, onLocationChange, onOpenRun, onUnsavedChange }: ReviewWorkspaceProps) => (
    <div>
      <button type="button" onClick={() => onUnsavedChange?.(1)}>Make an unsaved decision</button>
      <p>{`workspace for ${location.runId}`}</p>
      <p data-testid="ws-location">{JSON.stringify(location)}</p>
      <button type="button" onClick={() => onLocationChange({ ...location, tab: "findings", row: "row-2", panel: "evidence" })}>
        Open findings
      </button>
      <button type="button" onClick={() => onOpenRun("run-5")}>Review again</button>
    </div>
  ),
}));
vi.mock("./components/review/workspace/FinishedReviewNotice", () => ({
  FinishedReviewNotice: ({ onOpenRun }: { onOpenRun: (id: string) => void }) => (
    <button type="button" onClick={() => onOpenRun("run-9")}>Open finished review</button>
  ),
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

function where() {
  return JSON.parse(screen.getByTestId("ws-location").textContent ?? "{}");
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  setToken(null);
  try { localStorage.clear(); } catch { /* blocked in one test */ }
  window.history.pushState({}, "", "/");
});

describe("workspace switch off (the default)", () => {
  it("/review/<run> is still the comment sheet and the landing gets workspace=false", async () => {
    mockApi();
    render(<App initialView="review" />);
    expect(await screen.findByText("landing workspace=false")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Try new design" })).not.toBeChecked();
    await goTo("/review/run-1");
    expect(await screen.findByText("crs sheet for run-1")).toBeInTheDocument();
    expect(screen.queryByText(/workspace for/)).not.toBeInTheDocument();
    await goTo("/review/run-1/cards");
    expect(await screen.findByText("cards for run-1")).toBeInTheDocument();
    await goTo("/review/run-1/how");
    expect(await screen.findByText("how page for run-1")).toBeInTheDocument();
  });

  it("/review/<run>/workspace opens the workspace anyway", async () => {
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=false");
    await goTo("/review/run-1/workspace");
    expect(await screen.findByText("workspace for run-1")).toBeInTheDocument();
    expect(where()).toEqual({ runId: "run-1", tab: "sheet", row: null, panel: null, documentId: null });
  });

  it("the inbox stays the inbox", async () => {
    localStorage.setItem(WORKSPACE_OPT_IN_KEY, "on");
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    await goTo("/review/inbox");
    expect(await screen.findByText("landing inbox workspace=true")).toBeInTheDocument();
  });
});

describe("Try new design", () => {
  it("an opt-in in storage turns /review/<run> into the workspace", async () => {
    localStorage.setItem(WORKSPACE_OPT_IN_KEY, "on");
    mockApi();
    render(<App initialView="review" />);
    expect(await screen.findByText("landing workspace=true")).toBeInTheDocument();
    await goTo("/review/run-1");
    expect(await screen.findByText("workspace for run-1")).toBeInTheDocument();
    // The other screens keep their own addresses.
    await goTo("/review/run-1/crs-sheet");
    expect(await screen.findByText("crs sheet for run-1")).toBeInTheDocument();
  });

  it("a blocked storage falls back to the old screen, no crash", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    mockApi();
    render(<App initialView="review" />);
    expect(await screen.findByText("landing workspace=false")).toBeInTheDocument();
    await goTo("/review/run-1");
    expect(await screen.findByText("crs sheet for run-1")).toBeInTheDocument();
  });

  it("pressing it on the landing turns the switch on and remembers it; off on the workspace goes back", async () => {
    const user = userEvent.setup();
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=false");
    await user.click(screen.getByRole("switch", { name: "Try new design" }));
    expect(await screen.findByText("landing workspace=true")).toBeInTheDocument();
    expect(localStorage.getItem(WORKSPACE_OPT_IN_KEY)).toBe("on");
    await goTo("/review/run-1");
    expect(await screen.findByText("workspace for run-1")).toBeInTheDocument();
    await user.click(screen.getByRole("switch", { name: "Try new design" }));
    expect(await screen.findByText("crs sheet for run-1")).toBeInTheDocument();
    expect(localStorage.getItem(WORKSPACE_OPT_IN_KEY)).toBeNull();
  });

  it("switching off on the workspace's own address returns to the old screen of that run", async () => {
    const user = userEvent.setup();
    localStorage.setItem(WORKSPACE_OPT_IN_KEY, "on");
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    await goTo("/review/run-1/workspace");
    await screen.findByText("workspace for run-1");
    await user.click(screen.getByRole("switch", { name: "Try new design" }));
    expect(await screen.findByText("crs sheet for run-1")).toBeInTheDocument();
  });
});

describe("turning the switch off with unsaved decisions", () => {
  it("asks first and stays on the workspace when the reader says no", async () => {
    const user = userEvent.setup();
    localStorage.setItem(WORKSPACE_OPT_IN_KEY, "on");
    mockApi();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    await goTo("/review/run-1");
    await screen.findByText("workspace for run-1");
    await user.click(screen.getByRole("button", { name: "Make an unsaved decision" }));
    await user.click(screen.getByRole("switch", { name: "Try new design" }));
    expect(confirm).toHaveBeenCalledWith("Some decisions on this sheet are not saved yet. Leave without saving them?");
    expect(screen.getByText("workspace for run-1")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Try new design" })).toBeChecked();

    confirm.mockReturnValue(true);
    await user.click(screen.getByRole("switch", { name: "Try new design" }));
    expect(await screen.findByText("crs sheet for run-1")).toBeInTheDocument();
  });
});

describe("the address keeps the place", () => {
  it("reloading with ?tab=standards&row=X&panel=evidence restores the place", async () => {
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=false");
    await goTo("/review/run-1/workspace?tab=standards&row=row-x&panel=evidence");
    expect(await screen.findByText("workspace for run-1")).toBeInTheDocument();
    expect(where()).toEqual({ runId: "run-1", tab: "standards", row: "row-x", panel: "evidence", documentId: null });
  });

  it("a junk query opens the default place", async () => {
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=false");
    await goTo("/review/run-1/workspace?tab=%%%&panel=nope");
    expect(await screen.findByText("workspace for run-1")).toBeInTheDocument();
    expect(where()).toMatchObject({ tab: "sheet", panel: null });
  });

  it("tab and row changes replace the address (no new history entry)", async () => {
    const user = userEvent.setup();
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=false");
    await goTo("/review/run-1/workspace");
    await screen.findByText("workspace for run-1");
    const depth = window.history.length;
    await user.click(screen.getByRole("button", { name: "Open findings" }));
    expect(window.location.pathname).toBe("/review/run-1/workspace");
    expect(window.location.search).toBe("?tab=findings&row=row-2&panel=evidence");
    expect(window.history.length).toBe(depth);
    expect(where()).toMatchObject({ tab: "findings", row: "row-2", panel: "evidence" });
  });

  it("links from the new pieces open the workspace address while the switch is off", async () => {
    const user = userEvent.setup();
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=false");
    await user.click(screen.getByRole("button", { name: "Open finished review" }));
    expect(await screen.findByText("workspace for run-9")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Review again" }));
    expect(await screen.findByText("workspace for run-5")).toBeInTheDocument();
  });

  it("with the switch on they open the plain run address (which is the workspace)", async () => {
    const user = userEvent.setup();
    localStorage.setItem(WORKSPACE_OPT_IN_KEY, "on");
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    await user.click(screen.getByRole("button", { name: "Open finished review" }));
    expect(await screen.findByText("workspace for run-9")).toBeInTheDocument();
  });
});
