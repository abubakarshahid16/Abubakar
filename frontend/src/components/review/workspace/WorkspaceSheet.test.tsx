/**
 * Builder C: the workspace comment sheet on made-up findings.
 *
 * MUTATION PROOF (checked by hand once): render CrsTable over `rows` instead
 * of `rows.map(plainRow)` and "codes stay folded" fails; drop the `extra`
 * block in WorkspaceEvidence and the Details assertions fail; stop calling
 * onOpenRow on close and "open and close" fails; drop useCrsKeys and the
 * keyboard test fails.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewFinding, ReviewRunSummary } from "../../../types/api";
import { buildCrsRows } from "../crs/crsRows";
import { EMPTY_FACTS } from "../crs/tiers";
import { useCrsDecisions } from "../crs/useCrsDecisions";
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

function Harness({ onOpenRow, start = null }: { onOpenRow: (key: string | null) => void; start?: string | null }) {
  const decisions = useCrsDecisions();
  const [open, setOpen] = useState<string | null>(start);
  return (
    <WorkspaceSheet
      runId="run-1" run={RUN} rows={ROWS} submittal={null} standardNames={new Map([["std-1", "API 610"]])}
      decisions={decisions} openRowKey={open}
      onOpenRow={(key) => { onOpenRow(key); setOpen(key); }}
      footer={<p data-testid="footer">Sign-off goes here</p>}
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
    expect(within(drawer).getByText("No field read from the datasheet matched this clause")).toBeVisible();
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
    expect(screen.getByTestId("drawer-position")).toHaveTextContent("Row 2 of 2");
    await user.click(screen.getByRole("button", { name: "Close evidence" }));
    expect(onOpenRow).toHaveBeenLastCalledWith(null);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens the drawer for an openRowKey given from outside", async () => {
    render(<Harness onOpenRow={vi.fn()} start={SEAL_KEY} />);
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByTestId("drawer-position")).toHaveTextContent("Row 2 of 2");
    const row = screen.getAllByRole("row").find((r) => r.getAttribute("data-row-key") === SEAL_KEY)!;
    expect(row).toHaveAttribute("aria-selected", "true");
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
});
