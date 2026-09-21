/** Slide-over panel used by the inspector, excluded viewer and page viewer. */
import { useEffect, useRef, type ReactNode } from "react";

export function Drawer({
  title,
  subtitle,
  onClose,
  size = "default",
  flush = false,
  children,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  /** How wide the panel opens.
   *
   *  `wide` is for a panel whose CONTENT has its own page geometry - a PDF
   *  rendered by the browser's own viewer, which reflows to the width it is
   *  given. At `max-w-3xl` an A4 page renders about the size of a postcard and
   *  the reader zooms every time. Everything else stays at the reading width,
   *  where a column of text is easier to read narrow than wide. */
  size?: "default" | "wide";
  /** Drop the body's padding and scrolling, for content that manages its own
   *  height. The default wrapper scrolls, which is right for a list and wrong
   *  for a viewport-filling frame: the frame would size itself to the content
   *  and then be scrolled by its parent as well as by itself. */
  flush?: boolean;
  children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    panel.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div
        className="absolute inset-0 bg-black/60"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={[
          "relative flex h-full w-full flex-col border-l border-ink-700",
          "bg-ink-900 shadow-2xl",
          size === "wide" ? "max-w-[90vw]" : "max-w-3xl",
        ].join(" ")}
      >
        <header className="flex items-start justify-between gap-4 border-b border-ink-700 px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-medium text-slateish-200">{title}</h2>
            {subtitle && (
              <p className="truncate font-mono text-xs text-slateish-400">{subtitle}</p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded border border-ink-600 px-3 py-1 text-sm text-slateish-300 hover:bg-ink-700"
          >
            Close
          </button>
        </header>
        {/* `min-h-0` on a flex child is what lets it be SHORTER than its
            content; without it the child's min-content height wins and the
            panel grows past the viewport instead of the child scrolling. */}
        <div
          className={
            flush
              ? "flex min-h-0 flex-1 flex-col overflow-hidden"
              : "min-h-0 flex-1 overflow-y-auto px-5 py-4"
          }
        >
          {children}
        </div>
      </div>
    </div>
  );
}
