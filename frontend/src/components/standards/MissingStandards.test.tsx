/**
 * The missing-standards list: a publisher link for a public standard, none for
 * a company one, and "Requested" only when someone recorded it.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { MissingStandards } from "./MissingStandards";
import type { MissingStandard } from "../../types/api";

const api610: MissingStandard = {
  identifier: "API 610", standard_family: "API", licence_status: "licensed_not_held",
  cited_by: [{ source_type: "submittal", document_id: "s1", filename: "x.pdf" }],
  status: "MISSING_LOCALLY", note: null, requested_by: null, requested_at: null,
  obtain: { publisher: "American Petroleum Institute (API)",
            url: "https://www.apiwebstore.org/", note: "Sold under licence" },
};
const saes: MissingStandard = {
  ...api610, identifier: "SAES-L-105", standard_family: "SAES",
  obtain: { publisher: "Client (company standard)", url: null,
            note: "Company standard - request it from the client's standards custodian and upload it" },
};

function mockFetch(rows: MissingStandard[], posts: unknown[] = []) {
  let current = rows;
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
    const json = (b: unknown) => new Response(JSON.stringify(b),
      { status: 200, headers: { "Content-Type": "application/json" } });
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      posts.push(body);
      current = current.map((r) => r.identifier === body.identifier
        ? { ...r, status: "REQUESTED", requested_by: "eng-1" } : r);
      return json({ identifier: body.identifier, status: "REQUESTED",
                    requested_by: "eng-1", requested_at: "2026-09-29T00:00:00Z" });
    }
    return json(current);
  }));
}

beforeEach(() => { vi.restoreAllMocks(); });

describe("missing standards", () => {
  it("links a public standard to its publisher and never a company one", async () => {
    mockFetch([api610, saes]);
    render(<MissingStandards />);
    const link = await screen.findByRole("link", { name: "American Petroleum Institute (API)" });
    expect(link.getAttribute("href")).toBe("https://www.apiwebstore.org/");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(screen.getByText(/standards custodian/)).toBeTruthy();
    expect(screen.getAllByRole("link")).toHaveLength(1);
  });

  it("shows Missing until someone records a request, then who did", async () => {
    const posts: unknown[] = [];
    mockFetch([api610], posts);
    render(<MissingStandards />);
    expect(await screen.findByText("Missing")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Mark requested" }));
    await waitFor(() => expect(screen.getByText("Requested")).toBeTruthy());
    expect(screen.getByText(/by eng-1/)).toBeTruthy();
    expect(posts).toEqual([{ identifier: "API 610", note: null }]);
    expect(screen.queryByRole("button", { name: "Mark requested" })).toBeNull();
  });

  it("says every cited standard is held when nothing is missing", async () => {
    mockFetch([]);
    render(<MissingStandards />);
    expect(await screen.findByText(/every cited standard is in the library/i)).toBeTruthy();
  });
});
