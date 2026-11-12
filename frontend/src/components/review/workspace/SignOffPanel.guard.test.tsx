/**
 * Signing waits for the AI review's open points (U2, finding 3). MUTATION
 * PROOF: ignore `signGuard.acked` in canSign and the disabled test fails.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ReviewRunSummary } from "../../../types/api";
import type { ReviewNumbers, SignGuard, SignOff } from "./contract";
import { SignOffPanel } from "./SignOffPanel";

vi.mock("../crs/BeforeYouSign", () => ({ BeforeYouSign: () => <div /> }));
vi.mock("./sign/issuedCopy", () => ({ downloadIssuedCopy: vi.fn() }));

const RUN = { review_run_id: "run-1" } as unknown as ReviewRunSummary;
const IDLE: SignOff = { busy: false, message: null, error: null, save: vi.fn(), sign: vi.fn(), workingCopy: vi.fn() };
const READY = {
  comments: 2, needsYou: 0, undecided: 0, unsaved: 0, unopenedNeedsYou: 0, signed: false, signedAt: null, signLeft: [],
  finalCodeRecorded: true, finalCode: "2", undecidedKeys: [], remainingToKeep: 0, standardsKnown: true, missingStandards: [],
  pagesKnown: true, unreadPages: [],
} as unknown as ReviewNumbers;

function panel(signGuard: SignGuard | null) {
  return <SignOffPanel numbers={READY} signOff={IDLE} run={RUN} rows={[]} gate={{ gate: null, error: null, reload: vi.fn() } as never}
    onRunChanged={vi.fn()} onJump={vi.fn()} signGuard={signGuard} />;
}

describe("SignOffPanel: the AI review's open points", () => {
  it("no AI review open points: Sign and export is enabled and no warning is drawn", () => {
    render(panel(null));
    expect(screen.getByRole("button", { name: "Sign and export" })).toBeEnabled();
    expect(screen.queryByTestId("ws-sign-guard")).toBeNull();
  });
  it("open points: a plain warning and Sign waits for the tick", async () => {
    const onAck = vi.fn();
    const { rerender } = render(panel({ open: 20, acked: false, onAck }));
    expect(screen.getByTestId("ws-sign-guard")).toHaveTextContent("The AI review of this document has 20 open points that are not on this sheet");
    expect(screen.getByRole("button", { name: "Sign and export" })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: "I have read the AI review's points" }));
    expect(onAck).toHaveBeenCalledWith(true);
    rerender(panel({ open: 20, acked: true, onAck }));
    expect(screen.getByRole("button", { name: "Sign and export" })).toBeEnabled();
  });
  it("points that could not be counted still need the tick, and the warning says so", () => {
    render(panel({ open: null, acked: false, onAck: vi.fn() }));
    expect(screen.getByTestId("ws-sign-guard")).toHaveTextContent("could not be counted");
    expect(screen.getByRole("button", { name: "Sign and export" })).toBeDisabled();
  });
});
