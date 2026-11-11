"""The class and word of one AI-reviewer line, in the contract's words (#1749).

The class/word/tier table is ONE: `api.agent_review_schemas.LINE_TABLE` (with its `WORD_FIXES`). This module asks it; it
holds no second table. A pair the contract refuses is never stored as it is.
"""

from __future__ import annotations

import logging

from . import agent_review_wording as wording
from .api import agent_review_schemas as contract

log = logging.getLogger(__name__)


class IllegalLine(ValueError):
    """The contract refuses this line's class, word or tier. The line is never stored as it is."""


def contract_class_and_word(line: dict) -> tuple[str, str]:
    """The contract's class and word of one line, as the core's `wording.classify` gives them (the "Not reviewed" class, the
    silent-paper Query and the caps are the core's). A pair the contract refuses raises `IllegalLine`."""
    got = wording.apply(line)
    cls, label = got["verdict_class"], got["verdict_label"]
    word = contract.legal_word(cls, label)
    if word is None:
        raise IllegalLine(f'class "{cls}" cannot carry the word "{label}"')
    return cls, word


def class_and_word_for_write(line: dict, tier: str | None) -> tuple[str, str]:
    """The pair to store. A line the contract refuses is stored as "Not reviewed" with the refusal as its reason (the least
    confident class; the run shows it), and the passed line is changed the same way so the CRS agrees."""
    try:
        cls, word = contract_class_and_word(line)
        if not contract.legal_tier(cls, tier):
            raise IllegalLine(f'class "{cls}" cannot have rule tier {tier!r}')
        return cls, word
    except IllegalLine as exc:
        log.warning(
            "agent review: a line was refused at write (%s)", type(exc).__name__
        )
        line["error"] = f"refused at write: {exc}"
        line["not_proven_reason"] = str(exc)
        return contract_class_and_word(line)
