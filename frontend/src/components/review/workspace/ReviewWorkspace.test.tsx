/**
 * Builder A: the workspace shell wires the data flow (SPEC section 7) on
 * made-up data. The other builders' pieces are stand-ins here so this test
 * checks the wiring only; their own tests check what they draw.
 *
 * MUTATION PROOF: open `undecidedKeys[1]` (or forget panel=evidence) on
 * "Decide comments" and the decide test fails; drop `location.tab` and render
 * the sheet always and the restore test fails; pass `null` as openRowKey and
 * the open-row test fails.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewRunSummary } from "../../../types/api";
import type { ActionBarProps, ReviewNumbers, WorkspaceLocation, WorkspaceRunData, WorkspaceSheetProps } from "./contract";
import { ReviewWorkspace } from "./ReviewWorkspace";

const data = vi.fn<() => WorkspaceRunData>();
vi.mock("./useWorkspaceRun", () => ({ useWorkspaceRun: () => data() }));

const NUMBERS: ReviewNumbers = {
  comments: 3, needsYou: 1, findingsInComments: 4, met: 10, notApplicable: 2, anotherDocument: 0, removed: 0,
  unreadPages: [4], missingStandards: ["API 610"], undecided: 2, undecidedKeys: ["row-b", "row-c"],
  unopenedNeedsYou: 1, unsaved: 0, signed: false, signedAt: null,
};
vi.mock("./numbers", () => ({
  computeReviewNumbers: () => NUMBERS,
  actionSteps: () => [
    { id: "standards", label: "Upload missing standards (1)", count: 1, done: false, enabled: true },
    { id: "pages", label: "Check unread pages (1)", count: 1, done: false, enabled: true },
    { id: "decide", label: "Decide comments (2)", count: 2, done: false, enabled: true },
    { id: "sign", label: "Sign and export", count: null, done: false, enabled: false },
  ],
  verdictLine: () => "3 comments, 1 needs your judgement. Not signed yet.",
}));
vi.mock("./ActionBar", () => ({
  ActionBar: ({ steps, onAction }: ActionBarProps) => (
    <div role="region" aria-label="What you need to do">
      {steps.map((s) => <button key={s.id} type="button" disabled={!s.enabled} onClick={() => onAction(s.id)}>{s.label}</button>)}
    </div>
  ),
}));
vi.mock("./SheetCountsLine", () => ({ SheetCountsLine: () => <p data-testid="ws-sheet-counts">counts</p> }));
vi.mock("./SignOffPanel", () => ({ SignOffPanel: () => <div data-testid="ws-sign-off">sign-off</div> }));
vi.mock("./useSignOff", () => ({
  useSignOff: () => ({ busy: false, message: null, error: null, save: vi.fn(), sign: vi.fn(), workingCopy: vi.fn() }),
}));
vi.mock("./WorkspaceSheet", () => ({
  WorkspaceSheet: ({ rows, openRowKey, onOpenRow, footer }: WorkspaceSheetProps) => (
    <div data-testid="ws-sheet">
      <p>{`open row: ${openRowKey ?? "none"}`}</p>
      {rows.map((r) => <button key={r.key} type="button" onClick={() => onOpenRow(r.key)}>{`row ${r.key}`}</button>)}
      <button type="button" onClick={() => onOpenRow(null)}>Close evidence</button>
      {footer}
    </div>
  ),
}));
vi.mock("./ReviewAgainButton", () => ({
  ReviewAgainButton: ({ documentId, onStarted }: { documentId: string; onStarted: (id: string) => void }) => (
    <button type="button" onClick={() => onStarted("run-2")}>{`Review again ${documentId}`}</button>
  ),
}));
vi.mock("../../../views/HowReviewedView", () => ({
  HowReviewedView: ({ runId, onOpenSteps }: { runId: string; onOpenSteps: () => void }) => (
    <div><p>{`how page for ${runId}`}</p><button type="button" onClick={onOpenSteps}>See the steps</button></div>
  ),
}));
vi.mock("../panels/BehindTheScenes", () => ({
  BehindTheScenes: ({ panel, onOpenPanel }: { panel: string; onOpenPanel: (p?: string) => void }) => (
    <div>
      <p>{`panel ${panel}`}</p>
      <button type="button" onClick={() => onOpenPanel(undefined)}>Back to the sheet</button>
      <button type="button" onClick={() => onOpenPanel("numbers")}>AI numbers</button>
    </div>
  ),
}));

function run(over: Partial<ReviewRunSummary> = {}): ReviewRunSummary {
  return {
    review_run_id: "run-1", submittal_document_id: "doc-sub", submittal_filename: "Pump datasheet rev B.pdf",
    status: "completed", ...over,
  } as ReviewRunSummary;
}

function ready(over: Partial<WorkspaceRunData> = {}): WorkspaceRunData {
  return {
    load: { kind: "ready" }, run: run(), findings: [],
    rows: [{ key: "row-a" }, { key: "row-b" }, { key: "row-c" }] as WorkspaceRunData["rows"],
    standardsState: { standards: [], missing: [{ identifier: "API 610", status: "MISSING_LOCALLY" }], error: null },
    standardNames: new Map(), submittal: null, summary: null, readiness: null, active: false,
    refresh: vi.fn(async () => {}), ...over,
  };
}

const changes: WorkspaceLocation[] = [];
const onOpenRun = vi.fn();
const onBack = vi.fn();

function Harness({ initial }: { initial: Partial<WorkspaceLocation> }) {
  const [location, setLocation] = useState<WorkspaceLocation>({
    runId: "run-1", tab: "sheet", row: null, panel: null, documentId: "doc-sub", ...initial,
  });
  return (
    <ReviewWorkspace
      location={location}
      onLocationChange={(next) => { changes.push(next); setLocation(next); }}
      onBack={onBack} onOpenRun={onOpenRun}
    />
  );
}

beforeEach(() => {
  changes.length = 0;
  onOpenRun.mockReset();
  onBack.mockReset();
  data.mockReturnValue(ready());
});

describe("ReviewWorkspace", () => {
  it("shows the file, the action bar, the tabs and the sheet with the sign-off under it", () => {
    render(<Harness initial={{}} />);
    expect(screen.getByRole("heading", { name: "Pump datasheet rev B.pdf" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "What you need to do" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Comment sheet" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("ws-sheet")).toContainElement(screen.getByTestId("ws-sign-off"));
    expect(screen.getByTestId("ws-sheet-counts")).toBeInTheDocument();
  });

  it('"Decide comments" opens the first undecided comment with its evidence', async () => {
    const user = userEvent.setup();
    render(<Harness initial={{ tab: "numbers" }} />);
    await user.click(screen.getByRole("button", { name: "Decide comments (2)" }));
    expect(changes.at(-1)).toMatchObject({ tab: "sheet", row: "row-b", panel: "evidence" });
    expect(screen.getByText("open row: row-b")).toBeInTheDocument();
  });

  it('"Upload missing standards" opens the Standards tab', async () => {
    const user = userEvent.setup();
    render(<Harness initial={{}} />);
    await user.click(screen.getByRole("button", { name: "Upload missing standards (1)" }));
    expect(changes.at(-1)?.tab).toBe("standards");
    expect(screen.getByText("panel standards")).toBeInTheDocument();
  });

  it("restores the place from the address: tab, open row and panel", () => {
    render(<Harness initial={{ tab: "standards", row: "row-c", panel: "evidence" }} />);
    expect(screen.getByRole("tab", { name: "Standards" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("panel standards")).toBeInTheDocument();
  });

  it("the open row comes from the address and row clicks go back to it", async () => {
    const user = userEvent.setup();
    render(<Harness initial={{ row: "row-c", panel: "evidence" }} />);
    expect(screen.getByText("open row: row-c")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "row row-a" }));
    expect(changes.at(-1)).toMatchObject({ row: "row-a", panel: "evidence" });
    await user.click(screen.getByRole("button", { name: "Close evidence" }));
    expect(changes.at(-1)).toMatchObject({ row: null, panel: null });
    expect(screen.getByText("open row: none")).toBeInTheDocument();
  });

  it("a row in the address without panel=evidence opens nothing", () => {
    render(<Harness initial={{ row: "row-c" }} />);
    expect(screen.getByText("open row: none")).toBeInTheDocument();
  });

  it("tab clicks change the address; How, the panels and their own links stay inside the workspace", async () => {
    const user = userEvent.setup();
    render(<Harness initial={{}} />);
    await user.click(screen.getByRole("tab", { name: "How this was reviewed" }));
    expect(changes.at(-1)?.tab).toBe("how");
    expect(screen.getByText("how page for run-1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "See the steps" }));
    expect(screen.getByText("panel steps")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "AI numbers" }));
    expect(screen.getByText("panel numbers")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to the sheet" }));
    expect(screen.getByTestId("ws-sheet")).toBeInTheDocument();
  });

  it('"Review again" opens the new run and "Reviews" goes back', async () => {
    const user = userEvent.setup();
    render(<Harness initial={{}} />);
    await user.click(screen.getByRole("button", { name: "Review again doc-sub" }));
    expect(onOpenRun).toHaveBeenCalledWith("run-2");
    await user.click(screen.getByRole("button", { name: "← Reviews" }));
    expect(onBack).toHaveBeenCalled();
  });

  it("writes the document into the address once the run names it", () => {
    render(<Harness initial={{ documentId: null }} />);
    expect(changes.at(-1)).toMatchObject({ documentId: "doc-sub" });
  });

  it("loading, failed and still-running runs show the sheet's own states", () => {
    data.mockReturnValue(ready({ load: { kind: "loading" }, run: null }));
    const { unmount } = render(<Harness initial={{}} />);
    expect(screen.getByText("Loading the sheet…")).toBeInTheDocument();
    unmount();

    data.mockReturnValue(ready({ load: { kind: "error", message: "This review run could not be found." }, run: null }));
    const second = render(<Harness initial={{}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("This review run could not be found.");
    second.unmount();

    data.mockReturnValue(ready({ run: run({ status: "failed", failure_reason: "the reader stopped" }) }));
    const third = render(<Harness initial={{}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("This review failed: the reader stopped");
    third.unmount();

    data.mockReturnValue(ready({ run: run({ status: "queued" }), active: true }));
    render(<Harness initial={{}} />);
    expect(screen.getByTestId("review-progress")).toHaveTextContent("Waiting to start");
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });
});
