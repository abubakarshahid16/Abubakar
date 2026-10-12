/**
 * After a CRS is issued (industry CRS practice, 2026-09-29): the contractor
 * replies with a response code, only the reviewer closes a comment, and each
 * step is on record. On screen:
 *   - controls appear only on a NUMBERED comment (a draft is not a comment yet);
 *   - a recorded reply defaults to "No response code stated", never "Accepted";
 *   - Close sends the reviewer's optional note, and the sheet is re-read;
 *   - an import reports every row it read, with its denominator.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CrsItemCell, CrsReplyImportControl, CrsResolutionCell, CrsResponseCell,
} from "./CrsCommentControls";
import type { CrsPreviewRow } from "../../types/api";

const setStatus = vi.fn();
const recordResponse = vi.fn();
const importReply = vi.fn();
const history = vi.fn();
vi.mock("../../api/client", () => ({
  reviews: {
    setCrsCommentStatus: (...a: unknown[]) => setStatus(...a),
    recordCrsResponse: (...a: unknown[]) => recordResponse(...a),
    importCrsReply: (...a: unknown[]) => importReply(...a),
    crsCommentHistory: (...a: unknown[]) => history(...a),
  },
}));

function row(over: Partial<CrsPreviewRow> = {}): CrsPreviewRow {
  return {
    item_no: "CRS-SUB7-001", crs_ref: "CRS-SUB7-001", row_ref: "RF-ABC123",
    document_name: "sheet.pdf", page_section: "p.4", comment: "c", comment_by: "Eng",
    contractor_response: "", final_resolution: "Open",
    ...over,
  } as CrsPreviewRow;
}

beforeEach(() => {
  [setStatus, recordResponse, importReply, history].forEach((f) => f.mockReset());
  setStatus.mockResolvedValue({ ok: true, data: {} });
  recordResponse.mockResolvedValue({ ok: true, data: {} });
});

describe("only a numbered comment can be answered or closed", () => {
  it("shows no controls on an unnumbered draft", () => {
    const draft = row({ item_no: 3, crs_ref: "", final_resolution: "" });
    render(<>
      <CrsResponseCell runId="run-1" row={draft} onChanged={vi.fn()} />
      <CrsResolutionCell runId="run-1" row={draft} onChanged={vi.fn()} />
      <CrsItemCell runId="run-1" row={draft} />
    </>);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("the reviewer closes a comment", () => {
  it("sends Closed with the note, then re-reads the sheet", async () => {
    const onChanged = vi.fn();
    render(<CrsResolutionCell runId="run-1" row={row()} onChanged={onChanged} />);
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await userEvent.type(screen.getByLabelText(/Closing note/), "verified on Rev 1");
    await userEvent.click(screen.getByRole("button", { name: "Confirm close" }));
    expect(setStatus).toHaveBeenCalledWith("run-1", "CRS-SUB7-001", "Closed", "verified on Rev 1");
    expect(onChanged).toHaveBeenCalled();
  });

  it("offers Reopen on a closed comment", () => {
    render(<CrsResolutionCell runId="run-1" row={row({ final_resolution: "Closed: done" })}
      onChanged={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Reopen" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close" })).toBeNull();
  });
});

describe("a recorded reply is never assumed to be agreement", () => {
  it("defaults to no response code and sends null when left so", async () => {
    render(<CrsResponseCell runId="run-1" row={row()} onChanged={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Record reply" }));
    const select = screen.getByLabelText(/Response code/) as HTMLSelectElement;
    expect(select.value).toBe("");
    await userEvent.type(screen.getByLabelText(/Contractor's reply/), "will revise");
    await userEvent.click(screen.getByRole("button", { name: "Save reply" }));
    expect(recordResponse).toHaveBeenCalledWith("run-1", "CRS-SUB7-001", null, "will revise");
  });

  it("prints the reply the sheet carries", () => {
    render(<CrsResponseCell runId="run-1" row={row({ contractor_response: "Rejected: vendor std" })}
      onChanged={vi.fn()} />);
    expect(screen.getByText("Rejected: vendor std")).toBeInTheDocument();
  });
});

describe("importing the returned sheet", () => {
  it("reports every row read and says statuses were not changed", async () => {
    importReply.mockResolvedValue({ ok: true, data: {
      rows_read: 4, updated: 1, updated_without_code: 1, no_response: 1,
      not_a_crs_number: 1, other_submittal: 0, unknown_number: 0, rows: [],
    } });
    const onChanged = vi.fn();
    render(<CrsReplyImportControl runId="run-1" onChanged={onChanged} />);
    const file = new File(["x"], "reply.xlsx");
    await userEvent.upload(screen.getByLabelText("Import contractor reply"), file);
    const status = await screen.findByRole("status");
    expect(status.textContent).toMatch(/4 row\(s\) read: 1 reply\(ies\) stored/);
    expect(status.textContent).toMatch(/1 stored with no response code stated/);
    expect(status.textContent).toMatch(/only the reviewer closes a comment/);
    expect(onChanged).toHaveBeenCalled();
  });
});
