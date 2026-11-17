"""THE EDITION CHECK SHOWN IN THE CRS (order 14 lane G): the one home the one CRS builder (`crs_one.build_team`) and its
completeness check call.

What the contract's edition cutoff says of the edition the library HOLDS of each rule book the paper's points cite
(`standard_editions.book_verdict`: the issue date the book prints, verified on its page, else the edition year of its file
name, judged against the cutoff): the held edition binds, is later (for information only), is older than the one that binds,
cannot be told, or is not known. Shown two ways in the team file only:

  * the sheet "Editions": one row per cited, held book: the book, the edition held, where its date was read (page and the
    printed line), the status, the edition that binds when it is known, the caveat and why; one note line with the counts;
  * every book reference in a cell (the sheet CRS "Rule books and clauses", the sheet Evidence "Rule book", the sheet "Not a
    comment") carries the status in brackets, e.g. "BOOK-X [edition binds]".

AN ENGINEER NOTE, NEVER A VERDICT (CLAUDE.md rule 4). Nothing here makes a Pass or a Fail, changes a point, a decision or a
row count; a later or "cannot tell" book's clause quotes stay as they are. The contractor file never shows it: it changes
nothing a contractor must do. A book the caller may not read is never named (the points carry readable books only, rule 5).

OFF = BYTE-SAME. `verdicts` is None while STANDARD_EDITIONS_ENABLED is off, while no cutoff file names the contract, or when
that file cannot be read; then every cell and sheet is what it was. The real cutoff is values read from a contract, so it
lives only in a local, git-ignored file (`standard_editions.load_policies`), never in the repository. Reads only.
"""

from __future__ import annotations

from collections import Counter

from . import standard_editions as se
from .agent_run_crs import _cell
from .config import settings
from .db import connect

CONTRACT = "project-contract"
SHEET = "Editions"
COLUMNS = (
    "Rule book", "Edition held", "Where the date was read", "Printed line (verified on the page)", "Status",
    "Edition that binds", "Caveat", "Why", "Points citing it",
)  # fmt: skip
WIDTHS = (40, 14, 32, 50, 46, 20, 50, 60, 10)
#: the status in brackets after a book reference in a cell (one word set; an unknown status is "edition not known", never a guess)
BRACKETS = {
    se.BINDING: "edition binds",
    se.LATER: "later edition: for information only",
    se.EARLIER: "older edition: engineer to check",
    se.CANNOT_TELL: "edition: engineer to check",
    se.NOT_KNOWN: "edition not known",
}
NOT_A_VERDICT = (
    "An engineer note, never a Pass or a Fail: no point, decision or count changes with it; "
    "the clause quotes of a later or unclear edition stay as they are."
)


def _cutoff_on_file() -> bool:
    try:
        return se.load_policies().get(CONTRACT) is not None
    except (OSError, ValueError):
        return False


def verdicts(points: list[dict]) -> dict[str, dict] | None:
    """{book name: `standard_editions.book_verdict` result} for every held book the points cite, or None (switch off, no cutoff
    for the contract, or a cutoff file that cannot be read): None leaves the CRS byte-same."""
    if not settings.standard_editions_enabled or not _cutoff_on_file():
        return None
    books: dict[str, str] = {}
    for p in points:
        for b in p.get("books") or []:
            books.setdefault(b["name"], b["id"])
    conn = connect()
    out: dict[str, dict] = {}
    for name, doc in books.items():
        got = se.book_verdict(conn, doc, name, CONTRACT)
        if (
            got is None
        ):  # the switch or the file changed while building: show nothing rather than half
            return None
        out[name] = got
    return out


def mark(name: str | None, editions: dict | None) -> str | None:
    """A book reference with its edition status in brackets; unchanged while the check is off or the book is not judged."""
    if not name or editions is None or name not in editions:
        return name
    return (
        f"{name} [{BRACKETS.get(editions[name].get('status'), BRACKETS[se.NOT_KNOWN])}]"
    )


def _where(printed: dict) -> str | None:
    if printed.get("page"):
        return f"p.{printed['page']}: {printed.get('source')}"
    return printed.get("source")


def sheet(editions: dict, points: list[dict], not_held: list[str]) -> tuple:
    """The sheet "Editions": (columns, rows, widths, note). One row per held book the points cite, most cited first."""
    cited: Counter = Counter()
    for p in points:
        for b in p.get("books") or []:
            cited[b["name"]] += 1
    order = sorted(editions, key=lambda n: (-cited[n], n))
    rows = []
    for name in order:
        v = editions[name]
        printed = v.get("printed") or {}
        rows.append([_cell(c) for c in (
            name, printed.get("date"), _where(printed), printed.get("quote"), v.get("status"),
            v.get("binding"), v.get("caveat") or None, v.get("reason") or None,
            cited[name],
        )])  # fmt: skip
    counts = Counter(v.get("status") for v in editions.values())
    told = (
        "; ".join(f"{BRACKETS.get(s, s)}: {k}" for s, k in counts.most_common())
        or "none"
    )
    note = (
        f"{len(rows)} held rule book(s) cited by this paper's points, each judged against the contract's edition cutoff ({told}). "
        f"{len(not_held)} rule book(s) not held: edition not known (sheet Rule books not held). {NOT_A_VERDICT}"
    )
    return COLUMNS, rows, WIDTHS, note
