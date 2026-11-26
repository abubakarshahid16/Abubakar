/**
 * Chat with several selected papers (planner 25 Nov 2026 23:35, note A): "review these" offers the real Review for each selected
 * paper, on the Reviews page, never a chat summary in its place. Invented titles only.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReviewOffer } from "./AssistantAnswer";

describe("ReviewOffer", () => {
  it("names every offered paper and links to the Reviews page", () => {
    render(<ReviewOffer offer={[
      { document_id: "d1", title: "INV-PAPER-1.pdf", status: "ready" },
      { document_id: "d2", title: "INV-PAPER-2.pdf", status: "ready" },
    ]} />);
    const offer = screen.getByTestId("chat-review-offer");
    expect(offer).toHaveTextContent("INV-PAPER-1.pdf");
    expect(offer).toHaveTextContent("INV-PAPER-2.pdf");
    expect(screen.getByRole("link", { name: "Open Reviews" })).toHaveAttribute("href", "/review");
  });

  it("draws nothing when nothing is offered", () => {
    const { container } = render(<ReviewOffer offer={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
