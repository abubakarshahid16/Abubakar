/** The query's ask as one readable list, and honest marks instead of gates (owner, 26 Nov 2026). Invented queries only. */
import { describe, expect, it } from "vitest";

import { LIST_FOUND, QUESTION_KEY_WORDS_MAX, draftAuthor, honestMarks, notInText, readableLines, readyLine, staleSources, startingText, withRequest } from "./technicalQueryQuestion";

const found = (n: number) => Array.from({ length: n }, (_, i) => ({ question: `Invented request ${i + 1}`, filename: "Invented form.pdf", page: 1 }));

describe("what the contractor is asking", () => {
  it("starts as a lead-in from the subject and the found requests, numbered, each with its file and page", () => {
    const text = startingText({ subject: "Fw: RE: Invented tie-in details", proposed_questions: found(3) });
    expect(text).toBe("About Invented tie-in details, the contractor asks for the following:\n1. Invented request 1\n2. Invented request 2\n3. Invented request 3");
    const lines = readableLines(text, found(3));
    expect(lines[0]).toMatchObject({ kind: "lead" });
    expect(lines[2]).toEqual({ kind: "item", n: 2, text: "Invented request 2", source: "Invented form.pdf, page 1" });
  });
  it("uses the email's own question as the lead-in when there is one, and the confirmed wording when confirmed", () => {
    expect(startingText({ extracted_question_main: "Please confirm the invented items below.", proposed_questions: found(1) })).toBe("Please confirm the invented items below.\n1. Invented request 1");
    expect(startingText({ confirmed_question: "Invented confirmed.", proposed_questions: found(2) })).toBe("Invented confirmed.");
  });
  it("with nothing found on the form, the form's own question section is the ask", () => {
    expect(startingText({ proposed_question: " The form's invented question. ", proposed_questions: [] })).toBe("The form's invented question.");
  });
  it("only the first LIST_FOUND go in; the rest are counted as possibly missed requests, and one can be added as the next number", () => {
    const all = found(LIST_FOUND + 2);
    const text = startingText({ subject: "Invented", proposed_questions: all });
    expect(notInText(text, all)).toHaveLength(2);
    expect(honestMarks({ proposed_questions: all, evidence: [{ evidence_state: "proposed", match_count: 3, match_terms: 4 }] }, text).question[0]).toMatch(/^2 more lines were found on the form/);
    expect(withRequest(text, "Invented request 7").split("\n").at(-1)).toBe(`${LIST_FOUND + 1}. Invented request 7`);
  });
});

describe("honest marks", () => {
  it("says when no source was found, when the sources are weak, and when a cited book is not held; never while still searching", () => {
    expect(honestMarks({ evidence: [] }, "").evidence).toEqual(["No source was found for this question yet: the answer has nothing to stand on."]);
    expect(honestMarks({ evidence: [], evidence_job: { state: "running" } }, "").evidence).toEqual([]);
    expect(honestMarks({ evidence: [{ evidence_state: "proposed", match_count: 1, match_terms: 5 }] }, "").evidence[0]).toMatch(/only weakly \(the best holds 1 of 5 key words\)/);
    expect(honestMarks({ evidence: [{ evidence_state: "proposed", match_count: 4, match_terms: 5 }] }, "").evidence).toEqual([]);
    const cited = honestMarks({ evidence: [{ evidence_state: "proposed", match_count: 4, match_terms: 5 }], evidence_coverage: { cited_first: ["Schedule F clause 1.1: not held among the contracts you may read", "Schedule B clause 2.1: found on page 3"] } }, "");
    expect(cited.evidence).toEqual(["The form cites schedule F clause 1.1: not held among the contracts you may read."]);
  });
  it("sources searched for a whole mail (more key words than any question holds) are said to be for the mail, not weak", () => {
    const stale = { evidence: [{ evidence_state: "proposed", match_count: 15, match_terms: QUESTION_KEY_WORDS_MAX + 190 }] };
    expect(staleSources(stale)).toBe(true);
    expect(honestMarks(stale, "").evidence).toEqual(["These sources were found for the whole text of the mail, not for the question: find them again for the question."]);
  });
  it("a form's own list marker is not shown as part of the request", () => {
    const f = [{ question: "- Invented line list", filename: "f.pdf", page: 2 }];
    expect(readableLines("Lead.\n1. - Invented line list", f)[1]).toEqual({ kind: "item", n: 1, text: "Invented line list", source: "f.pdf, page 2" });
  });
});

describe("where the sources and the draft stand (builder A's ready)", () => {
  const base = { evidence: "ready" as const, evidence_fresh: true, draft: "ready" as const, draft_fresh: true };
  it("says what is under way, what failed, and why no draft was written; nothing when all is ready", () => {
    expect(readyLine({ ...base, evidence: "refreshing" })).toBe("Finding the sources for this question; a draft follows.");
    expect(readyLine({ ...base, draft: "refreshing" })).toBe("Writing a draft from the sources found.");
    expect(readyLine({ ...base, draft: "not_written", draft_note: "no passage found in the contract documents you may read" })).toBe("No draft was written: no passage found in the contract documents you may read.");
    expect(readyLine({ ...base, draft_fresh: false })).toBe("The draft answers an earlier wording of the question.");
    expect(readyLine(base)).toBeNull();
    expect(readyLine(null)).toBeNull();
  });
  it("says who wrote the draft and whether it used paid credit", () => {
    expect(draftAuthor({ system: true, model: "invented-small:9b" })).toBe("Written by invented-small:9b, the AI on this computer, from the sources found (no credit needed).");
    expect(draftAuthor({ system: true, model: null })).toBe("Written by the AI on this computer from the sources found (no credit needed).");
    expect(draftAuthor({ system: true, model: "claude-invented" })).toBe("Written by Claude from the sources found (uses paid credit).");
    expect(draftAuthor({ system: false, model: null })).toBe("Written by an engineer.");
    expect(draftAuthor({ model: "x" })).toBeNull(); // an older draft with no origin recorded: nothing claimed
  });
  it("the engineer's saved wording comes before the proposal", () => {
    expect(startingText({ edited_question: "Invented edit.", proposed_questions: [{ question: "Invented request", filename: "f.pdf", page: 1 }] })).toBe("Invented edit.");
  });
});
