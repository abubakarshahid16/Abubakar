/** The owner's design audit of the Dashboard (26 Nov 2026 23:05): which AI answers by name (J), plain warning words (J), and At a
 *  glance as three large tiles (K). Invented numbers and model names. */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { answersLine } from "../../views/DashboardViewContent";
import { type GlanceRow } from "./AtAGlance";
import { GlanceTiles } from "./GlanceTiles";
import { plainWarning } from "./MetricWarning";

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
});
