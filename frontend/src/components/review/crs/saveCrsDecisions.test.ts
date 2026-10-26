import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReviewFinding } from "../../../types/api";
import type { CrsRow } from "./crsRows";
import { saveCrsDecisions } from "./saveCrsDecisions";

const update = vi.fn();
const decideCrsFinding = vi.fn();
vi.mock("../../../api/client", () => ({
  reviews: {
    update: (...a: unknown[]) => update(...a),
    decideCrsFinding: (...a: unknown[]) => decideCrsFinding(...a),
  },
}));

const OK = { ok: true, data: {} };
const REFUSED = { ok: false, error: { code: "forbidden", message: "Not allowed." } };

function finding(id: string, over: Partial<ReviewFinding> = {}): ReviewFinding {
  return { id, approval_status: "pending", confirmed_by: null, engineer_comment: null, ...over } as ReviewFinding;
}

function row(key: string, findings: ReviewFinding[]): CrsRow {
  return { key, findings, commentNo: 1 } as CrsRow;
}

beforeEach(() => {
  for (const fn of [update, decideCrsFinding]) {
    fn.mockReset();
    fn.mockResolvedValue(OK);
  }
});

describe("#1124 follow-up: a grouped row that fails half-way", () => {
  it("says how many of its findings reached the record", async () => {
    decideCrsFinding.mockResolvedValueOnce(OK).mockResolvedValueOnce(REFUSED);
    const r = row("r1", [finding("a"), finding("b"), finding("c")]);

    const out = await saveCrsDecisions("run-1", [r], { r1: { kind: "keep" } }, ["r1"]);

    expect(out.saved).toEqual([]);
    expect(out.failed).toEqual([{
      key: "r1", message: "Comment 1: saved 1 of 3; Not allowed.",
      words: "Comment 1 was not saved. Try again in a moment.", detail: "saved 1 of 3; Not allowed.",
    }]);
    expect(out.wrote).toBe(true);
  });

  it("a row refused at its first finding wrote nothing and says only why", async () => {
    decideCrsFinding.mockResolvedValue(REFUSED);
    const out = await saveCrsDecisions("run-1", [row("r1", [finding("a")])], { r1: { kind: "keep" } }, ["r1"]);
    expect(out.failed).toEqual([{
      key: "r1", message: "Comment 1: Not allowed.", words: "Comment 1 was not saved. Try again in a moment.", detail: "Not allowed.",
    }]);
    expect(out.wrote).toBe(false);
  });
});

describe("#1124 follow-up: a decision the record already holds is not sent again", () => {
  it("a Keep skips a finding that is already confirmed", async () => {
    const r = row("r1", [finding("a", { confirmed_by: "eng", approval_status: "accepted" }), finding("b")]);
    const out = await saveCrsDecisions("run-1", [r], { r1: { kind: "keep" } }, ["r1"]);
    expect(decideCrsFinding.mock.calls).toEqual([["run-1", "b", "accept", "", "kept_as_written", undefined]]);
    expect(out.saved).toEqual(["r1"]);
  });

  /** Order 214 fix 10. MUTATION PROOF: put back `reviewsApi.confirm` for a Keep
   *  and these fail - a kept comment must have a decision record with a reason. */
  it("a comment confirmed the old way (no decision record) is kept again, with its reason", async () => {
    const r = row("r1", [finding("a", { confirmed_by: "eng" })]);
    await saveCrsDecisions("run-1", [r], { r1: { kind: "keep" } }, ["r1"]);
    expect(decideCrsFinding.mock.calls).toEqual([["run-1", "a", "accept", "", "kept_as_written", undefined]]);
  });

  it("Keep all remaining sends one record per row, sharing the click's id", async () => {
    const rows = [row("r1", [finding("a")]), row("r2", [finding("b")])];
    await saveCrsDecisions("run-1", rows, { r1: { kind: "keep", clickId: "c-1" }, r2: { kind: "keep", clickId: "c-1" } }, ["r1", "r2"]);
    expect(decideCrsFinding.mock.calls).toEqual([
      ["run-1", "a", "accept", "", "kept_in_bulk", "c-1"],
      ["run-1", "b", "accept", "", "kept_in_bulk", "c-1"],
    ]);
  });

  it("an edit saves the wording, then the decision that names why it is kept", async () => {
    const edit = { kind: "edit" as const, observation: "", requiredAction: "State the set pressure." };
    await saveCrsDecisions("run-1", [row("r1", [finding("a")])], { r1: edit }, ["r1"]);
    expect(update.mock.calls).toEqual([["a", { engineer_comment: "State the set pressure." }]]);
    expect(decideCrsFinding.mock.calls).toEqual([["run-1", "a", "accept", "", "edited_by_engineer"]]);
  });

  it("a Remove skips a finding that is already rejected", async () => {
    const r = row("r1", [finding("a", { approval_status: "rejected" }), finding("b")]);
    await saveCrsDecisions("run-1", [r], { r1: { kind: "remove", reason: "Duplicate" } }, ["r1"]);
    expect(decideCrsFinding.mock.calls).toEqual([["run-1", "b", "reject", "", "duplicate"]]);
  });

  it("an edit skips a finding whose comment already reads the same", async () => {
    const r = row("r1", [finding("a", { engineer_comment: "State the set pressure." }), finding("b")]);
    const edit = { kind: "edit" as const, observation: "", requiredAction: " State the set pressure. " };
    await saveCrsDecisions("run-1", [r], { r1: edit }, ["r1"]);
    expect(update.mock.calls).toEqual([["b", { engineer_comment: "State the set pressure." }]]);
  });

  it("a row the record already holds whole saves with no call and writes nothing", async () => {
    const r = row("r1", [finding("a", { confirmed_by: "eng", approval_status: "accepted" })]);
    const out = await saveCrsDecisions("run-1", [r], { r1: { kind: "keep" } }, ["r1"]);
    expect(decideCrsFinding).not.toHaveBeenCalled();
    expect(out).toEqual({ saved: ["r1"], failed: [], missing: [], wrote: false });
  });
});

/** v2.1 round 2: a decision whose comment left the sheet is never skipped
 *  quietly (it would stay "not saved" for ever and hold Sign).
 *  MUTATION PROOF: put back `if (!row || !decision) continue` and this fails. */
describe("v2.1 round 2: a comment that is no longer on the sheet", () => {
  it("is reported as failed, in plain words, and listed as missing", async () => {
    const out = await saveCrsDecisions("run-1", [row("r1", [finding("a")])],
      { r1: { kind: "keep" }, gone: { kind: "keep" } }, ["r1", "gone"]);
    expect(out.saved).toEqual(["r1"]);
    expect(out.missing).toEqual(["gone"]);
    expect(out.failed).toHaveLength(1);
    expect(out.failed[0].key).toBe("gone");
    expect(out.failed[0].message).toContain("this comment is no longer on the sheet");
    expect(out.failed[0].words).toContain("this comment is no longer on the sheet");
  });

  it("a sign-in that ended says so in plain words, the server's words kept as detail", async () => {
    decideCrsFinding.mockResolvedValue({ ok: false, disconnected: false, error: { code: "unauthenticated", message: "Token expired (401)." } });
    const out = await saveCrsDecisions("run-1", [{ ...row("r1", [finding("a")]), commentNo: 3 } as CrsRow], { r1: { kind: "keep" } }, ["r1"]);
    expect(out.failed[0].words).toBe("Comment 3 was not saved. Your sign-in has ended. Sign in again to carry on.");
    expect(out.failed[0].detail).toBe("Token expired (401).");
  });
});
