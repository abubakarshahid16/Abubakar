"""Order 236 (#1330): the engineer's CRS copy never opens a comment with the
digest "Ref:" id; the contractor's copy still does. `crs_export.py` is in the
danger zone (rule 6)."""

from __future__ import annotations

from ._base import APP, Mutation

_M = APP / "crs_export.py"
_T = "tests/test_crs_export.py"
_TAGS = ("honesty", "critical")
_ANCHOR = "comment if crs_ref or copy == COPY_INTERNAL else"


def _m(n: str, description: str, replacement: str) -> Mutation:
    return Mutation(
        id=f"M1330-{n}",
        phase=1330,
        description=description,
        path=_M,
        anchor=_ANCHOR,
        replacement=replacement,
        target=_T,
        keyword="internal_copy_never_opens_a_comment_with_the_reference",
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "the engineer's copy opens an unnumbered comment with the Ref id again",
        "comment if crs_ref else",
    ),
    _m(
        "02",
        "the contractor's copy loses the Ref id it needs for an unnumbered row",
        "comment if True else",
    ),
)
