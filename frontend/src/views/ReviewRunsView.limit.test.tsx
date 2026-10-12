/**
 * The submittal and standards lists ask for the backend maximum (the default
 * stops at 20) and say where a list was cut. Invented identifiers only.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewRunsView } from "./ReviewRunsView";

const documents = vi.fn();
vi.mock("../api/client", () => ({
  api: { documents: (...args: unknown[]) => documents(...args) },
  reviews: {
    reviewRuns: async () => ({ ok: true, data: { runs: [] } }),
    list: async () => ({ ok: true, data: { findings: [] } }),
    readiness: async () => ({ ok: false, error: { message: "n/a" } }),
    visionReaderStatus: async () => ({ ok: false, error: { message: "n/a" } }),
    reviewRunStandards: async () => ({ ok: true, data: { standards: [] } }),
  },
}));

const rows = (n: number) =>
  Array.from({ length: n }, (_, i) => ({
    id: `d${i}`, filename: `SUB-A-${i}.pdf`, document_role: "CONTRACTOR_SUBMITTAL",
  }));

beforeEach(() => documents.mockReset());

describe("review picker limits", () => {
  it("asks for 200 rows on both lists", async () => {
    documents.mockResolvedValue({ ok: true, data: rows(3), response: { headers: new Headers({ "X-Total-Count": "3" }) } });
    render(<ReviewRunsView />);
    await screen.findByLabelText("Submittal");
    const limits = documents.mock.calls.map(([o]) => (o as { limit?: number }).limit);
    expect(limits).toEqual([200, 200]);
    expect(screen.queryByTestId("submittals-boundary")).toBeNull();
  });

  it("states the boundary when the list was cut", async () => {
    documents.mockImplementation(async (o?: { document_role?: string[] }) =>
      o?.document_role?.[0] === "COMPANY_STANDARD"
        ? { ok: true, data: [], response: { headers: new Headers({ "X-Total-Count": "0" }) } }
        : { ok: true, data: rows(200), response: { headers: new Headers({ "X-Total-Count": "450" }) } });
    render(<ReviewRunsView />);
    expect(await screen.findByTestId("submittals-boundary"))
      .toHaveTextContent("Showing the newest 200 of 450 contractor submittals");
  });
});
