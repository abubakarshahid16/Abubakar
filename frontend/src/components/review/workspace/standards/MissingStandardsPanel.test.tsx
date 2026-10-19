/**
 * v2.1 gap T1: each missing standard has an Upload button that uses the
 * existing upload path; an administrator's upload is marked Company
 * standard, anyone else's is not and the #620 wait is said in plain words;
 * "Review again" calls onReviewAgain. Made-up data only.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ADMIN_ONLY_REVIEW_MESSAGE, ALREADY_IN_LIBRARY_MESSAGE, MissingStandardsPanel, NON_ADMIN_UPLOADED_MESSAGE,
  NOT_CHECKED_MESSAGE, READ_IN_READY_MESSAGE, READING_IN_MESSAGE,
} from "./MissingStandardsPanel";

const uploadOne = vi.fn();
const me = vi.fn();
const setRoleBulk = vi.fn();
const uploadDisciplines = vi.fn();
const documentRead = vi.fn();
vi.mock("../../../Uploader", () => ({ uploadOne: (...a: unknown[]) => uploadOne(...a) }));
vi.mock("../../../../api/client", () => ({
  api: {
    uploadDisciplines: (...a: unknown[]) => uploadDisciplines(...a),
    document: (...a: unknown[]) => documentRead(...a),
  },
  auth: { me: (...a: unknown[]) => me(...a) },
  classification: { setRoleBulk: (...a: unknown[]) => setRoleBulk(...a) },
}));

const MISSING = [{ id: "m1", name: "API 610" }, { name: "ISO 5199" }];
const pdf = () => new File(["%PDF"], "API 610.pdf", { type: "application/pdf" });

beforeEach(() => {
  uploadOne.mockReset().mockResolvedValue({ phase: "done", documentId: "doc-new", duplicateOf: null, awaitingGrant: false });
  me.mockReset().mockResolvedValue({ ok: true, data: { required: true, user: { roles: ["engineer"] } } });
  setRoleBulk.mockReset().mockResolvedValue({ ok: true, data: { updated: ["doc-new"], failed: [] } });
  uploadDisciplines.mockReset().mockResolvedValue({ ok: true, data: { required: true, default: ["Mechanical"], choices: ["Mechanical"] } });
  documentRead.mockReset().mockResolvedValue({ ok: true, data: { id: "doc-new", status: "ready" } });
});

function show(over: Partial<Parameters<typeof MissingStandardsPanel>[0]> = {}) {
  const onReviewAgain = vi.fn();
  render(<MissingStandardsPanel runId="run-1" documentId="doc-sub" missing={MISSING} onReviewAgain={onReviewAgain} {...over} />);
  return onReviewAgain;
}

describe("Upload missing standards (T1)", () => {
  it("lists each missing standard with its own Upload button", () => {
    show();
    expect(screen.getAllByTestId("missing-standard")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Upload API 610" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload ISO 5199" })).toBeInTheDocument();
    expect(screen.getByText(/not in the library \(2\)/)).toBeInTheDocument();
  });

  it("an administrator's upload goes through the existing uploader and is marked Company standard", async () => {
    me.mockResolvedValue({ ok: true, data: { required: true, user: { roles: ["admin"] } } });
    show();
    await userEvent.upload(screen.getByLabelText("File for API 610"), pdf());
    expect(await screen.findByText(READ_IN_READY_MESSAGE)).toBeInTheDocument();
    expect(uploadOne).toHaveBeenCalledWith(expect.any(File), ["Mechanical"], expect.any(Function));
    expect(setRoleBulk).toHaveBeenCalledWith({ document_ids: ["doc-new"], document_role: "COMPANY_STANDARD" });
  });

  it("anyone else's upload is not marked, and the screen says it waits for an administrator (#620)", async () => {
    show();
    await userEvent.upload(screen.getByLabelText("File for ISO 5199"), pdf());
    expect(await screen.findByRole("status")).toHaveTextContent(NON_ADMIN_UPLOADED_MESSAGE);
    expect(screen.getByRole("status")).toHaveTextContent(/administrator has to mark it as a company standard and confirm it/);
    expect(setRoleBulk).not.toHaveBeenCalled();
  });

  it("a file already in the library is never re-marked", async () => {
    me.mockResolvedValue({ ok: true, data: { required: true, user: { roles: ["admin"] } } });
    uploadOne.mockResolvedValue({ phase: "done", documentId: "doc-old", duplicateOf: "doc-old", awaitingGrant: false });
    show();
    await userEvent.upload(screen.getByLabelText("File for API 610"), pdf());
    expect(await screen.findByRole("status")).toHaveTextContent(ALREADY_IN_LIBRARY_MESSAGE);
    expect(setRoleBulk).not.toHaveBeenCalled();
  });

  it("a failed upload says so in plain words", async () => {
    uploadOne.mockResolvedValue({ phase: "error", code: "too_large", message: "The file is too large." });
    show();
    await userEvent.upload(screen.getByLabelText("File for API 610"), pdf());
    expect(await screen.findByRole("alert")).toHaveTextContent("Not uploaded: The file is too large.");
  });

  it("Review again calls onReviewAgain", async () => {
    const onReviewAgain = show();
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    expect(onReviewAgain).toHaveBeenCalledTimes(1);
  });

  it("Review again is off, with the reason, when the review does not name its document", () => {
    show({ documentId: null });
    expect(screen.getByRole("button", { name: "Review again" })).toBeDisabled();
    expect(screen.getByText(/cannot be run again from here/)).toBeInTheDocument();
  });

  it("no missing standards: says so and still offers Review again", () => {
    show({ missing: [] });
    expect(screen.getByText("No standards are missing")).toBeInTheDocument();
    expect(screen.queryAllByTestId("missing-standard")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Review again" })).toBeEnabled();
  });

  /** Round 2 item 8. MUTATION PROOF: say "No standards are missing" whatever
   *  `known` says and this fails. */
  it("a list that could not be checked is said as such, never as none missing", () => {
    show({ missing: [], known: false });
    expect(screen.getByText(NOT_CHECKED_MESSAGE)).toBeInTheDocument();
    expect(screen.queryByText("No standards are missing")).toBeNull();
  });

  /** Round 2 item 8. MUTATION PROOF: skip the wait (say "done" at once) and
   *  "Reading it in" never shows: this fails. */
  it("after an administrator's upload it waits for the file to be read in, then says to review again", async () => {
    me.mockResolvedValue({ ok: true, data: { required: true, user: { roles: ["admin"] } } });
    let answer: (v: unknown) => void = () => {};
    documentRead.mockReturnValueOnce(new Promise((resolve) => { answer = resolve; }));
    show();
    await userEvent.upload(screen.getByLabelText("File for API 610"), pdf());
    expect(await screen.findByText(READING_IN_MESSAGE)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload API 610" })).toBeDisabled();
    answer({ ok: true, data: { id: "doc-new", status: "ready" } });
    expect(await screen.findByText(READ_IN_READY_MESSAGE)).toBeInTheDocument();
    expect(documentRead).toHaveBeenCalledWith("doc-new");
  });

  it("a file that cannot be read in says why", async () => {
    me.mockResolvedValue({ ok: true, data: { required: true, user: { roles: ["admin"] } } });
    documentRead.mockResolvedValue({ ok: false, disconnected: false, error: { code: "not_found", message: "gone" } });
    show();
    await userEvent.upload(screen.getByLabelText("File for API 610"), pdf());
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  /** Round 2 item 8. MUTATION PROOF: show the button whatever `isAdmin` says. */
  it("someone who is not an administrator is not offered Review again, and is told why", () => {
    show({ isAdmin: false });
    expect(screen.queryByRole("button", { name: "Review again" })).toBeNull();
    expect(screen.getByTestId("ws-missing-admin-only")).toHaveTextContent(ADMIN_ONLY_REVIEW_MESSAGE);
  });
});
