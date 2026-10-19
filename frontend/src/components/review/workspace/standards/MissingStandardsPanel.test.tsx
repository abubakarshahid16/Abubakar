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
  ADMIN_UPLOADED_MESSAGE, ALREADY_IN_LIBRARY_MESSAGE, MissingStandardsPanel, NON_ADMIN_UPLOADED_MESSAGE,
} from "./MissingStandardsPanel";

const uploadOne = vi.fn();
const me = vi.fn();
const setRoleBulk = vi.fn();
const uploadDisciplines = vi.fn();
vi.mock("../../../Uploader", () => ({ uploadOne: (...a: unknown[]) => uploadOne(...a) }));
vi.mock("../../../../api/client", () => ({
  api: { uploadDisciplines: (...a: unknown[]) => uploadDisciplines(...a) },
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
    expect(await screen.findByRole("status")).toHaveTextContent(ADMIN_UPLOADED_MESSAGE);
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
});
