/**
 * Order 141 D: the engineer's Keep / Edit / Remove on the workspace reach the
 * record before any copy of the sheet is read, or the screen says plainly
 * that they did not. The real workspace, sheet, decision hooks, automatic
 * saving, sign-off and CRS tab; only the API, the download and two heavy
 * read-only panels are stand-ins. Made-up data only.
 *
 * MUTATION PROOF (done once by hand): drop the `beforeCopy` call from the
 * CRS tab's export (panels/BehindTheScenes CrsSheetPage) and "could not be
 * saved" and "a draft waiting" fail (the copy is downloaded without the
 * decisions); drop it from the tab's sheet read and "the CRS tab saves
 * first" fails (the sheet is read while the Keep is on screen only); drop
 * the draft check in ReviewWorkspace `beforeCopy`, or the `beforeCopy` call
 * in useSignOff's working copy, and "a draft waiting" fails. Order 144:
 * skip the export's own `beforeCopy` and "Export saves first" fails; drop
 * the "Saving your decisions first…" words, the `ws-undo-ended` line or the
 * preview's `ws-crs-preview-draft` line and their tests fail.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useMemo, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewFinding, ReviewRunSummary } from "../../../types/api";
import { buildCrsRows } from "../crs/crsRows";
import { CrsDraftContext, draftStorageKey } from "../crs/useCrsDecisions";
import { EMPTY_FACTS } from "../crs/tiers";
import type { WorkspaceLocation, WorkspaceRunData } from "./contract";
import { ReviewWorkspace } from "./ReviewWorkspace";

/** The order the record and the copies were touched in. */
const calls: string[] = [];
const confirm = vi.fn();
const previewCrs = vi.fn();
const downloadCrs = vi.fn();
vi.mock("../../../api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../../api/client")>();
  const no = async () => ({ ok: false, disconnected: false, error: { code: "not_found", message: "not here" } });
  return {
    ...real,
    reviews: {
      ...real.reviews,
      confirm: (...a: unknown[]) => confirm(...a),
      previewCrs: (...a: unknown[]) => previewCrs(...a),
      crsIssueGate: no,
      reviewRuns: no,
    },
  };
});
vi.mock("../downloadCrs", () => ({ downloadCrs: (...a: unknown[]) => downloadCrs(...a) }));
vi.mock("../panels/ReviewNotes", () => ({ ReviewNotes: () => null }));
vi.mock("../CrsPreviewSheet", () => ({ CrsPreviewSheet: () => <p data-testid="crs-preview-sheet">the sheet</p> }));

function f(id: string, page: number): ReviewFinding {
  return {
    id, compliance_status: "NON_COMPLIANT", matched_phrase: `Field ${id}`, finding: `${id} found`,
    required_action: `Contractor to fix ${id}.`, contractor_page: page, approval_status: "pending", standard_document_id: "std-1",
    standard_clause: "4.1",
  } as ReviewFinding;
}
const FINDINGS = [f("a", 1), f("b", 2), f("c", 3)];
const RUN = { review_run_id: "run-1", submittal_document_id: "doc-1", submittal_filename: "x.pdf", status: "completed" } as ReviewRunSummary;

function useData(): WorkspaceRunData {
  const rows = useMemo(() => buildCrsRows(FINDINGS, EMPTY_FACTS, new Map()), []);
  const [refresh] = useState(() => async () => {});
  return useMemo(() => ({
    load: { kind: "ready" }, run: RUN, findings: FINDINGS, rows,
    standardsState: { standards: [], missing: [], error: null }, missingStandardIds: [],
    standardNames: new Map(), submittal: null, summary: null, readiness: null, active: false, refresh,
  }) as WorkspaceRunData, [rows, refresh]);
}
vi.mock("./useWorkspaceRun", () => ({ useWorkspaceRun: () => useData() }));

function Harness({ draft = false }: { draft?: boolean }) {
  const [location, setLocation] = useState<WorkspaceLocation>({ runId: "run-1", tab: "sheet", row: null, panel: null, documentId: "doc-1" });
  return (
    <CrsDraftContext.Provider value={draft ? "run-1" : null}>
      <ReviewWorkspace location={location} onLocationChange={setLocation} onBack={() => {}} onOpenRun={() => {}} />
    </CrsDraftContext.Provider>
  );
}

const savedOk = async (id: string) => { calls.push(`confirm ${id}`); return { ok: true, data: {} }; };

beforeEach(() => {
  calls.length = 0;
  window.sessionStorage.clear();
  window.localStorage.clear();
  confirm.mockReset().mockImplementation(savedOk);
  previewCrs.mockReset().mockImplementation(async () => {
    calls.push("preview");
    return { ok: true, data: { rows: [], columns: [], review_notes: [] } };
  });
  downloadCrs.mockReset().mockImplementation(async (_run: string, copy: string) => { calls.push(`download ${copy}`); return null; });
});

describe("decisions reach the record before a copy of the sheet is read (order 141 D)", () => {
  it("the CRS tab saves the decisions on screen first, so its sheet shows them", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getAllByRole("button", { name: /^Keep comment/ })[0]);
    // Straight to the CRS tab, before the automatic save's pause is over.
    await user.click(screen.getByRole("tab", { name: /CRS/ }));
    await waitFor(() => expect(previewCrs).toHaveBeenCalled());
    expect(calls[0]).toBe("confirm a");
    expect(calls.indexOf("preview")).toBeGreaterThan(calls.indexOf("confirm a"));
  });

  it("the CRS tab's internal copy saves first: a decision the tab could not save on opening is saved by Export", async () => {
    const user = userEvent.setup();
    // The save the tab makes on opening fails; the one Export makes works.
    confirm.mockImplementationOnce(async () => ({ ok: false, disconnected: false, error: { code: "internal", message: "no" } }));
    render(<Harness />);
    await user.click(screen.getAllByRole("button", { name: /^Keep comment/ })[0]);
    await user.click(screen.getByRole("tab", { name: /CRS/ }));
    expect(await screen.findByTestId("crs-copy-waits")).toBeInTheDocument();
    expect(calls).not.toContain("confirm a");
    await user.click(screen.getByRole("button", { name: /Export CRS - internal review copy/ }));
    await waitFor(() => expect(downloadCrs).toHaveBeenCalledWith("run-1", "internal"));
    // Export's own save put the Keep on the record before the copy was asked for.
    expect(calls.indexOf("confirm a")).toBeGreaterThanOrEqual(0);
    expect(calls.indexOf("download internal")).toBeGreaterThan(calls.indexOf("confirm a"));
  });

  it("while the CRS tab saves first, it says so (not just \"Loading\")", async () => {
    const user = userEvent.setup();
    let release: () => void = () => {};
    confirm.mockImplementationOnce((id: string) => new Promise((resolve) => {
      release = () => { calls.push(`confirm ${id}`); resolve({ ok: true, data: {} }); };
    }));
    render(<Harness />);
    await user.click(screen.getAllByRole("button", { name: /^Keep comment/ })[0]);
    await user.click(screen.getByRole("tab", { name: /CRS/ }));
    expect(await screen.findByText("Saving your decisions first…")).toBeInTheDocument();
    release();
    await screen.findByTestId("crs-preview-sheet");
    expect(screen.queryByText("Saving your decisions first…")).toBeNull();
  });

  it("opening the CRS tab during the Keep all Undo saves them, and says the Undo is gone", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByTestId("ws-keep-all"));
    await user.click(screen.getByRole("button", { name: "Yes, keep them" }));
    expect(screen.getByTestId("ws-keep-all-done")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /CRS/ }));
    await screen.findByTestId("crs-preview-sheet");
    expect(confirm).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId("ws-undo-ended")).toHaveTextContent("Keep all was saved; Undo is no longer offered.");
  });

  it("a decision that could not be saved: the CRS tab's internal copy is not downloaded, and the tab says why", async () => {
    const user = userEvent.setup();
    confirm.mockImplementation(async () => ({ ok: false, disconnected: false, error: { code: "internal", message: "no" } }));
    render(<Harness />);
    await user.click(screen.getAllByRole("button", { name: /^Keep comment/ })[0]);
    await user.click(screen.getByRole("tab", { name: /CRS/ }));
    const tab = await screen.findByTestId("ws-crs-tab");
    expect(await within(tab).findByTestId("crs-copy-waits")).toHaveTextContent("1 decision is not saved yet");
    await user.click(within(tab).getByRole("button", { name: /Export CRS - internal review copy/ }));
    await waitFor(() => expect(within(tab).getByRole("alert")).toHaveTextContent("1 decision is not saved yet"));
    expect(downloadCrs).not.toHaveBeenCalled();
  });

  it("a draft waiting for an answer holds both copies, and says so", async () => {
    const user = userEvent.setup();
    window.sessionStorage.setItem(draftStorageKey("run-1"), JSON.stringify({
      decisions: { x: { kind: "keep" } }, opened: [], stamps: {}, openedStamps: {},
    }));
    render(<Harness draft />);
    expect(await screen.findByText(/you had not saved was found/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Download working copy" }));
    await waitFor(() => expect(screen.getAllByText(/had not saved earlier is waiting/).length).toBeGreaterThan(0));
    await user.click(screen.getByRole("tab", { name: /CRS/ }));
    const tab = await screen.findByTestId("ws-crs-tab");
    await user.click(within(tab).getByRole("button", { name: /Export CRS - internal review copy/ }));
    await waitFor(() => expect(within(tab).getByRole("alert")).toHaveTextContent("had not saved earlier is waiting"));
    expect(downloadCrs).not.toHaveBeenCalled();
    // The bar's Preview CRS says it too (order 144 item 1).
    await user.click(screen.getByRole("button", { name: "Preview CRS" }));
    expect(await screen.findByTestId("ws-crs-preview-draft")).toHaveTextContent(
      "1 decision from an earlier visit is not on the record, so this preview does not show it: bring it back or discard it first.");
  });
});
