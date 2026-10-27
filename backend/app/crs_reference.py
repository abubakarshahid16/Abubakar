"""Order 227: what a CRS Standard Reference says about WHICH copy of the standard it cites.

A reader who has to open the clause needs the standard, its edition, the clause and the page
("SAES-G-005 (2023) cl. 4.3.5 (p.15)"). The edition is the one the library knows: stored on
the finding (`standard_edition`) or printed in the standard's own file name or title. Never
guessed, and a year that is not an edition is not read as one:

  * the standard's own NUMBER is not an edition ("ISO 2014", "NFPA 2001", "IEC 2000", "BS 1992":
    a four-digit number that is the first number in the name);
  * an addendum, amendment, errata, supplement or corrigendum year is not the edition
    ("API 650 2020 Addendum 1 2021" is the 2020 edition);
  * a date in a file name ("rev 2024-05-01") and a pressure class or rating ("Class 2000",
    "2500 psi", "# 1500") are numbers, not editions;
  * two different years left after those skips ("ISO 9001:2015 (reaffirmed 2020)", "rev 2019
    approved 2023", "2019-2023") cannot be told apart by any list of words, so the edition is not
    recorded rather than the last year guessed;
  * no edition known says so ("edition not recorded"); a name that already carries its edition
    year is not given it twice.
"""

from __future__ import annotations

import re

from . import standard_ids

NOT_RECORDED = "edition not recorded"

_NUMBERISH = re.compile(r"\d")
_SIDE_YEAR = re.compile(
    r"(?:addend\w*|amend\w*|errat\w*|suppl\w*|corrigend\w*|\bamd|\bcor|\badd)"
    r"[\s.\-_]*(?:no\.?)?[\s.\-_]*\d{0,2}[\s.\-_,:]*$"
    r"|(?:\+|\b)A\d{1,2}[\s.\-_,:]*$",
    re.IGNORECASE,
)
_DATE_TAIL = re.compile(r"[\-/]\d{1,2}[\-/]\d{1,2}(?!\d)")
_RATING_BEFORE = re.compile(r"(?:\bclass|\bcl\.?|#)[\s.\-_]*$", re.IGNORECASE)
_RATING_AFTER = re.compile(r"[\s\-_]*(?:psi|lbs?\b|#)", re.IGNORECASE)


def edition_of(name: str) -> str | None:
    """The edition year in a standard's name or title, or None. See the module note for
    what is NOT an edition."""
    text = str(name or "").replace("_", " ")
    first_number = _NUMBERISH.search(text)
    left: list[str] = []
    for found in standard_ids._EDITION_YEAR.finditer(text):
        if first_number and found.start() == first_number.start():
            continue  # the standard's own number ("ISO 2014")
        if _SIDE_YEAR.search(text[: found.start()]):
            continue  # an addendum or amendment year
        if _DATE_TAIL.match(text, found.end()):
            continue  # a date ("2024-05-01")
        if _RATING_BEFORE.search(text[: found.start()]) or _RATING_AFTER.match(
            text, found.end()
        ):
            continue  # a pressure class or rating ("Class 2000", "2500 psi")
        left.append(found.group(1))
    return left[0] if len(set(left)) == 1 else None


def tail(finding: dict, name: str, clause: str, page) -> str:
    """Everything a reference prints after the standard's name: edition, clause words, page."""
    return edition_words(finding, name) + clause + (f" (p.{page})" if page else "")


def edition_words(finding: dict, name: str) -> str:
    """The edition words for the standard called `name`: (2023), or (edition not recorded);
    nothing when the name already carries its edition year."""
    stored = str(finding.get("standard_edition") or "").strip()
    edition = stored or edition_of(name)
    if not edition:
        return f" ({NOT_RECORDED})"
    present = re.search(rf"(?<!\d){re.escape(edition)}(?!\d)", name)
    return "" if present else f" ({edition})"


def check_reference(finding: dict) -> str:
    """A kind B (datasheet check) row's Standard Reference (order 228.1): the source its
    checklist item cites, "API 520-I 3.20 (p.12)" with the page once located. A check with no
    source prints "Datasheet check" and nothing else; its program id is internal."""
    cited = " ".join(str(finding.get("standard_clause") or "").split())
    page = finding.get("standard_page")
    if not cited:
        return "Datasheet check"
    return f"{cited} (p.{page})" if page else cited


def check_id(finding: dict) -> str:
    """ "PSV-14" of a kind B check: the program's own id, for the internal copy only."""
    found = re.match(
        r"Datasheet check ([A-Z]+-[A-Z0-9]+)",
        finding.get("requirement_source_text") or finding.get("ai_rationale") or "",
    )
    return found.group(1) if found else ""


def engine_of(finding: dict) -> str:
    """The engine an AI draft says wrote it: the words after "Written by" up to the end of
    that sentence (", from the datasheet" or a full stop that ends a word). "an unnamed engine"
    and "a local model" are kept whole. Internal copy only."""
    found = re.search(
        r"Written by (.+?)(?:, from the datasheet|\.(?:\s|$)|$)",
        str(finding.get("ai_rationale") or ""),
    )
    return found.group(1).strip() if found else ""


def relates_to(rationale: str) -> str:
    """The standard name after "Relates to: ", without the engine sentence that may follow."""
    if "Relates to: " not in rationale:
        return ""
    return rationale.split("Relates to: ", 1)[1].split(" Written by ")[0].rstrip(".")


def internal_bits(finding: dict) -> list[str]:
    """What the INTERNAL reasoning cell keeps of a row's program-side names (order 228.1/228.2):
    the check's id and the engine that wrote a draft."""
    return [
        text
        for text in (
            f"Check: {check_id(finding)}" if check_id(finding) else "",
            f"Written by: {engine_of(finding)}" if engine_of(finding) else "",
        )
        if text
    ]
