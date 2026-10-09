"""#666 "the model stays in RAM after every call": each entry deletes one part;
backend/tests/test_w7_666_model_memory.py must notice."""
from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_w7_666_model_memory.py"
_TAG = ("w7_666", "model_memory")
REPO = APP.parent.parent


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(4201, "the interactive default is thirty minutes again", APP / "config.py",
       '    ollama_keep_alive: str = "5m"\n', '    ollama_keep_alive: str = "30m"\n',
       "interactive_default_is_five_minutes"),
    _m(4202, "the env example puts thirty minutes back", APP.parent / ".env.example",
       "OLLAMA_KEEP_ALIVE=5m", "OLLAMA_KEEP_ALIVE=30m", "env_example"),
    _m(4203, "a call ignores the keep-alive setting", APP / "model_transport.py",
       '"keep_alive": _keep_alive()}', '"keep_alive": "5m"}', "follows_the_setting"),
    _m(4204, "the transport forgets which models it used", APP / "model_transport.py",
       "            _USED_MODELS.add(str(model))\n", "            pass\n", "remembers_which_models"),
    _m(4205, "free-all unloads nothing", APP / "model_memory.py",
       "    for model in before:\n        unload(model)\n", "    for model in []:\n        unload(model)\n",
       "free_all_unloads_every"),
    _m(4206, "free-all reports what it asked, not what Ollama says", APP / "model_memory.py",
       "    still = after if after is not None else []\n", "    still = []\n", "will_not_unload"),
    _m(4207, "an unload does not send keep-alive 0", APP / "model_memory.py",
       "        with model_transport.keep_alive_override(0):\n",
       "        with model_transport.keep_alive_override(None):\n", "free_all_unloads_every"),
    _m(4208, "the P1 runner never unloads", REPO / "eval" / "p1" / "run_p1.py",
       "    finally:\n        _unload_models()\n", "    finally:\n        pass\n", "p1_runner_unloads"),
    _m(4209, "the P1 runner unloads only when it succeeds", REPO / "eval" / "p1" / "run_p1.py",
       "    try:\n        return _run()\n    finally:\n        _unload_models()\n",
       "    result = _run()\n    _unload_models()\n    return result\n", "error_and_on_ctrl_c"),
    _m(4210, "the free-memory route is open to anyone", APP / "main.py",
       '    actor: dict | None = Depends(admin_mod.current_admin)):\n    """Give back the memory',
       '    actor: dict | None = None):\n    """Give back the memory', "refuses_a_non_admin"),
    _m(4211, "the route frees nothing", APP / "main.py",
       "    return model_memory_mod.free_all()\n",
       '    return {"reachable": True, "freed": [], "still_loaded": []}\n', "frees_model_memory_for_an_admin"),
    Mutation(id="M4212", phase=4212, runner="vitest",
             description="the button does not call the server",
             path=FRONTEND_SRC / "components" / "FreeModelMemory.tsx",
             anchor="    const r = await api.freeModelMemory();\n",
             replacement="    const r: any = { ok: true, data: { reachable: true, freed: [], still_loaded: [] } };\n",
             target="src/components/FreeModelMemory.test.tsx", keyword="asks the server to unload", tags=_TAG),
    Mutation(id="M4213", phase=4213, runner="vitest",
             description="the result hides a model that is still loaded",
             path=FRONTEND_SRC / "components" / "FreeModelMemory.tsx",
             anchor="                  result.still_loaded.length > 0\n                    ?",
             replacement="                  false\n                    ?",
             target="src/components/FreeModelMemory.test.tsx", keyword="still loaded", tags=_TAG),
    Mutation(id="M4214", phase=4214, runner="vitest",
             description="the button is shown to everyone",
             path=FRONTEND_SRC / "views" / "DashboardTechnicalDetails.tsx",
             anchor="        {isAdmin && <FreeModelMemory />}\n", replacement="        {<FreeModelMemory />}\n",
             target="src/components/FreeModelMemory.test.tsx", keyword="administrator only", tags=_TAG),
)
