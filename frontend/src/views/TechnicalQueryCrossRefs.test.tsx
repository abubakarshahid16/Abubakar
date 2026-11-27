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
    expect(lines[0]).toHaveTextContent("TQ-0007 is in this app: Invented subject (waiting for your approval). Read it before you reply: open it.");
    fireEvent.click(screen.getByRole("button", { name: "open it" }));
    expect(onOpen).toHaveBeenCalledWith("q7");
    expect(lines[1]).toHaveTextContent("CFC-0008 is in this app, but you cannot open it");
    expect(lines[1].querySelector("button")).toBeNull();
    expect(lines[2]).toHaveTextContent("TQ-0009 is not in this app.");
  });

  it("draws nothing when the request names no other query", () => {
    const { container } = render(<TechnicalQueryCrossRefs refs={[]} onOpen={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("recognises the server's own mark for these references, so it is not shown twice", () => {
    expect(REFS_MARK.test("The question names TQ-0007. Read it in this app before you reply.")).toBe(true);
    expect(REFS_MARK.test("The reply does not answer question 1. Check it by hand.")).toBe(false);
  });
});
