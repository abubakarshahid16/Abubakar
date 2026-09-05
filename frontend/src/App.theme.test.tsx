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

vi.mock("./api/client", () => ({
  auth: { me: vi.fn(async () => ({ ok: false, disconnected: true })), login: vi.fn() },
  onSignedOut: vi.fn(),
  setToken: vi.fn(),
  api: { documents: vi.fn(async () => ({ ok: false, disconnected: true })) },
  health: { get: vi.fn(async () => ({ ok: false, disconnected: true })) },
}));

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
