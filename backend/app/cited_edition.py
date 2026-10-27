"""R7 (#771): a submittal that cites one edition of a standard while the library holds another is
SAID, never read as the same edition silently.

`standard_ids.find_citations` reads a citation without its year ("API 650 (2013)" is the standard
"API 650"), and `applicability.find_standard` matches the library by number, so a datasheet citing
the 2013 edition of API 650 was reviewed against whatever edition the library holds with nothing said.
Here the year the submittal prints right after a citation is read, the year the library entry's own
file name or title prints is read, and when BOTH are known and differ the engineer gets a note.

HONEST THREE WAYS: same, different, or not known. Nothing is said when either year is not printed
(an edition is never guessed from nothing), when the submittal cites one standard under two different
years, or when the file name and title give two years. A standard's own number ("NFPA 2001"), an
addendum year, a date and a pressure rating are not editions: the rules are `crs_reference.edition_of`'s.
The held edition is read from the file name and title each time, not stored in a new column (said in
the note's limits). Read only; no network; no document text leaves the machine.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from . import crs_reference, standard_ids

NOTE = "Cited edition differs from the library's - engineer to check"

#: The year printed right after a citation: "(2013)", "-2020", ", 2013", ": 2020", "edition 2013".
_AFTER = re.compile(
    r"^[ \t]*[,:;(\[\-\u2013/]*[ \t]*(?:(?:edition|ed\.?|rev\.?|issue|version)[ \t]*)?[,:(\-\u2013/]*"
    r"[ \t]*((?:19[5-9]|20[0-4])\d)(?![\dA-Za-z]|\.\d)",
    re.IGNORECASE,
)


_ARTICLE = {"older": "an older", "newer": "a newer"}


def cited_years(text: str) -> dict[str, tuple[str, str | None]]:
    """{identifier key: (identifier as printed, the edition year printed after it or None)}.
    A standard cited under two different years is cited with None: which one is meant is unknown."""
    found: dict[str, tuple[str, str | None]] = {}
    conflicted: set[str] = set()
    text = text or ""
    for ident, _start, end in standard_ids.find_citations(text):
        match = _AFTER.match(text[end : end + 40])
        # the rules for "is this year an edition" (a rating, a date, an addendum) are
        # `crs_reference.edition_of`'s, so it reads the citation with what follows the year
        year = (
            crs_reference.edition_of(f"{ident} {text[end : end + match.end() + 8]}")
            if match
            else None
        )
        key = standard_ids.key(ident)
        seen = found.get(key)
        if key in conflicted:
            continue
        if seen is None:
            found[key] = (ident, year)
        elif year is not None and seen[1] is not None and seen[1] != year:
            found[key] = (seen[0], None)
            conflicted.add(key)
        elif seen[1] is None and year is not None:
            found[key] = (seen[0], year)
    return found


def held_year(entry: dict) -> str | None:
    """The edition the library entry's file name and title print, or None when neither prints one
    or they print two different years."""
    years = {
        year
        for year in (
            crs_reference.edition_of(str(entry.get(field) or ""))
            for field in ("filename", "title")
        )
        if year
    }
    return next(iter(years)) if len(years) == 1 else None


def differs(
    text: str, library: list[dict], matching: Callable[[list[dict], str], list[dict]]
) -> list[dict]:
    """One item per cited standard the library holds whose printed edition year differs from EVERY
    held copy's: {identifier, cited, held, relation, document_id, held_name}. A library that holds
    two editions of a standard says nothing when one of them is the cited edition, and nothing
    when a held copy prints no year (it could be the cited one)."""
    out: list[dict] = []
    for _key, (ident, cited) in cited_years(text).items():
        entries = matching(library, ident)
        years = [held_year(entry) for entry in entries]
        if cited is None or not entries or None in years or cited in years:
            continue
        # compare against the nearest held edition; the note names it
        nearest = min(
            range(len(entries)), key=lambda i: abs(int(years[i]) - int(cited))
        )
        entry, held = entries[nearest], years[nearest]
        out.append(
            {
                "identifier": ident,
                "cited": cited,
                "held": held,
                "relation": "older" if cited < held else "newer",
                "document_id": entry["id"],
                "held_name": entry.get("filename") or entry.get("title") or "",
                "held_all": [e.get("filename") or "" for e in entries],
            }
        )
    return out


def notes(items: list[dict]) -> list[dict]:
    """The Review notes (internal, never a contractor comment) for `differs`' items."""
    return [
        {
            "note": NOTE,
            "standard": item["identifier"],
            "count": None,
            "detail": (
                f"The datasheet cites {item['identifier']} ({item['cited']}); the library holds "
                f"{item['held_name']} ({item['held']}). The cited edition is {item['relation']} "
                "than the held one. This review checked the requirements of the held edition. "
                "Confirm that the cited edition does not change them, or upload the cited edition."
            ),
        }
        for item in items
    ]


def for_submittal(
    submittal_id: str, allowed_document_ids: frozenset[str]
) -> list[dict]:
    """The Review notes of one submittal, read under the caller's grants: only library standards the
    caller may read are compared, and only the submittal's own text is read. A check that cannot
    run is said (the error's type only), never skipped silently and never fatal to the export."""
    from . import applicability  # late: applicability reads the library and the chunks

    def matching(library: list[dict], ident: str) -> list[dict]:
        return [
            entry
            for entry in library
            if any(
                standard_ids.same_standard(ident, name)
                for name in applicability._library_names(entry)
            )
        ]

    try:
        text = applicability._submittal_text(submittal_id, allowed_document_ids)
        library = applicability._library(allowed_document_ids)
        return notes(differs(text, library, matching))
    except Exception as exc:  # noqa: BLE001 - a side note must not fail the CRS content
        return [
            {
                "note": NOTE,
                "standard": "",
                "count": None,
                "detail": f"The cited-edition check could not run ({type(exc).__name__}).",
            }
        ]
