/**
 * Keep the reader's place on a long list (order 14, G2).
 *
 * On the Documents screen a click on Details or Choose kind made the page jump under the pointer: the click changes what is on the
 * page (a drawer opens, a button becomes a picker) and the browser may move the scroll position with it (focus moving, rows
 * off screen changing height). `keepScroll` remembers where the nearest scrolling ancestor of the clicked element was, makes the
 * change, and puts that position back for the next two frames if anything moved it.
 */

/** The element that scrolls for `from`: the nearest ancestor that scrolls, else the page. */
export function scrollerOf(from: Element | null): HTMLElement {
  for (let el = from?.parentElement ?? null; el; el = el.parentElement) {
    const overflow = getComputedStyle(el).overflowY;
    if ((overflow === "auto" || overflow === "scroll") && el.scrollHeight > el.clientHeight) return el;
  }
  return (document.scrollingElement as HTMLElement | null) ?? document.documentElement;
}

export function keepScroll(from: Element | null, change: () => void): void {
  const scroller = scrollerOf(from);
  const top = scroller.scrollTop;
  change();
  const put = () => {
    if (scroller.scrollTop !== top) scroller.scrollTop = top;
  };
  if (typeof requestAnimationFrame === "function") {
    requestAnimationFrame(() => {
      put();
      requestAnimationFrame(put);
    });
  } else {
    put();
  }
}
