/**
 * Item G (order 164.2) at the app: a reload keeps the user signed in (the
 * server's cookie answers `/auth/me`), the login asks for the cookie, and
 * signing out tells the server to clear it. The page holds no token.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { isSignedIn, onSignedOut, setCookieSession, setToken } from "./api/client";

const ME = { id: "u1", email: "eng@example.test", display_name: "Eng", roles: [] };
const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

function mockApi({ cookieSignedIn, loginToken = null }: { cookieSignedIn: boolean; loginToken?: string | null }) {
  const calls: { url: string; method: string; headers: Headers; body: string | null }[] = [];
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push({ url, method: init?.method ?? "GET", headers: new Headers(init?.headers), body: (init?.body as string) ?? null });
    if (url.includes("/auth/me")) {
      return cookieSignedIn ? json({ required: true, user: ME }) : json({ detail: { code: "unauthenticated", message: "sign in to continue" } }, 401);
    }
    if (url.includes("/auth/login")) return json({ token: loginToken, user: ME, expires_in_seconds: 28800 });
    if (url.includes("/auth/logout")) return json({ signed_out: true });
    if (url.includes("/documents")) return json([]);
    if (url.includes("/metrics")) return json({ refresh_seconds: 15 });
    return json({ ok: true, embed_model_present: true, answer_model_configured: true, ingestion: { alive: true, stalled: false, busy: false } });
  }));
  return calls;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  onSignedOut(null);
  setToken(null);
  setCookieSession(false);
  try { localStorage.clear(); sessionStorage.clear(); } catch { /* ignore */ }
  window.history.pushState({}, "", "/");
});

describe("the browser's cookie login", () => {
  it("a reload keeps the user signed in: the cookie answers /auth/me and no login form is shown", async () => {
    mockApi({ cookieSignedIn: true });
    render(<App initialView="documents" />);
    expect(await screen.findByText("Eng", { exact: false })).toBeInTheDocument();
    expect(screen.queryByLabelText(/password/i)).toBeNull();
    expect(isSignedIn()).toBe(true);
  });

  it("with no cookie the login form shows, and nothing says the page is signed in", async () => {
    mockApi({ cookieSignedIn: false });
    render(<App initialView="documents" />);
    expect(await screen.findByLabelText(/password/i)).toBeInTheDocument();
    expect(isSignedIn()).toBe(false);
  });

  it("signing in asks for the cookie and the page then counts as signed in without holding a token", async () => {
    const calls = mockApi({ cookieSignedIn: false });
    const user = userEvent.setup();
    render(<App initialView="documents" />);
    await user.type(await screen.findByLabelText(/email/i), "eng@example.test");
    await user.type(screen.getByLabelText(/password/i), "a-long-enough-password");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("Eng", { exact: false })).toBeInTheDocument();
    const login = calls.find((c) => c.url.includes("/auth/login"))!;
    expect(JSON.parse(login.body!).session).toBe("cookie");
    expect(isSignedIn()).toBe(true);
    expect(calls.filter((c) => c.url.includes("/documents")).every((c) => !c.headers.get("Authorization"))).toBe(true);
  });

  it("signing out tells the server to clear the cookie and the page forgets at once", async () => {
    const calls = mockApi({ cookieSignedIn: true });
    const user = userEvent.setup();
    render(<App initialView="documents" />);
    await screen.findByText("Eng", { exact: false });
    await user.click(screen.getByRole("button", { name: /sign out/i }));
    expect(await screen.findByLabelText(/password/i)).toBeInTheDocument();
    const logout = calls.find((c) => c.url.includes("/auth/logout"))!;
    expect(logout.method).toBe("POST");
    expect(logout.headers.get("X-Requested-With")).toBe("rag-ui");
    expect(isSignedIn()).toBe(false);
  });

  it("when the server refuses the cookie (plain http on a network address) the bearer token is held and sent instead", async () => {
    const calls = mockApi({ cookieSignedIn: false, loginToken: "tok-123" });
    const user = userEvent.setup();
    render(<App initialView="documents" />);
    await user.type(await screen.findByLabelText(/email/i), "eng@example.test");
    await user.type(screen.getByLabelText(/password/i), "a-long-enough-password");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("Eng", { exact: false })).toBeInTheDocument();
    const afterLogin = calls.slice(calls.findIndex((c) => c.url.includes("/auth/login")) + 1);
    const later = afterLogin.filter((c) => c.url.includes("/documents"));
    expect(later.length).toBeGreaterThan(0);
    expect(later.every((c) => c.headers.get("Authorization") === "Bearer tok-123")).toBe(true);
  });
});
