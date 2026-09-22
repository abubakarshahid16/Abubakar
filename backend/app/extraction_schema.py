"""B50 - the contract a model's extracted row must satisfy, or be refused.

A ROW THAT FAILS THIS SCHEMA IS A REFUSAL, NEVER A FACT. That is the whole
point: the alternative is coercion, and coercion is how a model's mistake
becomes a stored value nobody questions afterwards.

WHY THIS EXISTS AT ALL. Two malformations were recorded from a real 9B run on
the frozen packet, and neither was caught by anything, for the only reason that
nothing read them:

  * `missing_evidence` came back as the STRING "None", where a list was
    specified. A caller doing `if not missing_evidence` sees a non-empty
    string, concludes evidence WAS named, and proceeds - the string "None"
    means its own opposite.
  * `contractor_page` came back as the STRING "page 4", where an integer was
    specified. `quotes.check_proposal` does `int(expected_page)` unguarded, so
    that value raises `ValueError` rather than being refused: a malformation
    would have become a 500 the moment anything wired it up.

So the two checks below are not hypothetical types. They are the two failures
that actually happened, with the model's own output as the test fixture.

STRICT MEANS STRICT. `extra="forbid"` because a model asked for JSON returns
extra keys cheerfully, and a row carrying a key it was never asked for did not
follow the contract. `strict=True` on the integer because pydantic would
otherwise accept "4" for 4 - lenient parsing is exactly the coercion this
module exists to refuse.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

#: Refusal slugs. They name what the ROW or the RESPONSE did, never what the
#: pipeline lacks - the rule `chunker.py`'s exclusion vocabulary sets out for
#: itself, because a slug describing the build goes false the day it ships.
ROW_INVALID = "schema_row_invalid"
PAGE_UNPARSEABLE = "schema_page_response_unparseable"
PAGE_NOT_A_LIST = "schema_page_response_not_a_list"


class ExtractedRow(BaseModel):
    """One value a model claims to have read off a datasheet page.

    Every field is required. A model that cannot fill one of them has not read
    the value, and `label` without `value` or `source_text` without a page is
    not a partial success - it is a row that cannot be validated later by
    B23 or located on the page, so it cannot be stored.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    #: Verbatim as printed, typos kept. A normalised label cannot be found on
    #: the page again, and B23 works on what the page actually says.
    label: str
    #: The scoping heading - Rated, Normal, Minimum, Material 1, Nozzle N1.
    #: EMPTY IS ALLOWED AND MEANS "this field has one column", which is a
    #: claim; it is not a default for "I could not tell". A row whose column
    #: cannot be determined on a multi-column field is refused by validator 4,
    #: not shipped with this left blank.
    column_header: str = ""
    value: str
    unit: str = ""
    is_blank: bool
    page: int
    #: The verbatim span holding label and value, which B23 checks against the
    #: page text. Without it a fact cannot be proven to come from where it says.
    source_text: str

    @field_validator("label", "value", "source_text")
    @classmethod
    def _not_blank(cls, text: str) -> str:
        if not text.strip():
            raise ValueError("must not be empty or whitespace")
        return text

    @field_validator("page")
    @classmethod
    def _real_page(cls, page: int) -> int:
        if page < 1:
            raise ValueError("page numbers start at 1")
        return page


def validate_row(raw: Any) -> tuple[ExtractedRow | None, str | None]:
    """`(row, None)` or `(None, reason)`. Never raises, never coerces.

    The reason is a sentence naming the field and what was wrong with it,
    because a refusal nobody can act on is only marginally better than a
    silent drop.
    """
    if not isinstance(raw, dict):
        return None, f"{ROW_INVALID}: expected an object, got {type(raw).__name__}"
    try:
        return ExtractedRow.model_validate(raw), None
    except ValidationError as exc:
        parts = []
        for error in exc.errors():
            where = ".".join(str(p) for p in error["loc"]) or "(row)"
            parts.append(f"{where}: {error['msg']}")
        return None, f"{ROW_INVALID}: " + "; ".join(parts)


def validate_page_response(text: str) -> tuple[list[ExtractedRow], list[str]]:
    """Every row a page's response yields, and a reason for each one refused.

    A RESPONSE THAT WILL NOT PARSE IS A PAGE REFUSAL, not an empty page: those
    are different facts about the page and only one of them is about the page
    at all. The distinction is B44's, applied to the model instead of the file.
    """
    body = (text or "").strip()
    if not body:
        return [], [f"{PAGE_UNPARSEABLE}: the response was empty"]
    if body.startswith("```"):
        body = body.split("```")[1] if body.count("```") >= 2 else body
        body = body[4:].strip() if body.lower().startswith("json") else body.strip()
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        return [], [f"{PAGE_UNPARSEABLE}: {exc.msg} at position {exc.pos}"]
    if isinstance(parsed, dict):
        parsed = parsed.get("rows", parsed.get("values", parsed))
    if not isinstance(parsed, list):
        return [], [f"{PAGE_NOT_A_LIST}: got {type(parsed).__name__}"]

    rows: list[ExtractedRow] = []
    refusals: list[str] = []
    for index, raw in enumerate(parsed):
        row, reason = validate_row(raw)
        if row is None:
            refusals.append(f"row {index}: {reason}")
        else:
            rows.append(row)
    return rows, refusals


class Refusals(BaseModel):
    """What a page produced that was not stored, kept beside what was.

    Counted per reason rather than listed only, because "11 rows refused" and
    "11 rows refused, all of them for a missing column header" are different
    engineering problems and the second is actionable.
    """

    model_config = ConfigDict(extra="forbid")

    page: int
    reasons: list[str] = Field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.reasons)
