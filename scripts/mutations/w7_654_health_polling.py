"""#654: the health poller is one, polite poller: 15 s, silent in a hidden tab,
backing off while the backend is silent, and leaves nothing behind. Ids M4801-M4809."""
from __future__ import annotations

from ._base import FRONTEND_SRC, Mutation

_P = FRONTEND_SRC / "components" / "Shell.tsx"
_T = "src/components/Shell.polling.test.tsx"
_TAG = ("w7", "reliability")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M4801", phase=4801, runner="vitest",
             description="the poll is back to every 5 seconds",
             path=_P, anchor="export const HEALTH_POLL_MS = 15000;",
             replacement="export const HEALTH_POLL_MS = 5000;",
             target=_T, keyword="is every 15 seconds", tags=_TAG),
    Mutation(id="M4802", phase=4802, runner="vitest",
             description="a hidden tab still polls (the schedule ignores visibility)",
             path=_P, anchor="      if (cancelled || tabHidden()) return;\n      timer",
             replacement="      if (cancelled) return;\n      timer",
             target=_T, keyword="schedules nothing when the tab was hidden", tags=_TAG),
    Mutation(id="M4803", phase=4803, runner="vitest",
             description="a tab that starts hidden still makes its first call",
             path=_P, anchor="      if (cancelled || tabHidden()) return;\n      await check();",
             replacement="      if (cancelled) return;\n      await check();",
             target=_T, keyword="makes no call at all in a hidden tab", tags=_TAG),
    Mutation(id="M4804", phase=4804, runner="vitest",
             description="showing the tab again does not look at once",
             path=_P, anchor="        void poll();           // shown again",
             replacement="        schedule();            // shown again",
             target=_T, keyword="looks at once when it is shown again", tags=_TAG),
    Mutation(id="M4805", phase=4805, runner="vitest",
             description="no back-off while the backend is silent",
             path=_P, anchor="return Math.min(base * 2 ** Math.max(0, failures), HEALTH_MAX_BACKOFF_MS);",
             replacement="return base;",
             target=_T, keyword="backs off while the backend does not answer", tags=_TAG),
    Mutation(id="M4806", phase=4806, runner="vitest",
             description="the back-off has no cap",
             path=_P, anchor="return Math.min(base * 2 ** Math.max(0, failures), HEALTH_MAX_BACKOFF_MS);",
             replacement="return base * 2 ** Math.max(0, failures);",
             target=_T, keyword="doubles with each failure and is capped", tags=_TAG),
    Mutation(id="M4807", phase=4807, runner="vitest",
             description="a good answer does not return the poll to its pace",
             path=_P, anchor="failures.current = result.ok ? 0 : failures.current + 1;",
             replacement="failures.current = result.ok ? failures.current : failures.current + 1;",
             target=_T, keyword="returns to the pace when it does", tags=_TAG),
    Mutation(id="M4808", phase=4808, runner="vitest",
             description="the visibility listener is never removed",
             path=_P, anchor='      document.removeEventListener("visibilitychange", onVisibility);\n',
             replacement="",
             target=_T, keyword="leaves no timer or listener behind", tags=_TAG),
    Mutation(id="M4809", phase=4809, runner="vitest",
             description="the pending timer survives closing the app",
             path=_P, anchor="      cancelled = true;\n      stop();\n",
             replacement="      cancelled = true;\n",
             target=_T, keyword="leaves no timer or listener behind", tags=_TAG),
)
