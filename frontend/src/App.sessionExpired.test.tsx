/**
 * An expired sign-in always says so, once, with the way to sign in again
 * (order 4b, switch SESSION_EXPIRED_NOTICE_ENABLED, carried on the signed-in
 * user by /auth/me and the login answer). Off: the plain login form, as before.
 *
 * MUTATION PROOF: drop `on401()` from App's onSignedOut handler and the
 * fetch, poll and image tests fail; drop the `usePoll` heartbeat from
 * useSessionExpiry and "an empty answer" fails; drop the `armed` check and
 * "never signed in", "switch off" and "chosen sign-out" fail.
 */
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { onSignedOut, setCookieSession, setToken } from "./api/client";
import { fetchImageObjectUrl, reportResponseStatus, request, signOutOn401 } from "./api/core";
import { FAST_MS, IDLE_MS } from "./hooks/usePoll";

const NOTICE = /sign-in expired, sign in again/i;
const ME = { id: "u1", email: "eng@example.test", display_name: "Eng", roles: [] };
const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));
const unauthenticated = () => reply({ detail: { code: "unauthenticated", message: "sign in to continue" } }, 401);

interface World { notice: boolean; me: "in" | "out"; documents: number; other: number; loginOk: boolean }
let world: World;
let calls: string[];

function stubApi() {
  calls = [];
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push(url);
    const user = { ...ME, session_expired_notice: world.notice };
    if (url.includes("/auth/me")) return world.me === "in" ? reply({ required: true, user }) : unauthenticated();
    if (url.includes("/auth/login")) {
      return world.loginOk ? reply({ token: null, user, expires_in_seconds: 28800 }) : unauthenticated();
    }
    if (url.includes("/auth/logout")) return reply({ signed_out: true });
    if (url.includes("/documents")) return world.documents === 401 ? unauthenticated() : reply([], world.documents);
    if (url.includes("/other")) {
      if (world.other === 401) return unauthenticated();
      return reply({ ok: world.other === 200 }, world.other);
    }
    if (url.includes("/metrics")) return reply({ refresh_seconds: 15 });
    return reply({ ok: true, embed_model_present: true, answer_model_configured: true, ingestion: { alive: true, stalled: false, busy: false } });
  }));
}

const count = (part: string) => calls.filter((c) => c.includes(part)).length;
const later = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

async function signedIn() {
  stubApi();
  render(<App initialView="documents" />);
  expect(await screen.findByText("Eng", { exact: false })).toBeInTheDocument();
}

beforeEach(() => {
  world = { notice: true, me: "in", documents: 200, other: 200, loginOk: true };
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  onSignedOut(null);
  setToken(null);
  setCookieSession(false);
  try { localStorage.clear(); sessionStorage.clear(); } catch { /* ignore */ }
  window.history.pushState({}, "", "/");
});

describe("an expired sign-in tells the reader (switch on)", () => {
  it("a 401 on a normal fetch shows the notice once, over the sign-in form", async () => {
    await signedIn();
    world.other = 401;
    await act(async () => { await request("/other"); });
    expect(screen.getAllByText(NOTICE)).toHaveLength(1);
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("a 401 on a poll shows the notice once, and the polling stops rather than repeat it", async () => {
    await signedIn();
    world.documents = 401;
    await later(IDLE_MS);
    expect(screen.getAllByText(NOTICE)).toHaveLength(1);
    const asked = count("/documents");
    expect(asked).toBeGreaterThan(0);
    await later(5 * IDLE_MS);
    expect(screen.getAllByText(NOTICE)).toHaveLength(1);
    expect(count("/documents")).toBe(asked);
  });

  it("several 401s at once still show one notice", async () => {
    await signedIn();
    world.other = 401;
    await act(async () => {
      await Promise.all([request("/other/a"), request("/other/b"), request("/other/c")]);
    });
    expect(screen.getAllByText(NOTICE)).toHaveLength(1);
  });

  it("the transports outside request() say the same: a page image, and an upload's reported status", async () => {
    await signedIn();
    world.other = 401;
    await act(async () => { await fetchImageObjectUrl("/api/other/page.png"); });
    expect(screen.getAllByText(NOTICE)).toHaveLength(1);
    act(() => { reportResponseStatus(401); });
    expect(screen.getAllByText(NOTICE)).toHaveLength(1);
  });

  it("an empty answer does not hide it: reads under an expired sign-in answer 200, so /auth/me is asked while signed in", async () => {
    await signedIn();
    world.me = "out"; // /documents keeps answering 200 [], as the backend's empty scope does
    await later(IDLE_MS);
    expect(screen.getAllByText(NOTICE)).toHaveLength(1);
  });

  it("a 403 is not an expired sign-in: no notice, the screen stays", async () => {
    await signedIn();
    world.other = 403;
    let result: unknown = null;
    await act(async () => { result = await request("/other"); });
    expect(screen.queryByText(NOTICE)).toBeNull();
    expect(screen.queryByLabelText(/password/i)).toBeNull();
    expect(screen.getByText("Eng", { exact: false })).toBeInTheDocument();
    expect(JSON.stringify(result)).toMatch(/refused/i);
  });

  it("a page opened with no sign-in was never expired: the plain form, no notice", async () => {
    world.me = "out";
    stubApi();
    render(<App initialView="documents" />);
    expect(await screen.findByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.queryByText(NOTICE)).toBeNull();
  });

  it("a chosen sign-out is not an expired sign-in, even when a late 401 arrives after it", async () => {
    await signedIn();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(screen.getByRole("button", { name: /sign out/i }));
    expect(await screen.findByLabelText(/password/i)).toBeInTheDocument();
    act(() => { signOutOn401(401); });
    expect(screen.queryByText(NOTICE)).toBeNull();
  });

  it("a wrong password keeps the notice; signing in again clears it and shows the screen again", async () => {
    await signedIn();
    world.other = 401;
    await act(async () => { await request("/other"); });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    world.loginOk = false;
    await user.type(screen.getByLabelText(/email/i), "eng@example.test");
    await user.type(screen.getByLabelText(/password/i), "a-wrong-password");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText(/did not match/i)).toBeInTheDocument();
    expect(screen.getAllByText(NOTICE)).toHaveLength(1);
    world.loginOk = true;
    await user.type(screen.getByLabelText(/password/i), "a-long-enough-password");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("Eng", { exact: false })).toBeInTheDocument();
    expect(screen.queryByText(NOTICE)).toBeNull();
  });
});

describe("switch off: as today", () => {
  it("a 401 goes to the plain sign-in form with no notice", async () => {
    world.notice = false;
    await signedIn();
    world.documents = 401;
    await later(IDLE_MS);
    expect(await screen.findByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.queryByText(NOTICE)).toBeNull();
  });

  it("makes no extra request: /auth/me is asked once, at the start", async () => {
    world.notice = false;
    await signedIn();
    await later(3 * IDLE_MS + FAST_MS);
    expect(count("/auth/me")).toBe(1);
    expect(screen.queryByText(NOTICE)).toBeNull();
  });
});
