"""Order 227 item 1: every CRS Standard Reference names the edition of the standard it cites.
`crs_mapping.py` is in the danger zone (rule 6). PR #1307: ids M1307-01 onwards, phase 1307."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_o227_reference_edition.py"
_TAGS = ("honesty", "o227")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1307-01",
        phase=1307,
        description="an unknown edition prints nothing, so the reference reads as if it had none to give",
        path=APP / "crs_reference.py",
        anchor='        return f" ({NOT_RECORDED})"\n',
        replacement='        return ""\n',
        target=_T,
        keyword="no_known_edition_says_so",
        tags=_TAGS,
    ),
    Mutation(
        id="M1307-02",
        phase=1307,
        description="an edition already in the name is printed a second time",
        path=APP / "crs_reference.py",
        anchor='    return "" if edition in name else f" ({edition})"\n',
        replacement='    return f" ({edition})"\n',
        target=_T,
        keyword="found_not_repeated",
        tags=_TAGS,
    ),
    Mutation(
        id="M1307-03",
        phase=1307,
        description="the edition stored on the finding is ignored in favour of the file name",
        path=APP / "crs_reference.py",
        anchor="    edition = stored or standard_ids.edition_of(name)\n",
        replacement="    edition = standard_ids.edition_of(name)\n",
        target=_T,
        keyword="stored_edition",
        tags=_TAGS,
    ),
    Mutation(
        id="M1307-04",
        phase=1307,
        description="the reference no longer carries the edition at all",
        path=APP / "crs_mapping.py",
        anchor="    return std + crs_reference.tail(finding, std, paragraph_ids.cited(finding), page)\n",
        replacement='    return std + paragraph_ids.cited(finding) + (f" (p.{page})" if page else "")\n',
        target=_T,
        keyword="stored_edition or reaches_the_row",
        tags=_TAGS,
    ),
)
