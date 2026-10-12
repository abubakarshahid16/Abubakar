/**
 * #508: a finding's cited page, boxed by the server or said to be unboxed.
 * The URL is the finding's evidence route (the text never travels in it).
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthedImage } from "../useAuthedImage";
import { EvidencePageImage } from "./EvidencePageImage";

const imageFor = vi.fn<(url: string | null) => AuthedImage>();

vi.mock("../useAuthedImage", () => ({
  useAuthedImage: (url: string | null) => imageFor(url),
}));
vi.mock("../../api/client", () => ({
  reviews: {
    evidenceImageUrl: (id: string, side: string) => `/api/reviews/findings/${id}/evidence-image?side=${side}`,
  },
}));

const ready = (answerLocated: boolean | null): AuthedImage =>
  ({ src: "blob:page", loading: false, failed: false, answerLocated });

beforeEach(() => imageFor.mockReset());

describe("EvidencePageImage", () => {
  it("asks the finding's evidence route for its side, not a URL carrying text", () => {
    imageFor.mockReturnValue(ready(true));
    render(<EvidencePageImage findingId="f-1" side="standard" page={12} />);
    expect(imageFor).toHaveBeenCalledWith("/api/reviews/findings/f-1/evidence-image?side=standard");
  });

  it("says the text is boxed only when the server drew the box", () => {
    imageFor.mockReturnValue(ready(true));
    render(<EvidencePageImage findingId="f-1" side="standard" page={12} />);
    expect(screen.getByTestId("evidence-located")).toHaveTextContent("The cited text is boxed on the page.");
    expect(screen.getByRole("img", { name: "Standard page 12" })).toHaveAttribute("src", "blob:page");
  });

  it("#785: a label box is named as the label, never as the value", () => {
    imageFor.mockReturnValue(ready(true));
    render(<EvidencePageImage findingId="f-1" side="submittal" page={2} box="label" />);
    expect(screen.getByTestId("evidence-located"))
      .toHaveTextContent("The field's label is boxed; the value read sits beside it.");
  });

  it("#785 point 3: a no-value row's label box says no value was found and where to look", () => {
    imageFor.mockReturnValue(ready(true));
    render(<EvidencePageImage findingId="f-1" side="submittal" page={2} box="where_to_look" />);
    expect(screen.getByTestId("evidence-located")).toHaveTextContent(
      "No value was found. The field's label is boxed - the only place the datasheet prints it; look beside it.");
  });

  it("#785: the value's stored position and a checklist clause say what they box", () => {
    imageFor.mockReturnValue(ready(true));
    const { rerender } = render(<EvidencePageImage findingId="f-1" side="submittal" page={2} box="value_position" />);
    expect(screen.getByTestId("evidence-located")).toHaveTextContent("The value read is boxed where the reader found it.");
    rerender(<EvidencePageImage findingId="f-1" side="standard" page={7} box="clause_text" />);
    expect(screen.getByTestId("evidence-located")).toHaveTextContent("The cited clause is boxed on the page.");
  });

  it("an unboxed page says no box was drawn instead of implying the evidence is shown", () => {
    imageFor.mockReturnValue(ready(false));
    render(<EvidencePageImage findingId="f-1" side="submittal" page={2} />);
    expect(screen.getByTestId("evidence-located")).toHaveTextContent("could not be placed on this page, so no box is drawn");
  });

  it("a page that cannot be loaded is said, not a broken image", () => {
    imageFor.mockReturnValue({ src: null, loading: false, failed: true, answerLocated: null });
    render(<EvidencePageImage findingId="f-1" side="submittal" page={2} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Page 2 could not be loaded from this screen.");
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("says loading while the page loads", () => {
    imageFor.mockReturnValue({ src: null, loading: true, failed: false, answerLocated: null });
    render(<EvidencePageImage findingId="f-1" side="submittal" page={2} />);
    expect(screen.getByText("Loading page 2…")).toBeInTheDocument();
  });

  it("#508: a scanned page's OCR box says it is the OCR's reading", () => {
    imageFor.mockReturnValue(ready(true));
    render(<EvidencePageImage findingId="f-1" side="standard" page={4} box="ocr_line" />);
    expect(screen.getByTestId("evidence-located")).toHaveTextContent(
      "A scanned page: the line holding the cited text is boxed, as the OCR read it - check the words on the page.");
  });

  it("#508: an unboxed scanned page says why, in the server's words", () => {
    imageFor.mockReturnValue(ready(false));
    render(<EvidencePageImage findingId="f-1" side="standard" page={4}
      reason="page 4 is a scanned image with no text layer and could not be read here (recognition took too long), so no box is drawn - read the page itself" />);
    expect(screen.getByTestId("evidence-located")).toHaveTextContent(
      "Page 4 is a scanned image with no text layer and could not be read here (recognition took too long), so no box is drawn - read the page itself.");
  });
});
