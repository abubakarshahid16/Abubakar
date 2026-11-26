/** Technical query reviewers on the Administration page (owner, 26 Nov 2026: nobody held the role, so Confirm was refused for
 *  everyone). Invented users only. */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminUser } from "../../types/admin";
import { SELF_GRANT_WORDS, TechnicalQueryReviewersSection } from "./TechnicalQueryReviewersSection";

const req = vi.hoisted(() => vi.fn());
vi.mock("../../api/core", () => ({ request: (...a: unknown[]) => req(...a) }));

const ok = (data: unknown) => ({ ok: true, data });
const user = (id: string, email: string, is_admin = false): AdminUser =>
  ({ user_id: id, email, disciplines: [], is_admin, active: true, created_at: "2026-01-01T00:00:00Z", last_login_at: null, warning: null });
const USERS = [user("u-admin", "admin@invented.example", true), user("u-eng", "eng@invented.example")];

function serve(holders: string[]) {
  let held = [...holders];
  req.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === "/auth/me") return ok({ required: true, user: { id: "u-admin", email: "admin@invented.example", display_name: "A", roles: [] } });
    if (path === "/technical-queries/reviewers") return ok({ items: held.map((id) => ({ id, email: `${id}@x` })) });
    const id = decodeURIComponent(path.split("/").pop() ?? "");
    held = init?.method === "PUT" ? [...held, id] : held.filter((h) => h !== id);
    return ok({ items: held.map((h) => ({ id: h, email: `${h}@x` })) });
  });
}

describe("Technical query reviewers", () => {
  beforeEach(() => { req.mockReset(); }); // braces: a returned mock would be run as the test's clean-up

  it("says nobody holds the role, gives it to another user through the existing route, and can take it back", async () => {
    serve([]);
    render(<TechnicalQueryReviewersSection users={USERS} />);
    expect(await screen.findByTestId("tq-reviewers-count")).toHaveTextContent("Nobody holds the role yet.");
    const eng = screen.getAllByTestId("tq-reviewer-row").find((r) => r.textContent?.includes("eng@"))!;
    await userEvent.click(within(eng).getByRole("button", { name: "Give the role" }));
    expect(req).toHaveBeenCalledWith("/technical-queries/reviewers/u-eng", { method: "PUT" });
    expect(await screen.findByTestId("tq-reviewers-count")).toHaveTextContent("1 of 2 active users hold the role.");
    await userEvent.click(within(eng).getByRole("button", { name: "Remove the role" }));
    expect(req).toHaveBeenLastCalledWith("/technical-queries/reviewers/u-eng", { method: "DELETE" });
  });

  it("the administrator's own row offers no grant and says why (the server's rule)", async () => {
    serve([]);
    render(<TechnicalQueryReviewersSection users={USERS} />);
    const own = (await screen.findAllByTestId("tq-reviewer-row")).find((r) => r.textContent?.includes("admin@"))!;
    expect(await within(own).findByText(SELF_GRANT_WORDS)).toBeInTheDocument();
    expect(within(own).queryByRole("button")).toBeNull();
  });

  it("a refusal is shown in the server's words; switched off, there is no section", async () => {
    req.mockImplementation(async (path: string) =>
      path === "/auth/me" ? ok({ required: true, user: null }) : { ok: false, disconnected: false, error: { code: "forbidden", message: "an administrator is required" } });
    render(<TechnicalQueryReviewersSection users={USERS} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("an administrator is required");
    req.mockImplementation(async () => ({ ok: false, disconnected: false, error: { code: "not_found", message: "not found" } }));
    const { container } = render(<TechnicalQueryReviewersSection users={USERS} />);
    await vi.waitFor(() => expect(container.querySelector("[data-testid='tq-reviewers']")).toBeNull());
  });
});
