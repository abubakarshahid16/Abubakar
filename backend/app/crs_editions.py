"""THE EDITION CHECK SHOWN IN THE CRS (order 14 lane G): the one home the one CRS builder (`crs_one.build_team`) and its
completeness check call.

What the contract's edition cutoff says of the edition the library HOLDS of each rule book the paper's points cite
(`standard_editions.book_verdict`: the issue date the book prints, verified on its page, else the edition year of its file
name, judged against the cutoff): the held edition binds, is later (for information only), is older than the one that binds,
cannot be told, or is not known. Shown two ways in the team file only:

  * the sheet "Editions": one row per cited, held book: the book, the edition held, where its date was read (page and the
    printed line), the status, the edition that binds when it is known, the caveat and why; one note line with the counts;
  * every book reference in a cell (the sheet CRS "Rule books and clauses", the sheet Evidence "Rule book", the sheet "Not a
    comment") carries the status in brackets, e.g. "BOOK-X [edition: binds]".

The words are ONE set (`crs_ai_words.edition_status_words`, rule 8). A date read only from the book's FILE NAME is a guess: it
never says "binds", "later" or "older", only "year from the file name only, engineer to check", and its Why says so. Books are
judged by DOCUMENT (two held books of one name each get their own verdict); a reference by name whose copies differ says so.

AN ENGINEER NOTE, NEVER A VERDICT (CLAUDE.md rule 4). Nothing here makes a Pass or a Fail, changes a point, a decision or a
row count; a later or "cannot tell" book's clause quotes stay as they are. The contractor file never shows it: it changes
nothing a contractor must do. A book the caller may not read is never named (the points carry readable books only, rule 5).

OFF = BYTE-SAME. `verdicts` is None while STANDARD_EDITIONS_ENABLED is off, while no cutoff file names the contract, or when
that file cannot be read; then every cell and sheet is what it was. The real cutoff is values read from a contract, so it
lives only in a local, git-ignored file (`standard_editions.load_policies`), never in the repository. Reads only.
"""

from __future__ import annotations

from collections import Counter

from . import agent_edition
from . import crs_ai_words as words
from . import standard_editions as se
from .agent_run_crs import _cell
from .config import settings
from .db import connect

CONTRACT = "project-contract"
SHEET = "Editions"
COLUMNS = (
    "Rule book", "Held document", "Edition held", "Where the date was read", "Printed line (verified on the page)", "Status",
    "Edition that binds", "Caveat", "Why", "Points citing it",
)  # fmt: skip
WIDTHS = (40, 22, 14, 32, 50, 46, 20, 50, 60, 10)
FILE_NAME_WHY = "The date is the edition year in the book's file name, not a date printed in the book: a guess, engineer to check."
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
    """{held document id: `standard_editions.book_verdict` result with its "book" name} for every held book the points cite, or
    None (switch off, no cutoff for the contract, or a cutoff file that cannot be read): None leaves the CRS byte-same."""
    if not settings.standard_editions_enabled or not _cutoff_on_file():
        return None
    books: dict[str, str] = {}
    for p in points:
        for b in p.get("books") or []:
            books.setdefault(b["id"], b["name"])
    conn = connect()
    out: dict[str, dict] = {}
    for doc, name in books.items():
        got = se.book_verdict(conn, doc, name, CONTRACT)
        if got is None:  # the switch or the file changed while building: nothing
            return None
        out[doc] = {**got, "book": name}
    return out


def by_name(editions: dict | None) -> dict[str, dict] | None:
    """{book name: its result} for a reference that names a book only; held copies of one name whose words differ: {"differs"}."""
    if editions is None:
        return None
    out: dict[str, dict] = {}
    for v in editions.values():
        seen = out.get(v["book"])
        same = seen is None or words.edition_status_words(
            seen
        ) == words.edition_status_words(v)
        out[v["book"]] = v if seen is None else (seen if same else {"differs": True})
    return out


def mark(
    name: str | None, editions: dict | None, doc_id: str | None = None
) -> str | None:
    """A book reference with its edition status in brackets (by its document when known, else by its name); unchanged while the
    check is off or the book is not judged."""
    if not name or editions is None:
        return name
    result = editions.get(doc_id) if doc_id else None
    result = result or (by_name(editions) or {}).get(name)
    return f"{name} [{words.edition_status_words(result)}]" if result else name


def names_without_unrecorded(points: list[dict], editions: dict | None) -> list[dict]:
    """W-H10 (order 14): a point's field said "(edition not recorded)" while the same row's book said "[edition: binds]". When every
    held book the point cites has its edition status on this file, the field (and an action that cites the book) drops those words:
    the edition is said once, in the book's brackets and on the sheet Editions. Off (None) or a book not judged: the points as they
    are. The page's list is worded the same way (`review_points_service._assemble`), so the page and the file agree."""
    if editions is None:
        return points
    from .crs_reference import NOT_RECORDED

    tag = f" ({NOT_RECORDED})"
    out = []
    for p in points:
        books = p.get("books") or []
        judged = bool(books) and all(editions.get(b.get("id")) for b in books)
        words_now = {k: p[k].replace(tag, "") for k in ("name", "action") if judged and isinstance(p.get(k), str) and tag in p[k]}
        out.append({**p, **words_now} if words_now else p)
    return out


def _where(printed: dict) -> str | None:
    if printed.get("page"):
        return f"p.{printed['page']}: {printed.get('source')}"
    return printed.get("source")


def _row(doc: str, v: dict, points_n: int) -> list:
    printed = v.get("printed") or {}
    said = words.edition_status_words(v)
    guess = said.endswith(words.EDITION_FILE_NAME_ONLY)
    why = " ".join(
        x
        for x in (
            FILE_NAME_WHY
            if printed.get("source") == agent_edition.FROM_FILE_NAME
            else "",
            v.get("reason") or "",
        )
        if x
    )
    return [_cell(c) for c in (
        v["book"], doc, printed.get("date"), _where(printed), printed.get("quote"), said,
        None if guess else v.get("binding"), None if guess else (v.get("caveat") or None), why or None, points_n,
    )]  # fmt: skip


def sheet(editions: dict, points: list[dict], not_held: list[str]) -> tuple:
    """The sheet "Editions": (columns, rows, widths, note). One row per held book (document) the points cite, most cited first."""
    cited: Counter = Counter()
    for p in points:
        for b in p.get("books") or []:
            cited[b["id"]] += 1
    order = sorted(editions, key=lambda d: (-cited[d], editions[d]["book"], d))
    rows = [_row(d, editions[d], cited[d]) for d in order]
    counts = Counter(words.edition_status_words(v) for v in editions.values())
    told = "; ".join(f"{w}: {k}" for w, k in counts.most_common()) or "none"
    note = (
        f"{len(rows)} held rule book(s) cited by this paper's points, each judged against the contract's edition cutoff ({told}). "
        f"{len(not_held)} rule book(s) not held: edition not known (sheet Rule books not held). {NOT_A_VERDICT}"
    )
    return COLUMNS, rows, WIDTHS, note
