/**
 * Tests for the rules that are cheap to break and silent when broken.
 *
 * Each of these was proven red by deleting or inverting the code it covers:
 * the null-renders-as-nothing rule, the confirm-before-destroy rule, the
 * offline-vs-failed distinction, and the seeded-but-useless summary.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  AdminDiscipline,
  AdminGrantDocument,
  AdminUser,
} from "../types/admin";
import { AdminView, type AdminViewProps } from "./AdminView";
import { management, reviews } from "../api/client";

/** A user who has NEVER signed in. The null rule cannot be tested on a
 *  fixture that carries a timestamp - the assertion would pass on a component
 *  that renders a dash for null and nothing would be proven. */
const neverSignedIn: AdminUser = {
  user_id: "usr_a1b2c3d4",
  email: "ali@example.com",
  disciplines: ["Civil Engineering"],
  is_admin: false,
  active: true,
  created_at: "2026-09-05T18:12:04Z",
  last_login_at: null,
  warning: null,
};

const noDiscipline: AdminUser = {
  user_id: "usr_e5f6a7b8",
  email: "new@example.com",
  disciplines: [],
  is_admin: false,
  active: true,
  created_at: "2026-09-05T21:40:00Z",
  last_login_at: null,
  warning: "no_discipline",
};

const disciplines: AdminDiscipline[] = [
  { name: "Civil Engineering", user_count: 2, document_count: 5, warning: null },
  { name: "IT", user_count: 1, document_count: 0, warning: "no_documents" },
];

const documents: AdminGrantDocument[] = [
  {
    document_id: "doc_626b1a92bf6d",
    filename: "NORSOKM501Rev5.pdf",
    disciplines: ["Civil Engineering"],
    warning: null,
  },
  {
    document_id: "doc_a728541bbdc5",
    filename: "doc13.pdf",
    disciplines: [],
    warning: "no_discipline_can_see_this",
  },
];

function props(over: Partial<AdminViewProps> = {}): AdminViewProps {
  return {
    users: [neverSignedIn, noDiscipline],
    usersFailure: null,
    disciplines,
    disciplinesFailure: null,
    documents,
    documentsFailure: null,
    created: null,
    createBusy: false,
    createError: null,
    onCreateUser: vi.fn(),
    onDismissCreated: vi.fn(),
    onDeactivateUser: vi.fn(),
    onResetPassword: vi.fn(),
    onGrant: vi.fn(),
    onRevoke: vi.fn(),
    onRetry: vi.fn(),
    busyKey: null,
    ...over,
  };
}

describe("password reset", () => {
  it("lets an administrator issue a reset token for an active user", async () => {
    const onResetPassword = vi.fn();
    const user = userEvent.setup();
    render(<AdminView {...props({ users: [neverSignedIn], onResetPassword })} />);
    await user.click(screen.getByRole("button", { name: "Reset password" }));
    expect(onResetPassword).toHaveBeenCalledWith(neverSignedIn.user_id);
  });
});

describe("null renders as nothing", () => {
  it("shows no dash, zero or 'never' for a user who has never signed in", () => {
    render(<AdminView {...props({ users: [neverSignedIn] })} />);
    const row = screen.getByText("ali@example.com").closest("tr")!;
    const cells = within(row).getAllByRole("cell");
    // Column order: email, disciplines, admin, created, last sign-in, actions.
    expect(cells[4]).toBeEmptyDOMElement();
    expect(row.textContent).not.toMatch(/never|N\/A|—|–/i);
    // A bare "-" or "0" anywhere in the row would be a placeholder.
    expect(row.textContent).not.toMatch(/(^|\s)[-0]($|\s)/);
  });

  it("shows nothing rather than 'not an admin' for is_admin false", () => {
    render(<AdminView {...props({ users: [neverSignedIn] })} />);
    const row = screen.getByText("ali@example.com").closest("tr")!;
    expect(within(row).getAllByRole("cell")[2]).toBeEmptyDOMElement();
  });
});

describe("destructive actions confirm first", () => {
  it("does not revoke on the first click", async () => {
    const onRevoke = vi.fn();
    render(<AdminView {...props({ onRevoke })} />);
    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
    expect(onRevoke).not.toHaveBeenCalled();
    expect(screen.getByText("Revoke Civil Engineering?")).toBeInTheDocument();
  });

  it("revokes exactly once after confirming, with the right document", async () => {
    const onRevoke = vi.fn();
    render(<AdminView {...props({ onRevoke })} />);
    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
    expect(onRevoke).toHaveBeenCalledTimes(1);
    expect(onRevoke).toHaveBeenCalledWith({
      document_id: "doc_626b1a92bf6d",
      discipline: "Civil Engineering",
    });
  });

  it("cancels without revoking", async () => {
    const onRevoke = vi.fn();
    render(<AdminView {...props({ onRevoke })} />);
    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await userEvent.click(screen.getByRole("button", { name: "Keep it" }));
    expect(onRevoke).not.toHaveBeenCalled();
  });

  it("does not deactivate on the first click", async () => {
    const onDeactivateUser = vi.fn();
    render(<AdminView {...props({ users: [neverSignedIn], onDeactivateUser })} />);
    await userEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    expect(onDeactivateUser).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    expect(onDeactivateUser).toHaveBeenCalledWith("usr_a1b2c3d4");
  });

  it("a revoke control is not styled as a neutral button", () => {
    render(<AdminView {...props()} />);
    expect(screen.getByRole("button", { name: "Revoke" }).className).toMatch(
      /hover:text-danger-500/,
    );
  });
});

describe("offline and failed never look the same", () => {
  it("says the backend is not running when offline", () => {
    render(<AdminView {...props({ users: null, usersFailure: { kind: "offline" } })} />);
    expect(screen.getByText("The backend is not running")).toBeInTheDocument();
    expect(screen.queryByText(/not built yet/i)).not.toBeInTheDocument();
  });

  it("says the route is not built for a 404, not 'no users'", () => {
    render(<AdminView {...props({ users: null, usersFailure: { kind: "missing" } })} />);
    expect(screen.getByText(/not built yet/i)).toBeInTheDocument();
    expect(screen.queryByText("No users")).not.toBeInTheDocument();
    expect(screen.queryByText("The backend is not running")).not.toBeInTheDocument();
  });

  it("shows the request's own message for a rejected request", () => {
    render(
      <AdminView
        {...props({
          users: null,
          usersFailure: { kind: "failed", code: "internal", message: "It blew up." },
        })}
      />,
    );
    expect(screen.getByText("It blew up.")).toBeInTheDocument();
    expect(screen.queryByText("The backend is not running")).not.toBeInTheDocument();
    expect(screen.queryByText(/not built yet/i)).not.toBeInTheDocument();
  });
});

describe("the seeded-but-useless summary", () => {
  it("counts users without a discipline and disciplines without documents", () => {
    render(<AdminView {...props()} />);
    const summary = screen.getByRole("status", { name: "Access problems" });
    expect(summary.textContent).toContain("1 user has no discipline.");
    expect(summary.textContent).toContain("1 discipline has no documents.");
    expect(summary.textContent).toContain("1 document is visible to nobody.");
  });

  it("is absent when nothing is wrong", () => {
    render(
      <AdminView
        {...props({
          users: [neverSignedIn],
          disciplines: [disciplines[0]],
          documents: [documents[0]],
        })}
      />,
    );
    expect(screen.queryByRole("status", { name: "Access problems" })).not.toBeInTheDocument();
  });
});

describe("the setup token", () => {
  it("is shown once, says so, and there is no password field anywhere", () => {
    const { container } = render(
      <AdminView
        {...props({
          created: {
            user_id: "usr_e5f6a7b8",
            email: "new@example.com",
            setup_token: "one-time-value",
            setup_token_expires_at: "2026-09-06T21:40:00Z",
            shown_once: true,
          },
        })}
      />,
    );
    expect(screen.getAllByText("one-time-value")).toHaveLength(1);
    expect(screen.getByText(/cannot be retrieved again/i)).toBeInTheDocument();
    expect(container.querySelector('input[type="password"]')).toBeNull();
  });
});

describe("row isolation", () => {
  it("keeps each user's warning in that user's own row", () => {
    render(<AdminView {...props()} />);
    const clean = screen.getByText("ali@example.com").closest("tr")!;
    const warned = screen.getByText("new@example.com").closest("tr")!;
    expect(warned.textContent).toContain("No discipline");
    expect(clean.textContent).not.toContain("No discipline");
    expect(clean.textContent).not.toContain("new@example.com");
  });
});

describe("engineering review controls", () => {
  it("renders baseline rules and submits a new rule", async () => {
    vi.spyOn(reviews, "baselineRules").mockResolvedValue({ ok: true, data: { rules: [{ id: "r1", submittal_doc_type: "Drawing", submittal_discipline: null, baseline_doc_type: "Specification", baseline_discipline: null, priority: 1, active: true, created_at: "2026-01-01" }] } });
    const create = vi.spyOn(reviews, "createBaselineRule").mockResolvedValue({ ok: true, data: { id: "r2", submittal_doc_type: "Report", submittal_discipline: null, baseline_doc_type: "Specification", baseline_discipline: null, priority: 0, active: true, created_at: "2026-01-01" } });
    vi.spyOn(management, "emailSummary").mockResolvedValue({ ok: true, data: { sent: true } });
    const user = userEvent.setup();
    render(<AdminView {...props()} />);
    expect(await screen.findByText("Specification")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Submittal document type" }), "Report");
    await user.type(screen.getByRole("textbox", { name: "Baseline document type" }), "Specification");
    await user.click(screen.getByRole("button", { name: "Add rule" }));
    expect(create).toHaveBeenCalled();
    vi.restoreAllMocks();
  });
});
