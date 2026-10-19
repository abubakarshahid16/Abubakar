/**
 * Workspace v2: the routes and the address. Owner, 19 Oct 2026: the
 * workspace replaced the old review design permanently. There is no "Try
 * new design" switch; a stored opt-in (or a blocked storage) changes
 * nothing; every review address opens the workspace or its first page; the
 * query string keeps the reader's place.
 *
 * MUTATION PROOF: decide what shows from this browser's stored choice again
 * (useWorkspaceSwitch(false)) and "a stored opt-out changes nothing" fails; render the TryNewDesignToggle again
 * and "no switch" fails; drop "workspace" from PANELS.review and its own
 * address is refused; stop reading window.location.search on popstate and
 * the restore test fails; use pushState for tab changes and the history
 * test fails.
 */
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { setToken } from "./api/client";
import { signOutOn401 } from "./api/core";
import { WORKSPACE_OPT_IN_KEY } from "./components/review/workspace/workspaceRoute";
import type { ReviewWorkspaceProps } from "./components/review/workspace/contract";
import { WATCH_STORAGE_KEY, watchRun, watchStorageKey } from "./components/review/workspace/reviewWatch";
import { draftStorageKey } from "./components/review/crs/useCrsDecisions";

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
  SubmittalsLandingView: ({ workspace, inbox, onOpenRunTab }: {
    workspace?: boolean; inbox?: boolean; onOpenRunTab?: (runId: string, tab: "crs") => void;
  }) => (
    <div>
      <p>{`landing${inbox ? " inbox" : ""} workspace=${String(Boolean(workspace))}`}</p>
      {onOpenRunTab && <button type="button" onClick={() => onOpenRunTab("run-7", "crs")}>Preview CRS</button>}
    </div>
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

const SIGNED_IN = { id: "user-a", email: "a@example.test", display_name: "Engineer A", roles: ["reviewer"] };

function mockApi(signedIn: typeof SIGNED_IN | null = null, loginAs: typeof SIGNED_IN | null = null) {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/auth/login")) return Promise.resolve(json({ token: "token-b", user: loginAs }));
    if (url.includes("/auth/me")) return Promise.resolve(json(signedIn ? { required: true, user: signedIn } : { required: false, user: null }));
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
  try { sessionStorage.clear(); } catch { /* blocked in one test */ }
  window.history.pushState({}, "", "/");
});

describe("the workspace is the only review design", () => {
  it("/review is the workspace's first page and /review/<run> the workspace, with no switch", async () => {
    mockApi();
    render(<App initialView="review" />);
    expect(await screen.findByText("landing workspace=true")).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "Try new design" })).toBeNull();
    await goTo("/review/run-1");
    expect(await screen.findByText("workspace for run-1")).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "Try new design" })).toBeNull();
    expect(screen.queryByText(/crs sheet for|cards for|how page for/)).toBeNull();
  });

  it("/review/<run>/workspace keeps working", async () => {
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    await goTo("/review/run-1/workspace");
    expect(await screen.findByText("workspace for run-1")).toBeInTheDocument();
    expect(where()).toEqual({ runId: "run-1", tab: "sheet", row: null, panel: null, documentId: null });
  });

  it("a stored opt-out of the old switch changes nothing", async () => {
    localStorage.setItem(WORKSPACE_OPT_IN_KEY, "off");
    mockApi();
    render(<App initialView="review" />);
    expect(await screen.findByText("landing workspace=true")).toBeInTheDocument();
    await goTo("/review/run-1");
    expect(await screen.findByText("workspace for run-1")).toBeInTheDocument();
  });

  it("a blocked storage changes nothing, no crash", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    mockApi();
    render(<App initialView="review" />);
    expect(await screen.findByText("landing workspace=true")).toBeInTheDocument();
    await goTo("/review/run-1");
    expect(await screen.findByText("workspace for run-1")).toBeInTheDocument();
  });

  it("the old inbox address leads to the workspace's first page", async () => {
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    await goTo("/review/inbox");
    expect(await screen.findByText("landing workspace=true")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/review");
  });

  it("an old screen's address opens the workspace on that tab and keeps the address tidy", async () => {
    const user = userEvent.setup();
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    await goTo("/review/run-1/standards");
    expect(await screen.findByText("workspace for run-1")).toBeInTheDocument();
    expect(where()).toEqual({ runId: "run-1", tab: "standards", row: null, panel: null, documentId: null });
    expect(window.location.pathname + window.location.search).toBe("/review/run-1?tab=standards");
    // Moving on from there writes the plain run address, never the old one.
    await user.click(screen.getByRole("button", { name: "Open findings" }));
    expect(window.location.pathname).toBe("/review/run-1");
    expect(window.location.search).toBe("?tab=findings&row=row-2&panel=evidence");
  });
});

describe("the address keeps the place", () => {
  it("reloading with ?tab=standards&row=X&panel=evidence restores the place", async () => {
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    await goTo("/review/run-1/workspace?tab=standards&row=row-x&panel=evidence");
    expect(await screen.findByText("workspace for run-1")).toBeInTheDocument();
    expect(where()).toEqual({ runId: "run-1", tab: "standards", row: "row-x", panel: "evidence", documentId: null });
  });

  it("v2.2: Preview CRS on the first page opens that review straight on the CRS tab", async () => {
    const user = userEvent.setup();
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    await user.click(screen.getByRole("button", { name: "Preview CRS" }));
    expect(await screen.findByText("workspace for run-7")).toBeInTheDocument();
    expect(where()).toEqual({ runId: "run-7", tab: "crs", row: null, panel: null, documentId: null });
  });

  it("a junk query opens the default place", async () => {
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    await goTo("/review/run-1/workspace?tab=%%%&panel=nope");
    expect(await screen.findByText("workspace for run-1")).toBeInTheDocument();
    expect(where()).toMatchObject({ tab: "sheet", panel: null });
  });

  it("tab and row changes replace the address (no new history entry)", async () => {
    const user = userEvent.setup();
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    await goTo("/review/run-1/workspace");
    await screen.findByText("workspace for run-1");
    const depth = window.history.length;
    await user.click(screen.getByRole("button", { name: "Open findings" }));
    expect(window.location.pathname).toBe("/review/run-1/workspace");
    expect(window.location.search).toBe("?tab=findings&row=row-2&panel=evidence");
    expect(window.history.length).toBe(depth);
    expect(where()).toMatchObject({ tab: "findings", row: "row-2", panel: "evidence" });
  });

  it("links from the new pieces open the workspace at the plain run address", async () => {
    const user = userEvent.setup();
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    await user.click(screen.getByRole("button", { name: "Open finished review" }));
    expect(await screen.findByText("workspace for run-9")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Review again" }));
    expect(await screen.findByText("workspace for run-5")).toBeInTheDocument();
  });
});

/** SF1: "Open it" on the finished notice leaves the workspace, so it asks
 *  about unsaved decisions first.
 *  MUTATION PROOF: pass openRunInWorkspace to the notice again and the
 *  first half fails (it leaves without asking). */
describe("the finished notice with unsaved decisions", () => {
  it("asks first, stays when the reader says stay, and goes when they say leave", async () => {
    const user = userEvent.setup();
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    await goTo("/review/run-1/workspace");
    await screen.findByText("workspace for run-1");
    await user.click(screen.getByRole("button", { name: "Make an unsaved decision" }));
    await user.click(screen.getByRole("button", { name: "Open finished review" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("not saved yet");
    await user.click(screen.getByRole("button", { name: "Stay here" }));
    expect(screen.getByText("workspace for run-1")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open finished review" }));
    await user.click(screen.getByRole("button", { name: "Leave this review" }));
    expect(await screen.findByText("workspace for run-9")).toBeInTheDocument();
  });

  it("does not ask when nothing is unsaved", async () => {
    const user = userEvent.setup();
    mockApi();
    const confirm = vi.spyOn(window, "confirm");
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    await user.click(screen.getByRole("button", { name: "Open finished review" }));
    expect(await screen.findByText("workspace for run-9")).toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();
  });
});

/** B6: the "review ready" list names files; it is kept under the signed-in
 *  user's id and is gone after sign-out.
 *  MUTATION PROOF: drop clearWatchedReviews() from signOut and this fails. */
describe("signing out clears the review-ready list", () => {
  it("keeps the list under the user's id, and sign-out removes it from memory and storage", async () => {
    const user = userEvent.setup();
    mockApi(SIGNED_IN);
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    // Signed in (the badge shows) before anything is watched.
    const signOut = (await screen.findAllByRole("button", { name: "Sign out" }))[0];
    act(() => { watchRun("run-1", "Private datasheet.pdf"); });
    expect(sessionStorage.getItem(watchStorageKey("user-a"))).toContain("Private datasheet.pdf");
    expect(sessionStorage.getItem(WATCH_STORAGE_KEY)).toBeNull();

    await user.click(signOut);
    expect(sessionStorage.getItem(watchStorageKey("user-a"))).toBeNull();
    expect(sessionStorage.getItem(WATCH_STORAGE_KEY)).toBeNull();
    // Whatever is watched next is not the last person's list.
    act(() => { watchRun("run-2", null); });
    expect(sessionStorage.getItem(WATCH_STORAGE_KEY)).not.toContain("Private datasheet.pdf");
  });

  /** A 401 from the server signs the reader out the same way: the list
   *  goes too.
   *  MUTATION PROOF: drop clearWatchedReviews() from App's onSignedOut
   *  handler and this fails. */
  it("a 401 from the server clears the list like sign-out does", async () => {
    mockApi(SIGNED_IN);
    render(<App initialView="review" />);
    await screen.findByText("landing workspace=true");
    await screen.findAllByRole("button", { name: "Sign out" });
    act(() => { watchRun("run-1", "Private datasheet.pdf"); });
    expect(sessionStorage.getItem(watchStorageKey("user-a"))).toContain("Private datasheet.pdf");

    // What every transport calls when the server answers 401.
    act(() => { signOutOn401(401); });
    expect(sessionStorage.getItem(watchStorageKey("user-a"))).toBeNull();
    expect(sessionStorage.getItem(WATCH_STORAGE_KEY)).toBeNull();
    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
    act(() => { watchRun("run-2", null); });
    expect(sessionStorage.getItem(WATCH_STORAGE_KEY)).not.toContain("Private datasheet.pdf");
  });
});

/** A decision draft can hold wording from the document. A sign-in that ran
 *  out keeps it for the same person, never for the next one on the tab.
 *  MUTATION PROOF: drop keepOnlyDraftsOf from App's check or signIn and
 *  the matching test fails. */
describe("another person's decision drafts never survive into the next sign-in", () => {
  it("a reload that learns who is signed in removes every other person's draft", async () => {
    sessionStorage.setItem(draftStorageKey("run-1", "user-z"), JSON.stringify({ decisions: { k: { kind: "keep" } } }));
    sessionStorage.setItem(draftStorageKey("run-1", "user-a"), JSON.stringify({ decisions: { k: { kind: "keep" } } }));
    mockApi(SIGNED_IN);
    render(<App initialView="review" />);
    await screen.findAllByRole("button", { name: "Sign out" });
    expect(sessionStorage.getItem(draftStorageKey("run-1", "user-z"))).toBeNull();
    expect(sessionStorage.getItem(draftStorageKey("run-1", "user-a"))).not.toBeNull();
  });

  it("after a session runs out, the next person who signs in does not inherit the draft", async () => {
    const user = userEvent.setup();
    const other = { ...SIGNED_IN, id: "user-b", email: "b@example.test", display_name: "Engineer B" };
    mockApi(SIGNED_IN, other);
    render(<App initialView="review" />);
    await screen.findAllByRole("button", { name: "Sign out" });
    sessionStorage.setItem(draftStorageKey("run-1", "user-a"), JSON.stringify({ decisions: { k: { kind: "keep" } } }));

    act(() => { signOutOn401(401); });
    await user.type(await screen.findByLabelText("Email"), "b@example.test");
    await user.type(screen.getByLabelText("Password"), "pw");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findAllByRole("button", { name: "Sign out" });
    expect(sessionStorage.getItem(draftStorageKey("run-1", "user-a"))).toBeNull();
  });
});
