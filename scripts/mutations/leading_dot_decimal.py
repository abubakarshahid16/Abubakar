"""Mutations for the leading-dot decimal reading (#1515, PR 1517): ".30" is 0.30,
"-.5" is -0.5, ".5 mm" is a measurement, a stranded or glued dot is no value.
Files: backend/app/numparse.py. Targets: tests/test_leading_dot_decimal.py,
tests/test_leading_dot_readers.py (the readers, #1518, PR 1520).
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_leading_dot_decimal.py"
_R = "tests/test_leading_dot_readers.py"
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
        # #1655: the rule in `_prefix_refused` now owns this case; the mutant lets a letter stand
        # directly before the number, so "p.4" is the decimal 0.4 again.
        anchor='    if not prefix:\n        return False\n    if prefix[-1] not in _SPACES + _BINDS:\n',
        replacement='    if not prefix:\n        return False\n    if prefix[-1].isalpha():\n        return False\n    if prefix[-1] not in _SPACES + _BINDS:\n',
        target=_T,
        keyword="glued_dot",
        tags=_TAG,
    ),
    Mutation(
        id="M1517-04",
        phase=1517,
        description="a stranded dot before a number ('.5.3', '...5') is read as a number again",
        path=APP / "numparse.py",
        # #1655: as M1517-03; the mutant lets a stranded dot stand before the number.
        anchor='    if not prefix:\n        return False\n    if prefix[-1] not in _SPACES + _BINDS:\n',
        replacement='    if not prefix:\n        return False\n    if prefix[-1] == ".":\n        return False\n    if prefix[-1] not in _SPACES + _BINDS:\n',
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
    Mutation(
        id="M1520-01",
        phase=1520,
        description="the readers ignore the switch and never read a leading-dot value (#1518)",
        path=APP / "numparse.py",
        anchor="    return lead if leading_dot_enabled() else plain",
        replacement="    return plain",
        target=_R,
        keyword="on_the_datasheet_reader or on_a_rule_table_reads or on_an_answer_figure",
        tags=_TAG,
    ),
    Mutation(
        id="M1520-02",
        phase=1520,
        description="the readers read a leading-dot value with the switch OFF (#1518)",
        path=APP / "numparse.py",
        anchor="    return lead if leading_dot_enabled() else plain",
        replacement="    return lead",
        target=_R,
        keyword="off_",
        tags=_TAG,
    ),
    Mutation(
        id="M1520-04",
        phase=1520,
        description="a leading-dot cell ('.5', '< .25') is not a numeric cell with the switch on (#1518)",
        path=APP / "numparse.py",
        anchor='CELL_LEAD = re.compile(r"^\\s*[<>=~±]{0,2}\\s*[-+]?(?:\\.\\d+|\\d[\\d,]*(?:\\.\\d+)?)\\s*$")',
        replacement='CELL_LEAD = re.compile(r"^\\s*[<>=~±]{0,2}\\s*[-+]?(?:\\d[\\d,]*(?:\\.\\d+)?)\\s*$")',
        target=_R,
        keyword="on_the_datasheet_reader",
        tags=_TAG,
    ),
)
