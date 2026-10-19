/**
 * v2.1 gap S2: Sign and export opens "Preview and confirm"; nothing is
 * issued until "Issue to contractor" is pressed, and it issues only through
 * the shared path (useSignOff -> crs/issueContractorCopy.ts -> downloadCrs
 * "issue"). Made-up data only.
 *
 * MUTATION PROOF (done once by hand): make `useSignOff.sign()` call
 * `issue()` directly instead of opening the confirm step, and "pressing
 * Sign issues nothing until Issue to contractor" fails.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CrsPreview } from "../../../../types/api";
import type { CrsDecisions, ReviewNumbers } from "../contract";
import { NO_SIGN_OFF_MESSAGE, issueConfirmed, useSignOff } from "../useSignOff";
import { SignConfirm, contractorView, summaryLine } from "./SignConfirm";

const downloadCrs = vi.fn();
const previewCrs = vi.fn();
vi.mock("../../downloadCrs", () => ({ downloadCrs: (...a: unknown[]) => downloadCrs(...a) }));
vi.mock("../../crs/saveCrsDecisions", () => ({ saveCrsDecisions: vi.fn() }));
vi.mock("../../../../api/client", () => ({
  api: {},
  reviews: {
    previewCrs: (...a: unknown[]) => previewCrs(...a),
    setCrsTransmittals: vi.fn(), importCrsReply: vi.fn(), setCrsCommentStatus: vi.fn(),
    recordCrsResponse: vi.fn(), crsCommentHistory: vi.fn(),
  },
}));

function sheet(): CrsPreview {
  return {
    title: "EXAMPLE OPERATING COMPANY", subtitle: "COMMENT RESOLUTION SHEET",
    header: [{ label: "Document Title:", value: "Pump datasheet rev B.pdf" }],
    columns: ["Item No", "Document Name", "Page No./Section", "COMPANY Comments", "Comment By",
      "Contractor's Response", "Final Resolution", "AI Review Comments", "Reasoning (internal)"],
    rows: [{ item_no: 1, row_ref: "RF-1", document_name: "Pump datasheet rev B.pdf", page_section: "p4",
      comment: "Design pressure is below API 610.", comment_by: "Reviewer", contractor_response: "",
      final_resolution: "", ai_review_comment: "internal note", reasoning: "internal reasoning" }],
    review_notes: [{ note: "kept inside", standard: "API 610", count: 1, detail: "" }],
    recommended_code: "", recommended_code_label: "Recommended Review Code:", recommended_code_reason: "",
  } as unknown as CrsPreview;
}

const CLEAR = { unopenedNeedsYou: 0, signLeft: [] as string[] } as unknown as ReviewNumbers;
const decisions = (unsaved: string[] = []) =>
  ({ state: { decisions: {}, opened: {} }, unsaved, markSaved: vi.fn() }) as unknown as CrsDecisions;

function Harness({ numbers = CLEAR, unsaved = [], onIssued = vi.fn(), refresh = vi.fn().mockResolvedValue(undefined) }: {
  numbers?: ReviewNumbers | null; unsaved?: string[]; onIssued?: () => void; refresh?: () => Promise<void>;
}) {
  const signOff = useSignOff({ runId: "run-1", rows: [], decisions: decisions(unsaved), refresh, numbers });
  return (
    <div>
      <button type="button" onClick={() => void signOff.sign()}>Sign and export</button>
      {signOff.error && <p data-testid="sign-off-error">{signOff.error}</p>}
      {signOff.message && <p data-testid="sign-off-message">{signOff.message}</p>}
      <SignConfirm runId="run-1" open={signOff.confirmOpen} onClose={signOff.closeConfirm} onIssued={onIssued}
        summary={{ comments: 12, finalCode: "2", signer: "Sam Lee" }} />
    </div>
  );
}

beforeEach(() => {
  downloadCrs.mockReset().mockResolvedValue(null);
  previewCrs.mockReset().mockResolvedValue({ ok: true, data: sheet() });
});

describe("Preview and confirm (S2)", () => {
  it("pressing Sign issues nothing until Issue to contractor is pressed", async () => {
    const onIssued = vi.fn();
    const refresh = vi.fn().mockResolvedValue(undefined);
    render(<Harness onIssued={onIssued} refresh={refresh} />);
    await userEvent.click(screen.getByRole("button", { name: "Sign and export" }));
    const dialog = await screen.findByRole("dialog");
    expect(downloadCrs).not.toHaveBeenCalled();
    expect(within(dialog).getByTestId("ws-sign-summary")).toHaveTextContent("12 comments, final code 2, signed by Sam Lee.");

    await userEvent.click(within(dialog).getByRole("button", { name: "Issue to contractor" }));
    expect(downloadCrs).toHaveBeenCalledTimes(1);
    expect(downloadCrs).toHaveBeenCalledWith("run-1", "issue");
    await waitFor(() => expect(onIssued).toHaveBeenCalled());
    expect(refresh).toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByTestId("sign-off-message")).toHaveTextContent(/Signed and exported/);
  });

  it("Cancel closes the step and issues nothing", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Sign and export" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(downloadCrs).not.toHaveBeenCalled();
  });

  it("Escape closes the step and issues nothing", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Sign and export" }));
    await screen.findByRole("dialog");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(downloadCrs).not.toHaveBeenCalled();
  });

  it("shows the sheet as the contractor gets it: no internal columns or notes", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Sign and export" }));
    const region = await screen.findByRole("region", { name: /Comment Resolution Sheet preview/i });
    const headers = within(region).getAllByRole("columnheader").map((th) => th.textContent);
    expect(headers).toEqual(["Item No", "Document Name", "Page No./Section", "COMPANY Comments", "Comment By",
      "Contractor's Response", "Final Resolution"]);
    expect(within(region).getByText("Design pressure is below API 610.")).toBeInTheDocument();
    expect(within(region).queryByText("internal note")).toBeNull();
    expect(within(region).queryByText(/Review notes - internal/)).toBeNull();
  });

  it("does not open while something is left, and says what in plain words", async () => {
    render(<Harness unsaved={["b1"]} />);
    await userEvent.click(screen.getByRole("button", { name: "Sign and export" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByTestId("sign-off-error")).toHaveTextContent("Save the 1 decision on screen first.");
    expect(downloadCrs).not.toHaveBeenCalled();
  });

  it("a refusal from the server stays in the step, in its words", async () => {
    downloadCrs.mockResolvedValue("A page is still unread.");
    const onIssued = vi.fn();
    render(<Harness onIssued={onIssued} />);
    await userEvent.click(screen.getByRole("button", { name: "Sign and export" }));
    await userEvent.click(await screen.findByRole("button", { name: "Issue to contractor" }));
    expect(await screen.findByTestId("ws-sign-error")).toHaveTextContent("A page is still unread.");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(onIssued).not.toHaveBeenCalled();
  });

  it("a preview that fails to load says so and still lets the reader issue", async () => {
    previewCrs.mockResolvedValue({ ok: false, error: { message: "server busy" } });
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Sign and export" }));
    expect(await screen.findByTestId("ws-sign-preview-error")).toHaveTextContent("server busy");
    expect(screen.getByRole("button", { name: "Issue to contractor" })).toBeEnabled();
  });

  it("issues nothing when no sign-off for that review is on screen", async () => {
    const outcome = await issueConfirmed("run-nobody");
    expect(outcome).toEqual({ ok: false, message: NO_SIGN_OFF_MESSAGE });
    expect(downloadCrs).not.toHaveBeenCalled();
  });

  it("the summary never shows 0 for what is not known", () => {
    expect(summaryLine({ comments: null, finalCode: null, signer: null }))
      .toBe("Number of comments not known yet, no final code recorded, signed under your name.");
    expect(summaryLine({ comments: 1, finalCode: "1", signer: "Sam Lee" })).toBe("1 comment, final code 1, signed by Sam Lee.");
  });

  it("contractorView drops only the internal columns", () => {
    const view = contractorView(sheet());
    expect(view.columns).not.toContain("AI Review Comments");
    expect(view.columns).not.toContain("Reasoning (internal)");
    expect(view.columns).toContain("Final Resolution");
    expect(view.review_notes).toEqual([]);
  });
});
