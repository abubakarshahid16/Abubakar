/**
 * Container tests: what the screen does with each kind of result.
 *
 * The routes do not exist yet, so the case that matters most is the one the
 * app is in today - every read 404s - and the screen must say the route is
 * missing rather than render three empty tables.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminClient, AdminResult } from "../types/admin";
import { AdminScreen } from "./AdminScreen";

function ok<T>(data: T): AdminResult<T> {
  return { ok: true, data };
}
// AdminResult<never> so an override slots into any of the seven methods:
// the failure arms carry no data, so `never` is assignable everywhere.
function fail(code: string, message = "no"): AdminResult<never> {
  return { ok: false, disconnected: false, error: { code, message } };
}
function offline(): AdminResult<never> {
  return { ok: false, disconnected: true, error: { code: "internal", message: "Cannot reach the backend." } };
}

function client(over: Partial<AdminClient> = {}): AdminClient {
  return {
    users: vi.fn(async () =>
      ok({
        users: [
          {
            user_id: "usr_a1b2c3d4",
            email: "ali@example.com",
            disciplines: [],
            is_admin: false,
            active: true,
            created_at: "2026-09-05T18:12:04Z",
            last_login_at: null,
            warning: "no_discipline" as const,
          },
        ],
      }),
    ),
    disciplines: vi.fn(async () =>
      ok({ disciplines: [{ name: "IT", user_count: 1, document_count: 0, warning: "no_documents" as const }] }),
    ),
    grants: vi.fn(async () =>
      ok({
        documents: [
          {
            document_id: "doc_1",
            filename: "spec.pdf",
            disciplines: ["IT"],
            warning: null,
          },
        ],
      }),
    ),
    createUser: vi.fn(async () =>
      ok({
        user_id: "usr_new",
        email: "new@example.com",
        setup_token: "one-time-value",
        setup_token_expires_at: "2026-09-06T21:40:00Z",
        shown_once: true,
      }),
    ),
    deactivateUser: vi.fn(async () => ok({ user_id: "usr_a1b2c3d4", active: false })),
    grant: vi.fn(async () => ok({ document_id: "doc_1", discipline: "IT", granted: true })),
    revoke: vi.fn(async () => ok({ document_id: "doc_1", discipline: "IT", granted: false })),
    ...over,
  } as AdminClient;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("unbuilt routes", () => {
  it("reports a 404 as a missing route, never as an empty list", async () => {
    render(
      <AdminScreen
        client={client({
          users: vi.fn(async () => fail("not_found")),
          disciplines: vi.fn(async () => fail("not_found")),
          grants: vi.fn(async () => fail("not_found")),
        })}
      />,
    );
    await waitFor(() => expect(screen.getAllByText(/not built yet/i).length).toBe(3));
    expect(screen.queryByText("No users")).not.toBeInTheDocument();
    expect(screen.queryByText("No documents")).not.toBeInTheDocument();
  });

  it("keeps a live section live when another route is missing", async () => {
    render(<AdminScreen client={client({ grants: vi.fn(async () => fail("not_found")) })} />);
    await waitFor(() => expect(screen.getByText("ali@example.com")).toBeInTheDocument());
    expect(screen.getAllByText(/not built yet/i)).toHaveLength(1);
  });
});

describe("offline is not a failed request", () => {
  it("renders the disconnected state, not an error card", async () => {
    render(<AdminScreen client={client({ users: vi.fn(async () => offline()) })} />);
    await waitFor(() =>
      expect(screen.getByText("The backend is not running")).toBeInTheDocument(),
    );
  });
});

describe("creating a user", () => {
  it("sends the form and shows the token once, and never re-reads it", async () => {
    const c = client();
    render(<AdminScreen client={c} />);
    await waitFor(() => expect(screen.getByText("ali@example.com")).toBeInTheDocument());

    await userEvent.type(screen.getByLabelText("Email"), "new@example.com");
    await userEvent.selectOptions(screen.getByLabelText("Discipline"), "IT");
    await userEvent.click(screen.getByRole("button", { name: "Create user" }));

    await waitFor(() => expect(screen.getByText("one-time-value")).toBeInTheDocument());
    expect(c.createUser).toHaveBeenCalledWith({
      email: "new@example.com",
      disciplines: ["IT"],
      is_admin: false,
    });
    // The list was re-read after the create; the token came only from the
    // create response and no list read can return it again.
    expect(c.users).toHaveBeenCalledTimes(2);
    expect(screen.getAllByText("one-time-value")).toHaveLength(1);

    await userEvent.click(screen.getByRole("button", { name: /hide it/i }));
    expect(screen.queryByText("one-time-value")).not.toBeInTheDocument();
  });

  it("names the conflict when the email is in use", async () => {
    render(
      <AdminScreen
        client={client({ createUser: vi.fn(async () => fail("email_in_use", "ignored")) })}
      />,
    );
    await waitFor(() => expect(screen.getByText("ali@example.com")).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText("Email"), "dup@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Create user" }));
    await waitFor(() =>
      expect(screen.getByText(/already has an account/i)).toBeInTheDocument(),
    );
  });
});

describe("grants", () => {
  it("revokes only after confirmation and then re-reads", async () => {
    const c = client();
    render(<AdminScreen client={c} />);
    await waitFor(() => expect(screen.getByText("spec.pdf")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
    expect(c.revoke).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() =>
      expect(c.revoke).toHaveBeenCalledWith({ document_id: "doc_1", discipline: "IT" }),
    );
    await waitFor(() => expect(c.grants).toHaveBeenCalledTimes(2));
  });
});

describe("the network layer", () => {
  it("never logs a setup token", async () => {
    const spy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<AdminScreen client={client()} />);
    await waitFor(() => expect(screen.getByText("ali@example.com")).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText("Email"), "new@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Create user" }));
    await waitFor(() => expect(screen.getByText("one-time-value")).toBeInTheDocument());
    const logged = [...spy.mock.calls, ...errorSpy.mock.calls].flat().join(" ");
    expect(logged).not.toContain("one-time-value");
  });
});
