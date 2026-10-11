"""#212: discipline is retired as a standard-selection rule. M5951."""
from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M5951", phase=5951, description="the retired discipline rule selects standards again",
             path=APP / "applicability.py",
             anchor='        _match_attribute(library, profile, "service", METHOD_SERVICE),\n',
             replacement=('        _match_attribute(library, profile, "discipline", METHOD_DISCIPLINE),\n'
                          '        _match_attribute(library, profile, "service", METHOD_SERVICE),\n'),
             target="tests/test_applicability.py", keyword="shared_discipline_does_not",
             tags=("honesty",)),
)
