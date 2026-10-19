/**
 * Release 1b: the once-said lines under the sheet, including the one that
 * says the grouping shown is from the last time it could be read.
 *
 * MUTATION PROOF: drop the `stale` line and "says once" fails; show it when
 * `stale` is false and "nothing" fails.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { STALE_GROUPING_NOTE } from "./crsRows";
import { SheetGroupingNote } from "./SheetGroupingNote";

describe("SheetGroupingNote", () => {
  it("says, once and in plain words, that the grouping is the last one that could be read", () => {
    render(<SheetGroupingNote rows={[]} notes={0} stale />);
    expect(screen.getAllByText(STALE_GROUPING_NOTE)).toHaveLength(1);
    expect(STALE_GROUPING_NOTE).toBe(
      "The sheet's grouping could not be refreshed; rows are shown as of the last time it could be read.",
    );
  });

  it("says nothing when the grouping is current and there is nothing to note", () => {
    const { container } = render(<SheetGroupingNote rows={[]} notes={0} />);
    expect(container).toBeEmptyDOMElement();
  });
});
