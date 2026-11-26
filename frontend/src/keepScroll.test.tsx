/** G2: a click on Details or Choose kind must not move the reader on a long list. jsdom has no layout, so the browser's jump is
 *  simulated by the change itself moving the scroll position; the test is that the place is put back. */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DocumentClassification, DocumentKindOption } from "./types/api";
import { DocumentKindChip } from "./components/DocumentKindChip";
import { keepScroll, scrollerOf } from "./keepScroll";

// jsdom has no `document.scrollingElement`: the root element stands in for the page.
Object.defineProperty(document, "scrollingElement", { value: document.documentElement, configurable: true });

afterEach(() => vi.unstubAllGlobals());

function frames() {
  const queue: FrameRequestCallback[] = [];
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => { queue.push(cb); return queue.length; });
  return () => { while (queue.length) queue.shift()!(0); };
}

describe("keepScroll", () => {
  it("puts the position back when the change moved it", () => {
    const run = frames();
    const page = document.scrollingElement as HTMLElement;
    page.scrollTop = 900;
    keepScroll(document.body, () => { page.scrollTop = 0; }); // the jump
    run();
    expect(page.scrollTop).toBe(900);
  });

  it("leaves the position alone when nothing moved it", () => {
    const run = frames();
    const page = document.scrollingElement as HTMLElement;
    page.scrollTop = 40;
    keepScroll(document.body, () => {});
    run();
    expect(page.scrollTop).toBe(40);
  });

  it("follows the nearest scrolling ancestor, not the page", () => {
    const box = document.createElement("div");
    box.style.overflowY = "auto";
    Object.defineProperty(box, "scrollHeight", { value: 2000 });
    Object.defineProperty(box, "clientHeight", { value: 500 });
    const inner = document.createElement("button");
    box.appendChild(inner);
    document.body.appendChild(box);
    expect(scrollerOf(inner)).toBe(box);
    box.remove();
  });
});

describe("Choose kind on a long list", () => {
  const KINDS: DocumentKindOption[] = [{ id: "datasheet", label: "Datasheet" }];
  const CLS = { document_id: "d1", subjects: [], document_kind: null, document_kind_state: "needs_engineer" } as unknown as DocumentClassification;

  it("keeps the reader's place when the button becomes the picker, and the picker takes the focus", async () => {
    const run = frames();
    const page = document.scrollingElement as HTMLElement;
    page.scrollTop = 1200;
    render(<DocumentKindChip classification={CLS} kinds={KINDS} isAdmin onConfirm={() => null} />);
    const button = screen.getByText("Choose type");
    page.scrollTop = 1200;
    // the browser's jump happens as the button disappears
    button.addEventListener("click", () => { queueMicrotask(() => { page.scrollTop = 0; }); });
    await userEvent.click(button);
    run();
    expect(page.scrollTop).toBe(1200);
    expect(screen.getByLabelText("Document type")).toHaveFocus();
  });
});
