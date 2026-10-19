/**
 * Round 2 item 6: after signing, "Download the issued copy" fetches the copy
 * the server already issued (GET .../crs/issued, then GET
 * .../crs/issued/{copy_id}); it never issues a new one. Made-up data only.
 *
 * MUTATION PROOF (done once by hand): show "Save decisions" instead of the
 * download button on a signed review and the panel test fails; fetch the
 * oldest copy instead of the newest and the "newest" test fails.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewRunSummary } from "../../../../types/api";
import type { IssueGateState } from "../../crs/issueGate";
import type { ReviewNumbers, SignOff } from "../contract";
import { SignOffPanel } from "../SignOffPanel";
import { NO_ISSUED_COPY_MESSAGE, downloadIssuedCopy } from "./issuedCopy";

const crsIssuedCopies = vi.fn();
const issuedCrsCopy = vi.fn();
const exportCrs = vi.fn();
vi.mock("../../../../api/client", () => ({
  reviews: {
    crsIssuedCopies: (...a: unknown[]) => crsIssuedCopies(...a),
    issuedCrsCopy: (...a: unknown[]) => issuedCrsCopy(...a),
    exportCrs: (...a: unknown[]) => exportCrs(...a),
  },
}));

const COPIES = [
  { id: "copy-old", review_run_id: "run-1", filename: "CRS old.xlsx", sha256: "a", size_bytes: 1, issued_by: "u", issued_at: "2026-10-10T08:00:00Z" },
  { id: "copy-new", review_run_id: "run-1", filename: "CRS new.xlsx", sha256: "b", size_bytes: 1, issued_by: "u", issued_at: "2026-10-16T08:00:00Z" },
];

beforeEach(() => {
  crsIssuedCopies.mockReset().mockResolvedValue({ ok: true, data: { copies: COPIES } });
  issuedCrsCopy.mockReset().mockResolvedValue({ ok: true, data: { blob: new Blob(["x"]), filename: "CRS new.xlsx" } });
  exportCrs.mockReset();
  URL.createObjectURL = vi.fn(() => "blob:made-up");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});

describe("downloadIssuedCopy", () => {
  it("fetches the newest issued copy, read only, and never issues", async () => {
    expect(await downloadIssuedCopy("run-1")).toBeNull();
    expect(crsIssuedCopies).toHaveBeenCalledWith("run-1");
    expect(issuedCrsCopy).toHaveBeenCalledWith("run-1", "copy-new");
    expect(exportCrs).not.toHaveBeenCalled();
  });

  it("says so in plain words when nothing was issued or the read failed", async () => {
    crsIssuedCopies.mockResolvedValue({ ok: true, data: { copies: [] } });
    expect(await downloadIssuedCopy("run-1")).toBe(NO_ISSUED_COPY_MESSAGE);
    crsIssuedCopies.mockResolvedValue({ ok: false, error: { message: "server busy" } });
    expect(await downloadIssuedCopy("run-1"))
      .toBe("Could not find the issued copy. Try again in a moment. Details: server busy");
    expect(issuedCrsCopy).not.toHaveBeenCalled();
  });

  /** #1168 follow-up. MUTATION PROOF (done once by hand): return the
   *  server's message as it came (the old code) and this fails. */
  it("a failure is said in plain words first, the server's words only as a detail", async () => {
    crsIssuedCopies.mockResolvedValue({ ok: false, disconnected: true, error: { message: "Failed to fetch" } });
    const listFailed = await downloadIssuedCopy("run-1");
    expect(listFailed).toBe(
      "Could not find the issued copy. The server could not be reached. Check your connection, then try again. Details: Failed to fetch");
    crsIssuedCopies.mockResolvedValue({ ok: true, data: { copies: COPIES } });
    issuedCrsCopy.mockResolvedValue({ ok: false, error: { code: "not_found", message: "copy_missing" } });
    const fileFailed = await downloadIssuedCopy("run-1");
    expect(fileFailed).toBe(
      "Could not download the issued copy. It could not be found. It may have been removed, or the link may be wrong. Details: copy_missing");
    expect(fileFailed?.startsWith("copy_missing")).toBe(false);
  });
});

describe("SignOffPanel after signing", () => {
  const signOff: SignOff = {
    busy: false, message: null, error: null, save: vi.fn(), sign: vi.fn(), workingCopy: vi.fn(),
  };
  const numbers = {
    comments: 2, undecided: 0, unsaved: 0, unopenedNeedsYou: 0, signed: true, signedAt: "2026-10-16T08:00:00Z",
    signLeft: [], finalCode: "2", finalCodeRecorded: true, missingStandards: [], standardsKnown: true,
    unreadPages: [], pagesKnown: true, pageRecordMissing: false, needsYou: 0, undecidedKeys: [],
  } as unknown as ReviewNumbers;
  const run = { review_run_id: "run-1", crs_issued_at: "2026-10-16T08:00:00Z" } as unknown as ReviewRunSummary;
  const gate = { gate: null, error: null, reload: vi.fn() } as unknown as IssueGateState;

  it("offers Download the issued copy, which fetches the copy on record", async () => {
    render(<SignOffPanel numbers={numbers} signOff={signOff} run={run} rows={[]} gate={gate} onRunChanged={vi.fn()} onJump={vi.fn()} />);
    expect(screen.getByText(/Signed on/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save decisions" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Download the issued copy" }));
    await waitFor(() => expect(issuedCrsCopy).toHaveBeenCalledWith("run-1", "copy-new"));
    expect(exportCrs).not.toHaveBeenCalled();
  });

  it("a failed download says why", async () => {
    issuedCrsCopy.mockResolvedValue({ ok: false, error: { message: "the archived copy no longer matches" } });
    render(<SignOffPanel numbers={numbers} signOff={signOff} run={run} rows={[]} gate={gate} onRunChanged={vi.fn()} onJump={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Download the issued copy" }));
    expect(await screen.findByTestId("ws-issued-copy-error"))
      .toHaveTextContent("Could not download the issued copy. Try again in a moment. Details: the archived copy no longer matches");
  });
});
