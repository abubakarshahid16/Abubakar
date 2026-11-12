import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FoundDuringReview } from "./FoundDuringReview";

describe("FoundDuringReview", () => {
  it("says how many rule books were found during the review, were not sent, and that a second review includes them", () => {
    render(<FoundDuringReview count={2} />);
    expect(screen.getByTestId("found-during-review")).toHaveTextContent(
      "2 more rule book(s) apply to this paper. They were not sent because they were not on the list you saw. Review again to include them.",
    );
  });

  it("shows nothing for none, and for a number that is not a count", () => {
    const { container, rerender } = render(<FoundDuringReview count={0} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<FoundDuringReview count={Number.NaN} />);
    expect(container).toBeEmptyDOMElement();
  });
});
