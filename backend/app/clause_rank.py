"""Which clause sentences the per-run clause-check budget is spent on
(#1309 order 235.1).

`ai_requirements.propose_checks` may ask the local model about at most
`ai_clause_checks_max_per_run` sentences. The cap goes first to the sentences
that print a figure (a limit is a number), then to those that name a field THIS
sheet states, then to those of a standard THIS sheet cites, and only then to
the rest, in the order given. The same rule for every document: it reads the
run's own stored facts and applicable standards, never a layout or a wording.
Ranking only chooses what is asked; it decides no verdict.
"""

from __future__ import annotations

import re
from collections.abc import Callable

#: A stated field's name shorter than this is too common to tie a sentence to.
_MIN_FIELD_CHARS = 4
_FIGURE = re.compile(r"\d")


def _words(text: str) -> str:
    """Lower-case words with one space around each, so a name is found only
    as whole words ("area" is not found in "particular")."""
    return " " + " ".join(re.findall(r"[a-z0-9]+", (text or "").lower())) + " "


def context(review_run_id: str | None) -> dict:
    """What this run's sheet says: the names of the fields it states and the
    standards it cites. Empty without a run (compiling one standard has no
    sheet to rank against)."""
    from . import applicability
    from .db import connect

    empty = {"fields": [], "cited": frozenset()}
    if not review_run_id:
        return empty
    conn = connect()
    run = conn.execute(
        "SELECT submittal_document_id FROM review_runs WHERE id = ?", (review_run_id,)
    ).fetchone()
    if run is None:
        return empty
    fields = {
        _words(name).strip()
        for row in conn.execute(
            "SELECT field_name, field_label FROM submittal_facts"
            " WHERE submittal_document_id = ? AND superseded_at IS NULL",
            (run["submittal_document_id"],),
        )
        for name in (row["field_name"], row["field_label"])
    }
    cited = frozenset(
        row["standard_document_id"]
        for row in conn.execute(
            "SELECT standard_document_id FROM review_applicable_standards"
            " WHERE review_run_id = ? AND included = 1 AND selection_method = ?",
            (review_run_id, applicability.METHOD_REFERENCED),
        )
    )
    return {
        "fields": [f" {f} " for f in sorted(fields) if len(f) >= _MIN_FIELD_CHARS],
        "cited": cited,
    }


def order(
    requirements: list[dict],
    review_run_id: str | None,
    sentence_of: Callable[[dict], str],
) -> list[dict]:
    """The sentences, most worth asking first (a stable sort: ties keep their
    given order). Lower key asks first: prints a figure, names a stated field,
    belongs to a standard the sheet cites."""
    ctx = context(review_run_id)

    def key(requirement: dict) -> tuple:
        text = sentence_of(requirement)
        words = _words(text)
        return (
            not _FIGURE.search(text),
            not any(f in words for f in ctx["fields"]),
            requirement.get("standard_document_id") not in ctx["cited"],
        )

    return sorted(requirements, key=key)


def per_standard(requirements: list[dict], asked: list[dict]) -> dict[str, dict]:
    """Per standard (by document id, counts only): its sentences, how many
    were asked and how many the per-run cap left unasked."""
    out: dict[str, dict] = {}
    asked_ids = {id(r) for r in asked}
    for r in requirements:
        row = out.setdefault(
            r.get("standard_document_id") or "",
            {"sentences": 0, "asked": 0, "skipped": 0},
        )
        row["sentences"] += 1
        row["asked" if id(r) in asked_ids else "skipped"] += 1
    return out
