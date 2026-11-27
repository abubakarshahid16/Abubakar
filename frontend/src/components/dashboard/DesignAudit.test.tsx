/** The owner's design audit of the Dashboard (26 Nov 2026 23:05): which AI answers by name (J), plain warning words (J), and At a
 *  glance as three large tiles (K). Invented numbers and model names. */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { answersLine } from "../../views/DashboardViewContent";
import { type GlanceRow } from "./AtAGlance";
import { GlanceTiles } from "./GlanceTiles";
import { plainWarning, plainWarningFor } from "./MetricWarning";

const row = (over: Partial<GlanceRow>): GlanceRow => ({
  label: "Technical queries and CFCs", inCount: 33, waiting: 33, late: null, done: 0, lateStatus: "no_due_dates",
  lateNote: "no open query has a due date", ...over,
});

describe("the Dashboard after the design audit", () => {
  it("names the AI that answers, and says when it is not running", () => {
    expect(answersLine({ answer_model: "invented:9b", answer_model_reachable: true })).toBe("Answers: the AI on this computer (invented:9b).");
    expect(answersLine({ answer_model: "invented:9b", answer_model_reachable: false })).toBe(
      "Answers: the AI on this computer (invented:9b), not running right now.");
    expect(answersLine({ answer_model: "", answer_model_reachable: false })).toBe("Answers: no AI is set up on this computer.");
  });

  it("says the AI steps' model warning in everyday words", () => {
    expect(plainWarning("The AI review steps: tiny:2b is not installed on the engine. They run on invented:9b instead.")).toBe(
      "Some review steps: tiny:2b is not on this computer. They run on invented:9b instead.");
    expect(plainWarning("A document has no readable text.")).toBe("A document has no readable text.");
  });

  it("draws one large tile per kind: the waiting number big, late red only when counted and above 0, done, and never a fake 0", () => {
    // the tiles are the shared kit's since 27 Nov 2026 03:34 (owner: the three tiles); the same promises, on the kit's tiles
    render(<GlanceTiles onOpen={() => undefined} rows={[
      row({ label: "Document reviews", waiting: 5, done: 1, lateStatus: "not_tracked", lateNote: "a review has no due date" }),
      row({}),
      row({ label: "Deliverables", waiting: 2, done: 1, late: 1, lateStatus: "counted", lateNote: "of 2 open with a due date" }),
    ]} />);
    const tiles = within(screen.getByRole("group", { name: "Waiting for a decision" })).getAllByRole("button");
    expect(tiles.map((t) => t.textContent)).toEqual([ // real spaces between the parts: read aloud or copied, never run together
      "Document reviews 5 waiting for you 1 done no due dates set",
      "Queries and CFCs 33 waiting for you 0 done no due dates set",
      "Deliverables 2 waiting for you 1 done 1 late",
    ]);
    expect(tiles[2].querySelector(".kit-late")?.textContent).toBe("1 late");
    expect(tiles[1].querySelector(".kit-late")).toBeNull();
  });

  it("says the system's warnings in everyday words on the main screen, model names only in the fold (owner's picture, 27 Nov 2026)", () => {
    expect(plainWarningFor({ code: "needs_ocr", message: "3 scanned page(s) have not been read yet. Recognition has not run on them, so they are not searchable until it does." }))
      .toBe("3 scanned pages have not been read yet, so they cannot be searched yet.");
    expect(plainWarningFor({ code: "pages_recognised", message: "1 scanned page(s) were read by OCR and are searchable. Recognised text is labelled." }))
      .toBe("1 scanned page was read as a picture and can be searched. Text read this way is marked as such wherever it is quoted.");
    expect(plainWarningFor({ code: "equation_pages", message: "12 page(s) are equation-heavy; the mathematics did not survive text extraction. The rendered page image is the mitigation." }))
      .toBe("12 pages are mostly equations, which do not come through as text. Open the page picture to read them.");
    const ai = plainWarningFor({ code: "ai_steps_model", message: "The AI review steps: tiny:2b is not installed on the engine. They run on invented:9b instead." });
    expect(ai).toBe("Some review steps run on a different AI model on this computer than the one that was set. Which one is under Technical detail.");
    expect(ai).not.toMatch(/tiny|invented|:\d+b/);
    // a shape the words were not written for keeps its own meaning (an older "OCR is not implemented" is not "not read yet")
    expect(plainWarningFor({ code: "needs_ocr", message: "23 page(s) have no extractable text. OCR is detected but NOT implemented." }))
      .toBe("23 page(s) have no extractable text. OCR is detected but NOT implemented.");
    // an unknown shape keeps the server's words through plainWarning
    expect(plainWarningFor({ code: "something_new", message: "Invented sentence." })).toBe("Invented sentence.");
  });
});
