"""THE ONE LIST of document kinds, each in one review family (order 14, planner 25 Nov 2026 item 1).

The app had four lists that disagreed: the router that sorts uploads (11 kinds), the engine's table (8 kinds), the paper-kind reading (6
to 9) and the kind sentences' nouns. `reference/kind_list.json` is now the only place a kind is named, with its label, its noun, its
FAMILY (written document, study or calculation, drawing or diagram, list register or schedule, certificate or record, datasheet) and
three flags; the other files hold only what is specific to a kind (the sorter's cues, the engine's review row) and are checked against
this list (`problems`, and a test). A kind that is not scored keeps its unscored behaviour: the family never makes a kind reviewable.

Equipment types and upload roles are other dimensions, not kinds (see the file's `_about`). Reads one file; no model, no network.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).parent / "reference" / "kind_list.json"
UNKNOWN = "unknown"
OTHER = "other"
FLAGS = ("routed", "code_decided", "cover_decided", "picker_needs_switch")
ROW_KEYS = ("label", "noun", "family", *FLAGS)


class KindListError(ValueError):
    """The list is missing or malformed: nothing may be decided from it until it is fixed."""


@lru_cache(maxsize=1)
def _load(mtime: float) -> dict:  # noqa: ARG001 - the argument is the cache key (re-read when the file changes)
    data = json.loads(PATH.read_text(encoding="utf-8"))
    families, kinds = data.get("families"), data.get("kinds")
    if not isinstance(families, dict) or not isinstance(kinds, dict) or not kinds:
        raise KindListError("the kind list needs `families` and `kinds`")
    for name, row in kinds.items():
        missing = [k for k in ROW_KEYS if k not in row]
        if missing:
            raise KindListError(f"kind {name}: missing {missing}")
        if row["family"] not in families:
            raise KindListError(
                f"kind {name}: family {row['family']!r} is not one of {sorted(families)}"
            )
        if any(not isinstance(row[f], bool) for f in FLAGS):
            raise KindListError(
                f"kind {name}: {', '.join(FLAGS)} must be true or false"
            )
    return data


def _data() -> dict:
    try:
        return _load(PATH.stat().st_mtime)
    except (OSError, ValueError) as exc:  # a json error is a ValueError
        if isinstance(exc, KindListError):
            raise
        raise KindListError(
            f"the kind list could not be read ({type(exc).__name__})"
        ) from exc


def norm(kind: str | None) -> str:
    k = str(kind or "").strip().lower().replace(" ", "_")
    return k or UNKNOWN


def kinds() -> dict[str, dict]:
    """Every kind, in the file's order: id -> {label, noun, family, routed, code_decided, picker_needs_switch}."""
    return dict(_data()["kinds"])


def families() -> dict[str, str]:
    """family id -> its label."""
    return dict(_data()["families"])


def has(kind: str | None) -> bool:
    return norm(kind) in _data()["kinds"]


def row(kind: str | None) -> dict | None:
    return _data()["kinds"].get(norm(kind))


def family_of(kind: str | None) -> str | None:
    """The review family of a kind; None for unknown, other or a kind not on the list (never a guess)."""
    r = row(kind)
    return r["family"] if r else None


def label_of(kind: str | None) -> str:
    r = row(kind)
    return r["label"] if r else "Unknown"


def noun_of(kind: str | None) -> str | None:
    """The noun a sentence uses for a kind, or None (a kind outside the list is a "document" to the caller)."""
    r = row(kind)
    return r["noun"] if r else None


def routed_kinds() -> tuple[str, ...]:
    """The kinds the upload sorter has cues for, in the list's order."""
    return tuple(k for k, r in _data()["kinds"].items() if r["routed"])


def confirmable_kinds(*, with_switch_kinds: bool) -> tuple[str, ...]:
    """The kinds a person may choose in the kind picker: the routed ones, and the switch-gated ones only when `with_switch_kinds`."""
    return tuple(
        k
        for k, r in _data()["kinds"].items()
        if r["routed"] or (with_switch_kinds and r["picker_needs_switch"])
    )


def cover_kinds() -> tuple[str, ...]:
    """The kinds the title-block reader (`document_kind`) may name from a document's number, title or cover."""
    return tuple(k for k, r in _data()["kinds"].items() if r["cover_decided"])


def paper_kinds() -> tuple[str, ...]:
    """The closed list the paper-kind reading answers from: the kinds it may decide by itself, then `other` (a real answer)."""
    return (*(k for k, r in _data()["kinds"].items() if r["code_decided"]), OTHER)


def problems(sorter_kinds, table_kinds) -> list[str]:
    """Where another file names a kind this list does not hold: the sorter's cue kinds and the engine table's rows (plain words)."""
    held = set(_data()["kinds"])
    out = [
        f"the sorter has cues for {k!r}, which is not on the kind list"
        for k in sorter_kinds
        if k not in held
    ]
    out += [
        f"the engine table has a row for {k!r}, which is not on the kind list"
        for k in table_kinds
        if k not in held | {UNKNOWN, OTHER}
    ]
    out += [
        f"the kind list says {k!r} is routed but the sorter has no cues for it"
        for k in routed_kinds()
        if k not in set(sorter_kinds)
    ]
    return out
