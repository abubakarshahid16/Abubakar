"""Mutations of the chat engine race: a question asked before /chat/models has
answered must wait for it (a moment at most) and read the engine from a ref.
Ids M1790-M1799. Target: src/views/ChatView.redesign.test.tsx.
"""

from __future__ import annotations

from ._base import FRONTEND_SRC, Mutation

_CHAT = FRONTEND_SRC / "views" / "ChatView.tsx"
_T = "src/views/ChatView.redesign.test.tsx"
_K = "a question asked before the engine list has arrived"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1790", phase=1790, runner="vitest",
             description="send no longer waits for the engine list (the race comes back)",
             path=_CHAT,
             anchor="      await Promise.race([\n        enginesReady.current,\n",
             replacement="      await Promise.race([\n        Promise.resolve(),\n",
             target=_T, keyword=_K, tags=("ui",)),
    Mutation(id="M1791", phase=1791, runner="vitest",
             description="send reads the engine from the render's state, not the ref",
             path=_CHAT,
             anchor="      const engine = modelRef.current;\n",
             replacement="      const engine = model;\n",
             target=_T, keyword=_K, tags=("ui",)),
    Mutation(id="M1792", phase=1792, runner="vitest",
             description="a list that never arrives hangs the question for ever",
             path=_CHAT,
             anchor="      await Promise.race([\n        enginesReady.current,\n"
                    "        new Promise<void>((resolve) => window.setTimeout(resolve, ENGINE_WAIT_MS)),\n"
                    "      ]);\n",
             replacement="      await enginesReady.current;\n",
             target=_T, keyword="does not wait forever", tags=("ui",)),
    Mutation(id="M1793", phase=1793, runner="vitest",
             description="a failed engine list stops the question from being asked",
             path=_CHAT,
             anchor="      if (cancelled || !r.ok) return;\n      setModels(r.data);\n      chooseModel(r.data.default);",
             replacement="      if (cancelled) return;\n      if (!r.ok) throw new Error(\"no engines\");\n"
                         "      setModels(r.data);\n      chooseModel(r.data.default);",
             target=_T, keyword="when the list fails", tags=("ui",)),
    Mutation(id="M1794", phase=1794, runner="vitest",
             description="picking an engine by hand does not reach the ref send reads",
             path=_CHAT,
             anchor="    modelRef.current = next;\n    setModel(next);\n",
             replacement="    setModel(next);\n",
             target="src/views/ChatView.test.tsx", keyword=None, tags=("ui",)),
)
