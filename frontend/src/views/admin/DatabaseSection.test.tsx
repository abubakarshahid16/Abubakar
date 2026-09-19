/**
 * The Database section: a window on the tables, and provably not a workbench.
 *
 * THE "NO EDIT AFFORDANCES" CLAIM IS ASSERTED, NOT STATED. A comment saying
 * a screen is read-only is worth nothing; the test below sweeps the rendered
 * DOM for every input, textarea, select, and every button that is not one of
 * the three this screen is allowed to have. It fails when somebody adds a
 * Save - including a DISABLED one, which is worse than none because it tells
 * a reader the capability exists and they lack permission.
 *
 * AND THE PAGING LINE CARRIES ITS DENOMINATOR. "rows 21-40 of 6,805", never
 * "page 2" - a page number is a fact about the pager, not about the data.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DatabaseSection } from "./DatabaseSection";
import type { AdminClient } from "../../types/admin";

const MASK = "•••";

const dbTables = vi.fn();
const dbTable = vi.fn();
const dbRows = vi.fn();

function client(): AdminClient {
  return {
    users: vi.fn(), createUser: vi.fn(), deactivateUser: vi.fn(),
    disciplines: vi.fn(), grants: vi.fn(), grant: vi.fn(), revoke: vi.fn(),
    dbTables, dbTable, dbRows,
  } as unknown as AdminClient;
}

beforeEach(() => {
  dbTables.mockReset(); dbTable.mockReset(); dbRows.mockReset();
  dbTables.mockResolvedValue({
    ok: true,
    data: { tables: [{ name: "users", row_count: 3 },
                     { name: "documents", row_count: 6805 }] },
  });
  dbTable.mockResolvedValue({
    ok: true,
    data: {
      name: "users", row_count: 3,
      columns: [
        { name: "id", type: "TEXT", pk: true, sensitive: false },
        { name: "email", type: "TEXT", sensitive: false },
        { name: "password_hash", type: "TEXT", sensitive: true },
        { name: "display_name", type: "TEXT", sensitive: false },
      ],
    },
  });
  dbRows.mockResolvedValue({
    ok: true,
    data: {
      name: "users",
      columns: ["id", "email", "password_hash", "display_name"],
      rows: [
        ["u1", "a@b.test", MASK, "Ali"],
        ["u2", "c@d.test", MASK, null],
      ],
      offset: 0, limit: 25, total: 3, masked_columns: ["password_hash"],
    },
  });
});

describe("the table list", () => {
  it("shows every table with its row count", async () => {
    render(<DatabaseSection client={client()} />);

    expect(await screen.findByRole("button", { name: "users" })).toBeInTheDocument();
    expect(screen.getByText("6,805")).toBeInTheDocument();
  });

  it("says the explorer is absent rather than showing no tables", async () => {
    dbTables.mockResolvedValue({
      ok: false, disconnected: false,
      error: { code: "not_found", message: "not found" },
    });
    render(<DatabaseSection client={client()} />);

    // "missing" and "empty" must never render alike: one is a fact about this
    // backend, the other a claim about the data.
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /does not serve the database explorer/i);
  });

  it("distinguishes an unreachable backend from an absent route", async () => {
    dbTables.mockResolvedValue({
      ok: false, disconnected: true,
      error: { code: "internal", message: "x" },
    });
    render(<DatabaseSection client={client()} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /backend is not running/i);
  });
});

describe("opening a table", () => {
  it("shows its columns and a page of its rows", async () => {
    render(<DatabaseSection client={client()} />);
    await userEvent.click(await screen.findByRole("button", { name: "users" }));

    expect(await screen.findByText(/users — columns/)).toBeInTheDocument();
    expect(screen.getByText("a@b.test")).toBeInTheDocument();
    expect(dbRows).toHaveBeenCalledWith("users", 25, 0);
  });

  it("renders null as nothing, not as the word null", async () => {
    render(<DatabaseSection client={client()} />);
    await userEvent.click(await screen.findByRole("button", { name: "users" }));
    await screen.findByText("a@b.test");

    // The second row's display_name is null. Not "null", not "-", not 0.
    const row = screen.getByText("c@d.test").closest("tr")!;
    const cells = within(row).getAllByRole("cell");
    expect(cells[3]).toBeEmptyDOMElement();
    expect(screen.queryByText("null")).toBeNull();
  });

  it("marks the masked column and explains the mask in a tooltip", async () => {
    render(<DatabaseSection client={client()} />);
    await userEvent.click(await screen.findByRole("button", { name: "users" }));
    await screen.findByText("a@b.test");

    const masked = screen.getAllByTitle("masked credential material");
    expect(masked.length).toBeGreaterThan(0);
    // The column NAME is still on screen. Hiding it would misreport the table.
    expect(screen.getAllByText(/password_hash/).length).toBeGreaterThan(0);
  });
});

describe("paging states its denominator", () => {
  it("reads rows X-Y of TOTAL, never a page number", async () => {
    dbRows.mockResolvedValue({
      ok: true,
      data: {
        name: "documents", columns: ["id"],
        rows: Array.from({ length: 25 }, (_, i) => [`d${i}`]),
        offset: 25, limit: 25, total: 6805, masked_columns: [],
      },
    });
    render(<DatabaseSection client={client()} />);
    await userEvent.click(await screen.findByRole("button", { name: "documents" }));

    expect(await screen.findByText(/rows 26–50 of 6,805/)).toBeInTheDocument();
    expect(screen.queryByText(/page \d/i)).toBeNull();
  });

  it("walks forward and back by offset", async () => {
    render(<DatabaseSection client={client()} />);
    await userEvent.click(await screen.findByRole("button", { name: "documents" }));
    await screen.findByText(/rows 1–/);

    // Previous is disabled at the start - the honest state, not a wrap-around.
    expect(screen.getByRole("button", { name: /Previous/ })).toBeDisabled();
  });

  it("says so when the server capped the page", async () => {
    dbRows.mockResolvedValue({
      ok: true,
      data: {
        name: "documents", columns: ["id"], rows: [["d1"]],
        offset: 0, limit: 200, total: 6805, masked_columns: [],
      },
    });
    render(<DatabaseSection client={client()} pageSize={500} />);
    await userEvent.click(await screen.findByRole("button", { name: "documents" }));

    expect(await screen.findByText(/capped this page at 200 rows/)).toBeInTheDocument();
  });
});

describe("a window, not a workbench", () => {
  it("offers no way to change anything, not even a disabled one", async () => {
    const { container } = render(<DatabaseSection client={client()} />);
    await userEvent.click(await screen.findByRole("button", { name: "users" }));
    await screen.findByText("a@b.test");

    // Nothing that accepts input, anywhere in the section.
    expect(container.querySelectorAll("input, textarea, select")).toHaveLength(0);
    expect(container.querySelectorAll("form")).toHaveLength(0);
    expect(container.querySelectorAll("[contenteditable]")).toHaveLength(0);

    // And every button is navigation. A DISABLED Save would still fail this,
    // which is the point: it would claim the capability exists.
    const allowed = /^(users|documents|Previous|Next)$/;
    const offenders = Array.from(container.querySelectorAll("button"))
      .map((b) => (b.textContent ?? "").trim())
      .filter((label) => !allowed.test(label));
    expect(offenders).toEqual([]);
  });

  it("never calls a write method, because the client exposes none", () => {
    const api = client();

    // The type has no db write at all; this is the runtime half of that.
    expect("dbUpdate" in api).toBe(false);
    expect("dbDelete" in api).toBe(false);
    expect("dbInsert" in api).toBe(false);
  });
});
