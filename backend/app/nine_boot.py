"""Imported once by `main` at start: with `AGENT_REVIEW_NINE_ROLES_ENABLED` on, import every module of the nine-role job BEFORE the registries freeze.

The call seam's templates, vocabularies and id sources are registered at module import and closed at app start (`nine_call.freeze`, in
`main.lifespan`), so a role module that is imported lazily after that could not register anything. `nine_job` imports every role module at its
top; this module only imports `nine_job` when the switch is on. With the switch off nothing nine-role is imported, so a review is today's."""

from __future__ import annotations

from .config import settings

if settings.agent_review_nine_roles_enabled:
    from . import nine_job  # noqa: F401 - imported for its registrations
