/**
 * An expired sign-in is said even while a page is still loading (27 Nov 2026: Documents and Ingestion load when opened). The notice
 * lives in the shell (App's onSignedOut and the sign-in screen), never in a lazily loaded page, so a 401 that lands before the page
 * is on screen is shown at once. Here the Documents page never finishes loading; a 401 on any request must still show the notice.
 * Invented values only.
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { onSignedOut, setCookieSession, setToken } from "./api/client";
import { request } from "./api/core";

// the Documents page's code never arrives: its loading boundary stays on the spinner for the whole test
vi.mock("./views/DocumentsView", () => new Promise(() => undefined));

const NOTICE = /sign-in expired, sign in again/i;
const ME = { id: "u1", email: "eng@example.test", display_name: "Eng", roles: [], session_expired_notice: true };
const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));
let expired = false;

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  onSignedOut(null);
  setToken(null);
  setCookieSession(false);
  try { localStorage.clear(); sessionStorage.clear(); } catch { /* ignore */ }
  window.history.pushState({}, "", "/");
});

describe("an expired sign-in while a page is still loading", () => {
  it("shows the notice at once, from the shell, though the page that would poll has not loaded", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/auth/me")) return reply({ required: true, user: ME });
      if (url.includes("/other")) return expired ? reply({ detail: { code: "unauthenticated", message: "sign in to continue" } }, 401) : reply({});
      return reply({ ok: true, embed_model_present: true, answer_model_configured: true, ingestion: { alive: true, stalled: false, busy: false } });
    }));
    render(<App initialView="documents" />);
    expect(await screen.findByText("Eng", { exact: false })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1, name: "Documents" })).toBeNull(); // the page is still loading
    expired = true;
    await act(async () => { await request("/other"); });
    expect(await screen.findAllByText(NOTICE)).toHaveLength(1);
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });
});
