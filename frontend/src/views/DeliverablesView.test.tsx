/**
 * The Deliverables screen: a list whose request failed is not an empty list
 * (audit 2026-09-30). The error box and "No deliverables have been registered
 * yet." once showed together, which states both "it failed" and "there are
 * none".
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeliverablesView } from "./DeliverablesView";

const list = vi.fn();
const ok = (data: unknown) => Promise.resolve({ ok: true, data });
vi.mock("../api/client", () => ({
  deliverables: {
    list: () => list(),
    alerts: () => ok({ alerts: [] }),
    expected: () => ok({ deliverables: [] }),
  },
  management: { escalationRules: () => ok({ rules: [] }) },
  risks: { list: () => ok({ risks: [] }) },
}));

beforeEach(() => { list.mockReset(); });

describe("the WBS register", () => {
  it("says the register could not be loaded, and never that nothing is registered", async () => {
    list.mockResolvedValue({
      ok: false, disconnected: false,
      error: { code: "internal_error", message: "the register broke" },
    });
    render(<DeliverablesView />);
    expect(await screen.findByText("the register broke")).toBeInTheDocument();
    expect(screen.getByText(/The WBS register could not be loaded/)).toBeInTheDocument();
    expect(screen.queryByText("No deliverables have been registered yet.")).toBeNull();
  });

  it("says nothing is registered when the register loaded empty", async () => {
    list.mockResolvedValue({ ok: true, data: { deliverables: [] } });
    render(<DeliverablesView />);
    expect(await screen.findByText("No deliverables have been registered yet.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
