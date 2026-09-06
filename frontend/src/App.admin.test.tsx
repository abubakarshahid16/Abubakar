/**
 * The admin capability gate.
 *
 * The administration screen was written, typed and tested, and then reachable
 * by nobody: it was imported by no file and named by no navigation entry.
 * These tests hold the two halves of the fix together - that an admin can get
 * there, and that a non-admin cannot, by any route including one where the
 * view state already says "admin".
 *
 * The rule under test: the capability comes from `Me.roles` in the body of
 * /api/auth/me and from nowhere else, and a non-admin's DOM does not contain
 * the entry AT ALL. "Hidden" is not a security boundary - a class is one
 * devtools edit away from not being there. The server is the real boundary
 * (every /api/admin/* route 404s a non-admin, see backend/app/admin.py
 * `current_admin`); this is the UI declining to advertise a door it knows is
 * locked, and declining to open it either.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { setToken } from "./api/client";
import { hasAdminCapability, navFor, NAV } from "./components/Shell";
import type { Health } from "./api/client";
import type { Me } from "./types/api";

const healthOnline: Health = {
  ok: true,
  embed_model_present: true,
  answer_model_present: true,
  ingestion: { alive: true, stalled: false, busy: false },
};

const ADMIN: Me = {
  id: "usr_admin",
  email: "boss@example.com",
  display_name: "Boss",
  // `admin` is a CAPABILITY sitting alongside a discipline, not instead of
  // one. A person is IT *and* admin, which is exactly why this is a list.
  roles: ["IT", "admin"],
};

const PLAIN: Me = {
  id: "usr_plain",
  email: "someone@example.com",
  display_name: "Someone",
  roles: ["IT"],
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Every route the app touches while these tests run, answered by URL. The
 *  admin routes answer with real (empty-but-valid) payloads so that reaching
 *  the screen is distinguishable from reaching it and having it 404. */
function mockApi(me: Me | null, opts: { required?: boolean } = {}) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const spy = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push({ url, init });
    if (url.includes("/auth/me")) {
      return Promise.resolve(
        json({ required: opts.required ?? true, user: me }),
      );
    }
    if (url.includes("/admin/users")) return Promise.resolve(json({ users: [] }));
    if (url.includes("/admin/disciplines")) {
      return Promise.resolve(json({ disciplines: [] }));
    }
    if (url.includes("/admin/grants")) return Promise.resolve(json({ documents: [] }));
    if (url.includes("/documents")) return Promise.resolve(json([]));
    if (url.includes("/metrics")) return Promise.resolve(json({ refresh_seconds: 15 }));
    return Promise.resolve(json(healthOnline));
  });
  vi.stubGlobal("fetch", spy);
  return { spy, calls };
}

/** The navigation button, or null. Deliberately a ROLE query rather than a
 *  text query: the screen's own <h1> is also "Administration", and a text
 *  match would let the presence of the heading disguise the absence of the
 *  button (and vice versa). */
function adminNavButton() {
  const nav = screen.queryByRole("navigation", { name: "Main" });
  if (!nav) return null;
  return within(nav).queryByRole("button", { name: /Administration/ });
}

beforeEach(() => vi.useRealTimers());
afterEach(() => {
  vi.unstubAllGlobals();
  // The token lives in a module-level variable in api/client.ts and would
  // otherwise leak from one test into the next.
  setToken(null);
});

describe("hasAdminCapability: the gate itself", () => {
  it("reads the capability out of Me.roles and nothing else", () => {
    expect(hasAdminCapability({ required: true, user: ADMIN })).toBe(true);
    expect(hasAdminCapability({ required: true, user: PLAIN })).toBe(false);
    // Not the email, not the display name. Only the roles list.
    expect(
      hasAdminCapability({
        required: true,
        user: { ...PLAIN, email: "admin@example.com", display_name: "Admin" },
      }),
    ).toBe(false);
  });

  it("is false while the answer is still unknown", () => {
    // `checking` and a backend that could not be reached both arrive here as
    // null. An unanswered question is not a yes.
    expect(hasAdminCapability(null)).toBe(false);
    expect(hasAdminCapability(undefined)).toBe(false);
    expect(hasAdminCapability({ required: true, user: null })).toBe(false);
  });

  it("appends the entry rather than mutating the shared NAV constant", () => {
    const before = NAV.length;
    expect(navFor({ required: true, user: PLAIN })).toHaveLength(before);
    expect(navFor({ required: true, user: ADMIN })).toHaveLength(before + 1);
    expect(navFor({ required: true, user: ADMIN }).at(-1)?.id).toBe("admin");
    expect(NAV).toHaveLength(before);
    expect(NAV.some((i) => i.id === "admin")).toBe(false);
  });
});

describe("an admin", () => {
  it("sees the navigation entry and can open the screen", async () => {
    mockApi(ADMIN);
    const user = userEvent.setup();
    render(<App />);

    const entry = await waitFor(() => {
      const b = adminNavButton();
      expect(b).not.toBeNull();
      return b!;
    });

    await user.click(entry);

    // The screen itself, not just a heading somewhere: AdminView's own <h1>.
    expect(
      await screen.findByRole("heading", { name: "Administration", level: 1 }),
    ).toBeInTheDocument();
    // And its sections, so a stub could not pass this.
    expect(screen.getByRole("heading", { name: /Users/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Disciplines/ })).toBeInTheDocument();
  });

  it("actually calls the admin routes once the screen is open", async () => {
    const { calls } = mockApi(ADMIN);
    const user = userEvent.setup();
    render(<App />);

    await user.click(
      await waitFor(() => {
        const b = adminNavButton();
        expect(b).not.toBeNull();
        return b!;
      }),
    );

    await waitFor(() => {
      const urls = calls.map((c) => c.url);
      expect(urls.some((u) => u.includes("/api/admin/users"))).toBe(true);
      expect(urls.some((u) => u.includes("/api/admin/disciplines"))).toBe(true);
      expect(urls.some((u) => u.includes("/api/admin/grants"))).toBe(true);
    });
  });

  it("attaches the bearer token to admin requests after signing in", async () => {
    // Sign-in first, because the token exists only after a login and the admin
    // routes 404 without it. This is the path a real admin walks.
    const calls: { url: string; init?: RequestInit }[] = [];
    let me: Me | null = null;
    const spy = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      calls.push({ url, init });
      if (url.includes("/auth/login")) {
        me = ADMIN;
        return Promise.resolve(
          json({ token: "tok_abc123", user: ADMIN, expires_in_seconds: 3600 }),
        );
      }
      if (url.includes("/auth/me")) {
        return me
          ? Promise.resolve(json({ required: true, user: me }))
          : Promise.resolve(json({ code: "unauthenticated", message: "sign in" }, 401));
      }
      if (url.includes("/admin/users")) return Promise.resolve(json({ users: [] }));
      if (url.includes("/admin/disciplines")) return Promise.resolve(json({ disciplines: [] }));
      if (url.includes("/admin/grants")) return Promise.resolve(json({ documents: [] }));
      if (url.includes("/documents")) return Promise.resolve(json([]));
      return Promise.resolve(json(healthOnline));
    });
    vi.stubGlobal("fetch", spy);

    const user = userEvent.setup();
    render(<App />);

    await user.type(await screen.findByLabelText("Email"), "boss@example.com");
    await user.type(screen.getByLabelText("Password"), "hunter2");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await user.click(
      await waitFor(() => {
        const b = adminNavButton();
        expect(b).not.toBeNull();
        return b!;
      }),
    );

    await waitFor(() => {
      const admin = calls.filter((c) => c.url.includes("/api/admin/"));
      expect(admin.length).toBeGreaterThan(0);
      for (const c of admin) {
        const auth = new Headers(c.init?.headers).get("Authorization");
        expect(auth).toBe("Bearer tok_abc123");
      }
    });
  });
});

describe("a non-admin", () => {
  it("has no administration entry ANYWHERE IN THE DOM, not merely hidden", async () => {
    mockApi(PLAIN);
    const { container } = render(<App />);

    // Wait for the identity to have landed, so this is an assertion about a
    // known non-admin rather than about a screen that has not decided yet.
    expect(await screen.findByText("Someone")).toBeInTheDocument();

    expect(adminNavButton()).toBeNull();
    // Not "invisible", not "display:none", not aria-hidden - absent. Nothing
    // in the rendered tree carries the word at all, so there is no node for a
    // devtools edit or an :not([hidden]) trick to reveal.
    expect(container.textContent).not.toMatch(/Administration/i);
    expect(container.querySelector('[aria-label="Main"]')).not.toBeNull();
    for (const el of Array.from(container.querySelectorAll("*"))) {
      expect(el.textContent ?? "").not.toMatch(/Administration/i);
    }
    // The six ordinary entries are still there, so this is not "the nav failed
    // to render" passing as "the admin entry is absent".
    expect(screen.getByRole("button", { name: /Documents/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Reports/ })).toBeInTheDocument();
  });

  it("does not get the screen even with the view state already set to admin", async () => {
    // The gate is the capability, NOT the absence of a button. This is the
    // case a hidden-nav-only implementation fails.
    const { calls } = mockApi(PLAIN);
    const { container } = render(<App initialView="admin" />);

    expect(await screen.findByText("Someone")).toBeInTheDocument();

    expect(screen.queryByRole("heading", { name: "Administration", level: 1 })).toBeNull();
    expect(container.textContent).not.toMatch(/Administration/i);
    // And it did not merely fail to render: it never asked. A screen that
    // fetched and then hid its output would have leaked the answer.
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    expect(calls.some((c) => c.url.includes("/api/admin/"))).toBe(false);
  });

  it("is still a non-admin when the roles list is empty or the user is null", async () => {
    mockApi({ ...PLAIN, roles: [] });
    render(<App />);
    expect(await screen.findByText("no roles")).toBeInTheDocument();
    expect(adminNavButton()).toBeNull();
  });
});

describe("authentication disabled", () => {
  it("shows the entry, because the backend serves the routes to anyone in that mode", async () => {
    // Stated rather than hidden: under AUTH_MODE=disabled, admin.current_admin
    // lets an unidentified caller through, because under that mode every
    // caller already reads every document. A UI stricter than the routes it
    // fronts would hide a screen the server is willing to serve. This is still
    // the API's answer (`required: false`), not a client-side guess.
    mockApi(null, { required: false });
    render(<App />);
    expect(await screen.findByText(/Authentication disabled/i)).toBeInTheDocument();
    await waitFor(() => expect(adminNavButton()).not.toBeNull());
  });
});
