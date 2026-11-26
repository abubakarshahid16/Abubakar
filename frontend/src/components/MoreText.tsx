import { useId, useState, type ReactNode } from "react";
import { LinkButton } from "./kit/Kit";

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
        <LinkButton
          
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen(!open)}
          
        >
          {open ? "Less" : "More"}
        </LinkButton>
      </p>
      <div id={id} hidden={!open} className="mt-2">{children}</div>
    </div>
  );
}
