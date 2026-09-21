"""B23 — a model-supplied quote is verified against its source or it is not used.

In the Phase 0.5 run the model was told, in the prompt, that every quote it output
must appear verbatim in the evidence it was given. It returned the clause with the
typographic inch mark `1/16”` rewritten as a straight `1/16"`. That one character
is harmless. What it proves is not: the model silently edits source text it has
been instructed to reproduce, and nothing in the path checked.

So quotes are normalised down a CLOSED list and then compared EXACTLY. The closed
list is the whole safety argument: every entry is a difference in typography or
whitespace that cannot change what an engineer reads. Nothing that could change a
meaning is normalised, which is why `1.6` never becomes `1.5`, `at least` never
becomes `approximately`, and `>=` never becomes `>`.

THE CLOSED LIST, and adding to it is a design decision, not a bug fix:

  1. curly quotes  ’ ‘ ” “  ->  ' "
  2. en dash and em dash  – —  ->  -
  3. non-breaking space  ->  normal space
  4. repeated whitespace  ->  one space
  5. leading and trailing whitespace stripped

NOT normalised, deliberately: case, digits, decimal points, units, operators,
comparison words, punctuation other than the dashes above, spelling, word order.
No stemming, no unit conversion, no number reformatting, no case folding. A quote
differing from its source in any of those is REJECTED.

Rejection is not repair. A failed quote does not get corrected to the source text —
that would launder a model's edit into a verified citation. The finding abstains,
the failure is recorded, and the model's text is preserved separately as unverified.
"""

from __future__ import annotations

#: Every substitution applied, in order. The list is closed; see the docstring.
_SUBSTITUTIONS = (
    ("’", "'"),      # right single quotation mark
    ("‘", "'"),      # left single quotation mark
    ("‛", "'"),      # single high-reversed-9
    ("”", '"'),      # right double quotation mark
    ("“", '"'),      # left double quotation mark
    ("‟", '"'),      # double high-reversed-9
    ("′", "'"),      # prime, used for feet/minutes
    ("″", '"'),      # double prime, used for inches/seconds
    ("–", "-"),      # en dash
    ("—", "-"),      # em dash
    ("‒", "-"),      # figure dash
    ("−", "-"),      # minus sign
    (" ", " "),      # non-breaking space
    (" ", " "),      # figure space
    (" ", " "),      # narrow no-break space
)

#: Reasons, so a caller can report WHY rather than only that it failed.
OK = "ok"
EMPTY_QUOTE = "empty_quote"
NO_SOURCE = "no_source_text"
NOT_FOUND = "not_present_in_source"


def normalise(text: str | None) -> str:
    """Apply the closed list, and nothing else.

    Rules 1-3 are character substitutions; rule 4 collapses runs of whitespace of
    any kind to a single space; rule 5 strips the ends. Case is untouched.
    """
    s = str(text or "")
    for old, new in _SUBSTITUTIONS:
        s = s.replace(old, new)
    return " ".join(s.split())


def validate(quote: str | None, source_text: str | None) -> tuple[bool, str]:
    """Does `quote` appear in `source_text` after the closed normalisation?

    Containment, not equality: a quote is a fragment of its source by definition.
    Both sides go through exactly the same normalisation, so the comparison is
    symmetric in what it forgives.
    """
    if not str(quote or "").strip():
        return False, EMPTY_QUOTE
    if not str(source_text or "").strip():
        return False, NO_SOURCE
    needle = normalise(quote)
    haystack = normalise(source_text)
    if not needle:
        return False, EMPTY_QUOTE
    return (needle in haystack, OK if needle in haystack else NOT_FOUND)


def validate_citation(quote: str | None, *, source_text: str | None,
                      expected_document_id: str | None = None,
                      actual_document_id: str | None = None,
                      expected_page: int | None = None,
                      actual_page: int | None = None) -> dict:
    """A quote plus the document and page it claims to come from.

    A quote that is verbatim but attributed to the wrong document or page is not a
    valid citation. `contractor_quote` must resolve to the contractor document and
    page; `requirement_quote` to the standard document and page. Both are checked
    here so no caller has to remember to.
    """
    ok, reason = validate(quote, source_text)
    failures = [] if ok else [reason]
    if expected_document_id is not None and actual_document_id is not None \
            and str(expected_document_id) != str(actual_document_id):
        failures.append("document_mismatch")
    if expected_page is not None and actual_page is not None \
            and int(expected_page) != int(actual_page):
        failures.append("page_mismatch")
    return {
        "valid": not failures,
        "failures": failures,
        "quote_as_given": quote,
        "quote_normalised": normalise(quote),
        "document_id": actual_document_id,
        "page": actual_page,
    }


def check_proposal(proposal: dict, *, contractor_source: str | None,
                   requirement_source: str | None,
                   contractor_document_id: str | None = None,
                   contractor_page: int | None = None,
                   requirement_document_id: str | None = None,
                   requirement_page: int | None = None) -> dict:
    """Validate a model proposal's two quotes and say what status it may carry.

    Returns `{"valid", "checks", "safe_status", "unverified_text"}`.

    When either quote fails, `safe_status` is `NEEDS_ENGINEER_REVIEW` and the
    model's own text is handed back under `unverified_text` rather than being
    stored as evidence. A caller must not promote a proposal to COMPLIANT or
    NON_COMPLIANT while `valid` is False.
    """
    checks = {
        "contractor_quote": validate_citation(
            proposal.get("contractor_quote"), source_text=contractor_source,
            expected_document_id=contractor_document_id,
            actual_document_id=proposal.get("contractor_document_id",
                                            contractor_document_id),
            expected_page=contractor_page,
            actual_page=proposal.get("contractor_page")),
        "requirement_quote": validate_citation(
            proposal.get("requirement_quote"), source_text=requirement_source,
            expected_document_id=requirement_document_id,
            actual_document_id=proposal.get("requirement_document_id",
                                            requirement_document_id),
            expected_page=requirement_page,
            actual_page=proposal.get("requirement_page")),
    }
    valid = all(c["valid"] for c in checks.values())
    return {
        "valid": valid,
        "checks": checks,
        # NOT the model's status. A proposal whose citations do not resolve may
        # not carry a verdict, whatever it asked for.
        "safe_status": None if valid else "NEEDS_ENGINEER_REVIEW",
        "unverified_text": None if valid else {
            "contractor_quote": proposal.get("contractor_quote"),
            "requirement_quote": proposal.get("requirement_quote"),
            "note": "preserved as unverified model output; not stored as evidence",
        },
    }
