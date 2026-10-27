"""Order 238/240 (PR 1337): a pump sheet's own labels for its flow and temperature are read as those
fields. `reference/datasheet_checks.json` is in the danger zone (rule 6). Ids M1337-01 onwards, phase 1337."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_240_pump_labels.py"
_JSON = APP / "reference" / "datasheet_checks.json"
_TAGS = ("honesty", "o240")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1337-01",
        phase=1337,
        description="the pump's 'capacity / flow' label is no longer the rated flow, so the contractor is asked for it",
        path=_JSON,
        anchor='        "^rated (flow|capacity)$",\n        "^(capacity ?/ ?flow|flow ?/ ?capacity)$"\n',
        replacement='        "^rated (flow|capacity)$"\n',
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1337-02",
        phase=1337,
        description="the pump's 'pumping temperature' label is no longer the operating temperature",
        path=_JSON,
        anchor='        "^(max(imum|\\\\.)? )?(normal )?operating temp(erature|\\\\.)?$",\n        "^(max(imum|\\\\.)? |normal )?pumping temp(erature|\\\\.)?$"\n',
        replacement='        "^(max(imum|\\\\.)? )?(normal )?operating temp(erature|\\\\.)?$"\n',
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1337-03",
        phase=1337,
        description="a bare 'capacity' or 'flow' is read as the rated flow (a valve's capacity becomes a pump's)",
        path=_JSON,
        anchor='"^(capacity ?/ ?flow|flow ?/ ?capacity)$"',
        replacement='"^(capacity|flow)( ?/ ?(capacity|flow))?$"',
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1337-04",
        phase=1337,
        description="a 'flowing temperature' (a relief temperature) is read as the operating temperature",
        path=_JSON,
        anchor='"^(max(imum|\\\\.)? |normal )?pumping temp(erature|\\\\.)?$"',
        replacement='"^(max(imum|\\\\.)? |normal )?(pumping |flowing )?temp(erature|\\\\.)?$"',
        target=_T,
        tags=_TAGS,
    ),
)
