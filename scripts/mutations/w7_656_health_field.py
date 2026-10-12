"""#656: /api/health says `answer_model_configured` (a name is set), not
`answer_model_present`. Ids M4901-M4903."""
from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_TAG = ("w7", "honesty")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M4901", phase=4901, description="the health field goes back to the name that over-claims",
             path=APP / "main.py", anchor='"answer_model_configured": bool(settings.answer_model),',
             replacement='"answer_model_present": bool(settings.answer_model),',
             target="tests/test_health.py", keyword="configured_not_present", tags=_TAG),
    Mutation(id="M4902", phase=4902, description="the field ignores the setting",
             path=APP / "main.py", anchor='"answer_model_configured": bool(settings.answer_model),',
             replacement='"answer_model_configured": True,',
             target="tests/test_health.py", keyword="configured_not_present", tags=_TAG),
    Mutation(id="M4903", phase=4903, runner="vitest",
             description="the badge always says a model is configured",
             path=FRONTEND_SRC / "components" / "Shell.tsx",
             anchor="              {connection.health.answer_model_configured\n",
             replacement="              {true\n",
             target="src/components/Shell.test.tsx", keyword="no answer model is configured", tags=_TAG),
)
