/**
 * Builder B: D4 automatic saving and its line in the bar, and S1 the final
 * code step that opens from the bar. Made-up data only.
 *
 * MUTATION PROOF: in useAutosave, mark every key of `outcome.saved` saved
 * without the "still the same on screen" filter and "a decision changed
 * while saving is sent again" fails; drop `signature === failedSig.current`
 * and "a failed save says why and does not loop" fails.
 * Round 2: let a queued save skip the pause check (`!asked && pausedNow`)
 * and "a save queued while one runs waits for the pause" fails; drop the
 * `disabled` check and "a signed review saves nothing" fails; drop
 * `forget(missing)` and "a comment no longer on the sheet" fails.
 */
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewRunSummary } from "../../../../types/api";
import type { CrsRow } from "../../crs/crsRows";
import { useCrsDecisions } from "../../crs/useCrsDecisions";
import { ActionBar } from "../ActionBar";
import type { ActionStep, AutosaveStatus, ReviewNumbers, SignOff } from "../contract";
import { actionSteps, computeReviewNumbers } from "../numbers";
import { type LeaveSaver, LeaveSaverContext } from "../useLeaveGuard";
import { useAutosave } from "./useAutosave";

const saveCrsDecisions = vi.fn();
const decideCode = vi.fn();
const rereadPages = vi.fn();
vi.mock("../../crs/saveCrsDecisions", () => ({ saveCrsDecisions: (...a: unknown[]) => saveCrsDecisions(...a) }));
vi.mock("../../../../api/client", () => ({
  reviews: { decideCode: (...a: unknown[]) => decideCode(...a), rereadPages: (...a: unknown[]) => rereadPages(...a) },
}));

const ROWS = [
  { key: "b1", tier: { tier: "B" }, priorState: "open", findings: [{ id: "f1" }] },
  { key: "b2", tier: { tier: "B" }, priorState: "open", findings: [{ id: "f2" }] },
] as unknown as CrsRow[];

function useBoth(refresh = vi.fn(async () => {})) {
  const decisions = useCrsDecisions();
  const autosave = useAutosave({ runId: "run-1", rows: ROWS, decisions, refresh, delayMs: 10 });
  return { decisions, autosave };
}

beforeEach(() => {
  saveCrsDecisions.mockReset();
  decideCode.mockReset();
});

describe("useAutosave", () => {
  it("saves after the pause, marks saved, and re-reads the run when something reached the record", async () => {
    saveCrsDecisions.mockImplementation(async (_r: string, _rows: unknown, _d: unknown, keys: string[]) => ({ saved: keys, failed: [], wrote: true }));
    const refresh = vi.fn(async () => {});
    const { result } = renderHook(() => useBoth(refresh));
    act(() => result.current.decisions.keep("b1"));
    expect(result.current.decisions.unsaved).toEqual(["b1"]);
    await waitFor(() => expect(result.current.decisions.unsaved).toEqual([]));
    expect(saveCrsDecisions).toHaveBeenCalledWith("run-1", ROWS, { b1: { kind: "keep" } }, ["b1"]);
    expect(result.current.autosave.phase).toBe("saved");
    expect(refresh).toHaveBeenCalled();
  });

  it("a failed save says why and does not loop; a new decision or Save now tries again", async () => {
    saveCrsDecisions.mockResolvedValue({ saved: [], failed: [{ key: "b1", message: "Comment 1: the server said no" }], wrote: false });
    const { result } = renderHook(() => useBoth());
    act(() => result.current.decisions.keep("b1"));
    await waitFor(() => expect(result.current.autosave.phase).toBe("failed"));
    expect(result.current.autosave.message).toBe("Comment 1: the server said no");
    await new Promise((r) => setTimeout(r, 60));
    expect(saveCrsDecisions).toHaveBeenCalledTimes(1);
    saveCrsDecisions.mockImplementation(async (_r: string, _rows: unknown, _d: unknown, keys: string[]) => ({ saved: keys, failed: [], wrote: false }));
    await act(async () => { await result.current.autosave.saveNow(); });
    expect(saveCrsDecisions).toHaveBeenCalledTimes(2);
    expect(result.current.autosave.phase).toBe("saved");
    expect(result.current.decisions.unsaved).toEqual([]);
  });

  it("a decision changed while saving is sent again", async () => {
    let release: () => void = () => {};
    saveCrsDecisions.mockImplementationOnce((_r: string, _rows: unknown, _d: unknown, keys: string[]) =>
      new Promise((resolve) => { release = () => resolve({ saved: keys, failed: [], wrote: false }); }));
    saveCrsDecisions.mockImplementation(async (_r: string, _rows: unknown, _d: unknown, keys: string[]) => ({ saved: keys, failed: [], wrote: false }));
    const { result } = renderHook(() => useBoth());
    act(() => result.current.decisions.keep("b1"));
    await waitFor(() => expect(saveCrsDecisions).toHaveBeenCalledTimes(1));
    act(() => result.current.decisions.remove("b1", "Duplicate"));
    await act(async () => { release(); });
    // The keep reached the record, but the screen now says remove: not saved.
    await waitFor(() => expect(saveCrsDecisions).toHaveBeenCalledTimes(2));
    expect(saveCrsDecisions.mock.calls[1][2]).toEqual({ b1: { kind: "remove", reason: "Duplicate" } });
    await waitFor(() => expect(result.current.decisions.unsaved).toEqual([]));
  });

  it("waits while paused (an Undo is offered)", async () => {
    saveCrsDecisions.mockResolvedValue({ saved: ["b1"], failed: [], wrote: false });
    const { result, rerender } = renderHook(({ paused }) => {
      const decisions = useCrsDecisions();
      return { decisions, autosave: useAutosave({ runId: "run-1", rows: ROWS, decisions, refresh: async () => {}, paused, delayMs: 10 }) };
    }, { initialProps: { paused: true } });
    act(() => result.current.decisions.keep("b1"));
    await new Promise((r) => setTimeout(r, 60));
    expect(saveCrsDecisions).not.toHaveBeenCalled();
    expect(result.current.autosave.waiting).toBe(true);
    rerender({ paused: false });
    await waitFor(() => expect(saveCrsDecisions).toHaveBeenCalledTimes(1));
  });
});

describe("useAutosave: pause, signed review, comments gone (v2.1 round 2)", () => {
  const savesAll = async (_r: string, _rows: unknown, _d: unknown, keys: string[]) => ({ saved: keys, failed: [], missing: [], wrote: false });

  it("a save queued while one runs waits for the pause (an Undo on offer); only Save now goes through", async () => {
    let release: () => void = () => {};
    saveCrsDecisions.mockImplementationOnce((_r: string, _rows: unknown, _d: unknown, keys: string[]) =>
      new Promise((resolve) => { release = () => resolve({ saved: keys, failed: [], missing: [], wrote: false }); }));
    saveCrsDecisions.mockImplementation(savesAll);
    const { result, rerender } = renderHook(({ paused }) => {
      const decisions = useCrsDecisions();
      return { decisions, autosave: useAutosave({ runId: "run-1", rows: ROWS, decisions, refresh: async () => {}, paused, delayMs: 10 }) };
    }, { initialProps: { paused: false } });
    act(() => result.current.decisions.keep("b1"));
    await waitFor(() => expect(saveCrsDecisions).toHaveBeenCalledTimes(1));
    // While the first save runs, another decision: its save is queued.
    act(() => result.current.decisions.keep("b2"));
    await new Promise((r) => setTimeout(r, 40));
    // Then "Keep all remaining" offers Undo: saving pauses.
    rerender({ paused: true });
    await act(async () => { release(); });
    await new Promise((r) => setTimeout(r, 60));
    expect(saveCrsDecisions).toHaveBeenCalledTimes(1);
    expect(result.current.decisions.unsaved).toEqual(["b2"]);
    expect(result.current.autosave.waiting).toBe(true);
    // "Save now" (which ends the Undo offer) saves even while paused.
    let ok = false;
    await act(async () => { ok = await result.current.autosave.saveNow(); });
    expect(ok).toBe(true);
    expect(saveCrsDecisions).toHaveBeenCalledTimes(2);
    expect(result.current.decisions.unsaved).toEqual([]);
  });

  it("a signed review (disabled) saves nothing, Save now included, and keeps the decision on screen", async () => {
    saveCrsDecisions.mockImplementation(savesAll);
    const { result } = renderHook(() => {
      const decisions = useCrsDecisions();
      return { decisions, autosave: useAutosave({ runId: "run-1", rows: ROWS, decisions, refresh: async () => {}, disabled: true, delayMs: 10 }) };
    });
    act(() => result.current.decisions.keep("b1"));
    await new Promise((r) => setTimeout(r, 60));
    let ok = true;
    await act(async () => { ok = await result.current.autosave.saveNow(); });
    expect(ok).toBe(false);
    expect(saveCrsDecisions).not.toHaveBeenCalled();
    expect(result.current.decisions.unsaved).toEqual(["b1"]);
    expect(result.current.autosave.waiting).toBe(false);
  });

  it("a comment no longer on the sheet is said, and taken off the unsaved list so Sign is not held", async () => {
    saveCrsDecisions.mockResolvedValue({
      saved: [], missing: ["gone"], wrote: false,
      failed: [{ key: "gone", message: "x", words: "A decision was not saved: this comment is no longer on the sheet, so it was taken off your list.", detail: null }],
    });
    const { result } = renderHook(() => useBoth());
    act(() => result.current.decisions.keep("gone"));
    await waitFor(() => expect(result.current.decisions.unsaved).toEqual([]));
    expect(result.current.decisions.state.decisions).toEqual({});
    expect(result.current.autosave.message).toContain("this comment is no longer on the sheet");
  });

  it("failures read as plain words, with the server's words folded as detail", async () => {
    saveCrsDecisions.mockResolvedValue({
      saved: [], missing: [], wrote: false,
      failed: [{ key: "b1", message: "Comment 3: Not allowed.", words: "Comment 3 was not saved. Try again in a moment.", detail: "Not allowed." }],
    });
    const { result } = renderHook(() => useBoth());
    act(() => result.current.decisions.keep("b1"));
    await waitFor(() => expect(result.current.autosave.phase).toBe("failed"));
    expect(result.current.autosave.message).toBe("Comment 3 was not saved. Try again in a moment.");
    expect(result.current.autosave.detail).toBe("Not allowed.");
  });

  it("puts its Save now in the app's slot for \"Save and leave\", and takes it out when it goes", async () => {
    saveCrsDecisions.mockImplementation(savesAll);
    const slot: { save: LeaveSaver | null } = { save: null };
    const register = vi.fn((save: LeaveSaver | null) => { slot.save = save; });
    const wrapper = ({ children }: { children: ReactNode }) => createElement(LeaveSaverContext.Provider, { value: register }, children);
    const { result, unmount } = renderHook(() => useBoth(), { wrapper });
    act(() => result.current.decisions.keep("b1"));
    let ok = false;
    await act(async () => { ok = await slot.save!(); });
    expect(ok).toBe(true);
    expect(result.current.decisions.unsaved).toEqual([]);
    unmount();
    expect(slot.save).toBeNull();
  });
});

const RUN = {
  review_run_id: "run-1", submittal_document_id: "doc-1", status: "completed", recommended_code: "B",
  review_codes: ["A", "B", "C"],
} as unknown as ReviewRunSummary;

function numbers(over: Partial<ReviewNumbers> = {}): ReviewNumbers {
  return {
    ...computeReviewNumbers({
      run: RUN, findings: [], rows: ROWS, summary: null, missingStandards: [], readiness: null,
      decisions: { decisions: {}, opened: {} }, unsaved: [], gate: null,
    }),
    ...over,
  };
}

const IDLE: SignOff = { busy: false, message: null, error: null, save: vi.fn(), sign: vi.fn(), workingCopy: vi.fn() };

function autosave(over: Partial<AutosaveStatus> = {}): AutosaveStatus {
  return { phase: "idle", message: null, waiting: false, saveNow: vi.fn(async () => {}), ...over };
}

describe("the saving line in the bar", () => {
  it.each([
    [autosave({ phase: "saving" }), 1, "Saving..."],
    [autosave({ phase: "failed", message: "Comment 2 was not saved. Try again in a moment." }), 1, "Comment 2 was not saved. Try again in a moment."],
    [autosave({ phase: "saved" }), 0, "Saved. Every decision is on the record."],
    [autosave(), 2, "2 decisions waiting to save..."],
    [autosave({ waiting: true }), 1, "1 decision will save once Undo is gone."],
  ])("says %#", (status, unsaved, words) => {
    const n = numbers({ unsaved });
    render(<ActionBar run={RUN} numbers={n} steps={actionSteps(n)} onAction={() => {}} signOff={IDLE} autosave={status} />);
    expect(screen.getByTestId("ws-autosave")).toHaveTextContent(words);
  });

  it("a failed save folds the server's words under Details", () => {
    const n = numbers({ unsaved: 1 });
    render(<ActionBar run={RUN} numbers={n} steps={actionSteps(n)} onAction={() => {}} signOff={IDLE}
      autosave={autosave({ phase: "failed", message: "Comment 2 was not saved. Try again in a moment.", detail: "HTTP 500 boom" })} />);
    expect(screen.getByTestId("ws-autosave")).not.toHaveTextContent("HTTP 500");
    expect(screen.getByTestId("ws-autosave-detail")).toHaveTextContent("Details");
    expect(screen.getByTestId("ws-autosave-detail")).toHaveTextContent("HTTP 500 boom");
  });

  it('"Save now" saves at once, and waits when nothing is unsaved', async () => {
    const status = autosave();
    const n = numbers({ unsaved: 1 });
    const { rerender } = render(<ActionBar run={RUN} numbers={n} steps={actionSteps(n)} onAction={() => {}} signOff={IDLE} autosave={status} />);
    await userEvent.click(screen.getByRole("button", { name: "Save now" }));
    expect(status.saveNow).toHaveBeenCalled();
    const none = numbers({ unsaved: 0 });
    rerender(<ActionBar run={RUN} numbers={none} steps={actionSteps(none)} onAction={() => {}} signOff={IDLE} autosave={status} />);
    expect(screen.getByRole("button", { name: "Save now" })).toBeDisabled();
  });
});

describe("Record the final code (S1)", () => {
  /** MUTATION PROOF: drop the code panel from ActionBar and this fails. */
  it("is a step before Sign and its control opens from the bar", async () => {
    decideCode.mockResolvedValue({ ok: true, data: {} });
    const onCodeRecorded = vi.fn();
    const n = numbers({ finalCodeRecorded: false });
    render(<ActionBar run={RUN} numbers={n} steps={actionSteps(n)} onAction={() => {}} signOff={IDLE} onCodeRecorded={onCodeRecorded} />);
    const ids = [...document.querySelectorAll("[data-step]")].map((b) => b.getAttribute("data-step"));
    expect(ids).toEqual(["standards", "pages", "decide", "code", "preview", "sign"]);
    await userEvent.click(screen.getByRole("button", { name: "Record the final code" }));
    const box = screen.getByTestId("ws-final-code");
    expect(box).toHaveTextContent("(the computer's proposal)");
    await userEvent.click(screen.getAllByRole("button", { name: "Record the final code" }).at(-1)!);
    expect(decideCode).toHaveBeenCalledWith("run-1", "B", null);
    await waitFor(() => expect(onCodeRecorded).toHaveBeenCalled());
  });
});

/** N2: failed requests in the bar read as plain words; the server's own
 *  words are folded under Details. MUTATION PROOF: show
 *  `result.error.message` again and both tests fail. */
describe("plain words for failures in the bar (v2.1 round 2, N2)", () => {
  const FAIL = { ok: false, disconnected: false, error: { code: "internal", message: "HTTP 502 Bad Gateway" } };

  it('"Read these pages again" failing', async () => {
    rereadPages.mockResolvedValue(FAIL);
    const n = numbers();
    const steps = [{ id: "pages", label: "Check unread pages (2)", count: 2, done: false, enabled: true, detail: "Pages 3 and 4 were not read" }] as ActionStep[];
    render(<ActionBar run={RUN} numbers={n} steps={steps} onAction={() => {}} signOff={IDLE} />);
    await userEvent.click(screen.getByRole("button", { name: /Check unread pages/ }));
    await userEvent.click(screen.getByRole("button", { name: "Read these pages again" }));
    const line = await screen.findByTestId("ws-reread-error");
    expect(line).toHaveTextContent("The pages could not be sent to be read again. Try again in a moment.");
    expect(line.querySelector("details")).toHaveTextContent("HTTP 502 Bad Gateway");
    expect(line.querySelector("p")).not.toHaveTextContent("HTTP 502");
  });

  it("recording the final code failing", async () => {
    decideCode.mockResolvedValue({ ok: false, disconnected: true, error: { code: "internal", message: "Nothing answered on the API port." } });
    const n = numbers({ finalCodeRecorded: false });
    render(<ActionBar run={RUN} numbers={n} steps={actionSteps(n)} onAction={() => {}} signOff={IDLE} />);
    await userEvent.click(screen.getByRole("button", { name: "Record the final code" }));
    await userEvent.click(screen.getAllByRole("button", { name: "Record the final code" }).at(-1)!);
    const line = await screen.findByTestId("sign-code-error");
    expect(line.querySelector("p")).toHaveTextContent(
      "The final code was not recorded. The server could not be reached. Check your connection, then try again.");
    expect(line.querySelector("details")).toHaveTextContent("Nothing answered on the API port.");
  });
});
