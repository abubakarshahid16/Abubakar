/**
 * v2.1 round 2: the "not saved yet" question. Escape means Stay and the
 * keyboard goes back where it was; it sits above the evidence panel's layer;
 * "Save and leave" leaves only when the save worked. Made-up data only.
 *
 * MUTATION PROOF: drop the Escape listener and "Escape stays" fails; drop
 * the focus return and "the keyboard goes back" fails; put back z-40 and
 * "above the evidence panel" fails; let saveAndLeave leave on a failed save
 * and "a failed save stays" fails.
 */
import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { LeaveConfirm } from "./LeaveConfirm";
import { SAVE_AND_LEAVE_FAILED, useLeaveGuard } from "./useLeaveGuard";

function Harness({ save }: { save?: () => Promise<boolean> }) {
  const [left, setLeft] = useState(false);
  const guard = useLeaveGuard(() => 2, save);
  return (
    <div>
      <button type="button" onClick={() => guard.guard("navigate", () => setLeft(true))}>Go to Documents</button>
      <p>{left ? "left the review" : "on the review"}</p>
      <LeaveConfirm pending={guard.pending} onLeave={guard.leave} onStay={guard.stay}
        onSaveAndLeave={guard.saveAndLeave} saving={guard.saving} saveError={guard.saveError} />
    </div>
  );
}

describe("LeaveConfirm (v2.1 round 2)", () => {
  it("Escape stays, and the keyboard goes back to where it was", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Go to Documents" });
    await user.click(opener);
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stay here" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByText("on the review")).toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("Escape answers only the question: a listener under it does not see it", async () => {
    const user = userEvent.setup();
    const under = vi.fn();
    document.addEventListener("keydown", under);
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Go to Documents" }));
    await user.keyboard("{Escape}");
    expect(under).not.toHaveBeenCalled();
    document.removeEventListener("keydown", under);
  });

  it("sits above the evidence panel's layer (z-[60])", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Go to Documents" }));
    expect(screen.getByRole("alertdialog").className).toContain("z-[70]");
  });

  it("offers no Save and leave when no save is known", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Go to Documents" }));
    expect(screen.queryByRole("button", { name: "Save and leave" })).toBeNull();
  });

  it("Save and leave saves, then leaves", async () => {
    const user = userEvent.setup();
    const save = vi.fn(async () => true);
    render(<Harness save={save} />);
    await user.click(screen.getByRole("button", { name: "Go to Documents" }));
    await user.click(screen.getByRole("button", { name: "Save and leave" }));
    expect(save).toHaveBeenCalledTimes(1);
    expect(screen.getByText("left the review")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("a failed save stays on the review and says so", async () => {
    const user = userEvent.setup();
    render(<Harness save={async () => false} />);
    await user.click(screen.getByRole("button", { name: "Go to Documents" }));
    await user.click(screen.getByRole("button", { name: "Save and leave" }));
    expect(screen.getByText("on the review")).toBeInTheDocument();
    expect(screen.getByTestId("leave-save-error")).toHaveTextContent(SAVE_AND_LEAVE_FAILED);
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("choosing Stay while the save runs means it does not leave afterwards", async () => {
    let finish: (ok: boolean) => void = () => {};
    const save = () => new Promise<boolean>((resolve) => { finish = resolve; });
    const go = vi.fn();
    const { result } = renderHook(() => useLeaveGuard(() => 1, save));
    act(() => { result.current.guard("navigate", go); });
    let saving: Promise<void> = Promise.resolve();
    act(() => { saving = result.current.saveAndLeave!(); });
    act(() => result.current.stay());
    await act(async () => { finish(true); await saving; });
    expect(go).not.toHaveBeenCalled();
  });
});
