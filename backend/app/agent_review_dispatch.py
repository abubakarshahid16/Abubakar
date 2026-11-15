"""The ONE branch between today's AI review and the nine-role review (`AGENT_REVIEW_NINE_ROLES_ENABLED`, off by default).

Off: `agent_review_jobs._ask` is called exactly as before (same arguments, same condition) and `nine_job` is never imported, no
nine-role table is made. On: `nine_job.run_roles` runs the nine roles inside the same job, run row and line table."""

from __future__ import annotations

from .config import settings


def run(run_id, submittal, kind, plan, holder, ask, *, reraise: tuple = ()) -> None:
    if not settings.agent_review_nine_roles_enabled:
        if plan["items"]:
            ask(run_id, submittal, kind, plan, holder)
        return
    from . import nine_job

    nine_job.run_roles(run_id, submittal, kind, plan, holder, ask, reraise=reraise)
