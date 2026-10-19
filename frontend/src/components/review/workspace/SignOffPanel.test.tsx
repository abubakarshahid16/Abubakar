/**
 * v2.2 round 2: in Simple view "Before you sign" folds behind one line that
 * says how much is left, from the one source (`numbers.signLeft`). It opens
 * by itself only while something there still stops Sign and export.
 * Made-up data only.
 *
 * MUTATION PROOF: drop the `folded` branch and the DETAILS checks fail; make
 * `open` always true and "folded shut" fails.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ReviewRunSummary } from "../../../types/api";
import type { ReviewNumbers, SignOff } from "./contract";
import { SignOffPanel, beforeYouSignSummary } from "./SignOffPanel";

vi.mock("../crs/BeforeYouSign", () => ({ BeforeYouSign: () => <div data-testid="before-you-sign">the ticks</div> }));
vi.mock("./sign/issuedCopy", () => ({ downloadIssuedCopy: vi.fn() }));

const RUN = { review_run_id: "run-1" } as unknown as ReviewRunSummary;
const IDLE: SignOff = { busy: false, message: null, error: null, save: vi.fn(), sign: vi.fn(), workingCopy: vi.fn() };

function numbers(signLeft: string[]): ReviewNumbers {
  return {
    comments: 2, needsYou: 0, undecided: 0, unsaved: 0, unopenedNeedsYou: 0, signed: false, signedAt: null,
    signLeft, finalCodeRecorded: true, finalCode: "2", undecidedKeys: [], remainingToKeep: 0,
  } as unknown as ReviewNumbers;
}

function renderPanel(signLeft: string[], folded: boolean) {
  render(<SignOffPanel numbers={numbers(signLeft)} signOff={IDLE} run={RUN} rows={[]}
    gate={{ gate: null, error: null, reload: vi.fn() } as never} onRunChanged={vi.fn()} onJump={vi.fn()} folded={folded} />);
}

describe("SignOffPanel: Before you sign in Simple view", () => {
  it("says how much is left in one line, from the shared numbers", () => {
    expect(beforeYouSignSummary({ signLeft: [] })).toBe("Before you sign: all done.");
    expect(beforeYouSignSummary({ signLeft: ["tick 2 unread pages"] })).toBe("Before you sign: 1 thing still to do (tick 2 unread pages).");
    expect(beforeYouSignSummary({ signLeft: ["record the final code", "tick 1 unread page"] }))
      .toBe("Before you sign: 2 things still to do (record the final code; tick 1 unread page).");
  });

  it("folds, and opens by itself while something there stops Sign", () => {
    renderPanel(["record the final code"], true);
    const fold = screen.getByTestId("ws-before-sign-fold");
    expect(fold.tagName).toBe("DETAILS");
    expect(fold).toHaveAttribute("open");
    expect(screen.getByTestId("ws-before-sign-summary").tagName).toBe("SUMMARY");
    expect(fold).toContainElement(screen.getByTestId("before-you-sign"));
  });

  it("stays folded shut when nothing there stops Sign", () => {
    renderPanel([], true);
    expect(screen.getByTestId("ws-before-sign-fold")).not.toHaveAttribute("open");
    expect(screen.getByTestId("ws-before-sign-summary")).toHaveTextContent("Before you sign: all done.");
  });

  it("Detailed view shows the box open, with no fold", () => {
    renderPanel(["record the final code"], false);
    expect(screen.queryByTestId("ws-before-sign-fold")).toBeNull();
    expect(screen.getByTestId("before-you-sign").closest("details")).toBeNull();
  });
});
