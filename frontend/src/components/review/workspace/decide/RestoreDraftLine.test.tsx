/**
 * v2.1 round 2: a draft found when the review opens is asked about, never
 * brought back by itself. MUTATION PROOF: render the "brought back" line
 * while `pendingRestore` is set and "asks first" fails.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { CrsDecisions } from "../../crs/useCrsDecisions";
import { RestoreDraftLine } from "./RestoreDraftLine";

function decisions(over: Partial<CrsDecisions>): CrsDecisions {
  return { restoreDraft: vi.fn(), discardDraft: vi.fn(), ...over } as unknown as CrsDecisions;
}

describe("RestoreDraftLine", () => {
  it("asks first: Yes brings them back, Discard throws them away", async () => {
    const d = decisions({ pendingRestore: { count: 3 } });
    render(<RestoreDraftLine decisions={d} />);
    expect(screen.getByTestId("ws-restored")).toHaveTextContent("3 decisions you had not saved were found. Bring them back?");
    await userEvent.click(screen.getByRole("button", { name: "Yes" }));
    expect(d.restoreDraft).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(d.discardDraft).toHaveBeenCalled();
  });

  it("after Yes, says how many came back and how many were dropped, until hidden", async () => {
    render(<RestoreDraftLine decisions={decisions({ pendingRestore: null, restored: 2, restoreDropped: 1 })} />);
    const line = screen.getByTestId("ws-restored");
    expect(line).toHaveTextContent("2 decisions you had not saved were brought back.");
    expect(line).toHaveTextContent("1 decision was not brought back, because its comment changed since, or is no longer on the sheet.");
    await userEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(screen.queryByTestId("ws-restored")).toBeNull();
  });

  it("shows nothing when there is no draft (or the review is signed)", () => {
    render(<RestoreDraftLine decisions={decisions({ pendingRestore: null, restored: 0, restoreDropped: 0 })} />);
    expect(screen.queryByTestId("ws-restored")).toBeNull();
  });
});
