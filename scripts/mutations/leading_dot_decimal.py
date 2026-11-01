"""Mutations for the leading-dot decimal reading (#1515, PR 1517): ".30" is 0.30,
"-.5" is -0.5, ".5 mm" is a measurement, a stranded or glued dot is no value.
Files: backend/app/numparse.py. Target: tests/test_leading_dot_decimal.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_leading_dot_decimal.py"
_TAG = ("leading_dot_decimal",)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1517-01",
        phase=1517,
        description="the measurement pattern ignores the switch and never reads a leading-dot value",
        path=APP / "numparse.py",
        anchor="    return _leading_dot_pattern(pattern) if leading_dot_enabled() else pattern",
        replacement="    return pattern",
        target=_T,
        keyword="measurement",
        tags=_TAG,
    ),
    Mutation(
        id="M1517-02",
        phase=1517,
        description="parse_value no longer accepts a leading-dot number: '.30' reads as 30 again",
        path=APP / "numparse.py",
        anchor='_NUM_PART_LEAD = r"[-+]?(?:\\.\\d+|\\d[\\d.,\\s]*)"',
        replacement='_NUM_PART_LEAD = r"[-+]?\\d[\\d.,\\s]*"',
        target=_T,
        keyword="the_decimal or minimum or maximum",
        tags=_TAG,
    ),
    Mutation(
        id="M1517-03",
        phase=1517,
        description="a dot glued to a letter ('p.4') is read as the decimal 0.4",
        path=APP / "numparse.py",
        anchor='        if m.group("num").lstrip("+-").startswith(".") and glued[-1:].isalnum():',
        replacement="        if False:",
        target=_T,
        keyword="glued_dot",
        tags=_TAG,
    ),
    Mutation(
        id="M1517-04",
        phase=1517,
        description="a stranded dot before a number ('.5.3', '...5') is read as a number again",
        path=APP / "numparse.py",
        anchor='        elif glued.rstrip().endswith(".") and not glued.rstrip()[-2:-1].isalnum():',
        replacement="        elif False:",
        target=_T,
        keyword="ambiguous",
        tags=_TAG,
    ),
    Mutation(
        id="M1517-05",
        phase=1517,
        description="the leading-dot measurement pattern is the unchanged pattern (value group not widened)",
        path=APP / "numparse.py",
        anchor='    lead = pattern.pattern.replace("(?P<value>\\\\d", "(?P<value>\\\\.\\\\d+|\\\\d", 1)',
        replacement="    lead = pattern.pattern",
        target=_T,
        keyword="measurement",
        tags=_TAG,
    ),
)
