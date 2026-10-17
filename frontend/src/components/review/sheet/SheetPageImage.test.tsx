/**
 * #967 item 5: the Sheet's page image carries every card's mark, drawn by
 * the server; the sentence over it states the count with its denominator.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthedImage } from "../../useAuthedImage";
import { marksSentence } from "./sheetCards";
import { SheetPageImage } from "./SheetPageImage";

const imageFor = vi.fn<(url: string | null) => AuthedImage>();

vi.mock("../../useAuthedImage", () => ({
  useAuthedImage: (url: string | null) => imageFor(url),
}));
vi.mock("../../../api/client", () => ({
  reviews: {
    sheetPageImageUrl: (runId: string, page: number, marks: { findingId: string; state: string }[]) =>
      `/api/reviews/runs/${runId}/page-image?page=${page}&marks=${encodeURIComponent(marks.map((m) => `${m.findingId}:${m.state}`).join(","))}`,
  },
}));

const ready = (marksLocated: number | null, marksTotal: number | null): AuthedImage =>
  ({ src: "blob:page", loading: false, failed: false, answerLocated: null, marksLocated, marksTotal });

beforeEach(() => imageFor.mockReset());

describe("SheetPageImage", () => {
  it("asks the run's page route with every mark's id and state, nothing else in the URL", () => {
    imageFor.mockReturnValue(ready(2, 2));
    render(<SheetPageImage runId="run-1" page={3} marks={[{ findingId: "f-1", state: "open" }, { findingId: "f-2", state: "answered" }]} />);
    expect(imageFor).toHaveBeenCalledWith("/api/reviews/runs/run-1/page-image?page=3&marks=f-1%3Aopen%2Cf-2%3Aanswered");
    expect(screen.getByRole("img", { name: "Datasheet page 3, values with a card underlined" })).toHaveAttribute("src", "blob:page");
  });

  it("says how many values are underlined out of how many have a card", () => {
    imageFor.mockReturnValue(ready(3, 4));
    render(<SheetPageImage runId="run-1" page={1} marks={[]} />);
    expect(screen.getByTestId("sheet-marks")).toHaveTextContent(
      "3 of 4 values with a card are underlined on the page; 1 could not be placed - read the page for that one.",
    );
  });

  it("never implies every value is marked when the server could place none", () => {
    imageFor.mockReturnValue(ready(0, 2));
    render(<SheetPageImage runId="run-1" page={1} marks={[]} />);
    expect(screen.getByTestId("sheet-marks")).toHaveTextContent("None of the 2 values with a card could be placed on this page");
  });

  it("says the page could not be loaded instead of a broken image", () => {
    imageFor.mockReturnValue({ src: null, loading: false, failed: true, answerLocated: null, marksLocated: null, marksTotal: null });
    render(<SheetPageImage runId="run-1" page={2} marks={[]} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Page 2 could not be loaded from this screen.");
  });
});

describe("marksSentence", () => {
  it("states every count with its denominator and never a bare zero", () => {
    expect(marksSentence(4, 4)).toBe("All 4 values with a card are underlined on the page.");
    expect(marksSentence(1, 1)).toBe("The 1 value with a card is underlined on the page.");
    expect(marksSentence(null, null)).toBe("The page is shown; whether its values are marked could not be read.");
    expect(marksSentence(0, 1)).toBe("None of the 1 value with a card could be placed on this page - read the page itself.");
  });
});
