/**
 * LoginView: one message for every credential failure (the enumeration-oracle
 * test), rate limiting as the only exception, offline short-circuits, and the
 * password never survives a failed attempt.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LoginView, RoleBadge, type LoginOutcome } from "./LoginView";
import type { Me } from "../types/api";

async function attempt(outcome: LoginOutcome, connected = true) {
  const onLogin = vi.fn(async () => outcome);
  const user = userEvent.setup();
  const view = render(<LoginView onLogin={onLogin} connected={connected} />);
  await user.type(screen.getByLabelText("Email"), "someone@example.com");
  await user.type(screen.getByLabelText("Password"), "hunter2");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  const alert = await screen.findByRole("alert");
  await waitFor(() => expect(alert.textContent?.trim()).not.toBe(""));
  const text = alert.textContent!.replace(/^!\s*/, "").trim();
  return { onLogin, text, view };
}

describe("LoginView: credential failures are indistinguishable", () => {
  it("renders the identical text with and without a backend message", async () => {
    const bare: LoginOutcome = { ok: false, kind: "credentials" };
    const leaky: LoginOutcome = { ok: false, kind: "credentials", message: "user not found" };
    expect(bare).not.toHaveProperty("message");
    expect(leaky.ok === false && leaky.message).toBe("user not found");

    const a = await attempt(bare);
    a.view.unmount();
    const b = await attempt(leaky);

    expect(a.text).not.toBe("");
    expect(b.text).toBe(a.text);
    expect(b.text).not.toMatch(/user not found/i);
  });

  it("rate_limited renders a different message from credentials", async () => {
    const a = await attempt({ ok: false, kind: "credentials" });
    a.view.unmount();
    const b = await attempt({ ok: false, kind: "rate_limited" });
    expect(b.text).not.toBe(a.text);
    expect(b.text).toMatch(/too many sign-in attempts/i);
  });
});

describe("LoginView: offline", () => {
  it("connected: false never calls onLogin and shows the offline message", async () => {
    const { onLogin, text } = await attempt({ ok: true }, false);
    expect(onLogin).not.toHaveBeenCalled();
    expect(text).toMatch(/backend is not running/i);
    expect(text).toMatch(/not a password problem/i);
  });
});

describe("LoginView: submission", () => {
  it("clears the password after a failed attempt", async () => {
    const pw = screen.queryByLabelText("Password");
    expect(pw).toBeNull();
    await attempt({ ok: false, kind: "credentials" });
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByLabelText("Email")).toHaveValue("someone@example.com");
  });

  it("disables submit while the promise is pending", async () => {
    let resolve!: (o: LoginOutcome) => void;
    const onLogin = vi.fn(() => new Promise<LoginOutcome>((r) => (resolve = r)));
    const user = userEvent.setup();
    render(<LoginView onLogin={onLogin} connected={true} />);
    await user.type(screen.getByLabelText("Email"), "someone@example.com");
    await user.type(screen.getByLabelText("Password"), "hunter2");
    const button = screen.getByRole("button", { name: "Sign in" });
    expect(button).toBeEnabled();

    await user.click(button);
    expect(onLogin).toHaveBeenCalledTimes(1);
    const pending = screen.getByRole("button", { name: /signing in/i });
    expect(pending).toBeDisabled();
    expect(pending).toHaveAttribute("aria-busy", "true");

    resolve({ ok: true });
    await waitFor(() => expect(screen.getByRole("button", { name: "Sign in" })).toHaveAttribute("aria-busy", "false"));
  });
});

describe("LoginView: password reset", () => {
  it("submits the one-time token and matching new password", async () => {
    const onResetPassword = vi.fn(async () => ({ ok: true as const }));
    const user = userEvent.setup();
    render(<LoginView onLogin={vi.fn()} onResetPassword={onResetPassword} connected />);
    await user.click(screen.getByRole("button", { name: "Set or reset password" }));
    await user.type(screen.getByLabelText("One-time reset token"), "t".repeat(43));
    await user.type(screen.getByLabelText("New password"), "Cedar#Orbit-42-Glass");
    await user.type(screen.getByLabelText("Confirm new password"), "Cedar#Orbit-42-Glass");
    await user.click(screen.getByRole("button", { name: "Save new password" }));
    await waitFor(() => expect(onResetPassword).toHaveBeenCalledWith(
      "t".repeat(43), "Cedar#Orbit-42-Glass"));
    expect(screen.getByText("Password saved. You can now sign in.")).toBeInTheDocument();
  });

  it("does not submit passwords that do not match", async () => {
    const onResetPassword = vi.fn();
    const user = userEvent.setup();
    render(<LoginView onLogin={vi.fn()} onResetPassword={onResetPassword} connected />);
    await user.click(screen.getByRole("button", { name: "Set or reset password" }));
    await user.type(screen.getByLabelText("One-time reset token"), "t".repeat(43));
    await user.type(screen.getByLabelText("New password"), "Cedar#Orbit-42-Glass");
    await user.type(screen.getByLabelText("Confirm new password"), "Different#Orbit-42");
    await user.click(screen.getByRole("button", { name: "Save new password" }));
    expect(onResetPassword).not.toHaveBeenCalled();
    expect(screen.getByText("The two passwords do not match.")).toBeInTheDocument();
  });
});

describe("RoleBadge", () => {
  it("me: null says authentication is disabled and invents no name", () => {
    const me: Me | null = null;
    expect(me).toBeNull();
    const { container } = render(<RoleBadge me={me} onLogout={vi.fn()} />);
    // Deliberately NOT role="status": a live region announces changes, and
    // this label never changes. As a status it also collided with the real
    // status messages on the Dashboard, so a screen reader heard it cut in.
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByText(/Authentication disabled/)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/admin|administrator|guest|anonymous/i);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("renders the real display name and roles when signed in", () => {
    const me: Me = { id: "u1", email: "ali@example.com", display_name: "Ali Z", roles: ["engineer"] };
    render(<RoleBadge me={me} onLogout={vi.fn()} />);
    expect(screen.getByText("Ali Z")).toBeInTheDocument();
    expect(screen.getByText("engineer")).toBeInTheDocument();
    expect(screen.queryByText(/Authentication disabled/)).toBeNull();
  });
});
