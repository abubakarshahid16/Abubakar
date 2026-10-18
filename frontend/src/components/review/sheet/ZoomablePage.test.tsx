/**
 * Order 85a (#967): the Sheet's page is readable - a tall frame, zoom, click
 * to enlarge, and a full-page view. It was a 512 px thumbnail with no zoom,
 * and a 152 px PDF strip for pages without cards.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PlainPageImage } from "./PlainPageImage";
import { ZoomablePage } from "./ZoomablePage";

vi.mock("../../useAuthedImage", () => ({
  useAuthedImage: (url: string | null) => ({
    src: url ? `blob:${url}` : null, loading: false, failed: false,
    answerLocated: null, marksLocated: null, marksTotal: null,
  }),
}));
vi.mock("../../../api/client", () => ({
  documentsApi: { pageImageUrl: (id: string, page: number) => `/api/documents/${id}/pages/${page}/image` },
}));

const image = () => screen.getByRole("img", { name: "Datasheet page 4" });

describe("the Sheet's page viewer", () => {
  it("fills most of the window and fits the page to its width", () => {
    render(<ZoomablePage src="blob:x" alt="Datasheet page 4" />);
    expect(screen.getByTestId("page-frame").className).toMatch(/h-\[80vh\]/);
    expect(image().dataset.scale).toBe("1");
    expect(image().style.width).toBe("100%");
  });

  it("zooms in and out, and back to fit width", () => {
    render(<ZoomablePage src="blob:x" alt="Datasheet page 4" />);
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(image().dataset.scale).toBe("0.75");                 // a whole page on a laptop
    expect(screen.getByRole("button", { name: "Zoom out" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Fit width" }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(image().dataset.scale).toBe("1.5");
    expect(screen.getByTestId("page-zoom")).toHaveTextContent("150%");
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(image().dataset.scale).toBe("1.25");
    fireEvent.click(screen.getByRole("button", { name: "Fit width" }));
    expect(image().dataset.scale).toBe("1");
  });

  it("enlarges on a click, and a second click fits the width again", () => {
    render(<ZoomablePage src="blob:x" alt="Datasheet page 4" />);
    fireEvent.click(image());
    expect(Number(image().dataset.scale)).toBeGreaterThanOrEqual(2);
    fireEvent.click(image());
    expect(image().dataset.scale).toBe("1");
  });

  it("opens the full page and closes it with Escape", () => {
    render(<ZoomablePage src="blob:x" alt="Datasheet page 4" />);
    fireEvent.click(screen.getByRole("button", { name: "Open full page" }));
    expect(screen.getByRole("dialog", { name: "Datasheet page 4, full page" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows a page without cards as the server's page image in the same viewer, not a PDF strip", () => {
    const { container } = render(<PlainPageImage documentId="sub-1" page={4} />);
    expect(image().getAttribute("src")).toBe("blob:/api/documents/sub-1/pages/4/image");
    expect(screen.getByTestId("page-frame").className).toMatch(/h-\[80vh\]/);
    expect(container.querySelector("iframe, object, embed")).toBeNull();
    expect(screen.getByText("No value on this page has a card.")).toBeInTheDocument();
  });

  it("says the page is loading inside the frame, so nothing jumps", () => {
    render(<ZoomablePage src={null} alt="Datasheet page 4" status="Loading page 4…" />);
    expect(screen.getByTestId("page-frame")).toHaveTextContent("Loading page 4…");
    expect(screen.getByRole("button", { name: "Open full page" })).toBeDisabled();
  });
});
