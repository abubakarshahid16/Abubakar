/**
 * Builder D: "New review" from the landing page in three clicks or fewer,
 * "Review again" in the workspace, and the landing with the switch on / off.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const calls: string[] = [];
const uploadDisciplines = vi.fn();
const document = vi.fn();
const documents = vi.fn();
const setRoleBulk = vi.fn();
const startReviewRun = vi.fn();
const reviewRuns = vi.fn();
const reviewRun = vi.fn();
const uploadOne = vi.fn();
const listProps = vi.fn();

vi.mock("../../../api/client", () => ({
  api: {
    uploadDisciplines: (...a: unknown[]) => { calls.push("disciplines"); return uploadDisciplines(...a); },
    document: (...a: unknown[]) => { calls.push("document"); return document(...a); },
    documents: (...a: unknown[]) => documents(...a),
  },
  classification: { setRoleBulk: (...a: unknown[]) => { calls.push("mark"); return setRoleBulk(...a); } },
  reviews: {
    startReviewRun: (...a: unknown[]) => { calls.push("start"); return startReviewRun(...a); },
    reviewRuns: (...a: unknown[]) => reviewRuns(...a),
    reviewRun: (...a: unknown[]) => reviewRun(...a),
    reviewRunSummary: async () => ({ ok: false, error: { code: "not_found", message: "" } }),
  },
}));
vi.mock("../../Uploader", () => ({
  uploadOne: (...a: unknown[]) => { calls.push("upload"); return uploadOne(...a); },
}));
// The list itself is builder E's; here only what the landing hands it matters.
vi.mock("../DocumentsFromContractors", () => ({
  DocumentsFromContractors: (props: Record<string, unknown>) => {
    listProps(props);
    return <p>documents list</p>;
  },
}));

import { NewReviewDropZone } from "./NewReviewDropZone";
import { ReviewAgainButton } from "./ReviewAgainButton";
import { NOT_ADMIN_MESSAGE } from "./newReview";
import { SubmittalsLandingView } from "../../../views/SubmittalsLandingView";

const file = new File(["%PDF-1.7"], "Pump datasheet rev B.pdf", { type: "application/pdf" });

beforeEach(() => {
  calls.length = 0;
  sessionStorage.clear();
  for (const m of [uploadDisciplines, document, documents, setRoleBulk, startReviewRun, reviewRuns, reviewRun, uploadOne, listProps]) m.mockReset();
  uploadDisciplines.mockResolvedValue({ ok: true, data: { required: true, choices: ["Mechanical"], default: ["Mechanical"] } });
  uploadOne.mockResolvedValue({ phase: "done", documentId: "doc-1", duplicateOf: null, awaitingGrant: false });
  setRoleBulk.mockResolvedValue({ ok: true, data: { document_role: "CONTRACTOR_SUBMITTAL", requested: 1, updated: ["doc-1"], unchanged: [], failed: [] } });
  document.mockResolvedValue({ ok: true, data: { id: "doc-1", status: "ready" } });
  startReviewRun.mockResolvedValue({ ok: true, data: { review_run_id: "run-1", submittal_filename: "Pump datasheet rev B.pdf" } });
  reviewRun.mockResolvedValue({ ok: true, data: { review_run_id: "run-1", status: "running" } });
  documents.mockResolvedValue({ ok: true, data: [] });
  reviewRuns.mockResolvedValue({ ok: true, data: { runs: [] } });
});

describe("NewReviewDropZone", () => {
  it("starts a review from one chosen file and opens it (two clicks)", async () => {
    const onStarted = vi.fn();
    const user = userEvent.setup();
    render(<NewReviewDropZone onStarted={onStarted} />);

    await user.click(screen.getByRole("button", { name: "choose a file" }));    // click 1
    await user.upload(screen.getByLabelText("Choose a contractor file to review"), file); // click 2

    await vi.waitFor(() => expect(onStarted).toHaveBeenCalledWith("run-1"));
    expect(calls).toEqual(["disciplines", "upload", "mark", "document", "start"]);
    expect(screen.getByRole("status")).toHaveTextContent("The review has started.");
  });

  it("a non-admin sees plain words and no review starts", async () => {
    setRoleBulk.mockResolvedValue({ ok: false, disconnected: false, error: { code: "not_found", message: "That is not something the backend knows about." } });
    const onStarted = vi.fn();
    render(<NewReviewDropZone onStarted={onStarted} />);
    await userEvent.upload(screen.getByLabelText("Choose a contractor file to review"), file);

    expect(await screen.findByRole("alert")).toHaveTextContent(NOT_ADMIN_MESSAGE);
    expect(startReviewRun).not.toHaveBeenCalled();
    expect(onStarted).not.toHaveBeenCalled();
  });
});

describe("ReviewAgainButton", () => {
  it("starts a review of the same document and opens the new run", async () => {
    startReviewRun.mockResolvedValue({ ok: true, data: { review_run_id: "run-2", submittal_filename: "Pump datasheet rev B.pdf" } });
    const onStarted = vi.fn();
    render(<ReviewAgainButton documentId="doc-1" filename="Pump datasheet rev B.pdf" onStarted={onStarted} />);
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    await vi.waitFor(() => expect(onStarted).toHaveBeenCalledWith("run-2"));
    expect(startReviewRun).toHaveBeenCalledWith("doc-1");
  });

  it("shows a refusal exactly as the API said it", async () => {
    const words = "a review of this submittal is already queued or running (run-1)";
    startReviewRun.mockResolvedValue({ ok: false, disconnected: false, error: { code: "invalid_parameter", message: words } });
    const onStarted = vi.fn();
    render(<ReviewAgainButton documentId="doc-1" onStarted={onStarted} />);
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(words);
    expect(screen.getByRole("alert").textContent).toBe(words);
    expect(onStarted).not.toHaveBeenCalled();
  });
});

describe("SubmittalsLandingView with the workspace switch", () => {
  it("off (the default): no drop zone, and the list gets exactly its old props", async () => {
    render(<SubmittalsLandingView onOpenRun={vi.fn()} />);
    await screen.findByText("documents list");
    expect(screen.queryByTestId("new-review-drop-zone")).toBeNull();
    expect(Object.keys(listProps.mock.lastCall?.[0] ?? {}).sort()).toEqual(
      ["documents", "onReview", "runs", "startingDocumentId", "submittalsTotal"],
    );
  });

  it("on: the drop zone opens the started run, and each row can open past reviews", async () => {
    const onOpenRun = vi.fn();
    const user = userEvent.setup();
    render(<SubmittalsLandingView onOpenRun={onOpenRun} workspace />);
    await screen.findByText("documents list");
    expect(listProps.mock.lastCall?.[0]?.onOpenPastRun).toBe(onOpenRun);

    const zone = screen.getByTestId("new-review-drop-zone");
    await user.click(within(zone).getByRole("button", { name: "choose a file" }));
    await user.upload(within(zone).getByLabelText("Choose a contractor file to review"), file);
    await vi.waitFor(() => expect(onOpenRun).toHaveBeenCalledWith("run-1"));
  });
});
