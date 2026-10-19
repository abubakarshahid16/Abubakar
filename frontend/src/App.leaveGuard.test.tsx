/**
 * v2.1 N1: ONE navigation guard for the review workspace.
 *
 * While the workspace reports unsaved decisions, every way out asks in the
 * page first: the browser's Back button, the main menu, "Open this point on
 * the cards view" (the navigation context), a link to Documents (NavLink),
 * and sign-out. With nothing unsaved nothing asks. A chosen sign-out removes
 * the reader's decision drafts; a sign-in that ran out (401) keeps them.
 *
 * MUTATION PROOF: hand the Shell `onNavigate` instead of `guardedNavigate`
 * and "the main menu asks" fails; drop the popstate check and "Back asks"
 * fails (the landing shows at once); hand the NavigationContext the plain
 * `onNavigate` and both link tests fail; drop clearDecisionDrafts() from
 * signOut and the sign-out test fails.
 * Round 2: push a second entry on "Leave" after Back (instead of
 * history.back with the one-shot skip) and "the next Back does not open the
 * review again" fails; drop `saveWorkspace` from the guard and "Save and
 * leave" fails.
 */
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useContext, useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { setToken } from "./api/client";
import { signOutOn401 } from "./api/core";
import { NavLink, NavigationContext } from "./components/NavLink";
import { draftStorageKey } from "./components/review/crs/useCrsDecisions";
import { LeaveSaverContext } from "./components/review/workspace/useLeaveGuard";
import type { ReviewWorkspaceProps } from "./components/review/workspace/contract";

vi.mock("./views/CrsSheetView", () => ({
  CrsSheetView: ({ runId }: { runId: string }) => <p>{`crs sheet for ${runId}`}</p>,
}));
vi.mock("./views/ReviewSheetView", () => ({
  ReviewSheetView: ({ runId }: { runId: string }) => <p>{`cards for ${runId}`}</p>,
}));
vi.mock("./views/DocumentsView", () => ({ DocumentsView: () => <p>documents page</p> }));
vi.mock("./views/StandardsView", () => ({ StandardsView: () => <p>standards page</p> }));
vi.mock("./views/SubmittalsLandingView", () => ({
  SubmittalsLandingView: () => <p>reviews landing</p>,
}));

/** A stand-in workspace: reports one unsaved decision on request, and has
 *  the two in-page links the real one has (the cards view through the
 *  navigation context, Documents through NavLink). */
function FakeWorkspace({ location, onUnsavedChange }: ReviewWorkspaceProps) {
  const navigate = useContext(NavigationContext);
  const register = useContext(LeaveSaverContext);
  // As the real one: nothing is reported unsaved once it is gone.
  useEffect(() => () => onUnsavedChange?.(0), [onUnsavedChange]);
  return (
    <div>
      <p>{`workspace for ${location.runId}`}</p>
      <button type="button" onClick={() => onUnsavedChange?.(2)}>Make two unsaved decisions</button>
      <button type="button" onClick={() => register?.(async () => { onUnsavedChange?.(0); return true; })}>Offer a save</button>
      <button type="button" onClick={() => navigate?.("review", location.runId, "cards")}>Open this point on the cards view</button>
      <NavLink view="documents">Documents page link</NavLink>
    </div>
  );
}
vi.mock("./components/review/workspace/ReviewWorkspace", () => ({
  ReviewWorkspace: (props: ReviewWorkspaceProps) => <FakeWorkspace {...props} />,
}));
vi.mock("./components/review/workspace/FinishedReviewNotice", () => ({ FinishedReviewNotice: () => null }));

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

const SIGNED_IN = { id: "user-a", email: "a@example.test", display_name: "Engineer A", roles: ["reviewer"] };

function mockApi(signedIn: typeof SIGNED_IN | null = null) {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
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

/** The browser's own Back: resolves once the browser has moved. */
async function realBack() {
  await act(async () => {
    const moved = new Promise((resolve) => window.addEventListener("popstate", resolve, { once: true }));
    window.history.back();
    await moved;
  });
}

async function openWorkspaceWithUnsaved(user: ReturnType<typeof userEvent.setup>) {
  render(<App initialView="review" />);
  await screen.findByText("reviews landing");
  await goTo("/review/run-1/workspace");
  await screen.findByText("workspace for run-1");
  await user.click(screen.getByRole("button", { name: "Make two unsaved decisions" }));
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  setToken(null);
  try { localStorage.clear(); } catch { /* ignore */ }
  try { sessionStorage.clear(); } catch { /* ignore */ }
  window.history.pushState({}, "", "/");
});

describe("the navigation guard (v2.1 N1)", () => {
  it("the browser's Back button asks; Stay keeps the workspace and its address, Leave goes back", async () => {
    const user = userEvent.setup();
    mockApi();
    await openWorkspaceWithUnsaved(user);
    // Back: the browser has already moved the address.
    await goTo("/review");
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "You have 2 decisions on this review that are not saved yet. If you leave, they are kept in this browser tab");
    expect(screen.getByText("workspace for run-1")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/review/run-1/workspace");
    await user.click(screen.getByRole("button", { name: "Stay here" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByText("workspace for run-1")).toBeInTheDocument();

    await goTo("/review");
    await user.click(screen.getByRole("button", { name: "Leave this review" }));
    expect(await screen.findByText("reviews landing")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/review");
  });

  it("after Back and Leave, the next Back does not open the review again (v2.1 round 2)", async () => {
    const user = userEvent.setup();
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("reviews landing");
    window.history.replaceState({}, "", "/review");
    await goTo("/review/run-1/workspace");
    await screen.findByText("workspace for run-1");
    await user.click(screen.getByRole("button", { name: "Make two unsaved decisions" }));
    // A real Back: the browser moves to the landing first.
    await realBack();
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/review/run-1/workspace");
    await user.click(screen.getByRole("button", { name: "Leave this review" }));
    expect(await screen.findByText("reviews landing")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/review");
    // Back once more goes on past the landing, not into the review again.
    await realBack();
    expect(window.location.pathname).not.toBe("/review/run-1/workspace");
    expect(screen.queryByText("workspace for run-1")).toBeNull();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("\"Save and leave\" saves through the workspace's save, then leaves (v2.1 round 2)", async () => {
    const user = userEvent.setup();
    mockApi();
    await openWorkspaceWithUnsaved(user);
    await user.click(screen.getByRole("button", { name: "Offer a save" }));
    await user.click(screen.getAllByRole("button", { name: /Standards Library/ })[0]);
    await user.click(screen.getByRole("button", { name: "Save and leave" }));
    expect(await screen.findByText("standards page")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("the main menu asks before it leaves", async () => {
    const user = userEvent.setup();
    mockApi();
    await openWorkspaceWithUnsaved(user);
    await user.click(screen.getAllByRole("button", { name: /Standards Library/ })[0]);
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText("workspace for run-1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Leave this review" }));
    expect(await screen.findByText("standards page")).toBeInTheDocument();
  });

  it("\"Open this point on the cards view\" asks", async () => {
    const user = userEvent.setup();
    mockApi();
    await openWorkspaceWithUnsaved(user);
    await user.click(screen.getByRole("button", { name: "Open this point on the cards view" }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.queryByText("cards for run-1")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Leave this review" }));
    expect(await screen.findByText("cards for run-1")).toBeInTheDocument();
  });

  it("a link to Documents asks", async () => {
    const user = userEvent.setup();
    mockApi();
    await openWorkspaceWithUnsaved(user);
    await user.click(screen.getByRole("link", { name: "Documents page link" }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Stay here" }));
    expect(screen.queryByText("documents page")).toBeNull();
    expect(screen.getByText("workspace for run-1")).toBeInTheDocument();
  });

  it("nothing asks when nothing is unsaved", async () => {
    const user = userEvent.setup();
    mockApi();
    render(<App initialView="review" />);
    await screen.findByText("reviews landing");
    await goTo("/review/run-1/workspace");
    await screen.findByText("workspace for run-1");
    await user.click(screen.getByRole("button", { name: "Open this point on the cards view" }));
    expect(await screen.findByText("cards for run-1")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await goTo("/review");
    expect(await screen.findByText("reviews landing")).toBeInTheDocument();
  });
});

describe("sign-out and a sign-in that ran out (v2.1 N1)", () => {
  it("sign-out asks first, then removes this person's decision drafts", async () => {
    const user = userEvent.setup();
    mockApi(SIGNED_IN);
    await openWorkspaceWithUnsaved(user);
    const draftKey = draftStorageKey("run-1", "user-a");
    sessionStorage.setItem(draftKey, JSON.stringify({ decisions: { "row-1": { kind: "keep" } }, opened: [] }));
    await user.click((await screen.findAllByRole("button", { name: "Sign out" }))[0]);
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Signing out removes them from this browser tab.");
    expect(sessionStorage.getItem(draftKey)).not.toBeNull();
    await user.click(screen.getByRole("button", { name: "Sign out without saving" }));
    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
    expect(sessionStorage.getItem(draftKey)).toBeNull();
  });

  it("a sign-in that ran out keeps the drafts for when the same person signs in again", async () => {
    mockApi(SIGNED_IN);
    render(<App initialView="review" />);
    await screen.findByText("reviews landing");
    await screen.findAllByRole("button", { name: "Sign out" });
    const draftKey = draftStorageKey("run-1", "user-a");
    sessionStorage.setItem(draftKey, JSON.stringify({ decisions: { "row-1": { kind: "keep" } }, opened: [] }));
    act(() => { signOutOn401(401); });
    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
    expect(sessionStorage.getItem(draftKey)).not.toBeNull();
  });
});
