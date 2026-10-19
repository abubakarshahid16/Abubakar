/**
 * Builder B: the bar, the sheet's count line and the sign-off panel show the
 * SAME numbers, all from one `computeReviewNumbers` result. Plus the click
 * paths: Sign waits for the blockers AND the comment sheet's issue gate
 * ("Before you sign": final code, unread page ticks), then calls
 * downloadCrs "issue" through the shared issuing path; the unread pages are
 * listed with "Read these pages again"; Save and the working copy use the
 * existing routes. Made-up data only.
 *
 * MUTATION PROOF (done once by hand): make SheetCountsLine show
 * `numbers.comments + 1` (a component counting on its own) and
 * "every shared count agrees" fails. Drop `numbers.signLeft.length === 0`
 * from the Sign rule in `actionSteps` and "Sign is off with no final code"
 * fails.
 */
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CrsIssueGate, ReviewReadiness, ReviewRunSummary } from "../../../types/api";
import { type IssueGateState, useIssueGate } from "../crs/issueGate";
import type { CrsDecisions, CrsRow, DecisionState, ReviewNumbers, ReviewNumbersInput, SignOff } from "./contract";
import { ActionBar } from "./ActionBar";
import { SheetCountsLine } from "./SheetCountsLine";
import { SignOffPanel } from "./SignOffPanel";
import { actionSteps, computeReviewNumbers } from "./numbers";
import { useSignOff } from "./useSignOff";

const downloadCrs = vi.fn();
const saveCrsDecisions = vi.fn();
const rereadPages = vi.fn();
const crsIssueGate = vi.fn();
const decideCrsPage = vi.fn();

vi.mock("../downloadCrs", () => ({ downloadCrs: (...a: unknown[]) => downloadCrs(...a) }));
vi.mock("../crs/saveCrsDecisions", () => ({ saveCrsDecisions: (...a: unknown[]) => saveCrsDecisions(...a) }));
vi.mock("../../../api/client", () => ({
  reviews: {
    rereadPages: (...a: unknown[]) => rereadPages(...a),
    crsIssueGate: (...a: unknown[]) => crsIssueGate(...a),
    decideCrsPage: (...a: unknown[]) => decideCrsPage(...a),
  },
}));

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
  ledger_state: "current", ledger_note: null,
};

/** Readiness that answered: nothing unread, nothing missing. */
const NONE_LEFT: ReviewReadiness = { ...READINESS, unread_pages: [], standards_missing: [] };

/** The issue gate as the server answers it; by default nothing is left. */
function gate(over: Partial<CrsIssueGate> = {}): CrsIssueGate {
  return {
    review_run_id: "run-1", issuable: true, final_code_recorded: true, blockers: [], unread_pages: [], open_findings: [], ...over,
  } as CrsIssueGate;
}
const CLEAR_GATE = gate();

function gateState(g: CrsIssueGate | null): IssueGateState {
  return { gate: g, error: null, reload: vi.fn().mockResolvedValue(undefined) };
}

const ROWS = [row("b1", "B"), row("b2", "B"), row("b3", "B", "agreed"), row("c1", "C"), row("c2", "C"), row("a1", "A")];

function numbersFor(over: Partial<ReviewNumbersInput> = {}): ReviewNumbers {
  return computeReviewNumbers({
    run: RUN, findings: [], rows: ROWS, summary: null, missingStandards: ["API 610"], readiness: READINESS,
    decisions: { decisions: { b1: { kind: "keep" } }, opened: {} }, unsaved: ["b1"], gate: null, ...over,
  });
}

const IDLE: SignOff = { busy: false, message: null, error: null, save: vi.fn(), sign: vi.fn(), workingCopy: vi.fn() };

function renderAll(numbers: ReviewNumbers, signOff: SignOff = IDLE, g: CrsIssueGate | null = null, run: ReviewRunSummary = RUN) {
  return render(
    <div>
      <ActionBar run={run} numbers={numbers} steps={actionSteps(numbers)} onAction={() => {}} signOff={signOff} />
      <SheetCountsLine numbers={numbers} />
      <SignOffPanel numbers={numbers} signOff={signOff} run={run} rows={ROWS} gate={gateState(g)}
        onRunChanged={() => {}} onJump={() => {}} />
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
  crsIssueGate.mockReset();
  decideCrsPage.mockReset();
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

  it("met and not applicable on the count line are the helper's: rows and clauses each in their own words", () => {
    const naRow = { ...row("na", "A"), tier: { tier: "A", label: "Not applicable", reason: null } } as unknown as CrsRow;
    const n = numbersFor({
      run: { ...RUN, requirement_split: { does_not_apply: 7 } } as unknown as ReviewRunSummary, rows: [...ROWS, naRow],
    });
    expect(n.met).toBe(1);
    expect(n.notApplicableRows).toBe(1);
    expect(n.notApplicableClauses).toBe(7);
    renderAll(n);
    const line = screen.getByTestId("ws-sheet-counts");
    expect(line.querySelector('[data-count="met"]')?.textContent).toBe(String(n.met));
    expect(line.querySelector('[data-count="notApplicableRows"]')?.textContent).toBe(String(n.notApplicableRows));
    expect(line.querySelector('[data-count="notApplicableClauses"]')?.textContent).toBe(String(n.notApplicableClauses));
    expect(line.textContent).toContain("1 row not applicable");
    expect(line.textContent).toContain("7 clauses not applicable");
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
  const n = numbersFor(input);
  const signOff = useSignOff({ runId: "run-1", rows: ROWS, decisions, refresh, numbers: n });
  const run = input.run ?? RUN;
  return (
    <div>
      <ActionBar run={run} numbers={n} steps={actionSteps(n)} onAction={() => {}} signOff={signOff} />
      <SheetCountsLine numbers={n} />
      <SignOffPanel numbers={n} signOff={signOff} run={run} rows={ROWS} gate={gateState(input.gate ?? null)}
        onRunChanged={() => {}} onJump={() => {}} />
    </div>
  );
}

/** The workspace's real wiring: the issue gate read by `useIssueGate` (the
 *  comment sheet's hook) feeds the one numbers helper and the sign-off box. */
function LiveGate({ input, decisions }: { input: Partial<ReviewNumbersInput>; decisions: CrsDecisions }) {
  const issueGate = useIssueGate("run-1", 0);
  const n = numbersFor({ ...input, gate: issueGate.gate });
  const refresh = async () => { await issueGate.reload(); };
  const signOff = useSignOff({ runId: "run-1", rows: ROWS, decisions, refresh, numbers: n });
  const run = input.run ?? RUN;
  return (
    <div>
      <ActionBar run={run} numbers={n} steps={actionSteps(n)} onAction={() => {}} signOff={signOff} />
      <SheetCountsLine numbers={n} />
      <SignOffPanel numbers={n} signOff={signOff} run={run} rows={ROWS} gate={issueGate}
        onRunChanged={() => {}} onJump={() => {}} />
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
      gate: CLEAR_GATE,
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

  it("Sign is off with no final code even when every comment is decided and saved; the bar and Before you sign say so alike", () => {
    const noCode = gate({ final_code_recorded: false, issuable: false });
    const input: Partial<ReviewNumbersInput> = {
      missingStandards: [], readiness: NONE_LEFT, run: { ...RUN, page_coverage: null } as unknown as ReviewRunSummary,
      decisions: ALL_DECIDED, unsaved: [], gate: noCode,
    };
    const n = numbersFor(input);
    expect(n.undecided).toBe(0);
    expect(n.unopenedNeedsYou).toBe(0);
    expect(n.signLeft).toEqual(["record the final code"]);
    expect(actionSteps(n).slice(0, 3).every((s) => s.done)).toBe(true);
    expect(actionSteps(n)[3].enabled).toBe(false);
    render(<Harness input={input} refresh={vi.fn().mockResolvedValue(undefined)} decisions={fakeDecisions(ALL_DECIDED, [])} />);
    for (const b of screen.getAllByRole("button", { name: "Sign and export" })) expect(b).toBeDisabled();
    expect(screen.getByTestId("ws-verdict").textContent).toContain("Not signed yet.");
    expect(screen.getByTestId("ws-sign-waits")).toHaveTextContent("Before you sign: record the final code.");
    // The comment sheet's own box, inside the sign-off, offers the control
    // and names the same thing left.
    const signOff = screen.getByTestId("ws-sign-off");
    expect(within(signOff).getByRole("button", { name: "Record the final code" })).toBeInTheDocument();
    expect(within(signOff).getByTestId("sign-left")).toHaveTextContent("Sign and export waits until you record the final code.");
    expect(downloadCrs).not.toHaveBeenCalled();
  });

  it("unread pages: the bar, the count line and the tick boxes show the gate's pages; Sign waits until they are ticked", async () => {
    let pagesLeft = [{ page: 9, reason: null }];
    crsIssueGate.mockImplementation(async () => ({
      ok: true, data: gate({ issuable: pagesLeft.length === 0, unread_pages: pagesLeft } as Partial<CrsIssueGate>),
    }));
    decideCrsPage.mockImplementation(async () => { pagesLeft = []; return { ok: true, data: {} }; });
    const input: Partial<ReviewNumbersInput> = {
      missingStandards: [], readiness: NONE_LEFT, run: { ...RUN, page_coverage: null } as unknown as ReviewRunSummary,
      decisions: ALL_DECIDED, unsaved: [],
    };
    render(<LiveGate input={input} decisions={fakeDecisions(ALL_DECIDED, [])} />);
    const pagesStep = await screen.findByRole("button", { name: "Check unread pages (1)" });
    expect(pagesStep).toBeEnabled();
    expect(screen.getByTestId("ws-sheet-counts").querySelector('[data-count="unreadPages"]')?.textContent).toBe("1");
    for (const b of screen.getAllByRole("button", { name: "Sign and export" })) expect(b).toBeDisabled();
    expect(screen.getByTestId("ws-sign-waits")).toHaveTextContent("Before you sign: tick 1 unread page.");
    const signOff = screen.getByTestId("ws-sign-off");
    expect(within(signOff).getByTestId("sign-left")).toHaveTextContent("Sign and export waits until you tick 1 unread page.");

    // Tick page 9 in the sign-off's "Before you sign" box.
    const page = within(signOff).getByTestId("sign-page-9");
    await userEvent.type(within(page).getByLabelText("What you checked on page 9"), "Checked the nozzle table by hand.");
    await act(async () => { await userEvent.click(within(page).getByRole("button", { name: "I checked page 9" })); });
    expect(decideCrsPage).toHaveBeenCalledWith("run-1", 9, "Checked the nozzle table by hand.");

    // The gate is read again: the page drops off everywhere and Sign is on.
    expect(await screen.findByRole("button", { name: /Check unread pages \(0\)/ })).toBeDisabled();
    expect(screen.queryByTestId("ws-sign-waits")).toBeNull();
    const [barSign, panelSign] = screen.getAllByRole("button", { name: "Sign and export" });
    expect(barSign).toBeEnabled();
    expect(panelSign).toBeEnabled();
    await userEvent.click(panelSign);
    expect(downloadCrs).toHaveBeenCalledWith("run-1", "issue");
  });

  it("a refused sign shows the API's words and does not refresh", async () => {
    downloadCrs.mockResolvedValue("Comments are still open on this run.");
    const refresh = vi.fn().mockResolvedValue(undefined);
    const clear: Partial<ReviewNumbersInput> = {
      missingStandards: [], readiness: NONE_LEFT, run: { ...RUN, page_coverage: null } as unknown as ReviewRunSummary,
      decisions: ALL_DECIDED, unsaved: [], gate: CLEAR_GATE,
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
    render(<Harness input={{ unsaved: [] }} refresh={refresh} decisions={fakeDecisions(ALL_DECIDED, [])} />);
    expect(screen.queryByTestId("ws-working-copy-waits")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Download working copy" }));
    expect(downloadCrs).toHaveBeenCalledWith("run-1", "internal");
    expect(await screen.findByRole("status")).toHaveTextContent(/not signed/);
  });

  /** SF7: the working copy is built from what is saved, so it waits while
   *  decisions on screen are not saved, and says why.
   *  MUTATION PROOF: drop `numbers.unsaved > 0` from the button's disabled
   *  rule and this fails. */
  it("the working copy waits while decisions are not saved, and says why", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    render(<Harness input={{ unsaved: ["b1"] }} refresh={refresh} decisions={fakeDecisions(ALL_DECIDED, ["b1"])} />);
    const button = screen.getByRole("button", { name: "Download working copy" });
    expect(button).toBeDisabled();
    expect(screen.getByTestId("ws-working-copy-waits")).toHaveTextContent("Save your decisions first: the working copy only has what is saved.");
    expect(button).toHaveAttribute("aria-describedby", "ws-working-copy-waits");
    await userEvent.click(button);
    expect(downloadCrs).not.toHaveBeenCalled();
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
    run: CLEAR_RUN, missingStandards: [], readiness: NONE_LEFT, decisions: ALL_DECIDED, unsaved: [], gate: CLEAR_GATE,
  };

  function expectWaiting(n: ReviewNumbers, unknown: Array<"standards" | "pages">) {
    const steps = actionSteps(n);
    for (const id of unknown) {
      const step = steps.find((s) => s.id === id)!;
      expect(step.done, id).toBe(false);
      // SF8: an unknown step still opens, so the reader can go and look.
      expect(step.enabled, id).toBe(true);
      expect(step.count, id).toBeNull();
    }
    expect(steps.find((s) => s.id === "sign")?.enabled).toBe(false);
    renderAll(n);
    const bar = screen.getByTestId("ws-action-bar");
    for (const id of unknown) {
      const button = bar.querySelector(`[data-step="${id}"]`)!;
      expect(button.getAttribute("data-done")).toBe("false");
      expect(button.textContent).not.toContain("✓");
      expect(button.textContent).toContain("cannot read yet");
      expect(button.textContent).not.toMatch(/\d/);
      expect(button).toBeEnabled();
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

  it("page checks not read (readiness null, issue gate not read): Sign stays off and the pages step is not done", () => {
    const n = numbersFor({ ...allClear, readiness: null, gate: null });
    expect(n.pagesKnown).toBe(false);
    // Readiness also lists missing standards, so that count is unknown too.
    expect(n.standardsKnown).toBe(false);
    expectWaiting(n, ["standards", "pages"]);
  });

  /** B2: readiness answered but its page ledger is not current (missing,
   *  stale, another file) and the issue gate has not answered: the empty
   *  unread list means "not counted", so no tick and no "(0)".
   *  MUTATION PROOF: let pagesKnown be `gate !== null || readiness !== null`
   *  again and this fails (the button reads "✓Check unread pages (0)"). */
  it.each(["missing", "stale", "not_as_submittal", undefined] as const)(
    "page ledger %s and no issue gate: the pages count is unknown, never a tick with 0",
    (ledger) => {
      const n = numbersFor({ ...allClear, readiness: { ...NONE_LEFT, ledger_state: ledger, pages_read: null }, gate: null });
      expect(n.pagesKnown).toBe(false);
      expect(n.standardsKnown).toBe(true);
      expectWaiting(n, ["pages"]);
      const pages = screen.getByTestId("ws-action-bar").querySelector('[data-step="pages"]')!;
      expect(pages.textContent).toBe("Check unread pages (cannot read yet)");
    },
  );

  it("page ledger not current but the issue gate answered: the gate's count is known", () => {
    const n = numbersFor({ ...allClear, readiness: { ...NONE_LEFT, ledger_state: "missing" }, gate: CLEAR_GATE });
    expect(n.pagesKnown).toBe(true);
    expect(actionSteps(n).find((s) => s.id === "pages")).toMatchObject({ count: 0, done: true });
  });

  /** B2 (round 2): a run with no page record. The issue gate answers an
   *  empty unread list plus its "no page coverage" blocker; that empty list
   *  is "nobody could count", so no tick, no "(0)", and plain words that the
   *  page record is missing. Readiness is either not read or its ledger is
   *  not current.
   *  MUTATION PROOF: let pagesKnown be `gate !== null || readiness current`
   *  again (drop the no-page-record check) and this fails (the button reads
   *  "✓Check unread pages (0)"). */
  it.each([
    ["readiness not read", null],
    ["page ledger missing", { ...NONE_LEFT, ledger_state: "missing" as const }],
  ])("no page record (issue gate: empty list + no page coverage), %s: never a tick with 0", async (_name, readiness) => {
    const noRecord = gate({
      issuable: false, unread_pages: [],
      blockers: ["no page coverage is recorded for this run, so no page can be called read"],
    });
    const n = numbersFor({ ...allClear, missingStandards: [], readiness: readiness ?? null, gate: noRecord });
    expect(n.pagesKnown).toBe(false);
    expect(n.pageRecordMissing).toBe(true);
    const step = actionSteps(n).find((s) => s.id === "pages")!;
    expect(step).toMatchObject({ count: null, done: false, enabled: true, label: "Check unread pages (cannot read yet)" });
    expect(actionSteps(n).find((s) => s.id === "sign")?.enabled).toBe(false);
    renderAll(n, IDLE, noRecord, CLEAR_RUN);
    const bar = screen.getByTestId("ws-action-bar");
    const button = bar.querySelector<HTMLButtonElement>('[data-step="pages"]')!;
    expect(button.getAttribute("data-done")).toBe("false");
    expect(button.textContent).toBe("Check unread pages (cannot read yet)");
    expect(button.textContent).not.toContain("✓");
    expect(button.textContent).not.toContain("(0)");
    expect(bar.querySelector('[data-count="unreadPages"]')).toBeNull();
    expect(screen.getByTestId("ws-sign-waits")).toHaveTextContent("The record of which pages were read is missing");
    await userEvent.click(button);
    expect(screen.getByTestId("ws-page-record-missing")).toHaveTextContent(
      "The record of which pages were read is missing for this review, so no page can be called read yet.",
    );
    for (const b of screen.getAllByRole("button", { name: "Sign and export" })) expect(b).toBeDisabled();
  });

  /** SF8: pressing an unknown pages step opens the pages box, which says the
   *  pages are not known instead of listing none. */
  it("an unknown pages step opens and says the pages are not known", async () => {
    const n = numbersFor({ ...allClear, readiness: null, gate: null });
    renderAll(n);
    const bar = screen.getByTestId("ws-action-bar");
    await userEvent.click(bar.querySelector<HTMLButtonElement>('[data-step="pages"]')!);
    const box = screen.getByTestId("ws-unread-pages");
    expect(box).toHaveTextContent("The page checks cannot be read yet");
    expect(box.textContent).not.toContain("undefined");
    expect(within(box).getByRole("button", { name: "Read these pages again" })).toBeEnabled();
  });

  it("both known and 0: unchanged, the steps are ticks and Sign is on", () => {
    const n = numbersFor(allClear);
    expect(n.standardsKnown && n.pagesKnown).toBe(true);
    const steps = actionSteps(n);
    expect(steps.slice(0, 3).every((s) => s.done && !s.enabled && s.count === 0)).toBe(true);
    expect(steps[3].enabled).toBe(true);
    renderAll(n, IDLE, CLEAR_GATE, CLEAR_RUN);
    const bar = screen.getByTestId("ws-action-bar");
    expect(within(bar).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "✓Upload missing standards (0)", "✓Check unread pages (0)", "✓Decide comments (0)", "Sign and export",
    ]);
    expect(screen.queryByTestId("ws-sign-waits")).toBeNull();
    expect(screen.getByTestId("ws-verdict").textContent).toBe("5 comments, 2 need your judgement. Ready to sign.");
    for (const b of screen.getAllByRole("button", { name: "Sign and export" })) expect(b).toBeEnabled();
  });
});
