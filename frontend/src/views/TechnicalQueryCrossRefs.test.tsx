/** The other queries a request names (builder A, 27 Nov 2026). Invented numbers. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { REFS_MARK, TechnicalQueryCrossRefs } from "./TechnicalQueryCrossRefs";

const refs = [
  { reference: "TQ-0007", held: true, query_id: "q7", status: "awaiting_review", subject: "Invented subject" },
  { reference: "CFC-0008", held: true, query_id: null, status: null, subject: null },
  { reference: "TQ-0009", held: false, query_id: null, status: null, subject: null },
];

describe("the other queries a request names", () => {
  it("opens one the caller may read, never names the subject of one they may not, and says when one is not held", () => {
    const onOpen = vi.fn();
    render(<TechnicalQueryCrossRefs refs={refs} onOpen={onOpen} />);
    const lines = screen.getAllByTestId("cross-ref");
    expect(lines).toHaveLength(3);
    expect(lines[0]).toHaveTextContent("TQ-0007 is held here: Invented subject (in progress: waiting for your approval). Read it before replying: open it.");
    fireEvent.click(screen.getByRole("button", { name: "open it" }));
    expect(onOpen).toHaveBeenCalledWith("q7");
    expect(lines[1]).toHaveTextContent("CFC-0008 is held here, but you may not open it");
    expect(lines[1].querySelector("button")).toBeNull();
    expect(lines[2]).toHaveTextContent("TQ-0009 is not held in this system.");
  });

  it("draws nothing when the request names no other query", () => {
    const { container } = render(<TechnicalQueryCrossRefs refs={[]} onOpen={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("recognises the server's own mark for these references, so it is not shown twice", () => {
    expect(REFS_MARK.test("The request names TQ-0007, held in this system: see it before replying.")).toBe(true);
    expect(REFS_MARK.test("The draft does not answer request item 1; check it by hand.")).toBe(false);
  });
});
