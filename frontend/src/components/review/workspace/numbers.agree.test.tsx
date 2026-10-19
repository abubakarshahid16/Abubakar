/**
 * Builder B: the bar, the sheet's count line and the sign-off panel show the
 * SAME numbers, all from one `computeReviewNumbers` result. Plus the click
 * paths: Sign waits for the blockers, then calls downloadCrs "issue"; the
 * unread pages are listed with "Read these pages again"; Save and the
 * working copy use the existing routes. Made-up data only.
 *
 * MUTATION PROOF (done once by hand): make SheetCountsLine show
 * `numbers.comments + 1` (a component counting on its own) and
 * "every shared count agrees" fails.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewReadiness, ReviewRunSummary } from "../../../types/api";
import type { CrsDecisions, CrsRow, DecisionState, ReviewNumbers, ReviewNumbersInput, SignOff } from "./contract";
import { ActionBar } from "./ActionBar";
import { SheetCountsLine } from "./SheetCountsLine";
import { SignOffPanel } from "./SignOffPanel";
import { actionSteps, computeReviewNumbers } from "./numbers";
import { useSignOff } from "./useSignOff";

const downloadCrs = vi.fn();
const saveCrsDecisions = vi.fn();
const rereadPages = vi.fn();

vi.mock("../downloadCrs", () => ({ downloadCrs: (...a: unknown[]) => downloadCrs(...a) }));
vi.mock("../crs/saveCrsDecisions", () => ({ saveCrsDecisions: (...a: unknown[]) => saveCrsDecisions(...a) }));
vi.mock("../../../api/client", () => ({ reviews: { rereadPages: (...a: unknown[]) => rereadPages(...a) } }));

type Tier = "A" | "B" | "C";
const LABEL: Record<Tier, string> = { A: "Met", B: "Comment", C: "Needs you" };
function row(key: string, tier: Tier, prior: "open" | "agreed" = "open"): CrsRow {
  return { key, tier: { tier, label: LABEL[tier], reason: null }, findings: [{ id: `${key}-f` }], priorState: prior } as unknown as CrsRow;
}

const RUN = {
  review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "Pump datasheet rev B.pdf", status: "completed",
  page_coverage: { pages_not_read_into_fields: [9, 4] },
} as unknown as ReviewRunSummary;

const READINESS: ReviewReadiness = {
  submittal_document_id: "doc-1", pages_total: 12, pages_read: 9, unread_pages: [12, 4], unread_page_reasons: {},
  standards_cited: 3, standards_held: [], standards_missing: ["ISO 5199"], last_run_id: null, nothing_changed: false, changes: [],
};

/** Readiness that answered: nothing unread, nothing missing. */
const NONE_LEFT: ReviewReadiness = { ...READINESS, unread_pages: [], standards_missing: [] };

const ROWS = [row("b1", "B"), row("b2", "B"), row("b3", "B", "agreed"), row("c1", "C"), row("c2", "C"), row("a1", "A")];

function numbersFor(over: Partial<ReviewNumbersInput> = {}): ReviewNumbers {
  return computeReviewNumbers({
    run: RUN, findings: [], rows: ROWS, summary: null, missingStandards: ["API 610"], readiness: READINESS,
    decisions: { decisions: { b1: { kind: "keep" } }, opened: {} }, unsaved: ["b1"], ...over,
  });
}

const IDLE: SignOff = { busy: false, message: null, error: null, save: vi.fn(), sign: vi.fn(), workingCopy: vi.fn() };

function renderAll(numbers: ReviewNumbers, signOff: SignOff = IDLE) {
  return render(
    <div>
      <ActionBar run={RUN} numbers={numbers} steps={actionSteps(numbers)} onAction={() => {}} signOff={signOff} />
      <SheetCountsLine numbers={numbers} />
      <SignOffPanel numbers={numbers} signOff={signOff} />
    </div>,
  );
}

const SHARED = ["comments", "needsYou", "undecided", "unreadPages", "missingStandards"] as const;

function helperValue(n: ReviewNumbers, key: (typeof SHARED)[number]): number {
  if (key === "unreadPages") return n.unreadPages.length;
  if (key === "missingStandards") return n.missingStandards.length;
  return n[key];
}

beforeEach(() => {
  downloadCrs.mockReset().mockResolvedValue(null);
  saveCrsDecisions.mockReset();
  rereadPages.mockReset();
});

describe("one source of numbers", () => {
  it("every shared count agrees across the bar, the count line and the sign-off panel, and with the helper", () => {
    const n = numbersFor();
    // A fixture where every shared count is non-zero, so no count can hide.
    for (const key of SHARED) expect(helperValue(n, key)).toBeGreaterThan(0);
    renderAll(n);
    const regions = [screen.getByTestId("ws-action-bar"), screen.getByTestId("ws-sheet-counts"), screen.getByTestId("ws-sign-off")];
    for (const key of SHARED) {
      const shown = regions.flatMap((r) => [...r.querySelectorAll(`[data-count="${key}"]`)].map((el) => el.textContent));
      expect(shown.length, `${key} is shown somewhere`).toBeGreaterThan(0);
      for (const text of shown) expect(Number(text), key).toBe(helperValue(n, key));
    }
    // Each shared count shows in at least two of the three, so a drift is caught.
    const where = (key: string) => regions.filter((r) => r.querySelector(`[data-count="${key}"]`)).length;
    expect(where("comments")).toBe(3);
    expect(where("needsYou")).toBe(2);
    expect(where("undecided")).toBe(2);
    expect(where("unreadPages")).toBe(2);
    expect(where("missingStandards")).toBe(2);
  });

  it("met and not applicable on the count line are the helper's (clauses when the run has them)", () => {
    const n = numbersFor({ run: { ...RUN, requirement_split: { does_not_apply: 7 } } as unknown as ReviewRunSummary });
    expect(n.met).toBe(1);
    expect(n.notApplicable).toBe(7);
    renderAll(n);
    const line = screen.getByTestId("ws-sheet-counts");
    expect(line.querySelector('[data-count="met"]')?.textContent).toBe(String(n.met));
    expect(line.querySelector('[data-count="notApplicable"]')?.textContent).toBe(String(n.notApplicable));
  });

  it("the expected numbers for this fixture", () => {
    const n = numbersFor();
    expect(n.comments).toBe(5);
    expect(n.needsYou).toBe(2);
    expect(n.undecided).toBe(3); // b2, c1, c2 (b1 decided, b3 agreed)
    expect(n.unreadPages).toEqual([4, 9, 12]);
    expect(n.missingStandards).toEqual(["API 610", "ISO 5199"]);
  });

  it("the verdict and the buttons say it in plain words, in fixed order", () => {
    renderAll(numbersFor());
    const bar = screen.getByTestId("ws-action-bar");
    expect(screen.getByTestId("ws-verdict").textContent).toBe("5 comments, 2 need your judgement. Not signed yet.");
    expect(within(bar).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Upload missing standards (2)", "Check unread pages (3)", "Decide comments (3)", "Sign and export",
    ]);
  });
});

describe("Check unread pages", () => {
  it("lists the pages and reads them again through the existing route", async () => {
    rereadPages.mockResolvedValue({ ok: true, data: READINESS });
    const onAction = vi.fn();
    const n = numbersFor();
    render(<ActionBar run={RUN} numbers={n} steps={actionSteps(n)} onAction={onAction} signOff={IDLE} />);
    await userEvent.click(screen.getByRole("button", { name: /Check unread pages/ }));
    expect(onAction).toHaveBeenCalledWith("pages");
    expect(screen.getByTestId("ws-unread-pages").textContent).toContain("Pages 4, 9 and 12");
    await userEvent.click(screen.getByRole("button", { name: "Read these pages again" }));
    expect(rereadPages).toHaveBeenCalledWith("doc-1");
    expect(await screen.findByRole("status")).toHaveTextContent(/read these pages again/i);
  });

  it("shows the API's refusal as it said it", async () => {
    rereadPages.mockResolvedValue({ ok: false, error: { message: "The reader is switched off." } });
    const n = numbersFor();
    render(<ActionBar run={RUN} numbers={n} steps={actionSteps(n)} onAction={() => {}} signOff={IDLE} />);
    await userEvent.click(screen.getByRole("button", { name: /Check unread pages/ }));
    await userEvent.click(screen.getByRole("button", { name: "Read these pages again" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The reader is switched off.");
  });

  it("a done step shows as a tick, not hidden, and cannot be pressed", () => {
    const n = numbersFor({ readiness: NONE_LEFT, run: { ...RUN, page_coverage: null } as unknown as ReviewRunSummary });
    render(<ActionBar run={RUN} numbers={n} steps={actionSteps(n)} onAction={() => {}} signOff={IDLE} />);
    const pages = screen.getByRole("button", { name: /Check unread pages/ });
    expect(pages).toBeDisabled();
    expect(pages.textContent).toContain("✓");
    expect(pages.getAttribute("data-done")).toBe("true");
  });
});

/** The real useSignOff wired to the three components, with the decisions
 *  and blockers the test controls. */
function Harness({ input, refresh, decisions }: { input: Partial<ReviewNumbersInput>; refresh: () => Promise<void>; decisions: CrsDecisions }) {
  const signOff = useSignOff({ runId: "run-1", rows: ROWS, decisions, refresh });
  const n = numbersFor(input);
  return (
    <div>
      <ActionBar run={RUN} numbers={n} steps={actionSteps(n)} onAction={() => {}} signOff={signOff} />
      <SheetCountsLine numbers={n} />
      <SignOffPanel numbers={n} signOff={signOff} />
    </div>
  );
}

function fakeDecisions(state: DecisionState, unsaved: string[]): CrsDecisions {
  return { state, unsaved, markSaved: vi.fn() } as unknown as CrsDecisions;
}

const ALL_DECIDED: DecisionState = {
  decisions: { b1: { kind: "keep" }, b2: { kind: "keep" }, c1: { kind: "keep" }, c2: { kind: "keep" } }, opened: { c1: true, c2: true },
};

describe("Sign and export", () => {
  it('stays off while a "Needs you" row was kept from the table but never opened, as the old sheet', () => {
    // Every row decided and saved, standards and pages clear, but c2 was
    // never opened.
    const notOpened: DecisionState = { decisions: ALL_DECIDED.decisions, opened: { c1: true } };
    const input: Partial<ReviewNumbersInput> = {
      missingStandards: [], readiness: NONE_LEFT, run: { ...RUN, page_coverage: null } as unknown as ReviewRunSummary,
      decisions: notOpened, unsaved: [],
    };
    const n = numbersFor(input);
    expect(n.undecided).toBe(0);
    expect(n.unopenedNeedsYou).toBe(1);
    expect(actionSteps(n).find((s) => s.id === "sign")?.enabled).toBe(false);
    render(<Harness input={input} refresh={vi.fn().mockResolvedValue(undefined)} decisions={fakeDecisions(notOpened, [])} />);
    for (const b of screen.getAllByRole("button", { name: "Sign and export" })) expect(b).toBeDisabled();
    expect(screen.getByTestId("ws-verdict").textContent).toContain("Not signed yet.");
    expect(screen.getByTestId("ws-sign-waits")).toHaveTextContent('Open the 1 "Needs you" row first.');
    expect(screen.getByTestId("ws-sign-off")).toHaveTextContent('opened the 1 row marked "Needs you"');
  });

  it("stays off until standards, pages and decisions are clear and saved, then calls downloadCrs issue", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const decisions = fakeDecisions(ALL_DECIDED, []);
    const blocked: Partial<ReviewNumbersInput> = { unsaved: [] };
    const { rerender } = render(<Harness input={blocked} refresh={refresh} decisions={decisions} />);
    const signButtons = () => screen.getAllByRole("button", { name: "Sign and export" });
    for (const b of signButtons()) expect(b).toBeDisabled();

    // Standards and pages clear, decisions still open: still off.
    const noBlockers: Partial<ReviewNumbersInput> = {
      missingStandards: [], readiness: NONE_LEFT, run: { ...RUN, page_coverage: null } as unknown as ReviewRunSummary, unsaved: [],
    };
    rerender(<Harness input={noBlockers} refresh={refresh} decisions={decisions} />);
    for (const b of signButtons()) expect(b).toBeDisabled();

    // Everything decided but one not saved: still off.
    rerender(<Harness input={{ ...noBlockers, decisions: ALL_DECIDED, unsaved: ["c2"] }} refresh={refresh} decisions={decisions} />);
    for (const b of signButtons()) expect(b).toBeDisabled();

    // All clear and saved: on.
    rerender(<Harness input={{ ...noBlockers, decisions: ALL_DECIDED, unsaved: [] }} refresh={refresh} decisions={decisions} />);
    const [barSign, panelSign] = signButtons();
    expect(barSign).toBeEnabled();
    expect(panelSign).toBeEnabled();
    expect(downloadCrs).not.toHaveBeenCalled();

    await userEvent.click(barSign);
    expect(downloadCrs).toHaveBeenCalledWith("run-1", "issue");
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(await screen.findByRole("status")).toHaveTextContent(/Signed and exported/);
  });

  it("a refused sign shows the API's words and does not refresh", async () => {
    downloadCrs.mockResolvedValue("Comments are still open on this run.");
    const refresh = vi.fn().mockResolvedValue(undefined);
    const clear: Partial<ReviewNumbersInput> = {
      missingStandards: [], readiness: NONE_LEFT, run: { ...RUN, page_coverage: null } as unknown as ReviewRunSummary,
      decisions: ALL_DECIDED, unsaved: [],
    };
    render(<Harness input={clear} refresh={refresh} decisions={fakeDecisions(ALL_DECIDED, [])} />);
    await userEvent.click(screen.getAllByRole("button", { name: "Sign and export" })[1]);
    expect(await screen.findByRole("alert")).toHaveTextContent("Comments are still open on this run.");
    expect(refresh).not.toHaveBeenCalled();
  });

  it("Save sends the unsaved decisions through saveCrsDecisions, marks them saved and refreshes", async () => {
    saveCrsDecisions.mockResolvedValue({ saved: ["b2"], failed: [], wrote: true });
    const refresh = vi.fn().mockResolvedValue(undefined);
    const state: DecisionState = { decisions: { b1: { kind: "keep" }, b2: { kind: "keep" } }, opened: {} };
    const decisions = fakeDecisions(state, ["b2"]);
    render(<Harness input={{ decisions: state, unsaved: ["b2"] }} refresh={refresh} decisions={decisions} />);
    await userEvent.click(screen.getByRole("button", { name: "Save decisions" }));
    expect(saveCrsDecisions).toHaveBeenCalledWith("run-1", ROWS, state.decisions, ["b2"]);
    await waitFor(() => expect(decisions.markSaved).toHaveBeenCalledWith(["b2"]));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(await screen.findByRole("status")).toHaveTextContent("1 decision saved.");
  });

  it("the working copy downloads the unsigned internal copy", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    render(<Harness input={{}} refresh={refresh} decisions={fakeDecisions(ALL_DECIDED, [])} />);
    await userEvent.click(screen.getByRole("button", { name: "Download working copy" }));
    expect(downloadCrs).toHaveBeenCalledWith("run-1", "internal");
    expect(await screen.findByRole("status")).toHaveTextContent(/not signed/);
  });

  it("a signed run shows Signed and cannot sign again", () => {
    const n = numbersFor({
      run: { ...RUN, crs_issued_at: "2026-10-19T10:00:00", page_coverage: null } as unknown as ReviewRunSummary,
      readiness: NONE_LEFT, missingStandards: [], decisions: ALL_DECIDED, unsaved: [],
    });
    renderAll(n);
    expect(screen.getByTestId("ws-verdict").textContent).toBe("Signed on 19 Oct 2026.");
    for (const b of screen.getAllByRole("button", { name: "Signed" })) expect(b).toBeDisabled();
  });
});

/** SPEC honesty rule: an unknown number is never shown as 0. A blocker
 *  count that could not be read is not "done" and keeps Sign off.
 *
 *  MUTATION PROOF (done once by hand): make `actionSteps` treat an unknown
 *  count as 0 again and "standards read failed" fails. */
describe("unknown blocker counts never count as done", () => {
  const CLEAR_RUN = { ...RUN, page_coverage: null } as unknown as ReviewRunSummary;
  const allClear: Partial<ReviewNumbersInput> = {
    run: CLEAR_RUN, missingStandards: [], readiness: NONE_LEFT, decisions: ALL_DECIDED, unsaved: [],
  };

  function expectWaiting(n: ReviewNumbers, unknown: Array<"standards" | "pages">) {
    const steps = actionSteps(n);
    for (const id of unknown) {
      const step = steps.find((s) => s.id === id)!;
      expect(step.done, id).toBe(false);
      expect(step.enabled, id).toBe(false);
      expect(step.count, id).toBeNull();
    }
    expect(steps.find((s) => s.id === "sign")?.enabled).toBe(false);
    renderAll(n);
    const bar = screen.getByTestId("ws-action-bar");
    for (const id of unknown) {
      const button = bar.querySelector(`[data-step="${id}"]`)!;
      expect(button.getAttribute("data-done")).toBe("false");
      expect(button.textContent).not.toContain("✓");
      expect(button.textContent).toContain("could not read this yet");
      expect(button.textContent).not.toMatch(/\d/);
    }
    for (const b of screen.getAllByRole("button", { name: "Sign and export" })) expect(b).toBeDisabled();
    expect(screen.getByTestId("ws-sign-waits")).toHaveTextContent("Waiting to read the standards and page checks.");
    expect(screen.getByTestId("ws-verdict").textContent).not.toContain("Ready to sign");
    expect(screen.getByTestId("ws-verdict").textContent).toContain("Not signed yet.");
    // No number is shown for an unknown count anywhere.
    const regions = [bar, screen.getByTestId("ws-sheet-counts"), screen.getByTestId("ws-sign-off")];
    const key = (id: string) => (id === "standards" ? "missingStandards" : "unreadPages");
    for (const id of unknown) {
      for (const r of regions) expect(r.querySelector(`[data-count="${key(id)}"]`), id).toBeNull();
    }
  }

  it("standards read failed: Sign stays off and the standards step is not done", () => {
    const n = numbersFor({ ...allClear, missingStandards: null });
    expect(n.standardsKnown).toBe(false);
    expect(n.pagesKnown).toBe(true);
    expectWaiting(n, ["standards"]);
  });

  it("page checks not read (readiness null): Sign stays off and the pages step is not done", () => {
    const n = numbersFor({ ...allClear, readiness: null });
    expect(n.pagesKnown).toBe(false);
    // Readiness also lists missing standards, so that count is unknown too.
    expect(n.standardsKnown).toBe(false);
    expectWaiting(n, ["standards", "pages"]);
  });

  it("both known and 0: unchanged, the steps are ticks and Sign is on", () => {
    const n = numbersFor(allClear);
    expect(n.standardsKnown && n.pagesKnown).toBe(true);
    const steps = actionSteps(n);
    expect(steps.slice(0, 3).every((s) => s.done && !s.enabled && s.count === 0)).toBe(true);
    expect(steps[3].enabled).toBe(true);
    renderAll(n);
    const bar = screen.getByTestId("ws-action-bar");
    expect(within(bar).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "✓Upload missing standards (0)", "✓Check unread pages (0)", "✓Decide comments (0)", "Sign and export",
    ]);
    expect(screen.queryByTestId("ws-sign-waits")).toBeNull();
    expect(screen.getByTestId("ws-verdict").textContent).toBe("5 comments, 2 need your judgement. Ready to sign.");
    for (const b of screen.getAllByRole("button", { name: "Sign and export" })) expect(b).toBeEnabled();
  });
});
