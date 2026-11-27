/** The query's ask as one readable list, and honest marks instead of gates (owner, 26 Nov 2026). Invented queries only. */
import { describe, expect, it } from "vitest";

import { pageHeaderSplit, problemChips, staleSources as staleOf } from "./technicalQueryQuestion";
import { LIST_FOUND, QUESTION_KEY_WORDS_MAX, boldSplit, plainMark, citedSplit, plainStatus, queryHeadline, querySteps, sharedSource, draftAuthor, honestMarks, notInText, readableLines, readyLine, staleSources, startingText, withRequest } from "./technicalQueryQuestion";

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
    expect(honestMarks({ evidence: [] }, "").evidence).toEqual(["No source found for this question yet. The reply has nothing to rest on."]);
    expect(honestMarks({ evidence: [], evidence_job: { state: "running" } }, "").evidence).toEqual([]);
    expect(honestMarks({ evidence: [{ evidence_state: "proposed", match_count: 1, match_terms: 5 }] }, "").evidence[0]).toBe("Weak match: the sources share few words with the question. Read them before you rely on the reply."); // plain words (owner, 27 Nov 2026)
    expect(honestMarks({ evidence: [{ evidence_state: "proposed", match_count: 4, match_terms: 5 }] }, "").evidence).toEqual([]);
    const cited = honestMarks({ evidence: [{ evidence_state: "proposed", match_count: 4, match_terms: 5 }], evidence_coverage: { cited_first: ["Schedule F clause 1.1: not held among the contracts you may read", "Schedule B clause 2.1: found on page 3"] } }, "");
    expect(cited.evidence).toEqual(["The form cites schedule F clause 1.1: not held among the contracts you may read."]);
  });
  it("sources searched for a whole mail (more key words than any question holds) are said to be for the mail, not weak", () => {
    const stale = { evidence: [{ evidence_state: "proposed", match_count: 15, match_terms: QUESTION_KEY_WORDS_MAX + 190 }] };
    expect(staleSources(stale)).toBe(true);
    expect(honestMarks(stale, "").evidence).toEqual(["These sources were found for the whole email, not for this question. Press Find the sources again."]);
  });
  it("a form's own list marker is not shown as part of the request", () => {
    const f = [{ question: "- Invented line list", filename: "f.pdf", page: 2 }];
    expect(readableLines("Lead.\n1. - Invented line list", f)[1]).toEqual({ kind: "item", n: 1, text: "Invented line list", source: "f.pdf, page 2" });
  });
});

describe("where the sources and the draft stand (builder A's ready)", () => {
  const base = { evidence: "ready" as const, evidence_fresh: true, draft: "ready" as const, draft_fresh: true };
  it("says what is under way, what failed, and why no draft was written; nothing when all is ready", () => {
    expect(readyLine({ ...base, evidence: "refreshing" })).toBe("Finding the sources for this question. The reply follows.");
    expect(readyLine({ ...base, draft: "refreshing" })).toBe("Writing the reply from the sources found.");
    expect(readyLine({ ...base, draft: "not_written", draft_note: "no passage found in the contract documents you may read" })).toBe("No reply was written: no passage found in the contract documents you may read.");
    expect(readyLine({ ...base, draft_fresh: false })).toBe("The reply answers an earlier wording of the question.");
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

describe("the server's composed ask (builder A: the one home)", () => {
  it("is shown exactly, whatever the page's own rule would compose", () => {
    const text = "About Invented, the contractor asks for the following:\n1. a\n2. b\n3. c\n4. d\n5. e\n6. f\n7. g\n8. h";
    expect(startingText({ ready: { question: text }, proposed_questions: [{ question: "zzz", filename: null, page: null }] })).toBe(text);
  });
});

describe("only the current wording's sources count", () => {
  it("sources found for an earlier wording never make the 'whole mail' or 'weak' marks", () => {
    const q = { evidence: [
      { evidence_state: "proposed", match_count: 4, match_terms: 5, for_current_question: true },
      { evidence_state: "proposed", match_count: 9, match_terms: QUESTION_KEY_WORDS_MAX + 100, for_current_question: false },
    ] };
    expect(staleSources(q)).toBe(false);
    expect(honestMarks(q, "").evidence).toEqual([]);
  });
});

describe("keep the cited, reject the others", () => {
  it("touches only the current wording's undecided sources: never an earlier wording's, never a flagged or decided one", () => {
    const rows = [
      { id: "c1", evidence_state: "proposed", supersession_state: "current", for_current_question: true },
      { id: "o1", evidence_state: "proposed", supersession_state: "current", for_current_question: true },
      { id: "old", evidence_state: "proposed", supersession_state: "current", for_current_question: false },
      { id: "flag", evidence_state: "needs_review", supersession_state: "current", for_current_question: true },
      { id: "done", evidence_state: "rejected", supersession_state: "current", for_current_question: true },
    ];
    const split = citedSplit(rows, JSON.stringify([{ evidence_id: "c1" }, { evidence_id: "flag" }]));
    expect(split.keep.map((e) => e.id)).toEqual(["c1"]);
    expect(split.reject.map((e) => e.id)).toEqual(["o1"]);
    expect(citedSplit(rows, "not json").keep).toEqual([]); // unreadable citations: nothing is kept by guess
  });
});

describe("read in ten seconds (owner, 26 Nov 2026 22:41)", () => {
  it("one sentence: who asks, how many items, about what", () => {
    const ask = "About X, the contractor asks for the following:\n1. a\n2. b\n3. c";
    expect(queryHeadline({ subject: "Fw: Invented tie-in details-Clarification" }, ask)).toBe("The contractor asks for 3 items about Invented tie-in details.");
    expect(queryHeadline({ contractor_name: "Invented Builders", title_short: "Invented valve" }, "What is the rating?")).toBe("Invented Builders asks one question about Invented valve.");
  });
  it("the status in everyday words; a priority only when it is not normal", () => {
    expect(plainStatus("drafting", "normal")).toBe("In progress");
    expect(plainStatus("awaiting_review", "high")).toBe("Waiting for your approval · high priority");
  });
  it("four steps, each with its own state", () => {
    const cited = JSON.stringify([{ label: "S1", evidence_id: "e1" }]);
    const steps = querySteps({ status: "awaiting_review", drafts: [{ citations_json: cited }], evidence: [{ for_current_question: true }], ready: { evidence: "ready", draft: "ready" } }, "x");
    expect(steps.map((s) => `${s.label}:${s.state}`)).toEqual(["Question found:done", "Sources found:done", "Reply written:done", "Approved:todo"]);
    // a reply that cites no source is never a plain tick (F's walk, 27 Nov 2026)
    expect(querySteps({ status: "awaiting_review", drafts: [{ citations_json: "[]" }], ready: { evidence: "ready", draft: "ready" } }, "x")[2])
      .toEqual({ label: "Reply written: uses no source yet", state: "warn" });
    expect(querySteps({ status: "drafting", ready: { evidence: "refreshing", draft: "none" } }, "x")[1].state).toBe("working");
  });
  it("the source is said once when every request shares it", () => {
    const one = [{ kind: "item" as const, n: 1, text: "a", source: "f.pdf, page 1" }, { kind: "item" as const, n: 2, text: "b", source: "f.pdf, page 1" }];
    expect(sharedSource(one)).toBe("f.pdf, page 1");
    expect(sharedSource([one[0], { ...one[1], source: "g.pdf, page 2" }])).toBeNull();
  });
  it("the asked phrase in bold: up to a colon, a near comma, or seven words", () => {
    expect(boldSplit("Matching line list: for the invented system")).toEqual(["Matching line list:", " for the invented system"]);
    expect(boldSplit("Piping class information for metallurgy details")).toEqual(["Piping class information for metallurgy details", ""]);
    expect(boldSplit("In order to implement the invented design note the contractor requires detailed information on the tie-in")[0]).toBe("In order to implement the invented design");
  });
});

describe("the server's marks in everyday words", () => {
  it("says 'the AI on this computer' and 'sources'", () => {
    expect(plainMark("The AI wrote this reply from the sources it found. Nobody has kept them yet.")).toBe("The AI wrote this reply from the sources it found. Nobody has kept them yet.");
  });

  it("keeps a request that wraps onto the next line in its item, never as a line above the list (the owner's regression query, 27 Nov 2026)", () => {
    const text = "Please confirm the following invented points:\n\n1. first invented point\n2. second invented point\n3. as-built invented drawings before Mechanical\nCompletion?\n\nRegards";
    const lines = readableLines(text, []);
    expect(lines.filter((l) => l.kind === "lead").map((l) => l.text)).toEqual(["Please confirm the following invented points:", "Regards"]);
    expect(lines.find((l) => l.n === 3)?.text).toBe("as-built invented drawings before Mechanical Completion?");
  });
});

describe("a question cut for its length (builder H's table, 5)", () => {
  it("shows the old cut mark as the plain sentence the server now writes", () => {
    // the word before an old mark was cut mid-word ("pu"): it goes with the mark; a word that ended a sentence stays
    const lines = readableLines("The contractor asks about the invented pu [cut here: the rest of the section is in the attachment text]", []);
    expect(lines.map((l) => l.text)).toEqual(["The contractor asks about the invented\u2026 The rest of the question is in the email files."]);
    expect(readableLines("It is the invented pump. [cut here: the rest of the section is in the attachment text]", [])[0].text)
      .toBe("It is the invented pump.\u2026 The rest of the question is in the email files.");
  });
});

describe("A's own walk of the Queries page (27 Nov 2026)", () => {
  it("never says 'No query number' under a number the subject shows", () => {
    const shown = problemChips({ needs_person: 1, ref_type: null, contractor_name: "X", subject: "CFC-00012 - Invented pump clarification" });
    expect(shown.map((c) => c.words)).toEqual(["Query number not confirmed"]);
    expect(shown[0].why).toBe("The subject has a number, but not a full TQ or CFC number. Check which query this is.");
    expect(problemChips({ needs_person: 1, ref_type: null, contractor_name: "X", subject: "Invented pump clarification" }).map((c) => c.words))
      .toEqual(["No query number"]);
  });

  it("shows a source's page header apart, keeping every word in order", () => {
    const text = "ABC-123 SCHEDULE X - INVENTED SPECIFICATION Page 7 of 84 Rev 06 CONTRACTOR shall keep the invented record.";
    const split = pageHeaderSplit(text)!;
    expect(split).toEqual({ header: "ABC-123 SCHEDULE X - INVENTED SPECIFICATION Page 7 of 84 Rev 06", body: "CONTRACTOR shall keep the invented record." });
    expect(`${split.header} ${split.body}`).toBe(text);
    expect(pageHeaderSplit("CONTRACTOR shall keep the invented record.")).toBeNull();
    expect(pageHeaderSplit(`${"word ".repeat(30)}Page 2 of 9 the rest`)).toBeNull(); // a long lead is not a header
  });
});

describe("sources found for a longer text than the question (lead-5's 1f, 27 Nov 2026)", () => {
  const source = (terms: number) => ({ for_current_question: true, match_terms: terms, match_count: 10 });
  it("never says 'found for the whole email' when the question itself holds that many key words", () => {
    // measured on a copy of live: all 7 such banners were false, the composed question held more than 60 key words itself
    expect(staleOf({ evidence: [source(80)], ready: { question_terms: 80 } } as never)).toBe(false);
    expect(staleOf({ evidence: [source(300)], ready: { question_terms: 80 } } as never)).toBe(true); // a whole mail's words
    expect(staleOf({ evidence: [source(80)] } as never)).toBe(true); // an older server: the fixed bound, as before
  });
});
