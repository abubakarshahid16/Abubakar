"""DOCUMENT GROUPS AND ROUTING BY FAMILY (order 14, planner 26 Nov 2026 14:45, lane L3; builder H).

`reference/document_groups.json` (DATA, not code) holds the kinds of document a contractor sends, each in ONE of the six review
families of the one kind list (`kind_list`, builder G), and per family the method kind a paper of that family is reviewed with when its
own kind is not one the method knows. Plain code; no model, no network, no write.

WHERE A PAPER GOES (`place`). A paper whose kind is on the kind list keeps that kind and its family ("kind"): nothing changes for it,
so a Claude review of a scored kind is unchanged. Any other paper is NEVER refused:
  - a group whose words stand, as whole words, in what the review already holds (the AI's subject of the paper, the paper's file
    name) names its group and family ("group");
  - else the family sharing the most words with them is the NEAREST family ("nearest"), and with none shared the table's
    `default_family` ("default"); both are logged "new kind seen" and the run records it.
A paper not placed by its kind is labelled "not yet scored for this kind" on its page and comment sheet (`not_scored`), whatever its
family's scores: no table and no switch makes it scored.

ROUTING (`route`, the engine's one hook after it names the paper). The run's identity record gains `family`, `document_group`,
`kind_placed` and `new_kind_seen` (codes and ids only, never the paper's words). With the switch KIND_FAMILY_ROUTE_ENABLED on,
a paper the method calls `other` is reviewed with its family's `route_kind` (its rule labels, method books and checklist floor); OFF
(the default, update 12 review B1: a Claude review stays exactly as before until a scored read), it is reviewed as `other`. A table that cannot be read places nothing and routes nothing: the review goes on as
before and its record says the step did not run (`aim_review.faults`).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

PATH = Path(__file__).parent / "reference" / "document_groups.json"
KIND, GROUP, NEAREST, DEFAULT = "kind", "group", "nearest", "default"
#: Words that say nothing about a document's kind, left out of the nearest-family count.
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "this",
        "to",
        "with",
        "document",
        "documents",
        "doc",
        "paper",
        "sheet",
        "part",
        "rev",
        "revision",
    ]
)
NOT_SCORED = "not yet scored for this kind"


class DocumentGroupsError(ValueError):
    """The table is missing or malformed: nothing is placed or routed from it."""


@dataclass(frozen=True)
class Placement:
    family: str
    group: str | None
    how: str  # KIND | GROUP | NEAREST | DEFAULT
    route_kind: (
        str | None
    )  # the method kind a paper the method calls `other` is reviewed with (None: the paper keeps its kind)

    @property
    def new_kind_seen(self) -> bool:
        return self.how in (NEAREST, DEFAULT)


def _norm(text: str | None) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


@lru_cache(maxsize=1)
def _load(mtime: float) -> dict:  # noqa: ARG001 - the cache key: re-read when the file changes
    from . import kind_list
    from .aim_review.library import KINDS

    data = json.loads(PATH.read_text(encoding="utf-8"))
    fams, groups = data.get("families"), data.get("groups")
    if not isinstance(fams, dict) or set(fams) != set(kind_list.families()):
        raise DocumentGroupsError("`families` must be the kind list's six families")
    for f, row in fams.items():
        if not isinstance(row, dict) or row.get("route_kind") not in KINDS:
            raise DocumentGroupsError(
                f"family {f}: `route_kind` must be one of the method's kinds"
            )
    if data.get("default_family") not in fams:
        raise DocumentGroupsError("`default_family` must be one of the families")
    if not isinstance(groups, dict) or not groups:
        raise DocumentGroupsError("`groups` must hold at least one group")
    for g, row in groups.items():
        words = row.get("words") if isinstance(row, dict) else None
        if (
            not isinstance(row, dict)
            or row.get("family") not in fams
            or not str(row.get("label") or "").strip()
        ):
            raise DocumentGroupsError(
                f"group {g}: needs a label and one of the families"
            )
        if row.get("kind") is not None and not kind_list.has(row["kind"]):
            raise DocumentGroupsError(
                f"group {g}: kind {row['kind']!r} is not on the kind list"
            )
        if (
            not isinstance(words, list)
            or not words
            or any(not _norm(w) or _norm(w) != w for w in words)
        ):
            raise DocumentGroupsError(
                f"group {g}: `words` must be plain lower-case words"
            )
    return data


def table() -> dict:
    try:
        return _load(PATH.stat().st_mtime)
    except (OSError, ValueError) as exc:
        if isinstance(exc, DocumentGroupsError):
            raise
        raise DocumentGroupsError(
            f"the document groups could not be read ({type(exc).__name__})"
        ) from exc


def _hits(row: dict, text: str) -> tuple[int, int]:
    """(how many of the group's names stand in the text as whole words, the longest one's length)."""
    found = [
        w
        for w in row["words"]
        if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", text)
    ]
    return len(found), max((len(w) for w in found), default=0)


def place(kind: str | None, texts) -> Placement:
    """Where a paper goes: by its kind when the kind list holds it, else by its group's words, else the nearest family."""
    from . import kind_list

    data, k = table(), kind_list.norm(kind)
    groups, fams = data["groups"], data["families"]
    text = _norm(" ".join(str(t) for t in texts or () if t))
    if kind_list.has(k):
        fam = kind_list.family_of(k)
        ranked = sorted(
            (
                (_hits(row, text), -i, g)
                for i, (g, row) in enumerate(groups.items())
                if row["family"] == fam
            ),
            reverse=True,
        )
        best = next((g for (n, _ln), _i, g in ranked if n), None)
        own = next((g for g, row in groups.items() if row.get("kind") == k), None)
        return Placement(fam, best or own, KIND, None)
    ranked = sorted(
        ((_hits(row, text), -i, g) for i, (g, row) in enumerate(groups.items())),
        reverse=True,
    )
    if ranked and ranked[0][0][0]:
        g = ranked[0][2]
        fam = groups[g]["family"]
        return Placement(fam, g, GROUP, fams[fam]["route_kind"])
    words = set(text.split()) - _STOP
    order = list(kind_list.families())
    shared = {
        f: len(
            words
            & {
                t
                for row in groups.values()
                if row["family"] == f
                for w in (*row["words"], _norm(row["label"]))
                for t in w.split()
            }
        )
        for f in order
    }
    fam = max(order, key=lambda f: (shared[f], -order.index(f)))
    if not shared[fam]:
        fam = data["default_family"]
        return Placement(fam, None, DEFAULT, fams[fam]["route_kind"])
    return Placement(fam, None, NEAREST, fams[fam]["route_kind"])


def _title(conn, paper_id: str) -> str:
    """The paper's file name without its extension (matched in memory only, never stored or logged)."""
    if conn is None:
        return ""
    try:
        row = conn.execute(
            "SELECT filename FROM documents WHERE id = ?", (str(paper_id),)
        ).fetchone()
    except sqlite3.Error:  # no documents table (a test copy): no title
        return ""
    return re.sub(r"\.[A-Za-z0-9]{1,5}$", "", str((row or [""])[0] or ""))


def enabled() -> bool:
    from .config import settings

    return bool(getattr(settings, "kind_family_route_enabled", False))


def route(conn, state, ident: dict, record) -> dict:
    """THE engine's hook after the paper is named: sets `state.identity` (the run's record, `record(ident)`, with the placement) and
    returns the identity the review's later steps use (the family's `route_kind` for a paper the method calls `other`)."""
    state.identity = record(ident)
    try:
        p = place(
            ident.get("kind"),
            (
                ident.get("subject"),
                str(ident.get("subject_key") or "").replace("_", " "),
                _title(conn, state.paper_id),
            ),
        )
    except Exception as exc:  # noqa: BLE001 - never a failed review: placed by nothing, routed as before, and the run says so
        from .aim_review import faults

        faults.record(
            "aim_document_group", "placing the paper in a document family", exc
        )
        return ident
    state.identity |= {
        "family": p.family,
        "document_group": p.group,
        "kind_placed": p.how,
        "new_kind_seen": p.new_kind_seen,
    }
    if p.new_kind_seen:
        log.info(
            "general review %s: new kind seen; reviewed with the %s family (%s)",
            state.run_id,
            p.family,
            p.how,
        )
    if (
        p.how != KIND
        and p.route_kind
        and str(ident.get("kind") or "other") == "other"
        and enabled()
    ):
        state.identity["reviewed_as"] = p.route_kind
        return {**ident, "kind": p.route_kind}
    return ident


def not_scored(identity: dict | None) -> dict | None:
    """The score line of a paper NOT placed by its kind (`aim_review_measured.for_run`): "not yet scored for this kind", with the family
    it was reviewed with; None for a paper placed by its kind and for a run made before the placement was recorded."""
    i = identity if isinstance(identity, dict) else {}
    how = i.get("kind_placed")
    if how not in (GROUP, NEAREST, DEFAULT):
        return None
    from . import kind_list

    fam = kind_list.families().get(str(i.get("family") or ""), "an unknown")
    try:
        group = (table()["groups"].get(str(i.get("document_group") or "")) or {}).get(
            "label"
        )
    except DocumentGroupsError:
        group = None
    what = (
        f"{group}, a kind of document this app has not been measured on"
        if how == GROUP and group
        else "a kind of document this app has not seen before (new kind seen)"
    )
    return {
        "kind_label": group or "New kind",
        "found": None,
        "target": None,
        "verdict": NOT_SCORED,
        "sentence": f"Not yet scored for this kind: {what}. It was reviewed with the {fam.lower()} family"
        + (
            " (the nearest family by its words)."
            if how == NEAREST
            else " (the general family: no family shared its words)."
            if how == DEFAULT
            else "."
        ),
    }
