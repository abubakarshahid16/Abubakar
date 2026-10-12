/**
 * #608: each Deliverables panel loads on its own. The risk register once hung
 * the whole screen on "Loading deliverables" because every request sat inside
 * one Promise.all. A slow or failed panel now shows its own spinner or error
 * and never blocks the WBS register.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeliverablesView } from "./DeliverablesView";

const ok = (data: unknown) => Promise.resolve({ ok: true, data });
const never = () => new Promise(() => {});
const item = {
  id: "d1", wbs_code: "1.1", title: "Pump datasheet", deliverable_type: "datasheet", revision: "0",
  status: "planned", due_date: null, parent_id: null, document_id: null,
};

const risksList = vi.fn();
const expectedList = vi.fn();
vi.mock("../api/client", () => ({
  deliverables: {
    list: () => ok({ deliverables: [item] }),
    alerts: () => ok({ alerts: [] }),
    expected: () => expectedList(),
  },
  management: { escalationRules: () => ok({ rules: [] }) },
  risks: { list: () => risksList() },
}));

beforeEach(() => {
  risksList.mockReset();
  expectedList.mockReset();
  expectedList.mockImplementation(() => ok({ deliverables: [] }));
});

describe("the Deliverables panels are independent", () => {
  it("renders the WBS register while the risk register never answers", async () => {
    risksList.mockImplementation(never);
    render(<DeliverablesView />);
    expect(await screen.findByText("Pump datasheet")).toBeInTheDocument();
    expect(screen.queryByText("Loading deliverables…")).toBeNull();
    // The slow panel has its own spinner, not a screen-wide one.
    expect(screen.getByText("Loading the risk register…")).toBeInTheDocument();
  });

  it("renders the WBS register while the expected-deliverables panel never answers", async () => {
    risksList.mockImplementation(() => ok({ risks: [] }));
    expectedList.mockImplementation(never);
    render(<DeliverablesView />);
    expect(await screen.findByText("Pump datasheet")).toBeInTheDocument();
    expect(screen.getByText("Loading expected deliverables…")).toBeInTheDocument();
  });

  it("shows a failed risk register as its own error and still shows the register", async () => {
    risksList.mockImplementation(() => Promise.resolve({
      ok: false, disconnected: false, error: { code: "internal_error", message: "the risk register broke" },
    }));
    render(<DeliverablesView />);
    expect(await screen.findByText("Pump datasheet")).toBeInTheDocument();
    expect(await screen.findByText("the risk register broke")).toBeInTheDocument();
    expect(await screen.findByText("The risk register could not be loaded.")).toBeInTheDocument();
  });

  it("treats a request that throws as that panel's failure, not the screen's", async () => {
    risksList.mockImplementation(() => Promise.reject(new Error("socket closed")));
    render(<DeliverablesView />);
    expect(await screen.findByText("Pump datasheet")).toBeInTheDocument();
    expect(await screen.findByText("The risk register could not be loaded.")).toBeInTheDocument();
  });
});
