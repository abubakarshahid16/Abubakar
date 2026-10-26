"""Order 227: what a CRS Standard Reference says about WHICH copy of the standard it cites.

A reader who has to open the clause needs the standard, its edition, the clause and the page
("SAES-G-005 (2023) cl. 4.3.5 (p.15)"). The edition is the one the library knows: stored on
the finding (`standard_edition`) or printed in the standard's own file name or title
(`standard_ids.edition_of`). Never guessed: no edition known says so ("edition not recorded"),
and a name that already carries its year is not given it twice.
"""

from __future__ import annotations

from . import standard_ids

NOT_RECORDED = "edition not recorded"


def tail(finding: dict, name: str, clause: str, page) -> str:
    """Everything a reference prints after the standard's name: edition, clause words, page."""
    return edition_words(finding, name) + clause + (f" (p.{page})" if page else "")


def edition_words(finding: dict, name: str) -> str:
    """ " (2023)" or " (edition not recorded)" for the standard called `name` ("" when the
    name already ends in or contains its edition year)."""
    edition = str(
        finding.get("standard_edition") or ""
    ).strip() or standard_ids.edition_of(name)
    if not edition:
        return f" ({NOT_RECORDED})"
    return "" if edition in name else f" ({edition})"
