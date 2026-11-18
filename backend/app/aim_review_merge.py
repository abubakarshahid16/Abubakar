"""The two merge passes of a general review's comments that run after the checklist-item and finding merges (`aim_review_view`): the same
PLACE (one field on the same page) sent under several rules, and the editor's (S5) GROUPS. Both are lossless (`_same_point`: every rule's
own words, every page, every quote), per kind (a Not met / Fail never joins a Question, nor two compare kinds), and NO CHAIN (a comment
whose lines sit in different places or groups stays as it is). Pure code on the points of a run: no model, no call."""

from __future__ import annotations

import re
from collections.abc import Callable


def _key_of(p: dict, extra) -> tuple | None:
    """The merge key of one sent line: its shown label, compare kind and provisional kind with `extra`; None for a Not met or a Fail."""
    from . import aim_review_view as V

    shown = str(p.get("shown_label") or "").lower()
    if (
        p.get("label") == "Not met"
        or "not met" in shown
        or "fail" in shown
        or extra is None
    ):
        return None
    return (
        p["shown_label"],
        p.get("compare_kind") or "",
        V._provisional_kind(p.get("code_note")),
        *extra,
    )


def place_key(p: dict) -> tuple | None:
    """The PLACE a sent line speaks about: its field (folded) and its page; None without either."""
    from . import aim_review_view as V

    field, page = V._field_key(p.get("field")), p.get("page")
    return _key_of(p, (field, page) if field and isinstance(page, int) else None)


def group_key(p: dict) -> tuple | None:
    """The editor's GROUP of a sent line (`same_point_as`, the group's first line number); None without a mark."""
    group = p.get("same_point_as")
    return _key_of(p, (group,) if isinstance(group, int) else None)


#: Words of approval: a member that says the value is fine is put AFTER the members that raise a concern (an engineer reads the concern
#: first, and a strict reader does not drop the whole merged comment for one approving sentence).
_APPROVAL = re.compile(
    r"\b(acceptable|consistent|complies|compliant|satisfied|no action|adequate|is fine|are fine)\b",
    re.IGNORECASE,
)


def lead_first(members: list[dict]) -> list[dict]:
    """The members of a merged group, the concern first (the judge's "concern"), a member whose own words approve something after
    those that do not; line order inside each step. Nothing is dropped or rewritten."""
    return sorted(
        members,
        key=lambda m: (
            bool(_APPROVAL.search(str(m.get("comment") or ""))),
            m.get("ask") != "concern",
            m["n"],
        ),
    )


def _merge(
    comments: list[dict],
    by_n: dict,
    key: Callable[[dict], tuple | None],
    order: Callable[[list], list],
) -> list[dict]:
    from . import aim_review_view as V

    groups: dict[tuple, list[dict]] = {}
    out = []
    for c in comments:
        keys = {key(by_n[n]) for n in c["lines"]}
        if len(keys) == 1 and None not in keys:
            groups.setdefault(keys.pop(), []).append(c)
        else:
            out.append(c)
    for cs in groups.values():
        if len(cs) == 1:
            out.append(cs[0])
            continue
        members = order([by_n[n] for c in cs for n in c["lines"]])
        out.append(V._same_point(members, keep_order=True))
    return sorted(out, key=lambda g: g["n"])


def _by_place(members: list[dict]) -> list[dict]:
    return sorted(members, key=lambda m: (m["page"] is None, m["page"] or 0, m["n"]))


def same_place(comments: list[dict], by_n: dict) -> list[dict]:
    """The same point sent under several rules (the repeats a strict judge marks WEAK): comments whose lines ALL speak about ONE field
    on the SAME page become one comment that keeps every line's own words and lists every rule."""
    return _merge(comments, by_n, place_key, _by_place)


def same_group(comments: list[dict], by_n: dict) -> list[dict]:
    """The comments the editor (S5) grouped as ONE point: those whose lines ALL carry the same group mark and the same kind."""
    return _merge(comments, by_n, group_key, lead_first)
