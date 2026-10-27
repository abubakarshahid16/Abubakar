"""Which clause sentences get the per-run clause-check budget (order 235 item 1).

`ai_clause_checks_max_per_run` (20) caps the model calls a review spends turning
clause sentences into proposed checks. On a pump sheet 249 of 269 sentences were
"not asked (budget)", and the 20 were the first 20 that happened to print a
digit. The cap stays; what changes is WHO gets it. Rank the sentences, code-only
and the same for every sheet:

1. a sentence about a field THE SHEET STATES (every word of one of the sheet's
   current field names appears in the sentence): a check on it can be compared
   with a value the sheet gives;
2. a sentence of a standard THE SHEET CITES (selection method "referenced");
3. a sentence that prints a figure (a limit is a number);
4. the rest, in their stored order.

The order is only an order: a proposal is still a DRAFT the engineer decides,
and code still verifies every part against the sentence. Each standard's share
is reported (asked of its sentences), so a standard that got none is visible.
Ids, counts and file names only; no sentence text.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[a-z][a-z0-9]{2,}")
_FIGURE = re.compile(r"\d")
#: Words that carry no field meaning ("rated" is not a stop word: it is part of
#: field names like "rated flow").
_STOP = frozenset(
    {"the", "and", "for", "with", "per", "min", "max", "not", "all", "any"}
)


def words(text: str | None) -> frozenset[str]:
    return frozenset(w for w in _WORD.findall((text or "").lower()) if w not in _STOP)


def sheet_context(
    review_run_id: str | None,
) -> tuple[list[frozenset[str]], frozenset[str]]:
    """(the word sets of the sheet's current field names, the ids of the
    standards the sheet cites) for a run. Empty for no run or no data."""
    if not review_run_id:
        return [], frozenset()
    from . import applicability
    from .db import connect

    conn = connect()
    run = conn.execute(
        "SELECT submittal_document_id FROM review_runs WHERE id = ?", (review_run_id,)
    ).fetchone()
    if run is None:
        return [], frozenset()
    names = {
        r["field_name"]
        for r in conn.execute(
            "SELECT DISTINCT field_name FROM submittal_facts"
            " WHERE submittal_document_id = ? AND superseded_at IS NULL",
            (run["submittal_document_id"],),
        )
    }
    cited = frozenset(
        r["standard_document_id"]
        for r in conn.execute(
            "SELECT standard_document_id FROM review_applicable_standards"
            " WHERE review_run_id = ? AND included = 1 AND selection_method = ?",
            (review_run_id, applicability.METHOD_REFERENCED),
        )
    )
    return [w for w in (words(n) for n in names) if w], cited


def _tied(sentence_words: frozenset[str], fields: list[frozenset[str]]) -> bool:
    return any(f <= sentence_words for f in fields)


def rank(
    requirements: list[dict],
    fields: list[frozenset[str]],
    cited: frozenset[str],
    sentence_of,
) -> list[dict]:
    """The requirements, best first; ties keep their stored order."""

    def key(requirement: dict) -> tuple[bool, bool, bool]:
        text = sentence_of(requirement)
        return (
            not _tied(words(text), fields),
            requirement.get("standard_document_id") not in cited,
            not _FIGURE.search(text),
        )

    return sorted(requirements, key=key)


def ordered(
    requirements: list[dict], review_run_id: str | None, sentence_of
) -> list[dict]:
    """`rank` with the run's own context (the sheet's fields and cited standards)."""
    fields, cited = sheet_context(review_run_id)
    return rank(requirements, fields, cited, sentence_of)


def by_standard(ordered_requirements: list[dict], asked: int) -> dict:
    """{standard id: {label, sentences, asked}} for the first `asked` of the
    ordered requirements; a standard with sentences and no check asked is
    listed with 0. A sentence with no standard is not listed."""
    from . import standard_labels

    out: dict[str, dict] = {}
    for index, requirement in enumerate(ordered_requirements):
        sid = requirement.get("standard_document_id")
        if not sid:
            continue
        entry = out.setdefault(sid, {"label": "", "sentences": 0, "asked": 0})
        entry["sentences"] += 1
        entry["asked"] += index < asked
    for sid, name in standard_labels.filenames(sorted(out)).items():
        out[sid]["label"] = name
    return out


#: Standards named in the report line before "and N more".
LINE_STANDARDS = 6


def share_line(shares: dict | None) -> str:
    """ " Asked per standard: A 5 of 40; B 0 of 12." - empty for no shares (a
    run stored before the shares were kept says nothing about them)."""
    if not shares:
        return ""
    ranked = sorted(
        shares.values(), key=lambda e: (-e["sentences"], e.get("label") or "")
    )
    parts = [
        f"{e.get('label') or 'a standard with no file name'} "
        f"{e['asked']} of {e['sentences']}"
        for e in ranked[:LINE_STANDARDS]
    ]
    more = len(ranked) - LINE_STANDARDS
    tail = f"; and {more} more standard(s)" if more > 0 else ""
    return f" Asked per standard: {'; '.join(parts)}{tail}."
