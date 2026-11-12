import { useId, useState, type ReactNode } from "react";

/**
 * A long explanation folded to one line. The text is kept in the page (never deleted) and is hidden until the reader
 * presses "More". `summary` is the one line that is always shown.
 */
export function MoreText({
  summary, children, className = "",
}: { summary: ReactNode; children: ReactNode; className?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className={className}>
      <p className="text-sm text-slateish-300">
        {summary}{" "}
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen(!open)}
          className="text-xs text-signal-400 underline decoration-dotted underline-offset-4 hover:text-signal-300"
        >
          {open ? "Less" : "More"}
        </button>
      </p>
      <div id={id} hidden={!open} className="mt-2">{children}</div>
    </div>
  );
}
