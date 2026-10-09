"""#647: the review's AI applicability tier runs under the machine rules -
tries the shared heavy-job lock and never waits, steps aside when another job
queues, always unloads the model and releases the lock. M5101 onward."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w5_677_scope_ledger.py"
_F = APP / "ai_applicability.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M5101", phase=5101, description="the tier runs although another heavy job holds the lock",
             path=_F, anchor="    if lock is None:\n", replacement="    if False:\n",
             target=_T, keyword="does_not_run_while_another", tags=("machine", "critical")),
    Mutation(id="M5102", phase=5102, description="the model is left loaded after the tier",
             path=_F, anchor="        ai_task_runner._unload(provider)\n", replacement="        pass\n",
             target=_T, keyword="unloads_the_model", tags=("machine",)),
    Mutation(id="M5103", phase=5103, description="the lock is kept after the tier",
             path=_F, anchor="        lock.release()\n", replacement="        pass\n",
             target=_T, keyword="unloads_the_model", tags=("machine", "critical")),
    Mutation(id="M5104", phase=5104, description="the review does not ask whether someone is waiting",
             path=_F, anchor="provider=provider, limit=limit, stop=_someone_waiting)",
             replacement="provider=provider, limit=limit)",
             target=_T, keyword="steps_aside", tags=("machine",)),
    Mutation(id="M5105", phase=5105, description="the tier keeps asking after someone starts waiting",
             path=_F, anchor="        if stopped or limit is not None and asked >= limit or not clause:\n",
             replacement="        if limit is not None and asked >= limit or not clause:\n",
             target=_T, keyword="steps_aside", tags=("machine",)),
)
