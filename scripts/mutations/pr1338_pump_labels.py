"""Order 228.11 (PR 1338): the spellings a pump datasheet prints for rated flow
and operating temperature."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_228_11_pump_labels.py"
_JSON = APP / "reference" / "datasheet_checks.json"
_FLOW = '        "^(rated )?(capacity ?/ ?flow|flow ?/ ?capacity)$",\n'

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1338-01",
        phase=1338,
        description="the rated flow loses the 'capacity / flow' spelling, so it is reported not found again",
        path=_JSON,
        anchor=_FLOW,
        replacement="",
        target=_T,
        keyword="spellings_a_pump_sheet_prints or not_reported_missing",
        tags=("honesty",),
    ),
    Mutation(
        id="M1338-02",
        phase=1338,
        description="the operating temperature loses the 'pumping temperature' spelling",
        path=_JSON,
        anchor='        "^(max(imum|\\\\.)? )?(normal )?pumping temp(erature|\\\\.)?$"\n',
        replacement='        "^$"\n',
        target=_T,
        keyword="spellings_a_pump_sheet_prints or not_reported_missing",
        tags=("honesty",),
    ),
    Mutation(
        id="M1338-03",
        phase=1338,
        description="a bare 'capacity' is taken for the pump's rated flow (also the relief valve's capacity)",
        path=_JSON,
        anchor=_FLOW,
        replacement='        "^(rated )?(capacity|capacity ?/ ?flow|flow ?/ ?capacity)$",\n',
        target=_T,
        keyword="looser_label",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1338-04",
        phase=1338,
        description="the reader is no longer asked with 'capacity / flow'",
        path=_JSON,
        anchor='        "capacity / flow",\n        "flow / capacity"\n',
        replacement='        "flow / capacity"\n',
        target=_T,
        keyword="reader_is_asked",
        tags=("honesty",),
    ),
)
