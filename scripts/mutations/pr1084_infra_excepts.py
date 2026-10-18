"""PR #1084 (order 79c, infrastructure): heavy_lock's "cannot tell" fallback
must still say why. backend/tests/test_79c_infra_excepts_log.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1084-01",
        phase=1084,
        description="an unreadable lock holder is swallowed without a log line",
        path=APP / "heavy_lock.py",
        anchor='        log.debug("heavy_lock: holder could not be checked (%s)", '
        "type(exc).__name__)\n",
        replacement="",
        target="tests/test_79c_infra_excepts_log.py",
        keyword="lock_holder_is_still_unknown",
        tags=("pr1084", "heavy_lock"),
    ),
)
