/**
 * PF5 (#885): the open items before issue, each closed by the engineer with
 * a reason; the blockers are the server's words.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { CrsIssueGatePanel } from "./CrsIssueGatePanel";
import type { CrsIssueGate } from "../../types/api";

const gate = vi.fn();
const decidePage = vi.fn();
const decideFinding = vi.fn();

vi.mock("../../api/client", () => ({
  reviews: {
    crsIssueGate: (...a: unknown[]) => gate(...a),
    decideCrsPage: (...a: unknown[]) => decidePage(...a),
    decideCrsFinding: (...a: unknown[]) => decideFinding(...a),
  },
}));

const open: CrsIssueGate = {
  review_run_id: "run-1", issuable: false, final_code_recorded: true,
  blockers: ["1 page(s) of the submittal were not read and no engineer has recorded checking them",
             "1 finding(s) on the sheet have no engineer's decision"],
  unread_pages: [{ page: 3, reason: "unreadable" }],
  open_findings: [{ finding_id: "f-1", row_kind: "requirement", item: 2 }],
};
const done: CrsIssueGate = { ...open, issuable: true, blockers: [], unread_pages: [], open_findings: [] };
const ok = { ok: true, data: { id: "d" } };

beforeEach(() => {
  gate.mockReset(); decidePage.mockReset(); decideFinding.mockReset();
});

describe("CrsIssueGatePanel", () => {
  it("prints the server's blockers and each open item", async () => {
    gate.mockResolvedValue({ ok: true, data: open });
    render(<CrsIssueGatePanel runId="run-1" />);
    expect(await screen.findByText("Not ready to issue to the contractor")).toBeInTheDocument();
    expect(screen.getByTestId("issue-blockers")).toHaveTextContent("1 finding(s) on the sheet have no engineer's decision");
    expect(screen.getByTestId("page-3")).toHaveTextContent("Page 3 was not read (unreadable).");
    expect(screen.getByTestId("finding-f-1")).toHaveTextContent("Item 2 has no engineer's decision.");
  });

  it("will not decide without the engineer's reason", async () => {
    gate.mockResolvedValue({ ok: true, data: open });
    render(<CrsIssueGatePanel runId="run-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "I checked this page" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Write the reason for this decision first.");
    expect(decidePage).not.toHaveBeenCalled();
  });

  it("records a page decision with the reason, then re-reads the gate", async () => {
    gate.mockResolvedValueOnce({ ok: true, data: open }).mockResolvedValue({ ok: true, data: done });
    decidePage.mockResolvedValue(ok);
    const changed = vi.fn();
    render(<CrsIssueGatePanel runId="run-1" onChange={changed} />);
    fireEvent.change(await screen.findByLabelText("Reason for page 3"), { target: { value: "checked: general notes only" } });
    fireEvent.click(screen.getByRole("button", { name: "I checked this page" }));
    await waitFor(() => expect(decidePage).toHaveBeenCalledWith("run-1", 3, "checked: general notes only"));
    expect(await screen.findByText("Ready to issue to the contractor")).toBeInTheDocument();
    expect(changed).toHaveBeenCalled();
  });

  it("accepts or rejects a finding with the reason", async () => {
    gate.mockResolvedValue({ ok: true, data: open });
    decideFinding.mockResolvedValue(ok);
    render(<CrsIssueGatePanel runId="run-1" />);
    fireEvent.change(await screen.findByLabelText("Reason for item 2"), { target: { value: "breach confirmed" } });
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(decideFinding).toHaveBeenCalledWith("run-1", "f-1", "reject", "breach confirmed"));
  });
});
