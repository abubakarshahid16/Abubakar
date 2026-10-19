/**
 * Builder C: the workspace comment sheet on made-up findings.
 *
 * MUTATION PROOF (checked by hand once): render CrsTable over `rows` instead
 * of `rows.map(plainRow)` and "codes stay folded" fails; drop the `extra`
 * block in WorkspaceEvidence and the Details assertions fail; stop calling
 * onOpenRow on close and "open and close" fails; drop useCrsKeys and the
 * keyboard test fails.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewFinding, ReviewRunSummary } from "../../../types/api";
import { buildCrsRows, spotCheckKeys } from "../crs/crsRows";
import { EMPTY_FACTS } from "../crs/tiers";
import { useCrsDecisions } from "../crs/useCrsDecisions";
import type { ReviewNumbers } from "./contract";
import { computeReviewNumbers } from "./numbers";
import { REASON_CODE_WORDS } from "../reasonWords";
import { WorkspaceSheet } from "./WorkspaceSheet";

const crsDecisions = vi.fn();
vi.mock("../../../api/client", () => ({
  reviews: { crsDecisions: (...a: unknown[]) => crsDecisions(...a) },
}));
vi.mock("../sheet/SheetPageImage", () => ({
  SheetPageImage: ({ page }: { page: number }) => <span>{`datasheet page ${page}`}</span>,
}));

const RUN = {
  review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "Pump datasheet rev B.pdf",
  status: "completed", requirement_split: null,
} as unknown as ReviewRunSummary;

function f(id: string, over: Partial<ReviewFinding> = {}): ReviewFinding {
  return {
    id, compliance_status: "NON_COMPLIANT", matched_phrase: `Field ${id}`, finding: `${id} found`,
    required_action: `Contractor to fix ${id}.`, contractor_page: 1, approval_status: "pending",
    standard_document_id: "std-1", standard_clause: "6.1", created_at: "2026-10-15T08:00:00Z", ...over,
  } as ReviewFinding;
}

const FINDINGS = [
  f("flange", {
    matched_phrase: "Flange rating", contractor_page: 2,
    finding: "no_field_matched: no field read from this datasheet names the flange rating (rule p4).",
    required_action: "Contractor to state the flange rating.",
  }),
  f("seal", { matched_phrase: "Seal plan", contractor_page: 5, finding: "Seal plan differs from API 682." }),
];
const ROWS = buildCrsRows(FINDINGS, EMPTY_FACTS, new Map([["std-1", "API 610"]]));
const FLANGE_KEY = ROWS.find((r) => r.findings[0].id === "flange")!.key;
const SEAL_KEY = ROWS.find((r) => r.findings[0].id === "seal")!.key;

function numbersOf(run: ReviewRunSummary = RUN): ReviewNumbers {
  return computeReviewNumbers({
    run, findings: FINDINGS, rows: ROWS, summary: null, missingStandards: [], readiness: null,
    decisions: { decisions: {}, opened: {} }, unsaved: [], gate: null,
  });
}

function Harness({ onOpenRow, start = null, numbers = numbersOf(), showKeys }: {
  onOpenRow: (key: string | null) => void; start?: string | null; numbers?: ReviewNumbers; showKeys?: boolean;
}) {
  const decisions = useCrsDecisions();
  const [open, setOpen] = useState<string | null>(start);
  return (
    <WorkspaceSheet
      runId="run-1" run={RUN} rows={ROWS} submittal={null} standardNames={new Map([["std-1", "API 610"]])}
      decisions={decisions} openRowKey={open} numbers={numbers} showKeys={showKeys}
      onOpenRow={(key) => { onOpenRow(key); setOpen(key); }}
      footer={<p data-testid="footer">Sign-off goes here</p>}
    />
  );
}

/** The workspace's real wiring: the numbers follow the decisions. */
function LiveHarness({ onOpenRow, start = null }: { onOpenRow: (key: string | null) => void; start?: string | null }) {
  const decisions = useCrsDecisions();
  const [open, setOpen] = useState<string | null>(start);
  const numbers = computeReviewNumbers({
    run: RUN, findings: FINDINGS, rows: ROWS, summary: null, missingStandards: [], readiness: null,
    decisions: decisions.state, unsaved: decisions.unsaved, gate: null,
  });
  return (
    <WorkspaceSheet
      runId="run-1" run={RUN} rows={ROWS} submittal={null} standardNames={new Map([["std-1", "API 610"]])}
      decisions={decisions} openRowKey={open} numbers={numbers}
      onOpenRow={(key) => { onOpenRow(key); setOpen(key); }}
    />
  );
}

/** Every element whose own text names the code. */
function codeNodes(code: RegExp): HTMLElement[] {
  return screen.queryAllByText(code);
}

beforeEach(() => {
  crsDecisions.mockReset();
  crsDecisions.mockResolvedValue({ ok: true, data: { decisions: [] } });
});

describe("WorkspaceSheet", () => {
  it("shows plain words in the table and keeps every code folded under Details", async () => {
    const user = userEvent.setup();
    const onOpenRow = vi.fn();
    render(<Harness onOpenRow={onOpenRow} />);

    const table = screen.getByRole("grid", { name: "Comment resolution sheet" });
    expect(within(table).getByText("no field read from this datasheet names the flange rating (review rule 4).")).toBeVisible();
    expect(within(table).queryByText(/no_field_matched/)).toBeNull();
    expect(within(table).queryByText(/\bp4\b/)).toBeNull();
    expect(screen.getByTestId("footer")).toBeInTheDocument();

    await user.click(within(table).getByRole("button", { name: /Open evidence for Comment 1/ }));
    expect(onOpenRow).toHaveBeenLastCalledWith(FLANGE_KEY);
    const drawer = await screen.findByRole("dialog");

    // In the drawer the codes exist only inside closed Details folds.
    const engine = codeNodes(/no_field_matched/);
    const rule = codeNodes(/^p4$/);
    expect(engine.length).toBeGreaterThan(0);
    expect(rule.length).toBeGreaterThan(0);
    for (const node of [...engine, ...rule]) expect(node).not.toBeVisible();
    expect(within(drawer).queryByText(/no_field_matched:/)).toBeNull();
    // The engine code's words are main's approved table (reasonWords).
    expect(within(drawer).getByText(REASON_CODE_WORDS.no_field_matched)).toBeVisible();
    expect(within(drawer).getByText("Review rule 4")).toBeVisible();

    for (const summary of within(drawer).getAllByText("Details")) await user.click(summary);
    for (const node of [...codeNodes(/no_field_matched/), ...codeNodes(/^p4$/)]) expect(node).toBeVisible();
  });

  it("opening, moving and closing a row all go through onOpenRow", async () => {
    const user = userEvent.setup();
    const onOpenRow = vi.fn();
    render(<Harness onOpenRow={onOpenRow} />);

    await user.click(screen.getByRole("button", { name: /Open evidence for Comment 1/ }));
    expect(onOpenRow).toHaveBeenLastCalledWith(FLANGE_KEY);
    await user.click(await screen.findByRole("button", { name: "Next →" }));
    expect(onOpenRow).toHaveBeenLastCalledWith(SEAL_KEY);
    expect(screen.getByTestId("drawer-position")).toHaveTextContent("Comment 2 of 2");
    await user.click(screen.getByRole("button", { name: "Close evidence" }));
    expect(onOpenRow).toHaveBeenLastCalledWith(null);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("the folded met / not applicable line counts ROWS (as the comment sheet), from the workspace's numbers", () => {
    // 7 clauses judged not applicable on the run, but no not-applicable ROW:
    // the table's fold counts rows, so it says 0 (CrsSheetView's rowCounts),
    // and the 7 clauses are said on their own clause line.
    const numbers = numbersOf({ ...RUN, requirement_split: { does_not_apply: 7 } } as unknown as ReviewRunSummary);
    expect(numbers.notApplicableRows).toBe(0);
    expect(numbers.notApplicableClauses).toBe(7);
    expect(numbers.met).toBe(0);
    render(<Harness onOpenRow={vi.fn()} numbers={numbers} />);
    // No met, not-applicable or other-document ROW: nothing to fold, exactly
    // as the comment sheet (the clauses are not rows and are not folded).
    expect(screen.queryByTestId("met-line")).toBeNull();
    expect(screen.queryByText(/7 not applicable/)).toBeNull();
  });

  it("opens the drawer for an openRowKey given from outside", async () => {
    render(<Harness onOpenRow={vi.fn()} start={SEAL_KEY} />);
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByTestId("drawer-position")).toHaveTextContent("Comment 2 of 2");
    const row = screen.getAllByRole("row").find((r) => r.getAttribute("data-row-key") === SEAL_KEY)!;
    expect(row).toHaveAttribute("aria-selected", "true");
  });

  /** Owner, 19 Oct 2026: the old review screens are gone, so the evidence
   *  panel offers no way back to the old cards view. */
  it("the evidence panel has no link to the old cards view", async () => {
    render(<Harness onOpenRow={vi.fn()} start={SEAL_KEY} />);
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).queryByRole("button", { name: /cards view/ })).toBeNull();
    expect(within(drawer).queryByText(/cards view/)).toBeNull();
  });

  it("keeps the table's keys: J / K move, E edits, R asks why, Enter keeps", async () => {
    const user = userEvent.setup();
    render(<Harness onOpenRow={vi.fn()} />);
    const rowOf = (key: string) => screen.getAllByRole("row").find((r) => r.getAttribute("data-row-key") === key)!;

    await user.keyboard("j");
    expect(rowOf(FLANGE_KEY)).toHaveAttribute("aria-selected", "true");
    await user.keyboard("j");
    expect(rowOf(SEAL_KEY)).toHaveAttribute("aria-selected", "true");
    await user.keyboard("k");
    expect(rowOf(FLANGE_KEY)).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{Enter}");
    expect(within(rowOf(FLANGE_KEY)).getByTestId("row-status")).toHaveTextContent("Kept");

    await user.keyboard("e");
    expect(screen.getByLabelText("Required action for comment 1")).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await user.keyboard("j");
    await user.keyboard("r");
    expect(screen.getByLabelText("Why remove comment 2?")).toBeInTheDocument();
  });

  /** v2.2 round 2: Simple view shows no key hints (table, drawer, panel);
   *  Detailed view shows them. The keys still work. MUTATION PROOF: ignore
   *  `showKeys` in CrsTable, CrsEvidenceDrawer or DecisionPanel and this fails. */
  it("shows the key hints only when asked (Detailed view), and none in Simple view", async () => {
    const { unmount } = render(<Harness onOpenRow={vi.fn()} start={FLANGE_KEY} showKeys={false} />);
    const drawer = await screen.findByRole("dialog");
    expect(document.body.textContent).not.toMatch(/J \/ K/);
    expect(screen.queryByTestId("ws-decide-keys")).toBeNull();
    expect(within(drawer).getByTestId("drawer-position")).toBeInTheDocument();
    unmount();
    render(<Harness onOpenRow={vi.fn()} start={FLANGE_KEY} />);
    await screen.findByRole("dialog");
    expect(screen.getByText(/Keys: J \/ K next and previous/)).toBeInTheDocument();
    expect(screen.getByTestId("ws-decide-keys")).toBeInTheDocument();
  });

  /** D1. MUTATION PROOF: drop the `decide` block in WorkspaceSheet (or the
   *  `onDecided` call in DecisionPanel's keep) and this fails. */
  it("the evidence panel decides: Keep moves to the next undecided comment by itself", async () => {
    const user = userEvent.setup();
    const onOpenRow = vi.fn();
    render(<LiveHarness onOpenRow={onOpenRow} start={FLANGE_KEY} />);
    const drawer = await screen.findByRole("dialog");
    const panel = within(drawer).getByTestId("ws-decide");
    expect(panel).toHaveTextContent("No decision yet.");
    await user.click(within(panel).getByRole("button", { name: "Keep" }));
    expect(onOpenRow).toHaveBeenLastCalledWith(SEAL_KEY);
    expect(within(screen.getByRole("dialog")).getByTestId("drawer-position")).toHaveTextContent("Comment 2 of 2");
    const flangeRow = screen.getAllByRole("row").find((r) => r.getAttribute("data-row-key") === FLANGE_KEY)!;
    expect(within(flangeRow).getByTestId("row-status")).toHaveTextContent("Kept");
  });

  it("Remove asks for a reason in the panel; the last decision says nothing is left", async () => {
    const user = userEvent.setup();
    render(<LiveHarness onOpenRow={vi.fn()} start={SEAL_KEY} />);
    const drawer = await screen.findByRole("dialog");
    await user.click(within(drawer).getByRole("button", { name: "Keep" }));
    // Seal kept: on to the flange comment (wrapping round to the top).
    await waitFor(() => expect(within(screen.getByRole("dialog")).getByTestId("ws-decide").getAttribute("data-row")).toBe(FLANGE_KEY));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Remove with reason" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Remove" }));
    expect(within(screen.getByRole("dialog")).getByRole("alert")).toHaveTextContent("Choose why this comment is removed.");
    await user.click(within(screen.getByRole("dialog")).getByLabelText("Duplicate"));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Remove" }));
    expect(screen.getByTestId("ws-decide-note")).toHaveTextContent("That was the last comment to decide.");
    expect(screen.getByTestId("ws-decide-now")).toHaveTextContent("Now: Removed: Duplicate.");
  });

  /** D1 / D6: Enter, E and R work while the panel is open, as its hint says.
   *  MUTATION PROOF: drop DecisionPanel's keydown listener (or the focus move
   *  to Keep) and this fails. */
  it("Enter keeps, E edits the wording and R removes while the panel is open; the hint says so", async () => {
    const user = userEvent.setup();
    render(<LiveHarness onOpenRow={vi.fn()} start={FLANGE_KEY} />);
    await screen.findByRole("dialog");
    expect(screen.getByTestId("ws-decide-keys")).toHaveTextContent("Enter keep · E edit wording · R remove · J / K next and previous");
    await waitFor(() => expect(screen.getByRole("button", { name: "Keep" })).toHaveFocus());
    await user.keyboard("{Enter}");
    await waitFor(() => expect(screen.getByTestId("ws-decide").getAttribute("data-row")).toBe(SEAL_KEY));
    await user.keyboard("r");
    expect(screen.getByRole("group", { name: "Why remove this comment?" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.keyboard("e");
    const box = screen.getByLabelText("Required action (what the contractor must do)");
    expect(box).toHaveFocus();
    await user.clear(box);
    await user.type(box, "Contractor to show the seal plan.");
    await user.click(screen.getByRole("button", { name: "Use this wording" }));
    expect(screen.getByTestId("ws-decide-now")).toHaveTextContent("Now: Kept, your wording.");
  });

  /** W4: the panel sits above the app's notices (z-50). */
  it("the evidence panel has its own layer above notices", async () => {
    render(<LiveHarness onOpenRow={vi.fn()} start={FLANGE_KEY} />);
    await screen.findByRole("dialog");
    expect(screen.getByTestId("ws-evidence-layer").className).toContain("z-[60]");
  });

  /** Round 2 item 1. MUTATION PROOF: drop `readOnly` from the table, the
   *  decide block or useCrsKeys and this fails. */
  it("read only (a signed review): no Keep / Edit / Remove, no decision panel, and Enter keeps nothing", async () => {
    const user = userEvent.setup();
    function ReadOnlyHarness() {
      const decisions = useCrsDecisions();
      const [open, setOpen] = useState<string | null>(null);
      return (
        <WorkspaceSheet runId="run-1" run={RUN} rows={ROWS} submittal={null} standardNames={new Map()}
          decisions={decisions} openRowKey={open} numbers={numbersOf()} onOpenRow={setOpen} readOnly />
      );
    }
    render(<ReadOnlyHarness />);
    const table = screen.getByRole("grid", { name: "Comment resolution sheet" });
    expect(within(table).queryByRole("button", { name: /^Keep comment/ })).toBeNull();
    expect(within(table).queryByRole("button", { name: /^Edit wording of comment/ })).toBeNull();
    expect(within(table).queryByRole("button", { name: /^Remove comment/ })).toBeNull();
    expect(screen.queryByText(/E edit · R remove · Enter keep/)).toBeNull();

    // The table's keys are off: J selects nothing, Enter keeps nothing.
    await user.keyboard("j");
    await user.keyboard("{Enter}");
    const flange = screen.getAllByRole("row").find((r) => r.getAttribute("data-row-key") === FLANGE_KEY)!;
    expect(within(flange).getByTestId("row-status")).not.toHaveTextContent("Kept");

    await user.click(within(table).getByRole("button", { name: /Open evidence for Comment 1/ }));
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).queryByTestId("ws-decide")).toBeNull();
    expect(within(drawer).queryByRole("button", { name: "Keep" })).toBeNull();
  });

  /** Round 2 item 9. MUTATION PROOF: drop the widening of the "Show" choice
   *  and the met row opened from outside is not in the list: this fails. */
  it("says Comment N of M over the comments, and a row hidden by Show is shown when it is opened", async () => {
    // Many met values, so most are folded away (only a few show as a sample to check).
    const met = Array.from({ length: 12 }, (_, i) => f(`met${i}`, {
      matched_phrase: `Value ${i}`, compliance_status: "COMPLIANT", contractor_page: 9, finding: `Value ${i} meets.`,
    }));
    const rows3 = buildCrsRows([...FINDINGS, ...met], EMPTY_FACTS, new Map([["std-1", "API 610"]]));
    const spot = spotCheckKeys(rows3, "run-1");
    const metKey = rows3.find((r) => r.tier.tier === "A" && !spot.has(r.key))!.key;
    const numbers = computeReviewNumbers({
      run: RUN, findings: [...FINDINGS, ...met], rows: rows3, summary: null, missingStandards: [], readiness: null,
      decisions: { decisions: {}, opened: {} }, unsaved: [], gate: null,
    });
    function Three({ start }: { start: string | null }) {
      const decisions = useCrsDecisions();
      const [open, setOpen] = useState<string | null>(start);
      return (
        <WorkspaceSheet runId="run-1" run={RUN} rows={rows3} submittal={null} standardNames={new Map()}
          decisions={decisions} openRowKey={open} numbers={numbers} onOpenRow={setOpen} />
      );
    }
    const first = render(<Three start={SEAL_KEY} />);
    expect(within(await screen.findByRole("dialog")).getByTestId("drawer-position")).toHaveTextContent("Comment 2 of 2");
    first.unmount();

    // The met row is folded away under "Standard"; opened from outside, the
    // list widens so it is there.
    render(<Three start={metKey} />);
    await screen.findByRole("dialog");
    expect(screen.getAllByRole("row").some((r) => r.getAttribute("data-row-key") === metKey)).toBe(true);
  });
});
