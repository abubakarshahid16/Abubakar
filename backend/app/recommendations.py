"""A "should" sentence of a standard is a RECOMMENDATION, recorded as its own type (order 288.2).

API RP 520 is a Recommended Practice: about 150 of its sizing and set-pressure sentences say
"should", and the extractor kept none of them. For a sheet whose design standard is RP 520 those
sentences are what the contract adopts. They are recorded now, as `requirement_type =
"recommendation"`, and a recommendation is never a limit:

* no number is kept from it (the sentence is advice, not a threshold), so a comparison cannot
  read it as a limit and it can never be matched to a sheet value;
* `standards.is_reviewable` refuses it to every existing review path, so nothing that reads
  requirements today can turn it into "does not meet";
* a sentence with "shall" / "must" AND "should" stays the mandatory requirement it was.

How a review raises a recommendation (a query to the engineer, never a verdict) is a separate step.
"""

from __future__ import annotations

import re

from . import requirement_quality

TYPE = "recommendation"
#: The types no review reads: a definition states no obligation, a recommendation is advice.
NOT_REVIEWED = (requirement_quality.DEFINITION, TYPE)

#: "should" and "should not" only. "may" is permission and "recommended" is not matched: the
#: coverage audit named "should" (4 of 147 held) and those are the words the owner asked for.
_RECOMMEND = re.compile(r"\bshould(?:\s+not)?\b", re.IGNORECASE)


def is_recommendation(sentence: str) -> bool:
    return bool(_RECOMMEND.search(sentence or ""))


def classify(sentence: str, limit: dict | None, mandatory: bool) -> str:
    """The stored type: a recommendation when no mandatory word is in the sentence, else what the
    parser always said."""
    from . import requirements_3b

    return requirements_3b.classify(sentence, limit) if mandatory else TYPE


CODE = "recommendation_query"


def named(applicable: list[dict]) -> set[str]:
    """The standards the datasheet itself NAMES (its design standards): the only ones whose
    recommendations a review raises (default house rule, to be confirmed by KJO)."""
    from . import applicability
    from .config import settings

    if not settings.recommendation_queries_enabled:
        return set()
    return {
        a["standard_document_id"]
        for a in applicable
        if a.get("selection_method") == applicability.METHOD_REFERENCED
    }


def left_out(
    row: dict, standard_id: str, design_standards: set[str], held_back: dict
) -> bool:
    """True when a recommendation takes no part in this review: its standard is not one the datasheet names.
    Counted in `held_back`, never in the scope ledger (advice is neither "applies" nor "does not apply" until a
    standard the sheet names makes it a question)."""
    if row.get("requirement_type") != TYPE or standard_id in design_standards:
        return False
    held_back[TYPE] = held_back.get(TYPE, 0) + 1
    return True


def hold_for_query(requirements: list[dict], held_items: list[dict]) -> list[dict]:
    """After every scope gate: a recommendation that still applies is never compared with a value (it has no
    limit); it becomes a held item, which the review turns into an engineer's query (`held_findings`), and the
    ledger counts as "applies, not checked" under its own reason."""
    advice = [r for r in requirements if r.get("requirement_type") == TYPE]
    held_items.extend(
        {"requirement": dict(r), "code": CODE, "detail": REASON} for r in advice
    )
    return [r for r in requirements if r.get("requirement_type") != TYPE]


REASON = "a recommendation of a standard this datasheet names: raised as a query, not compared with a value"


def query_words(requirement: dict, standard_label: str) -> str:
    """The query, in the words the finding carries. Never a verdict: the finding's status is the engineer's question."""
    clause = f" cl. {requirement['clause']}" if requirement.get("clause") else ""
    page = f" (p.{requirement['page']})" if requirement.get("page") else ""
    said = " ".join(str(requirement.get("requirement_text") or "").split())
    return (
        f'Query: recommended by {standard_label}{clause}{page}: "{said}" Please confirm or justify. '
        "This is a recommendation, not a requirement; it is not compared with the datasheet."
    )
