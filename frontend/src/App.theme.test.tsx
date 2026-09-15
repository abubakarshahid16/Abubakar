/**
 * The theme attribute is stamped on <html>, and the toggle changes it.
 *
 * This is the test the bug needed and did not have. ThemeToggle called a
 * handler, Shell declared the props, index.css defined both palettes - and
 * App never passed the props or stamped the attribute, so every piece looked
 * right in isolation and the button did nothing.
 *
 * It also guards something larger: the bare @theme block still carries the
 * pre-redesign palette (#070b10 ground, #7d90a4 secondary at 4.1:1). The
 * corrected values live in [data-theme="dark"], so an unstamped document
 * serves the OLD contrast to everyone. Stopping the stamp is not a cosmetic
 * regression.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Everything App reaches for on mount answers "disconnected". The mock is
// built on the real module so a method this file forgets still exists rather
// than being `undefined` - the previous hand-written partial stubbed a
// `health.get` that no longer exists and omitted `api.health` / `api.metrics`
// (Shell's health poll and DocumentsView's refresh), which surfaced as four
// unhandled "api.X is not a function" rejections that failed the whole run
// even though every assertion here passed.
vi.mock("./api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("./api/client")>();
  // Declared inside the factory: vi.mock is hoisted above any top-level const.
  const disconnected = async () => ({ ok: false as const, disconnected: true as const });
  return {
    ...real,
    auth: { ...real.auth, me: vi.fn(disconnected), login: vi.fn(disconnected) },
    api: {
      ...real.api,
      health: vi.fn(disconnected),
      metrics: vi.fn(disconnected),
      documents: vi.fn(disconnected),
    },
  };
});

import App from "./App";

describe("the theme attribute", () => {
  beforeEach(() => {
    document.documentElement.removeAttribute("data-theme");
    try { localStorage.clear(); } catch { /* ignore */ }
  });

  it("is stamped on <html> as soon as the app renders", async () => {
    render(<App />);
    await waitFor(() =>
      expect(document.documentElement.getAttribute("data-theme")).toBe("dark"),
    );
  });

  it("changes to light when the Light control is pressed", async () => {
    render(<App />);
    await waitFor(() =>
      expect(document.documentElement.getAttribute("data-theme")).toBe("dark"),
    );
    const light = screen.getAllByRole("button", { name: /light/i })[0];
    await userEvent.click(light);
    await waitFor(() =>
      expect(document.documentElement.getAttribute("data-theme")).toBe("light"),
    );
  });
});
