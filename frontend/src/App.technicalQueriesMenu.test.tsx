/**
 * The Technical Queries menu entry follows the server's switch from the FIRST screen after sign-in (found on the practice copy, 26 Nov 2026: the
 * entry stayed hidden until a reload, because the sign-in answer did not carry the switch and the page rebuilt its status without it).
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { onSignedOut, setCookieSession, setToken } from "./api/client";

const ME = { id: "u1", email: "eng@example.test", display_name: "Eng", roles: [] };
const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

function mockApi(technicalQueries: boolean, signedIn = false) {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/auth/me")) {
      return signedIn ? json({ required: true, user: ME, technical_queries: technicalQueries }) : json({ detail: { code: "unauthenticated", message: "sign in to continue" } }, 401);
    }
    if (url.includes("/auth/login")) return json({ token: null, user: ME, expires_in_seconds: 28800, technical_queries: technicalQueries });
    if (url.includes("/documents")) return json([]);
    if (url.includes("/metrics")) return json({ refresh_seconds: 15 });
    return json({ ok: true, embed_model_present: true, answer_model_configured: true, ingestion: { alive: true, stalled: false, busy: false } });
  }));
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

async function signIn() {
  const user = userEvent.setup();
  render(<App initialView="documents" />);
  await user.type(await screen.findByLabelText(/email/i), "eng@example.test");
  await user.type(screen.getByLabelText(/password/i), "a-long-enough-password");
  await user.click(screen.getByRole("button", { name: /sign in/i }));
  await screen.findByText("Eng", { exact: false });
}

describe("the Technical Queries menu entry", () => {
  it("is in the menu right after a sign-in when the server has the feature on", async () => {
    mockApi(true);
    await signIn();
    expect(screen.getAllByText("Technical Queries").length).toBeGreaterThan(0);
  });

  it("is not in the menu when the feature is off", async () => {
    mockApi(false);
    await signIn();
    expect(screen.queryByText("Technical Queries")).toBeNull();
  });

  it("is in the menu after a reload (the /me answer carries it)", async () => {
    mockApi(true, true);
    render(<App initialView="documents" />);
    await screen.findByText("Eng", { exact: false });
    expect(screen.getAllByText("Technical Queries").length).toBeGreaterThan(0);
  });
});
