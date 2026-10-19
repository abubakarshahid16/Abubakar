/**
 * The one shared way to issue the contractor's copy refuses, in plain words
 * and without asking the server, while the comment sheet's rules are not
 * met: something unsaved, a "Needs you" row unopened, or anything the issue
 * gate still wants (final code, unread page ticks, open items).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type IssueChecks, issueContractorCopy, issueWaitsFor } from "./issueContractorCopy";

const downloadCrs = vi.fn();
vi.mock("../downloadCrs", () => ({ downloadCrs: (...a: unknown[]) => downloadCrs(...a) }));

const CLEAR: IssueChecks = { unsaved: 0, unopenedNeedsYou: 0, signLeft: [] };

beforeEach(() => { downloadCrs.mockReset().mockResolvedValue(null); });

describe("issueContractorCopy", () => {
  it("waits for each rule, in plain words, and never asks the server meanwhile", async () => {
    const cases: Array<[Partial<IssueChecks>, string]> = [
      [{ unsaved: 2 }, "Save the 2 decisions on screen first."],
      [{ unopenedNeedsYou: 1 }, 'Open the 1 "Needs you" row first.'],
      [{ signLeft: ["record the final code"] }, "Before you sign: record the final code."],
      [{ signLeft: ["tick 2 unread pages"] }, "Before you sign: tick 2 unread pages."],
    ];
    for (const [over, words] of cases) {
      expect(issueWaitsFor({ ...CLEAR, ...over })).toBe(words);
      expect(await issueContractorCopy("run-1", { ...CLEAR, ...over })).toEqual({ ok: false, message: words });
    }
    expect(downloadCrs).not.toHaveBeenCalled();
  });

  it("with everything clear asks for the issue copy once, and passes on a refusal as the server said it", async () => {
    expect(issueWaitsFor(CLEAR)).toBeNull();
    expect(await issueContractorCopy("run-1", CLEAR)).toEqual({ ok: true });
    expect(downloadCrs).toHaveBeenCalledWith("run-1", "issue");
    downloadCrs.mockResolvedValue("Comments are still open on this run.");
    expect(await issueContractorCopy("run-1", CLEAR)).toEqual({ ok: false, message: "Comments are still open on this run." });
  });
});
