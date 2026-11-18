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
});
