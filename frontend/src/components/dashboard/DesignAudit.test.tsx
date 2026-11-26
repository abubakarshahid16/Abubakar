/** The owner's design audit of the Dashboard (26 Nov 2026 23:05): which AI answers by name (J), plain warning words (J), and At a
 *  glance as three large tiles (K). Invented numbers and model names. */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { answersLine } from "../../views/DashboardViewContent";
import { GlanceTiles, type GlanceRow } from "./AtAGlance";
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
    render(<GlanceTiles rows={[
      row({ label: "Document reviews", waiting: 5, done: 1, lateStatus: "not_tracked", lateNote: "a review has no due date" }),
      row({}),
      row({ label: "Deliverables", waiting: 2, done: 1, late: 1, lateStatus: "counted", lateNote: "of 2 open with a due date" }),
    ]} />);
    const tiles = screen.getAllByTestId("glance-tile");
    expect(tiles.map((t) => t.textContent)).toEqual([
      "Reviews5waitingno due dates1 done",
      "Queries and CFCs33waitinglate: not counted0 done",
      "Deliverables2waiting1 late1 done",
    ]);
    expect(within(tiles[2]).getByTestId("glance-late").className).toContain("text-danger-500");
    expect(within(tiles[1]).getByTestId("glance-late").className).not.toContain("text-danger-500");
  });
});
