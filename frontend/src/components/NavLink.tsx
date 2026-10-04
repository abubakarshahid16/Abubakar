/**
 * In-app links that go through the app's own navigation.
 *
 * A plain `<a href="/documents">` makes the browser load the page again, and
 * the sign-in token lives in memory only - so such a link signed the reader
 * out. This one calls the app's `onNavigate` (history push, no reload). The
 * href is kept so "open in new tab" still works; a modified click is left to
 * the browser.
 *
 * Outside the app (an isolated render with no provider) there is nothing to
 * navigate with, so the text is shown without a link rather than as a link
 * that would reload the page.
 */
import { createContext, useContext, type ReactNode } from "react";

import { pathForView } from "../routing";
import type { ViewId } from "./Shell";

export type NavigateFn = (view: ViewId, recordId?: string) => void;

export const NavigationContext = createContext<NavigateFn | null>(null);

export function NavLink({
  view, recordId, className, children,
}: { view: ViewId; recordId?: string; className?: string; children: ReactNode }) {
  const navigate = useContext(NavigationContext);
  if (!navigate) return <span className={className}>{children}</span>;
  return (
    <a
      href={pathForView(view, recordId)}
      className={className}
      onClick={(event) => {
        if (event.defaultPrevented || event.button !== 0
          || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        navigate(view, recordId);
      }}
    >
      {children}
    </a>
  );
}
