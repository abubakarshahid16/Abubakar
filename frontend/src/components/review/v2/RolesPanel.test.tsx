import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NOT_RECORDED, RolesPanel, RolesView, type RoleRow } from "./RolesPanel";

const api = { request: vi.fn() };
vi.mock("../../../api/core", () => ({ request: (...a: unknown[]) => api.request(...a) }));

const role = (n: number, over: Partial<RoleRow> = {}): RoleRow => ({
  role_no: n, role: ["", "Reader", "Project context", "Librarian", "Reviewer", "Checklist", "Second reviewer", "Code", "Decision rule", "Writer"][n],
  state: "ran", why: null, engine: n === 7 || n === 8 ? "code" : "claude", models: n === 7 || n === 8 ? [] : ["m1"], calls: 2, usd: 0.5,
  produced: {}, reads: [], ...over,
});
const nine = (over: Record<number, Partial<RoleRow>> = {}) => Array.from({ length: 9 }, (_, i) => role(i + 1, over[i + 1]));

beforeEach(() => api.request.mockReset());

describe("RolesView", () => {
  it("says plainly when there is no record, and invents nothing", () => {
    render(<RolesView roles={null} />);
    expect(screen.getByTestId("roles-not-recorded")).toHaveTextContent(NOT_RECORDED);
    expect(screen.queryByTestId("roles-panel")).toBeNull();
  });
  it("names a role that did not run with its reason, and says cost not known rather than 0", () => {
    render(<RolesView roles={nine({ 2: { state: "not_run", why: "none held for this project", engine: null, models: [], calls: 0 }, 4: { usd: null } })} />);
    expect(screen.getByTestId("roles-line")).toHaveTextContent("Roles run: 8 of 9; not run: 2 Project context: none held for this project");
    expect(screen.getByTestId("role-4")).toHaveTextContent("cost (USD) not known");
    expect(screen.getByTestId("role-7")).not.toHaveTextContent("cost");
  });
  it("shows a count for a document the user may not read, never its name", () => {
    const reads = [
      { document_kind: "rule_book", pages: [3, 4], chars: 900, pictures: 0, readable: true, name: "Readable book" },
      { document_kind: "project_document", pages: [1], chars: 400, pictures: 0, readable: false, name: null },
      { document_kind: "project_document", pages: [2], chars: 400, pictures: 0, readable: false, name: "SECRET-NAME-LEAK" },
    ];
    render(<RolesView roles={nine({ 4: { reads } })} />);
    const line = screen.getByTestId("role-reads");
    expect(line).toHaveTextContent("Readable book");
    expect(line).toHaveTextContent("2 document(s) you may not read");
    expect(document.body.textContent).not.toContain("SECRET-NAME-LEAK");
  });
});

describe("RolesPanel", () => {
  it("loads the record of the run and shows the nine roles", async () => {
    api.request.mockResolvedValue({ ok: true, data: { roles: nine() } });
    render(<RolesPanel runId="r1" />);
    await waitFor(() => expect(screen.getByTestId("roles-panel")).toBeInTheDocument());
    expect(api.request).toHaveBeenCalledWith("/reviews/runs/r1/roles");
    expect(screen.getAllByTestId(/^role-\d$/)).toHaveLength(9);
  });
  it("says not recorded when the route has nothing (an old run)", async () => {
    api.request.mockResolvedValue({ ok: false, disconnected: false, error: { code: "not_found", message: "x" } });
    render(<RolesPanel runId="r1" />);
    await waitFor(() => expect(screen.getByTestId("roles-not-recorded")).toBeInTheDocument());
  });
});
