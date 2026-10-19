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
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewRunSummary } from "../../../types/api";
import type { ActionBarProps, ActionStep, ReviewNumbers, WorkspaceLocation, WorkspaceRunData, WorkspaceSheetProps } from "./contract";
import { REVIEW_HELP_HIDDEN_KEY, ReviewWorkspace, reviewHelpWords } from "./ReviewWorkspace";
import { VIEW_MODE_KEY } from "./useViewMode";

const data = vi.fn<() => WorkspaceRunData>();
/** Stands in for the API call the real ReviewAgainButton makes. */
const startReviewRun = vi.fn();
vi.mock("./useWorkspaceRun", () => ({ useWorkspaceRun: () => data() }));

const NUMBERS: ReviewNumbers = {
  comments: 3, needsYou: 1, findingsInComments: 4, met: 10, notApplicableRows: 2, notApplicableClauses: null, anotherDocument: 0, removed: 0,
  unreadPages: [4], missingStandards: ["API 610"], standardsKnown: true, pagesKnown: true, pageRecordMissing: false, undecided: 2, undecidedKeys: ["row-b", "row-c"],
  unopenedNeedsYou: 1, remainingToKeep: 1, finalCode: null, finalCodeRecorded: false, unsaved: 0, signLeft: ["tick 1 unread page"], signed: false, signedAt: null,
};
/** The issue gate the workspace reads (as the comment sheet): a stand-in. */
const issueGateFor = vi.fn();
vi.mock("../crs/issueGate", () => ({
  useIssueGate: (runId: string) => { issueGateFor(runId); return { gate: null, error: null, reload: vi.fn() }; },
}));
/** What the mocked numbers answer now (a test may sign the review). */
let numbersNow: ReviewNumbers = NUMBERS;
vi.mock("./numbers", () => ({
  computeReviewNumbers: () => numbersNow,
  actionSteps: () => [
    { id: "standards", label: "Upload missing standards (1)", count: 1, done: false, enabled: true },
    { id: "pages", label: "Check unread pages (1)", count: 1, done: false, enabled: true },
    { id: "decide", label: "Decide comments (2)", count: 2, done: false, enabled: true },
    { id: "code", label: "Record the final code", count: null, done: false, enabled: true },
    { id: "sign", label: "Sign and export", count: null, done: false, enabled: true },
  ],
  verdictLine: () => "3 comments, 1 needs your judgement. Not signed yet.",
}));
vi.mock("./ActionBar", () => ({
  // As the real bar: Sign calls signOff.sign(), every other step onAction.
  ActionBar: ({ steps, onAction, signOff, autosave }: ActionBarProps) => (
    <div role="region" aria-label="What you need to do">
      {steps.map((s) => (
        <button key={s.id} type="button" disabled={!s.enabled}
          onClick={() => (s.id === "sign" ? void signOff.sign() : onAction(s.id))}>{s.label}</button>
      ))}
      {autosave && <p data-testid="ws-autosave">{`${autosave.phase}${autosave.waiting ? " waiting" : ""}`}</p>}
      {autosave && <button type="button" onClick={() => void autosave.saveNow()}>Save now</button>}
    </div>
  ),
}));
const saveCrsDecisions = vi.fn();
vi.mock("../crs/saveCrsDecisions", () => ({ saveCrsDecisions: (...a: unknown[]) => saveCrsDecisions(...a) }));
const reviewAgain = vi.fn();
const loadPriorDecision = vi.fn();
vi.mock("./newReview", () => ({
  reviewAgain: (...a: unknown[]) => reviewAgain(...a),
  loadPriorDecision: (...a: unknown[]) => loadPriorDecision(...a),
}));
vi.mock("./decide/useSignerName", () => ({
  useSignerName: () => "Sam Engineer", useSigner: () => ({ name: "Sam Engineer", signInOff: false }),
}));
vi.mock("./sign/SignConfirm", () => ({
  SignConfirm: ({ open, summary, onClose, newerReview }: {
    open: boolean; summary: object; onClose: () => void; newerReview?: { at: string | null } | null | "unknown";
  }) => (open ? (
    <div role="dialog" aria-label="Preview and confirm"
      data-newer={newerReview === "unknown" ? "not known" : newerReview ? newerReview.at ?? "no date" : "none"}>
      <p data-testid="sign-summary">{JSON.stringify(summary)}</p>
      <button type="button" onClick={onClose}>Cancel signing</button>
    </div>
  ) : null),
}));
vi.mock("./standards/MissingStandardsPanel", () => ({
  MissingStandardsPanel: ({ missing, onReviewAgain }: { missing: { name: string }[]; onReviewAgain: () => void }) => (
    <section data-testid="missing-standards-panel">
      {missing.map((m) => <p key={m.name}>{`missing ${m.name}`}</p>)}
      <button type="button" onClick={onReviewAgain}>Review again after uploading</button>
    </section>
  ),
}));
vi.mock("./crs/CrsTabPanel", () => ({ CrsTabPanel: ({ runId }: { runId: string }) => <p>{`crs page for ${runId}`}</p> }));
vi.mock("./SheetCountsLine", () => ({ SheetCountsLine: () => <p data-testid="ws-sheet-counts">counts</p> }));
vi.mock("./SignOffPanel", () => ({
  SignOffPanel: ({ folded }: { folded?: boolean }) => <div data-testid="ws-sign-off" data-folded={String(Boolean(folded))}>sign-off<div data-testid="sign-pages">tick boxes</div></div>,
}));
/** As the real hook: sign() runs the checks (rawSign) and opens the one
 *  confirm step; nothing here ever issues. */
const rawSign = vi.fn();
vi.mock("./useSignOff", async () => {
  const { useState: useStateReal } = await import("react");
  return {
    useSignOff: () => {
      const [confirmOpen, setConfirmOpen] = useStateReal(false);
      return {
        busy: false, message: null, error: null, save: vi.fn(), workingCopy: vi.fn(),
        sign: async () => { rawSign(); setConfirmOpen(true); },
        confirmOpen, closeConfirm: () => setConfirmOpen(false),
      };
    },
  };
});
vi.mock("./WorkspaceSheet", () => ({
  WorkspaceSheet: ({ rows, openRowKey, onOpenRow, footer, decisions, readOnly }: WorkspaceSheetProps & { readOnly?: boolean }) => (
    <div data-testid="ws-sheet" data-read-only={readOnly ? "true" : "false"}>
      <button type="button" onClick={() => decisions.keep("row-b")}>Keep row-b</button>
      <p>{`open row: ${openRowKey ?? "none"}`}</p>
      {rows.map((r) => <button key={r.key} type="button" onClick={() => onOpenRow(r.key)}>{`row ${r.key}`}</button>)}
      <button type="button" onClick={() => onOpenRow(null)}>Close evidence</button>
      {footer}
    </div>
  ),
}));
// The header button is a stand-in; `useReviewAgain` (the missing standards
// panel's "Review again") is the real rule, over the mocked API above. A test
// that sets `realHeaderButton` gets the real header button, with every prop
// the workspace hands it.
let realHeaderButton = false;
vi.mock("./ReviewAgainButton", async (importOriginal) => {
  const real = await importOriginal<typeof import("./ReviewAgainButton")>();
  return {
  ...real,
  ReviewAgainButton: (props: Parameters<typeof real.ReviewAgainButton>[0]) => realHeaderButton ? <real.ReviewAgainButton {...props} /> : (({ documentId, onStarted, mayStart, beforeStart, onOpenRun: openRunning, label }: {
    documentId: string; onStarted: (id: string) => void; mayStart?: () => boolean; onOpenRun?: (id: string) => void;
    beforeStart?: (go: () => void) => void; label?: string;
  }) => (
    <>
      <button type="button" onClick={() => {
        const go = () => { startReviewRun(documentId); onStarted("run-2"); };
        if (beforeStart) beforeStart(go); else if (!mayStart || mayStart()) go();
      }}>
        {`${label ?? "Review again"} ${documentId}`}
      </button>
      {/* As the real button: the running review opens through onOpenRun, else onStarted. */}
      <button type="button" onClick={() => (openRunning ?? onStarted)("run-running")}>Open the review that is running</button>
    </>
  ))(props),
  };
});
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
    missingStandardIds: ["API 610"],
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
  startReviewRun.mockReset();
  reviewAgain.mockReset();
  loadPriorDecision.mockReset().mockResolvedValue({ kind: "none" });
  window.sessionStorage.clear();
  window.localStorage.clear();
  data.mockReturnValue(ready());
  numbersNow = NUMBERS;
  realHeaderButton = false;
  vi.restoreAllMocks();
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

  it('"Check unread pages" goes to the sheet, where the tick boxes of "Before you sign" are', async () => {
    const user = userEvent.setup();
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    render(<Harness initial={{ tab: "numbers" }} />);
    expect(issueGateFor).toHaveBeenCalledWith("run-1");
    await user.click(screen.getByRole("button", { name: "Check unread pages (1)" }));
    expect(changes.at(-1)?.tab).toBe("sheet");
    expect(screen.getByTestId("ws-sign-off")).toContainElement(screen.getByTestId("sign-pages"));
    expect(scrolled).toHaveBeenCalled();
  });

  /** T1 wiring. MUTATION PROOF: make onAction("standards") go to the tab
   *  again and this fails. */
  it('"Upload missing standards" opens the missing standards panel; its Review again starts a new review', async () => {
    const user = userEvent.setup();
    reviewAgain.mockResolvedValue({ ok: true, runId: "run-9" });
    render(<Harness initial={{}} />);
    await user.click(screen.getByRole("button", { name: "Upload missing standards (1)" }));
    expect(screen.getByTestId("missing-standards-panel")).toHaveTextContent("missing API 610");
    await user.click(screen.getByRole("button", { name: "Review again after uploading" }));
    expect(reviewAgain).toHaveBeenCalledWith("doc-sub", "Pump datasheet rev B.pdf");
    await waitFor(() => expect(onOpenRun).toHaveBeenCalledWith("run-9"));
    // The full list is one press away.
    await user.click(screen.getByRole("button", { name: "Upload missing standards (1)" }));
    await user.click(screen.getByRole("button", { name: "Upload missing standards (1)" }));
    await user.click(screen.getByRole("button", { name: "See every standard this review used" }));
    expect(changes.at(-1)?.tab).toBe("standards");
  });

  /** T1 + L2: the panel's "Review again" asks exactly what the header asks.
   *  MUTATION PROOF: call reviewAgain straight from onReviewAgain (the old
   *  startAgain) and this fails (a signed review is replaced without asking). */
  it('the missing standards panel\'s "Review again" asks first when the latest review is signed', async () => {
    const user = userEvent.setup();
    loadPriorDecision.mockResolvedValue({ kind: "signed" });
    reviewAgain.mockResolvedValue({ ok: true, runId: "run-9" });
    render(<Harness initial={{}} />);
    await user.click(screen.getByRole("button", { name: "Upload missing standards (1)" }));
    await user.click(screen.getByRole("button", { name: "Review again after uploading" }));
    const ask = await screen.findByRole("group", { name: "Start a new review?" });
    expect(ask).toHaveTextContent("already signed");
    expect(reviewAgain).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Yes, start a new review" }));
    await waitFor(() => expect(onOpenRun).toHaveBeenCalledWith("run-9"));
  });

  /** #1168 follow-up: the runs list read when the workspace opened goes stale
   *  once the engineer records a final code (or signs). The header's real
   *  "Review again" must read the latest review again at click time and ask.
   *  MUTATION PROOF: hand the button `runs={documentRuns}` again and the stale
   *  list answers "nothing decided": a fresh review starts without asking. */
  it('the header\'s "Review again" re-reads the latest review at click time: a final code recorded since the page opened asks first', async () => {
    const user = userEvent.setup();
    realHeaderButton = true;
    // What the server holds now: the engineer recorded code "C" after the page opened.
    const onServer = [run({ engineer_final_code: "C" } as Partial<ReviewRunSummary>)];
    loadPriorDecision.mockImplementation(async (_id: string, held?: ReviewRunSummary[]) => {
      const latest = (held ?? onServer)[0];
      return latest?.engineer_final_code ? { kind: "final_code", finalCode: latest.engineer_final_code } : { kind: "none" };
    });
    reviewAgain.mockResolvedValue({ ok: true, runId: "run-9" });
    // Read when the workspace opened: no final code yet.
    data.mockReturnValue({ ...ready(), documentRuns: [run()] } as WorkspaceRunData);
    render(<Harness initial={{}} />);
    await user.click(screen.getByRole("button", { name: "Review again" }));
    const ask = await screen.findByRole("group", { name: "Start a new review?" });
    expect(ask).toHaveTextContent('final code "C"');
    expect(reviewAgain).not.toHaveBeenCalled();
    expect(onOpenRun).not.toHaveBeenCalled();
  });

  it('the header\'s "Review again" asks when the fresh read fails', async () => {
    const user = userEvent.setup();
    realHeaderButton = true;
    loadPriorDecision.mockImplementation(async (_id: string, held?: ReviewRunSummary[]) => (held ? { kind: "none" } : { kind: "unknown" }));
    data.mockReturnValue({ ...ready(), documentRuns: [run()] } as WorkspaceRunData);
    render(<Harness initial={{}} />);
    await user.click(screen.getByRole("button", { name: "Review again" }));
    const ask = await screen.findByRole("group", { name: "Start a new review?" });
    expect(ask).toHaveTextContent("Could not check");
    expect(reviewAgain).not.toHaveBeenCalled();
  });

  /** #1168 follow-up. MUTATION PROOF: hand the not-finished screen's
   *  "New review" a cached `runs` list again and this fails. */
  it('a review that did not finish: its "New review" also re-reads the latest review at click time', async () => {
    const user = userEvent.setup();
    realHeaderButton = true;
    loadPriorDecision.mockImplementation(async (_id: string, held?: ReviewRunSummary[]) => (
      held ? { kind: "none" } : { kind: "final_code", finalCode: "C" }));
    data.mockReturnValue({ ...ready({ run: run({ status: "failed" }) }), documentRuns: [run()] } as WorkspaceRunData);
    render(<Harness initial={{}} />);
    await user.click(screen.getByRole("button", { name: "New review" }));
    expect(await screen.findByRole("group", { name: "Start a new review?" })).toHaveTextContent('final code "C"');
    expect(reviewAgain).not.toHaveBeenCalled();
  });

  it('the missing standards panel\'s "Review again" asks about unsaved decisions first, in the page', async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm");
    reviewAgain.mockResolvedValue({ ok: true, runId: "run-9" });
    render(<Harness initial={{}} />);
    await user.click(screen.getByRole("button", { name: "Keep row-b" }));
    await user.click(screen.getByRole("button", { name: "Upload missing standards (1)" }));
    await user.click(screen.getByRole("button", { name: "Review again after uploading" }));
    expect(screen.getByTestId("leave-confirm")).toHaveTextContent("1 decision on this review that is not saved yet");
    await user.click(screen.getByRole("button", { name: "Stay here" }));
    expect(loadPriorDecision).not.toHaveBeenCalled();
    expect(reviewAgain).not.toHaveBeenCalled();
    expect(confirm).not.toHaveBeenCalled();
  });

  /** S2 wiring. MUTATION PROOF: render a second, workspace-owned confirm
   *  (or open it without the checks in useSignOff.sign) and this fails. */
  it("Sign runs the checks and opens the one preview and confirm step with the counts; nothing is issued from the bar", async () => {
    const user = userEvent.setup();
    rawSign.mockReset();
    render(<Harness initial={{ row: "row-b", panel: "evidence" }} />);
    await user.click(screen.getByRole("button", { name: "Sign and export" }));
    expect(rawSign).toHaveBeenCalledTimes(1);
    expect(screen.getAllByRole("dialog", { name: "Preview and confirm" })).toHaveLength(1);
    expect(screen.getByRole("dialog", { name: "Preview and confirm" })).toBeInTheDocument();
    expect(JSON.parse(screen.getByTestId("sign-summary").textContent!)).toEqual({ comments: 3, finalCode: null, signer: "Sam Engineer", signInOff: false });
    // The evidence panel closed for the dialog.
    expect(changes.at(-1)).toMatchObject({ row: null, panel: null });
    await user.click(screen.getByRole("button", { name: "Cancel signing" }));
    expect(screen.queryByRole("dialog", { name: "Preview and confirm" })).toBeNull();
  });

  it("S3: the contractor copy and replies page is a tab", async () => {
    const user = userEvent.setup();
    render(<Harness initial={{}} />);
    await user.click(screen.getByRole("tab", { name: "CRS preview and replies" }));
    expect(changes.at(-1)?.tab).toBe("crs");
    expect(screen.getByText("crs page for run-1")).toBeInTheDocument();
  });

  /** S4. MUTATION PROOF: drop CrsFooter from the sheet's footer and this fails. */
  it("S4: the honesty footer sits under the sheet", () => {
    render(<Harness initial={{}} />);
    expect(screen.getByTestId("ws-sheet")).toContainElement(screen.getByTestId("crs-footer"));
  });

  /** D2 / W4. MUTATION PROOF: drop PANEL_ROOM from the section and this fails. */
  it("the page makes room on the right while the evidence panel is open", () => {
    const { unmount } = render(<Harness initial={{ row: "row-b", panel: "evidence" }} />);
    const section = screen.getByTestId("review-workspace");
    expect(section).toHaveAttribute("data-panel-open", "true");
    expect(section.className).toContain("lg:pr-[37rem]");
    unmount();
    render(<Harness initial={{}} />);
    expect(screen.getByTestId("review-workspace").className).not.toContain("lg:pr-[37rem]");
  });

  it('"Review again" in the header is secondary, never the main button', () => {
    render(<Harness initial={{}} />);
    // The header's own buttons: none carries the filled main style.
    const header = screen.getByRole("heading", { name: "Pump datasheet rev B.pdf" }).closest("header")!;
    for (const b of header.querySelectorAll("button")) expect(b.className).not.toContain("bg-signal-500");
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
    // Simple view (the default): the engineer tabs sit under "Details".
    await user.click(screen.getByRole("tab", { name: "Details" }));
    expect(changes.at(-1)?.tab).toBe("how");
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

  it('with an unsaved decision, "Reviews" and "Review again" ask first, in the page, and stay when the reader says no', async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm");
    const unsaved = vi.fn();
    data.mockReturnValue(ready());
    render(
      <ReviewWorkspace
        location={{ runId: "run-1", tab: "sheet", row: null, panel: null, documentId: "doc-sub" }}
        onLocationChange={() => {}} onBack={onBack} onOpenRun={onOpenRun} onUnsavedChange={unsaved}
      />,
    );
    // Nothing unsaved: leaving does not ask.
    await user.click(screen.getByRole("button", { name: "← Reviews" }));
    expect(confirm).not.toHaveBeenCalled();
    expect(onBack).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Keep row-b" }));
    expect(unsaved).toHaveBeenLastCalledWith(1);
    await user.click(screen.getByRole("button", { name: "← Reviews" }));
    expect(screen.getByTestId("leave-confirm")).toHaveTextContent("You have 1 decision on this review that is not saved yet.");
    await user.click(screen.getByRole("button", { name: "Stay here" }));
    expect(onBack).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "Review again doc-sub" }));
    await user.click(screen.getByRole("button", { name: "Stay here" }));
    expect(startReviewRun).not.toHaveBeenCalled();
    expect(onOpenRun).not.toHaveBeenCalled();

    // The reader chooses to leave: both go.
    await user.click(screen.getByRole("button", { name: "← Reviews" }));
    await user.click(screen.getByRole("button", { name: "Leave this review" }));
    expect(onBack).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole("button", { name: "Review again doc-sub" }));
    await user.click(screen.getByRole("button", { name: "Leave this review" }));
    expect(onOpenRun).toHaveBeenCalledWith("run-2");
    // N1: one style of question, never a browser pop-up.
    expect(confirm).not.toHaveBeenCalled();
  });

  /** N1: inside the app, the workspace asks through the app's one guard
   *  (no second question of its own). MUTATION PROOF: ignore the
   *  `leaveGuard` prop and this fails (the workspace shows its own). */
  it("uses the app's guard when given one, and shows no question of its own", async () => {
    const user = userEvent.setup();
    const guard = vi.fn(() => false);
    render(
      <ReviewWorkspace
        location={{ runId: "run-1", tab: "sheet", row: null, panel: null, documentId: "doc-sub" }}
        onLocationChange={() => {}} onBack={onBack} onOpenRun={onOpenRun} leaveGuard={guard}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Keep row-b" }));
    await user.click(screen.getByRole("button", { name: "← Reviews" }));
    expect(guard).toHaveBeenCalledWith("navigate", expect.any(Function));
    expect(screen.queryByTestId("leave-confirm")).toBeNull();
    expect(onBack).not.toHaveBeenCalled();
  });

  /** B/D drafts (v2.1 round 2): a draft found on opening is asked about
   *  first ("Bring them back?"), and only "Yes" puts it back on screen.
   *  MUTATION PROOF: drop RestoreDraftLine and this fails. */
  it('asks before bringing back unsaved decisions from this tab\'s draft', async () => {
    const user = userEvent.setup();
    const { draftStorageKey, CrsDraftContext, recordStamp } = await import("../crs/useCrsDecisions");
    const rows = [
      { key: "row-a", priorState: "open", findings: [{ id: "f-a" }] },
      { key: "row-b", priorState: "open", findings: [{ id: "f-b" }] },
      { key: "row-c", priorState: "open", findings: [{ id: "f-c" }] },
    ] as unknown as WorkspaceRunData["rows"];
    data.mockReturnValue(ready({ rows }));
    window.sessionStorage.setItem(draftStorageKey("run-1"), JSON.stringify({
      decisions: { "row-b": { kind: "keep" }, "row-c": { kind: "keep" } }, opened: [],
      stamps: { "row-b": recordStamp(rows[1]), "row-c": recordStamp(rows[2]) },
    }));
    render(
      <CrsDraftContext.Provider value="run-1">
        <Harness initial={{}} />
      </CrsDraftContext.Provider>,
    );
    expect(screen.getByTestId("ws-restored")).toHaveTextContent("2 decisions you had not saved were found. Bring them back?");
    await user.click(screen.getByRole("button", { name: "Yes" }));
    expect(await screen.findByText("2 decisions you had not saved were brought back.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Hide" }));
    expect(screen.queryByTestId("ws-restored")).toBeNull();
  });

  /** S4: "Open the review that is running" leaves the sheet too, so it asks
   *  first like "← Reviews" and "Review again".
   *  MUTATION PROOF: drop `onOpenRun={openRun}` from the header's
   *  ReviewAgainButton and this fails (the run opens without asking). */
  it('with an unsaved decision, "Open the review that is running" asks first and stays when the reader says no', async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm");
    data.mockReturnValue(ready());
    render(
      <ReviewWorkspace
        location={{ runId: "run-1", tab: "sheet", row: null, panel: null, documentId: "doc-sub" }}
        onLocationChange={() => {}} onBack={onBack} onOpenRun={onOpenRun}
      />,
    );
    // Nothing unsaved: it opens without asking.
    await user.click(screen.getByRole("button", { name: "Open the review that is running" }));
    expect(confirm).not.toHaveBeenCalled();
    expect(onOpenRun).toHaveBeenLastCalledWith("run-running");
    onOpenRun.mockClear();

    await user.click(screen.getByRole("button", { name: "Keep row-b" }));
    await user.click(screen.getByRole("button", { name: "Open the review that is running" }));
    await user.click(screen.getByRole("button", { name: "Stay here" }));
    expect(onOpenRun).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Open the review that is running" }));
    await user.click(screen.getByRole("button", { name: "Leave this review" }));
    expect(onOpenRun).toHaveBeenCalledWith("run-running");
    expect(confirm).not.toHaveBeenCalled();
  });

  /** Round 2 item 3. MUTATION PROOF: go back to `run.status === "failed"`
   *  as the only not-finished state and the cancelled review shows an empty
   *  sheet: this fails. */
  it("a cancelled review, or one in a state this screen does not know, says so and offers New review", async () => {
    const user = userEvent.setup();
    data.mockReturnValue(ready({ run: run({ status: "cancelled" }) }));
    const first = render(<Harness initial={{}} />);
    expect(screen.getByTestId("ws-not-finished")).toHaveTextContent("This review was cancelled before it finished");
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "New review doc-sub" }));
    expect(startReviewRun).toHaveBeenCalledWith("doc-sub");
    expect(onOpenRun).toHaveBeenCalledWith("run-2");
    first.unmount();

    data.mockReturnValue(ready({ run: run({ status: "stalled" }) }));
    render(<Harness initial={{}} />);
    expect(screen.getByTestId("ws-not-finished")).toHaveTextContent("This review did not finish, so there is no sheet to show.");
    expect(screen.getByRole("button", { name: "New review doc-sub" })).toBeInTheDocument();
  });

  /** Round 2 item 4. MUTATION PROOF: drop the newer-review line (or stop
   *  passing `newerReview` to SignConfirm) and this fails. */
  it("an older review says a newer one exists, opens it, and Sign is told it is older", async () => {
    const user = userEvent.setup();
    const newer = run({ review_run_id: "run-9", created_at: "2026-10-18T09:00:00Z" });
    data.mockReturnValue({ ...ready(), newerRun: newer } as WorkspaceRunData);
    render(<Harness initial={{}} />);
    const line = screen.getByTestId("ws-newer-review");
    expect(line).toHaveTextContent(`A newer review of this document exists (${new Date("2026-10-18T09:00:00Z").toLocaleDateString()}).`);
    await user.click(screen.getByRole("button", { name: "Sign and export" }));
    expect(screen.getByRole("dialog", { name: "Preview and confirm" })).toHaveAttribute(
      "data-newer", new Date("2026-10-18T09:00:00Z").toLocaleDateString());
    await user.click(screen.getByRole("button", { name: "Cancel signing" }));
    await user.click(within(line).getByRole("button", { name: "Open it" }));
    expect(onOpenRun).toHaveBeenCalledWith("run-9");
  });

  /** v2.2. MUTATION PROOF: stop drawing the earlier-reviews list on the
   *  review page (or stop passing currentRunId) and this fails. */
  it("the review page lists every review of the file and offers Compare on an earlier one", async () => {
    const user = userEvent.setup();
    const earlier = run({ review_run_id: "run-0", created_at: "2026-10-10T09:00:00Z" });
    const current = ready().run!;
    data.mockReturnValue({ ...ready(), documentRuns: [current, earlier] } as WorkspaceRunData);
    render(<Harness initial={{}} />);
    const box = screen.getByTestId("ws-past-reviews");
    await user.click(within(box).getByRole("button", { name: /All reviews of this file \(2\)/ }));
    expect(within(box).getAllByRole("button", { name: /Compare with this one/ })).toHaveLength(1);
  });

  it("a file with one review shows no earlier-reviews list", () => {
    render(<Harness initial={{}} />);
    expect(screen.queryByTestId("ws-past-reviews")).toBeNull();
  });

  it("the newest review shows no newer-review line and Sign is not told otherwise", async () => {
    const user = userEvent.setup();
    data.mockReturnValue({ ...ready(), documentRuns: [run()] } as WorkspaceRunData);
    render(<Harness initial={{}} />);
    expect(screen.queryByTestId("ws-newer-review")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Sign and export" }));
    expect(screen.getByRole("dialog", { name: "Preview and confirm" })).toHaveAttribute("data-newer", "none");
  });

  /** #1168 follow-up. MUTATION PROOF: pass `null` when the document's
   *  reviews could not be read and this fails (the warning failed open). */
  it("when the document's reviews could not be read, Sign is told it is not known whether a newer one exists", async () => {
    const user = userEvent.setup();
    data.mockReturnValue({ ...ready(), documentRuns: null, newerRun: null } as WorkspaceRunData);
    render(<Harness initial={{}} />);
    await user.click(screen.getByRole("button", { name: "Sign and export" }));
    expect(screen.getByRole("dialog", { name: "Preview and confirm" })).toHaveAttribute("data-newer", "not known");
  });

  /** Round 2 item 8. MUTATION PROOF: show the header button whatever
   *  `isAdmin` says and this fails. */
  it("someone who is not an administrator is not offered Review again, and is told why", () => {
    render(
      <ReviewWorkspace
        location={{ runId: "run-1", tab: "sheet", row: null, panel: null, documentId: "doc-sub" }}
        onLocationChange={() => {}} onBack={onBack} onOpenRun={onOpenRun} isAdmin={false}
      />,
    );
    expect(screen.queryByRole("button", { name: "Review again doc-sub" })).toBeNull();
    expect(screen.getByTestId("ws-review-again-admin-only")).toHaveTextContent("Only an administrator can start a review.");
  });

  it('a failed review offers "Review again", which starts a new review and opens it', async () => {
    const user = userEvent.setup();
    data.mockReturnValue(ready({ run: run({ status: "failed", failure_reason: "the reader stopped" }) }));
    render(<Harness initial={{}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("This review failed: the reader stopped");
    await user.click(screen.getByRole("button", { name: "New review doc-sub" }));
    expect(startReviewRun).toHaveBeenCalledWith("doc-sub");
    expect(onOpenRun).toHaveBeenCalledWith("run-2");
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

    data.mockReturnValue(ready({ load: { kind: "error", message: "The server did not answer." }, run: null }));
    const second = render(<Harness initial={{}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("The server did not answer.");
    second.unmount();

    // W1: no "run" in the words when the review is not there.
    data.mockReturnValue(ready({ load: { kind: "ready" }, run: null }));
    const missing = render(<Harness initial={{}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("This review could not be found.");
    missing.unmount();

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

/** D3 / D4: decisions save by themselves; "Keep all remaining comments"
 *  offers Undo, and nothing is saved while it does. Real useCrsDecisions,
 *  real rows with kinds. */
describe("ReviewWorkspace saving", () => {
  const rows = [
    { key: "row-b", tier: { tier: "B" }, priorState: "open", findings: [{ id: "f-b" }] },
    { key: "row-c", tier: { tier: "C" }, priorState: "open", findings: [{ id: "f-c" }] },
  ] as unknown as WorkspaceRunData["rows"];

  beforeEach(() => {
    saveCrsDecisions.mockReset();
    saveCrsDecisions.mockImplementation(async (_run: string, _rows: unknown, _d: unknown, keys: string[]) => ({ saved: keys, failed: [], wrote: false }));
    data.mockReturnValue(ready({ rows }));
  });

  /** MUTATION PROOF: drop useAutosave (or pass the raw decisions without
   *  saving) and this fails. */
  it("a decision saves by itself after a short pause", async () => {
    const user = userEvent.setup();
    const unsaved = vi.fn();
    render(
      <ReviewWorkspace
        location={{ runId: "run-1", tab: "sheet", row: null, panel: null, documentId: "doc-sub" }}
        onLocationChange={() => {}} onBack={onBack} onOpenRun={onOpenRun} onUnsavedChange={unsaved}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Keep row-b" }));
    expect(unsaved).toHaveBeenLastCalledWith(1);
    await waitFor(() => expect(saveCrsDecisions).toHaveBeenCalledWith("run-1", rows, { "row-b": { kind: "keep" } }, ["row-b"]), { timeout: 4000 });
    await waitFor(() => expect(unsaved).toHaveBeenLastCalledWith(0));
    expect(screen.getByTestId("ws-autosave")).toHaveTextContent("saved");
  });

  /** MUTATION PROOF: pass `paused: false` to useAutosave and this fails
   *  (the kept comments save while Undo is still offered). */
  it('"Keep all remaining comments" keeps only ordinary comments, asks once, offers Undo and saves nothing meanwhile', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      render(<Harness initial={{}} />);
      await user.click(screen.getByTestId("ws-keep-all"));
      expect(screen.getByRole("group", { name: "Keep all remaining comments?" })).toHaveTextContent('Comments marked "Needs you" are not touched.');
      await user.click(screen.getByRole("button", { name: "Yes, keep them" }));
      expect(screen.getByTestId("ws-keep-all-done")).toHaveTextContent("1 comment kept.");
      expect(screen.getByTestId("ws-autosave")).toHaveTextContent("waiting");
      await act(async () => { vi.advanceTimersByTime(5000); });
      expect(saveCrsDecisions).not.toHaveBeenCalled();
      await user.click(screen.getByRole("button", { name: "Undo" }));
      await act(async () => { vi.advanceTimersByTime(20000); });
      expect(saveCrsDecisions).not.toHaveBeenCalled();

      // Again, and this time let the Undo time run out: then it saves, and
      // only the ordinary comment (never the "Needs you" one).
      await user.click(screen.getByTestId("ws-keep-all"));
      await user.click(screen.getByRole("button", { name: "Yes, keep them" }));
      await act(async () => { vi.advanceTimersByTime(12000); });
      await act(async () => { vi.advanceTimersByTime(2000); });
      expect(saveCrsDecisions).toHaveBeenCalledTimes(1);
      expect(saveCrsDecisions.mock.calls[0][3]).toEqual(["row-b"]);
    } finally {
      vi.useRealTimers();
    }
  });

  /** Round 2 item 1. MUTATION PROOF: drop `disabled: numbers.signed` from
   *  useAutosave (or `readOnly` from the sheet) and this fails. */
  it("a signed review is read only: no Keep all, the sheet is read only, and nothing is saved", async () => {
    numbersNow = { ...NUMBERS, signed: true, signedAt: "2026-10-16T10:00:00Z" };
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      render(<Harness initial={{}} />);
      expect(screen.getByTestId("ws-sheet")).toHaveAttribute("data-read-only", "true");
      expect(screen.queryByTestId("ws-keep-all")).toBeNull();
      // Even an edit that reached the decisions some other way is never sent.
      await user.click(screen.getByRole("button", { name: "Keep row-b" }));
      await act(async () => { vi.advanceTimersByTime(10000); });
      expect(saveCrsDecisions).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("ReviewWorkspace v2.2: Simple / Detailed view", () => {
  /** Review 2: the switch was drawn absolutely above the title and covered
   *  the file name on a phone. It now sits in the title row, in the flow. */
  it("the Simple | Detailed switch sits in the title row, not floating over it", () => {
    render(<Harness initial={{}} />);
    const title = screen.getByRole("heading", { level: 1 });
    const header = title.closest("header")!;
    expect(within(header).getByRole("group", { name: "View" })).toBeInTheDocument();
    expect(header.querySelector(".absolute")).toBeNull();
    // The title keeps room on a phone: the switch wraps to the next line
    // instead of squeezing the file name to one letter.
    expect(title.className).toMatch(/min-w-\[12rem\]/);
  });

  /** MUTATION PROOF: drop `mode={view.mode}` from WorkspaceTabs and the
   *  Simple strip shows every tab, so this fails. */
  it("Simple is the default: Comment sheet, CRS preview and replies and Details; the switch shows Detailed", async () => {
    const user = userEvent.setup();
    render(<Harness initial={{}} />);
    const sw = within(screen.getByRole("group", { name: "View" }));
    expect(sw.getByRole("button", { name: "Simple" })).toHaveAttribute("aria-pressed", "true");
    expect(sw.getByRole("button", { name: "Detailed" })).toHaveAttribute("aria-pressed", "false");
    const main = within(screen.getByRole("tablist", { name: "Review sections" }));
    expect(main.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Comment sheet", "CRS preview and replies", "Details"]);
    expect(screen.queryByRole("tab", { name: "Findings" })).toBeNull();

    await user.click(sw.getByRole("button", { name: "Detailed" }));
    expect(sw.getByRole("button", { name: "Detailed" })).toHaveAttribute("aria-pressed", "true");
    expect(within(screen.getByRole("tablist", { name: "Review sections" })).getAllByRole("tab")).toHaveLength(7);
    expect(screen.queryByRole("tab", { name: "Details" })).toBeNull();
    expect(window.localStorage.getItem(VIEW_MODE_KEY)).toBe("detailed");
  });

  /** v2.2 round 2: Simple view is short for a manager. "Before you sign"
   *  folds behind one line that says how much is left (open while something
   *  there stops Sign); the honesty footer folds behind "How these comments
   *  were counted" but stays in the page. Detailed view shows both open.
   *  MUTATION PROOF: drop `folded` / FoldInSimple and this fails; render the
   *  footer only in Detailed and the "stays in the page" check fails. */
  it("Simple view folds Before you sign and the honesty footer; Detailed shows both open", async () => {
    const user = userEvent.setup();
    render(<Harness initial={{}} />);
    // "Before you sign" is told to fold (SignOffPanel.test.tsx checks the fold itself).
    expect(screen.getByTestId("ws-sign-off")).toHaveAttribute("data-folded", "true");
    const footFold = screen.getByTestId("ws-honesty-fold");
    expect(footFold.tagName).toBe("DETAILS");
    expect(footFold).not.toHaveAttribute("open");
    expect(within(footFold).getByText("How these comments were counted").tagName).toBe("SUMMARY");
    // The honesty rule: the footer is in the page, only folded.
    expect(footFold).toContainElement(screen.getByTestId("crs-footer"));

    await user.click(within(screen.getByRole("group", { name: "View" })).getByRole("button", { name: "Detailed" }));
    expect(screen.getByTestId("ws-sign-off")).toHaveAttribute("data-folded", "false");
    expect(screen.queryByTestId("ws-honesty-fold")).toBeNull();
    expect(screen.getByTestId("crs-footer").closest("details")).toBeNull();
  });

  it("a link to ?tab=steps in Simple view opens the steps tab with the Details row open", () => {
    render(<Harness initial={{ tab: "steps" }} />);
    expect(screen.getByRole("tab", { name: "Details" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tablist", { name: "Details" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Steps" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("panel steps")).toBeInTheDocument();
  });
});

describe("ReviewWorkspace v2.2: the one-line help", () => {
  const steps = (signEnabled: boolean): ActionStep[] => [
    { id: "sign", label: "Sign and export", count: null, done: false, enabled: signEnabled },
  ];

  it("says the next thing in plain words, from the numbers only", () => {
    expect(reviewHelpWords({ ...NUMBERS, undecided: 2 }, steps(false)))
      .toBe("Go through each comment: Keep it, Edit the wording, or Remove it. Your choices save by themselves.");
    expect(reviewHelpWords({ ...NUMBERS, undecided: 0, finalCodeRecorded: false }, steps(false)))
      .toBe("All comments are decided. Record the final code, then preview the CRS and sign.");
    expect(reviewHelpWords({ ...NUMBERS, undecided: 0, finalCodeRecorded: true, finalCode: "2" }, steps(true)))
      .toBe("Everything is done. Preview the CRS, then sign to issue it to the contractor.");
    expect(reviewHelpWords({ ...NUMBERS, undecided: 0, signed: true, signedAt: "2026-10-19" }, steps(false)))
      .toBe("This review is signed. The CRS was issued; you can still read it and import the contractor's replies.");
  });

  it("says nothing it cannot back: a final code not known yet, or Sign still waiting", () => {
    expect(reviewHelpWords({ ...NUMBERS, undecided: 0, finalCodeRecorded: null }, steps(false))).toBeNull();
    expect(reviewHelpWords({ ...NUMBERS, undecided: 0, finalCodeRecorded: true }, steps(false))).toBeNull();
  });

  /** MUTATION PROOF: drop the ReviewHelpLine and this fails. */
  it("shows under the title and Hide keeps it hidden in this browser", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<Harness initial={{}} />);
    expect(screen.getByTestId("ws-review-help")).toHaveTextContent("Go through each comment");
    await user.click(screen.getByRole("button", { name: "Hide this help" }));
    expect(screen.queryByTestId("ws-review-help")).toBeNull();
    expect(window.localStorage.getItem(REVIEW_HELP_HIDDEN_KEY)).toBe("1");
    unmount();
    render(<Harness initial={{}} />);
    expect(screen.queryByTestId("ws-review-help")).toBeNull();
  });
});
