"""#631: the Documents poll rule ("fast while a document is being worked on")
is still proven by frontend/src/hooks/usePoll.test.tsx after its timing was
made to wait for the decision instead of racing it."""
from __future__ import annotations

from ._base import FRONTEND_SRC, Mutation

_T = "src/hooks/usePoll.test.tsx"
_TAG = ("w8", "reliability")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M3201", phase=3201, runner="vitest",
             description="the Documents screen never polls fast, even while a document is being worked on",
             path=FRONTEND_SRC / "views" / "DocumentsView.tsx",
             anchor="(load.state === \"ready\" && load.documents.some((d) => !SETTLED.has(d.status)));",
             replacement="false;",
             target=_T, keyword="polls fast while a document", tags=_TAG),
    Mutation(id="M3202", phase=3202, runner="vitest",
             description="the poll interval is always the idle one",
             path=FRONTEND_SRC / "hooks" / "usePoll.ts",
             anchor="  return busy ? FAST_MS : IDLE_MS;",
             replacement="  return IDLE_MS;",
             target=_T, keyword="polls fast while a document", tags=_TAG),
    Mutation(id="M3203", phase=3203, runner="vitest",
             description="the Documents screen polls fast even when every document has settled",
             path=FRONTEND_SRC / "views" / "DocumentsView.tsx",
             anchor="(load.state === \"ready\" && load.documents.some((d) => !SETTLED.has(d.status)));",
             replacement="true;",
             target=_T, keyword="backs off once every document", tags=_TAG),
)
