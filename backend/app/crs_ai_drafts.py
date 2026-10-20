"""Order 161 D, second part: ONE ROW PER FIELD for the AI / web check drafts,
and no placeholder text ever takes a CRS row (planner answer on #692).

Two AI drafts about the same datasheet field ("Minimum operating pressure"
twice) were two rows. `merge` marks them: the lowest id leads, carries both
drafts' words (as its `finding`), every id (`crs_merged_ids`), the key a number could
have been issued under (`crs_member_keys`) and a key that depends on the field
alone (`crs_key`, so the row's number survives a draft being added or
dropped); the others are `crs_skip`. When the drafts differ the row keeps all
of them and says so - never one picked silently. A draft that says nothing
(empty, "n/a", "-") is `crs_skip` as well: no row, still in the review data.

Only drafts in the same state merge: an engineer's confirmed draft is their
own comment and is never merged with an unconfirmed one, and two confirmed
drafts merge only when the engineer worded them the same.

In place and idempotent, like `crs_item_series.merge`. GENERAL: nothing here
knows a sheet's layout or a draft's wording.
"""

from __future__ import annotations

import re

#: Text that is a stand-in for "nothing to say".
_PLACEHOLDERS = frozenset({"na", "tbd", "tbc", "none", "nil", "null"})


def _fold(text) -> str:
    return " ".join(str(text or "").lower().split())


def is_placeholder(text) -> bool:
    """No letters or digits, or only a stand-in word ("n/a", "TBD", "-")."""
    squeezed = re.sub(r"[\W_]+", "", _fold(text))
    return not squeezed or squeezed in _PLACEHOLDERS


def merge(findings: list[dict]) -> None:
    from . import crs_mapping as cm  # crs_mapping imports this module

    groups: dict[tuple, list[dict]] = {}
    for f in findings:
        if (
            cm._rejected(f)
            or f.get("origin") not in (cm._AI_ORIGIN, cm._WEB_ORIGIN)
            or f.get("crs_skip")
            or f.get("crs_merged_ids")
        ):
            continue
        confirmed = bool(f.get("confirmed_by"))
        if not (confirmed or f.get("engineer_comment")) and is_placeholder(
            cm._finding_text(f)
        ):
            f["crs_skip"] = True
            continue
        section = _fold(f.get("contractor_section"))
        if section:
            key = (
                f["origin"],
                f.get("contractor_page"),
                section,
                confirmed,
                _fold(f.get("engineer_comment")),
            )
            groups.setdefault(key, []).append(f)
    for key, group in groups.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda f: str(f.get("id") or ""))
        lead, rest = group[0], group[1:]
        lead["crs_member_keys"] = sorted(cm.finding_comment_key(f) for f in group)
        lead["crs_merged_ids"] = [f.get("id") for f in group if f.get("id")]
        lead["crs_key"] = cm.comment_key("ai drafts of one field", *key[:3])
        lead["finding"], lead["required_action"] = _drafts_text(cm, group), ""
        if lead["origin"] == cm._AI_ORIGIN:
            names = dict.fromkeys(n for n in map(cm._ai_relates_to, group) if n)
            lead["ai_rationale"] = (
                f"Relates to: {'; '.join(names) or 'no standard named'}."
            )
        for f in rest:
            f["crs_skip"] = True


def _drafts_text(cm, group: list[dict]) -> str:
    from .ai_engineering_check import UNVERIFIED_LABEL

    def one(f: dict) -> str:
        text = cm._finding_text(f)
        if f.get("origin") == cm._AI_ORIGIN and cm._ai_unverified(f):
            text = f"{UNVERIFIED_LABEL}. {text}"
        return text

    drafts = list(dict.fromkeys(one(f) for f in group if f.get("id")))
    distinct = {_fold(d): d for d in drafts}
    if len(distinct) == 1:
        return drafts[0]
    numbered = " ".join(f"({i}) {d}" for i, d in enumerate(distinct.values(), 1))
    return f"{len(distinct)} drafts about this field differ; all are kept. {numbered}"


def row_extras(finding: dict) -> dict:
    """What a row built from this finding adds: every finding it stands on
    (a decision on the row decides all of them, #986) and the keys its drafts
    were numbered under."""
    return {
        "finding_ids": finding.get("crs_merged_ids") or [finding.get("id") or ""],
        "member_keys": finding.get("crs_member_keys") or [],
    }
