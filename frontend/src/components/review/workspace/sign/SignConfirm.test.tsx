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
import { NEWER_REVIEW_UNKNOWN, SignConfirm, contractorView, olderReviewWarning, summaryLine } from "./SignConfirm";

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
      final_resolution: "Open", ai_review_comment: "internal note", reasoning: "internal reasoning", crs_ref: "RF-1" }],
    review_notes: [{ note: "kept inside", standard: "API 610", count: 1, detail: "" }],
    recommended_code: "", recommended_code_label: "Recommended Review Code:", recommended_code_reason: "",
  } as unknown as CrsPreview;
}

const CLEAR = { unopenedNeedsYou: 0, signLeft: [] as string[] } as unknown as ReviewNumbers;
const decisions = (unsaved: string[] = []) =>
  ({ state: { decisions: {}, opened: {} }, unsaved, markSaved: vi.fn() }) as unknown as CrsDecisions;

function Harness({ numbers = CLEAR, unsaved = [], onIssued = vi.fn(), refresh = vi.fn().mockResolvedValue(undefined), newerReview = null }: {
  numbers?: ReviewNumbers | null; unsaved?: string[]; onIssued?: () => void; refresh?: () => Promise<void>;
  newerReview?: { at: string | null } | null | "unknown";
}) {
  const signOff = useSignOff({ runId: "run-1", rows: [], decisions: decisions(unsaved), refresh, numbers });
  return (
    <div>
      <button type="button" onClick={() => void signOff.sign()}>Sign and export</button>
      {signOff.error && <p data-testid="sign-off-error">{signOff.error}</p>}
      {signOff.message && <p data-testid="sign-off-message">{signOff.message}</p>}
      <SignConfirm runId="run-1" open={signOff.confirmOpen} onClose={signOff.closeConfirm} onIssued={onIssued}
        summary={{ comments: 12, finalCode: "2", signer: "Sam Lee" }} newerReview={newerReview} />
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

  /** Round 2 item 5. MUTATION PROOF: drop `readOnly` from the preview in
   *  SignConfirm and this fails (the transmittal form and row buttons show). */
  it("the preview is a look only: no transmittal form, no reply import, no row buttons", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Sign and export" }));
    const region = await screen.findByRole("region", { name: /Comment Resolution Sheet preview/i });
    expect(within(region).queryByRole("form", { name: "Transmittal numbers" })).toBeNull();
    expect(within(region).queryByLabelText("Import contractor reply")).toBeNull();
    expect(within(region).queryByRole("button", { name: "History" })).toBeNull();
    expect(within(region).queryByRole("button", { name: "Record reply" })).toBeNull();
    expect(within(region).queryByRole("button", { name: "Close" })).toBeNull();
    // The cells still say what the sheet says.
    expect(within(region).getByText("Open")).toBeInTheDocument();
    expect(within(region).queryAllByRole("button")).toHaveLength(0);
  });

  /** Round 2 item 5. MUTATION PROOF: drop the Tab handling and focus leaves
   *  the step; drop the focus return and the last check fails. */
  it("keeps the keyboard inside the step and gives it back to Sign on close", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const signButton = screen.getByRole("button", { name: "Sign and export" });
    await user.click(signButton);
    const dialog = await screen.findByRole("dialog");
    await screen.findByRole("region", { name: /Comment Resolution Sheet preview/i });
    const issue = within(dialog).getByRole("button", { name: "Issue to contractor" });
    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    issue.focus();
    await user.tab();
    expect(cancel).toHaveFocus();
    await user.tab({ shift: true });
    expect(issue).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(signButton).toHaveFocus();
  });

  it("Escape in a box being typed in does not close the step", async () => {
    const user = userEvent.setup();
    render(<Harness newerReview={{ at: "17/10/2026" }} />);
    await user.click(screen.getByRole("button", { name: "Sign and export" }));
    const box = await screen.findByRole("checkbox");
    box.focus();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  /** Round 2 item 4. MUTATION PROOF: let Issue ignore `newerReview` and this fails. */
  it("signing an older review asks first: Issue waits for the tick", async () => {
    const user = userEvent.setup();
    render(<Harness newerReview={{ at: "17/10/2026" }} />);
    await user.click(screen.getByRole("button", { name: "Sign and export" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByTestId("ws-sign-older")).toHaveTextContent(olderReviewWarning("17/10/2026"));
    expect(olderReviewWarning("17/10/2026")).toMatch(/^You are signing an older review/);
    const issue = within(dialog).getByRole("button", { name: "Issue to contractor" });
    expect(issue).toBeDisabled();
    await user.click(within(dialog).getByRole("checkbox", { name: "Yes, sign this older review anyway" }));
    expect(issue).toBeEnabled();
    await user.click(issue);
    expect(downloadCrs).toHaveBeenCalledWith("run-1", "issue");
  });

  /** #1168 follow-up. "Issue to contractor" runs the issuer useSignOff
   *  registered, with the checks as they are at click time, not as they were
   *  when Sign opened the step. MUTATION PROOF (done once by hand): pass
   *  empty checks to issueContractorCopy in useSignOff's issuer and both
   *  cases issue (downloadCrs "issue" is called), so this fails. */
  it("Issue refuses when a decision went unsaved or a Needs you row is unopened after the step opened", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Sign and export" }));
    const dialog = await screen.findByRole("dialog");

    rerender(<Harness unsaved={["b1"]} />);
    await user.click(within(dialog).getByRole("button", { name: "Issue to contractor" }));
    expect(await screen.findByTestId("ws-sign-error")).toHaveTextContent("Save the 1 decision on screen first.");
    expect(downloadCrs).not.toHaveBeenCalled();

    rerender(<Harness numbers={{ unopenedNeedsYou: 1, signLeft: [] } as unknown as ReviewNumbers} />);
    await user.click(within(dialog).getByRole("button", { name: "Issue to contractor" }));
    await waitFor(() => expect(screen.getByTestId("ws-sign-error")).toHaveTextContent(/marked "Needs you"/));
    expect(downloadCrs).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  /** #1168 follow-up: the newer-review check fails closed. MUTATION PROOF
   *  (done once by hand): treat "unknown" as "this is the newest" and Issue
   *  is enabled with no line shown, so this fails. */
  it("when it could not be checked whether a newer review exists, it says so and Issue waits for the tick", async () => {
    const user = userEvent.setup();
    render(<Harness newerReview="unknown" />);
    await user.click(screen.getByRole("button", { name: "Sign and export" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByTestId("ws-sign-older")).toHaveTextContent(NEWER_REVIEW_UNKNOWN);
    expect(NEWER_REVIEW_UNKNOWN).toBe("Whether a newer review of this document exists could not be checked.");
    expect(within(dialog).queryByText(/You are signing an older review/)).toBeNull();
    const issue = within(dialog).getByRole("button", { name: "Issue to contractor" });
    expect(issue).toBeDisabled();
    await user.click(within(dialog).getByRole("checkbox", { name: "Yes, sign this older review anyway" }));
    expect(issue).toBeEnabled();
    await user.click(issue);
    expect(downloadCrs).toHaveBeenCalledWith("run-1", "issue");
  });

  it("known to be the newest review: no line, no tick", async () => {
    render(<Harness newerReview={null} />);
    await userEvent.click(screen.getByRole("button", { name: "Sign and export" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByTestId("ws-sign-older")).toBeNull();
    expect(within(dialog).getByRole("button", { name: "Issue to contractor" })).toBeEnabled();
  });

  it("says the signer is not known when sign-in is off", () => {
    expect(summaryLine({ comments: 2, finalCode: "1", signer: null, signInOff: true }))
      .toBe("2 comments, final code 1, signer not known (sign-in is off).");
  });
});

describe("the sheet's code line (review 2)", () => {
  /** No em dash on screen: the reason follows the code after a full stop. */
  it("shows the code and its reason without an em dash", async () => {
    const { CrsPreviewSheet } = await import("../../CrsPreviewSheet");
    const withCode = { ...sheet(), recommended_code: "2", recommended_code_label: "Approved with comments",
      recommended_code_reason: "Two comments to answer." } as CrsPreview;
    render(<CrsPreviewSheet preview={withCode} runId="run-1" onChanged={vi.fn()} readOnly />);
    const line = screen.getByText("Two comments to answer.", { exact: false }).closest("p")!;
    expect(line.textContent).toBe("Approved with comments 2. Two comments to answer.");
    expect(line.textContent).not.toContain("\u2014");
  });
});

