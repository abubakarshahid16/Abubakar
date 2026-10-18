/**
 * The Sheet's page viewer (order 85a, #967): the datasheet page at a size an
 * engineer can read.
 *
 * It was two things: a page with cards shrunk to fit 512 px tall (about 360
 * px wide, text unreadable, no zoom), and a page without cards shown as the
 * original PDF in a frame 152 px tall. Now every page is the server's page
 * image in ONE viewer: at least about 80% of the window tall, fit to its
 * width, with zoom (fit width, minus, plus, click to enlarge) and an "open
 * full page" view at the image's own size.
 */
import { type ReactNode, useEffect, useState } from "react";

/** Zoom steps, as a share of the frame's width; the first is "fit width". */
const ZOOM_STEPS = [1, 1.25, 1.5, 2, 2.5, 3] as const;
/** Clicking the page jumps to this step, and back to fit width. */
const CLICK_STEP = 3;

export function ZoomablePage({ src, alt, caption }: { src: string; alt: string; caption?: ReactNode }) {
  const [step, setStep] = useState(0);
  const [full, setFull] = useState(false);
  useEffect(() => {
    if (!full) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setFull(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [full]);
  const scale = ZOOM_STEPS[step];
  const button = "rounded-[var(--radius-xs)] border border-ink-600 px-2 py-0.5 text-slateish-200 hover:border-ink-500 disabled:opacity-40";

  return (
    <figure className="space-y-1" data-page-viewer="">
      {caption}
      <div role="toolbar" aria-label="Page zoom" className="flex flex-wrap items-center gap-2 text-xs">
        <button type="button" className={button} aria-pressed={step === 0} onClick={() => setStep(0)}>Fit width</button>
        <button type="button" className={button} aria-label="Zoom out" disabled={step === 0} onClick={() => setStep((s) => Math.max(0, s - 1))}>−</button>
        <span data-testid="page-zoom" className="min-w-10 text-center text-slateish-400">{Math.round(scale * 100)}%</span>
        <button type="button" className={button} aria-label="Zoom in" disabled={step === ZOOM_STEPS.length - 1} onClick={() => setStep((s) => Math.min(ZOOM_STEPS.length - 1, s + 1))}>+</button>
        <button type="button" className={button} onClick={() => setFull(true)}>Open full page</button>
      </div>
      <div data-testid="page-frame" className="h-[80vh] min-h-[24rem] overflow-auto rounded-[var(--radius-sm)] border border-ink-700 bg-white max-sm:h-[60vh]">
        <img
          src={src} alt={alt} data-scale={scale}
          title={step === 0 ? "Click to enlarge" : "Click to fit the width"}
          onClick={() => setStep((s) => (s === 0 ? CLICK_STEP : 0))}
          style={{ width: `${scale * 100}%`, maxWidth: "none" }}
          className={`block h-auto ${step === 0 ? "cursor-zoom-in" : "cursor-zoom-out"}`}
        />
      </div>
      {full && (
        <div role="dialog" aria-modal="true" aria-label={`${alt}, full page`} className="fixed inset-0 z-50 overflow-auto bg-ink-950/95 p-4">
          <button type="button" autoFocus onClick={() => setFull(false)} className={`${button} sticky top-0 mb-2 bg-ink-900`}>
            Close full page
          </button>
          <img src={src} alt={alt} className="mx-auto block max-w-none bg-white" />
        </div>
      )}
    </figure>
  );
}
