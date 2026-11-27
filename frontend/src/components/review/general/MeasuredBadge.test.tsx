import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { type GeneralMeasured, MeasuredBadge } from "./MeasuredBadge";

const BELOW: GeneralMeasured = {
  kind_label: "datasheet", found: 5.7, target: 7, verdict: "below target",
  sentence: "Measured on planted test copies of this kind: 5.7 of 10 mistakes found (target 7): below target.",
};

describe("MeasuredBadge", () => {
  it("shows the server's sentence and marks 'below target' visibly", () => {
    render(<MeasuredBadge measured={BELOW} />);
    expect(screen.getByTestId("general-measured-sentence")).toHaveTextContent(BELOW.sentence);
    expect(screen.getByTestId("general-measured-below")).toHaveTextContent("Below target");
    expect(screen.getByTestId("general-measured")).toHaveAttribute("data-verdict", "below target");
  });

  it("does not mark a kind at or above target as below", () => {
    render(<MeasuredBadge measured={{ ...BELOW, found: 7.7, verdict: "at or above target",
      sentence: "Measured on planted test copies of this kind: 7.7 of 10 mistakes found (target 7): at or above target." }} />);
    expect(screen.queryByTestId("general-measured-below")).toBeNull();
    expect(screen.getByTestId("general-measured-sentence")).toHaveTextContent("7.7 of 10");
  });

  it("says a kind is not measured and shows no score", () => {
    render(<MeasuredBadge measured={{ kind_label: "study", found: null, target: 7, verdict: "not measured",
      sentence: "This kind has not been measured on test copies yet." }} />);
    expect(screen.getByTestId("general-measured-sentence")).toHaveTextContent("has not been measured");
    expect(screen.queryByTestId("general-measured-below")).toBeNull();
    expect(screen.getByTestId("general-measured").textContent).not.toMatch(/of 10/);
  });

  it("renders nothing for a null or empty measured", () => {
    const { container, rerender } = render(<MeasuredBadge measured={null} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<MeasuredBadge measured={undefined} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<MeasuredBadge measured={{ ...BELOW, sentence: "" }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says one wrong comment in the singular, in plain words (H's audit 57)", () => {
    const wrong = "A strict reader judged 1 of 49 comments wrong.";
    render(<MeasuredBadge measured={{ ...BELOW, found: 8, sentence: `Measured on 1 planted test copy. ${wrong}`,
      false_alarm: { wrong: 1, of: 49, percent: 2, target_percent: 10, within_target: true, sentence: wrong } }} />);
    expect(screen.getByTestId("general-measured-plain").textContent).toBe("Checked on 1 practice copy with known mistakes: this kind of paper found 8 of 10 (target 7); 1 of its 49 comments was wrong (limit 10%).");
    expect(screen.getByTestId("general-measured-plain").textContent).not.toMatch(/planted|test cop/);
  });
  it("draws the wrong-comment share exactly as the server worded it, with its N of M", () => {
    const wrong = "A strict reader judged 23 of 124 comments wrong across those test copies (19%; target 10% or less).";
    render(<MeasuredBadge measured={{ ...BELOW, sentence: `${BELOW.sentence} ${wrong}`,
      false_alarm: { wrong: 23, of: 124, percent: 19, target_percent: 10, within_target: false, sentence: wrong } }} />);
    expect(screen.getByTestId("general-measured-sentence")).toHaveTextContent("23 of 124 comments wrong across those test copies (19%; target 10% or less)");
  });
  it("says the score in plain words first, the full sentence with its version one click away (H's audit, 27 Nov 2026)", () => {
    render(<MeasuredBadge measured={{ ...BELOW, found: 5.79, sentence: "Measured on 1 planted test copy (measured 18 Nov 2026, version 0000abcd). Update 9 round cut short." }} />);
    // the sample says its size (F's gate, 27 Nov 2026): "Measured on 1 planted test copy" -> "On 1 test copy"
    expect(screen.getByTestId("general-measured-plain").textContent).toBe("Checked on 1 practice copy with known mistakes: this kind of paper found 5.7 of 10 (target 7).");
    expect(screen.getByTestId("general-measured-plain").textContent).not.toMatch(/version|round|strict reader/);
    expect(screen.getByText("How this was measured")).toBeTruthy();
    expect(screen.getByTestId("general-measured-sentence").textContent).toContain("version 0000abcd");
  });
});
