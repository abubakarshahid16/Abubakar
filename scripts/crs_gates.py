"""THE SHARED GATES G1 to G7 (owner order 14, 16 Nov 2026): code checks of a finished review's CRS, for every document kind. READ ONLY.

    python scripts/crs_gates.py <run id> --db <COPY of the database> [--file page|run|both] [--mapping <kind-to-book JSON>]
                                [--replay <second run id> --replay-db <COPY holding it>] [--json <report file>]

Exit 0 when every gate passes on every file judged; 1 when any gate fails, is not run or is undecided; 2 when the run cannot be
judged. G6 reads the second run in a separate process, so two copies never share a connection. This is a tool, not part of the app
(`scripts/check_unused_modules.py`: a module only a script and a test import belongs in scripts/); it imports the app's own code.

The gates CHECK. They change no verdict, no CRS cell, nothing that leaves the machine: no model, no network, no write. Every lane's work
is judged by them (it prints, per gate, PASS / FAIL / NOT RUN / UNDECIDED with counts and the
failing row ids). No document text is printed: row ids, counts, clause numbers and the gate's own words only.

WHICH FILE. Two files carry a review's comments and both are judged (`--file`):
  page  the paper's ONE CRS (`crs_one.build_team`, drawn from `review_points_service.export_listing`, the file the page downloads and the
        completeness rule guards): its sheet "CRS" holds one comment per field (`crs_comments.group`), its sheet "Evidence" every point.
  run   the AI run's own internal file (`crs_ai_workbook.layout_view` drawn by `crs_layout.build_layout_crs`, the file stored with the
        run): its sheet "CRS" holds one row per item line, the other lines are on "Not reviewed or not applicable".
Both are BUILT AGAIN by the app's own builder from the stored run, then read back from the workbook, so a writer change is measured on
an old run without a new review. Rows: page "C<n>" = comment n of the sheet CRS, "E<n>" = point n of the sheet Evidence; run "R<n>" =
Item No n of the file. G3 to G6 judge the comment rows (C / R on the sheet CRS); G1, G2 and G7 judge every row that cites a book (E on
the page; every R line of the run file).

THE GATES, EXACTLY.
  G1 Every quote shown as a standard's words is found word for word in the stored pages of the cited book
     (`agent_review_standards.verify`: the review's own matcher, the book's stored pages, never the checklist or the stored
     requirement row). Shown as a standard's words: on the page a point's clause quote or its rule text "as stored"; in the run file
     a line's clause quote and the words its comment quotes after "requires:" (`crs_ai_workbook._item_ask`, a checklist line's own
     item wording first). A shown quote with no held book to search fails.
  G2 Every cited clause (a row naming a book AND a clause) is in a book that governs the paper's kind. The mapping is a JSON file
     (`--mapping`, format MAPPING_FORMAT; lane C owns its contents; a book may be limited to clause prefixes) and, without it, the app's
     own tables: `reference/standard_roles.json` (kind -> roles, standard -> role; `kind_standards`) and
     `reference/governing_standards.json` (equipment type -> books, materials books, books that apply in part; `applicability`).
     With the app's tables a book with no entry, or one that applies to the type only in part, is NOT JUDGED (counted, never a pass);
     with a file, a book the file does not list for the kind fails. No mapping for the kind: "G2 not run: no kind-to-book mapping".
  G3 No comment row says one of NOISE_PATTERNS ("found none", "no correction needed", "could not be read" and their plain variants), in
     any cell. The sheet Evidence is not judged: the completeness rule keeps every point there.
  G4 One comment per field or topic. FIELD = the row's field name (the point's name with its tags taken off, `review_points.split_tags`;
     `crs_comments.is_field` says it is a field) folded by `field_key`: lower case, text in brackets dropped, every character that is not a
     letter or digit dropped ("Over pressure %" = "Overpressure"). TOPIC, for a row with no field = the book's key and the clause. A row
     with neither is its own key. Two comment rows with one key fail (both ids are listed).
  G5 A firm finding names the value on the paper and the clause. FIRM = the row's class is a decision or a not-met, on the app's own rank
     scale (`review_points.RANKS`): 1 Not met proven by code, 2 Not met two readers agree, 3 Not met one reader, 6 Met two readers
     agree, 7 Met proven by code (not 4 Question, 5 Met one reader, 8 Does not apply). It must carry a paper quote that code verified on
     the page (a value shown only "as stored, not verified" fails; a code-proven absence, the line's `absence_check` "proven", names
     "not on the paper" and counts) AND a book and a clause.
  G6 Same input twice gives at least REPLAY_AT_LEAST % the same comments. SAME COMMENT = the same G4 key, the same rank and the same set
     of (book key, clause). Reported as "M of N" where N = the comments of both runs together counted once (|A or B|), M = in both.
  G7 A rule whose book we do not hold is listed as "book missing", never guessed. A book is NOT HELD when it is in the run's missing
     list (`agent_review_missing_book`) or the library holds no document for it (`applicability.find_standard`). Fails: a row citing
     such a book that gives a verdict (met, not met, does not apply) or shows a clause or a rule text of it; and a missing book of the
     run that the file does not name anywhere. A question with no clause and no rule text passes (it asks, it does not guess).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "backend") not in sys.path:
    sys.path.insert(0, str(REPO / "backend"))

PASS, FAIL, NOT_RUN, UNDECIDED = "PASS", "FAIL", "NOT RUN", "UNDECIDED"
GATES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7")
FILE_PAGE, FILE_RUN = "page", "run"
REPLAY_AT_LEAST = 90
FIRM_RANKS = frozenset({1, 2, 3, 6, 7})
MAPPING_FORMAT = "crs-gates-kind-books/1"
NOISE_PATTERNS = (  # (the words the owner named, the pattern of them and their plain variants), matched on folded text
    ("found none", r"\bfound none\b|\bnone (?:was |were )?found\b"),
    (
        "no correction needed",
        r"\bno corrections? (?:is |are |was |were )?(?:needed|required)\b",
    ),
    (
        "could not be read",
        r"\b(?:could|can) ?not be read\b|\bcouldn'?t be read\b|\bcan'?t be read\b",
    ),
)
_NOISE = tuple((label, re.compile(rx)) for label, rx in NOISE_PATTERNS)
LIST_AT_MOST = 40  # failing ids printed per gate; the counts are always whole


# ------------------------------------------------------------------------------------------------ the row model


@dataclass
class Row:
    """One row of a CRS file as the gates read it (built by the app's builder, read back from the workbook)."""

    id: str
    cells: tuple[str, ...] = ()  # the row's cells as built, as text
    field: str = ""  # the field name as shown ("" when the row has none)
    rank: int | None = None  # the app's rank scale (`review_points.RANKS`)
    paper_value: str | None = None  # the paper value the row shows
    value_verified: bool = False  # code verified that value on the paper's page
    absence_proven: bool = False  # code proved the paper does not state it (the stored absence proof): "not on the paper" is its value
    book: str = ""  # the book the row's finding rests on
    clause: str = ""
    clauses: tuple[tuple[str, str], ...] = ()  # every (book, clause) the row cites
    quotes: tuple[str, ...] = ()  # every text the row shows as the standard's own words
    quote_docs: tuple[str, ...] = ()  # the held documents of the cited book
    quote_page: int | None = None
    names: tuple[str, ...] = ()  # every book the row names
    shows_rule_words: bool = False  # the row shows a clause or a rule text of its book
    is_missing_listing: bool = False  # the row IS the "rule book not held" listing


@dataclass
class Result:
    gate: str
    status: str
    checked: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)  # (row id, why)
    counts: dict[str, int] = field(default_factory=dict)
    note: str = ""

    def to_json(self) -> dict:
        return {"gate": self.gate, "status": self.status, "checked": self.checked, "failed": len(self.failed),
                "ids": [f"{i} ({w})" for i, w in self.failed], "counts": self.counts, "note": self.note}  # fmt: skip


def _fold(text) -> str:
    return " ".join(str(text or "").split()).lower()


def _finish(
    gate: str,
    checked: int,
    failed: list[tuple[str, str]],
    note: str = "",
    undecided: int = 0,
) -> Result:
    counts = dict(Counter(w for _i, w in failed))
    if failed:
        status = FAIL
    elif undecided:
        status = UNDECIDED
    elif checked:
        status = PASS
    else:
        status, note = NOT_RUN, note or "no row to check"
    return Result(gate, status, checked, failed, counts, note)


# ------------------------------------------------------------------------------------------------ G1 quotes from the book


def g1_quotes(rows: list[Row], books) -> Result:
    """`books`: an object with `.book(document id) -> pass_guards.Book` (default `agent_review_standards.BookPages()`, each book read
    once); every shown quote goes through `agent_review_standards.verify`, the review's one in-book check."""
    from app import agent_review_standards as standards

    failed, checked = [], 0
    for r in rows:
        shown = [
            q
            for q in dict.fromkeys(" ".join(str(q or "").split()) for q in r.quotes)
            if q
        ]
        if not shown:
            continue
        checked += 1
        if not r.quote_docs:
            failed.append((r.id, "no held book to search"))
            continue
        for q in shown:
            if not any(
                standards.verify(d, q, r.quote_page, books).found for d in r.quote_docs
            ):
                failed.append((r.id, "quote not in the stored book"))
                break
    return _finish(
        "G1", checked, failed, f"{checked} rows show a quote from a standard"
    )


# ------------------------------------------------------------------------------------------------ G2 books that govern the kind


def _clause_key(clause) -> str:
    c = _fold(clause)
    c = re.sub(r"^(?:clause|section|para(?:graph)?)\.?\s*", "", c)
    return c.replace(" ", "")


def clause_in(clause: str, prefixes: list[str] | None) -> bool:
    """True when the clause is one of the prefixes or under one ("UG-150" covers "UG-150(a)" and "UG-150.1", never "UG-1500")."""
    if prefixes is None:
        return True
    c = _clause_key(clause)
    for p in (_clause_key(x) for x in prefixes):
        if p and (c == p or (c.startswith(p) and c[len(p)] in ".(-)")):
            return True
    return False


@dataclass
class KindBooks:
    """Which books govern ONE paper kind: `judge(book, clause) -> ("pass" | "fail" | "unknown", why)`."""

    source: str
    governs: list[dict]  # {"book": name, "clauses": [prefixes] | None}
    does_not: list[str] = field(
        default_factory=list
    )  # books said NOT to govern the kind
    in_part: list[str] = field(
        default_factory=list
    )  # books that govern in part, clause range not given
    closed: bool = False  # a file: a book it does not list does not govern

    def judge(self, book: str, clause: str) -> tuple[str, str]:
        from app.standard_ids import same_standard

        for e in self.governs:
            if same_standard(book, e["book"]):
                if clause_in(clause, e.get("clauses")):
                    return "pass", ""
                return (
                    "fail",
                    "clause outside the part of the book that governs this kind",
                )
        if any(same_standard(book, b) for b in self.does_not):
            return "fail", "book does not govern this kind"
        if any(same_standard(book, b) for b in self.in_part):
            return "unknown", "book governs this kind in part; clause range not given"
        if self.closed:
            return "fail", "book not listed for this kind"
        return "unknown", "no entry for this book"


def mapping_from_file(
    path: str | Path, kind: str | None, equipment: str | None
) -> KindBooks | None:
    """Lane C's file: {"format": MAPPING_FORMAT, "kinds": {"<kind>|<equipment type>" or "<kind>": [{"book", "clauses"?}]}}. The most
    specific key wins; None when the file has no entry for this paper."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != MAPPING_FORMAT or not isinstance(data.get("kinds"), dict):
        raise ValueError(f"{Path(path).name}: not a {MAPPING_FORMAT} file")
    kinds = {_fold(k): v for k, v in data["kinds"].items()}
    for key in ([f"{_fold(kind)}|{_fold(equipment)}"] if equipment else []) + [
        _fold(kind)
    ]:
        if key in kinds:
            entries = [e for e in kinds[key] if isinstance(e, dict) and e.get("book")]
            return KindBooks(
                f"mapping file {Path(path).name} ({key})", entries, closed=True
            )
    return None


def mapping_from_app(kind: str | None, equipment: str | None) -> KindBooks | None:
    """The app's own tables (cited in the module words). None when neither table says anything about this kind or type."""
    from app import applicability, kind_standards

    roles = kind_standards.table()
    gov = applicability.governing_table()
    kind_roles = roles.get("kinds_apply", {}).get(_fold(kind)) if kind else None
    etype = _fold(equipment) if equipment else ""
    type_books = gov["equipment_types"].get(etype) if etype else None
    if kind_roles is None and type_books is None:
        return None
    governs = [{"book": b} for b in type_books or []]
    governs += [
        {"book": b} for b in roles.get("method_standards", {}).get(_fold(kind), [])
    ]
    does_not = []
    for std, role in roles.get("standards", {}).items():
        if kind_roles is not None and role in kind_roles:
            governs.append({"book": std})
        elif kind_roles is not None:
            does_not.append(std)
    if type_books is not None:
        governs += [{"book": b} for b in gov["materials_standards"]]
    in_part = (
        [e["standard"] for e in gov["partial_standards"].get(etype, [])]
        if etype
        else []
    )
    src = "app tables: standard_roles.json" + (
        ", governing_standards.json" if type_books is not None else ""
    )
    return KindBooks(src, governs, does_not, in_part)


def g2_books(
    rows: list[Row], books: KindBooks | None, kind: str | None, equipment: str | None
) -> Result:
    if books is None:
        return Result("G2", NOT_RUN, note=f"G2 not run: no kind-to-book mapping (kind {kind or 'not recorded'}, "
                                         f"equipment type {equipment or 'not recorded'})")  # fmt: skip
    failed, checked, unknown = [], 0, Counter()
    for r in rows:
        for book, clause in r.clauses:
            if not (str(book or "").strip() and str(clause or "").strip()):
                continue
            checked += 1
            got, why = books.judge(book, clause)
            if got == "fail":
                failed.append((r.id, f"{why}: clause {clause}"))
            elif got == "unknown":
                unknown[why] += 1
    note = f"{checked} cited clauses; mapping: {books.source}"
    if unknown:
        note += "; not judged: " + ", ".join(
            f"{n} {w}" for w, n in sorted(unknown.items())
        )
    res = _finish("G2", checked, failed, note, undecided=sum(unknown.values()))
    res.counts = dict(
        Counter(w.split(": clause ")[0] for _i, w in failed)
    )  # by reason; the clause stays with each id
    res.counts.update({f"not judged: {w}": n for w, n in unknown.items()})
    return res


# ------------------------------------------------------------------------------------------------ G3 noise


def noise_in(text) -> str | None:
    """The owner's words the text says (see NOISE_PATTERNS), or None."""
    t = _fold(text)
    return next((label for label, rx in _NOISE if rx.search(t)), None)


def g3_noise(rows: list[Row]) -> Result:
    failed = []
    for r in rows:
        hit = next((h for h in (noise_in(c) for c in r.cells) if h), None)
        if hit:
            failed.append((r.id, f'says "{hit}"'))
    return _finish("G3", len(rows), failed, f"{len(rows)} comment rows")


# ------------------------------------------------------------------------------------------------ G4 one comment per field or topic


def field_key(name) -> str:
    """The field folded for comparison (see G4): lower case, bracketed text dropped, only letters and digits kept."""
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", _fold(name))
    return re.sub(r"[^0-9a-z]+", "", t)


def _book_key(book) -> str:
    from app.standard_ids import key

    return key(str(book or "")) or _fold(book)


def key_of(r: Row) -> str:
    f = field_key(r.field)
    if f:
        return f"field|{f}"
    if str(r.book).strip() and str(r.clause).strip():
        return f"topic|{_book_key(r.book)}|{_clause_key(r.clause)}"
    return f"row|{r.id}"


def g4_one_per_field(rows: list[Row]) -> Result:
    by: dict[str, list[str]] = {}
    for r in rows:
        by.setdefault(key_of(r), []).append(r.id)
    failed = [
        (i, f"{len(ids)} comments on one {k.split('|', 1)[0]}")
        for k, ids in by.items()
        if len(ids) > 1
        for i in ids
    ]
    return _finish(
        "G4", len(rows), failed, f"{len(rows)} comment rows, {len(by)} fields or topics"
    )


# ------------------------------------------------------------------------------------------------ G5 firm findings


def g5_firm(rows: list[Row]) -> Result:
    failed, firm = [], 0
    for r in rows:
        if r.rank not in FIRM_RANKS:
            continue
        firm += 1
        named = (
            r.value_verified or r.absence_proven
        )  # an absence proven by code names "not on the paper" as the value
        if not named and not str(r.paper_value or "").strip():
            failed.append((r.id, "no paper value"))
        elif not named:
            failed.append((r.id, "paper value not verified on the page"))
        elif not (str(r.book).strip() and str(r.clause).strip()):
            failed.append((r.id, "no book and clause"))
    return _finish(
        "G5", firm, failed, f"{firm} firm findings of {len(rows)} comment rows"
    )


# ------------------------------------------------------------------------------------------------ G6 replay


def signature(r: Row) -> list:
    """The G6 identity of one comment row (JSON-able): its G4 key, its rank, its sorted (book key, clause) pairs."""
    pairs = sorted(
        {
            (_book_key(b), _clause_key(c))
            for b, c in r.clauses
            if str(b or "").strip() or str(c or "").strip()
        }
    )
    return [
        key_of(r) if not key_of(r).startswith("row|") else "row|",
        r.rank,
        [list(p) for p in pairs],
    ]


def g6_replay(
    first: list[list] | None, second: list[list] | None, why_not: str = ""
) -> Result:
    if first is None or second is None:
        return Result(
            "G6",
            NOT_RUN,
            note=why_not
            or "G6 not run: give a second run of the same paper (--replay)",
        )
    a = Counter(json.dumps(s, sort_keys=True) for s in first)
    b = Counter(json.dumps(s, sort_keys=True) for s in second)
    both, union = sum((a & b).values()), sum((a | b).values())
    pct = (100.0 * both / union) if union else None
    failed = (
        []
        if pct is not None and pct >= REPLAY_AT_LEAST
        else [("replay", f"under {REPLAY_AT_LEAST}% the same")]
    )
    note = (f"{both} of {union} comments the same ({pct:.1f}%; first run {len(first)}, second run {len(second)}; "
            f"needs {REPLAY_AT_LEAST}%)" if union else "neither run has a comment")  # fmt: skip
    return _finish("G6", union, failed, note)


# ------------------------------------------------------------------------------------------------ G7 book missing


def g7_missing(
    rows: list[Row], missing: list[str], library: list[dict], file_text: str
) -> Result:
    """`missing`: the run's missing-book names; `library`: the held books (`review_points.library_of`); `file_text`: every cell of the
    built file, folded, for the "listed" check."""
    from app import applicability
    from app.standard_ids import same_standard

    def not_held(name: str) -> bool:
        return (
            any(same_standard(name, m) for m in missing)
            or applicability.find_standard(library, name) is None
        )

    failed, checked = [], 0
    for r in rows:
        if r.is_missing_listing:
            continue
        gone = [n for n in r.names if str(n or "").strip() and not_held(n)]
        if not gone:
            continue
        checked += 1
        if r.rank not in (None, 4):
            failed.append((r.id, "verdict on a rule whose book is not held"))
        elif r.shows_rule_words:
            failed.append((r.id, "rule words shown for a book not held"))
    for k, name in enumerate(missing, start=1):
        checked += 1
        if _fold(name) not in file_text:
            failed.append((f"missing book {k}", "not listed as book missing"))
    return _finish(
        "G7",
        checked,
        failed,
        f"{len(missing)} books missing in the run; {checked} rows or books checked",
    )


# ------------------------------------------------------------------------------------------------ the files, built by the app's builders


class GateInputError(Exception):
    """The run cannot be judged as asked (not found, not the paper's latest, a file whose rows differ from its builder's selection)."""


def _cells(row) -> tuple[str, ...]:
    return tuple(str(c) for c in row if c is not None and str(c).strip())


def _all_text(wb) -> str:
    return _fold(
        " ".join(
            str(c)
            for ws in wb.worksheets
            for r in ws.iter_rows(values_only=True)
            for c in r
            if c is not None
        )
    )


def _point_row(rid: str, p: dict) -> Row:
    """A point of the page's list (an Evidence row of the one CRS)."""
    line, ref = p.get("_line") or {}, p.get("rule_ref") or {}
    names = [b.get("name") for b in p.get("books") or []] + [
        p.get("rule_book"),
        ref.get("name"),
        line.get("standard"),
    ]
    names = tuple(dict.fromkeys(str(n).strip() for n in names if str(n or "").strip()))
    book = str(p.get("rule_book") or ref.get("name") or "")
    clause = str(p.get("clause") or ref.get("clause") or "")
    page = line.get("clause_page")
    return Row(
        id=rid, field="", rank=p.get("rank"), book=book, clause=clause, clauses=((book, clause),) if clause else (),
        quotes=tuple(q for q in (p.get("clause_quote"), p.get("rule_text")) if q),
        quote_docs=tuple(dict.fromkeys(d for d in (p.get("_book_docs") or [p.get("_book_doc")]) if d)),
        quote_page=page if isinstance(page, int) and not isinstance(page, bool) else None,
        names=names, shows_rule_words=bool(clause or p.get("clause_quote") or p.get("rule_text")),
    )  # fmt: skip


def absence_proven(line: dict) -> bool:
    """The stored line carries a code proof that the paper does not state the value (`agent_review_absence`, `proven`)."""
    proof = line.get("absence_check")
    return isinstance(proof, dict) and proof.get("proven") is True


def _comment_row(c: dict, cells) -> Row:
    """A comment of the page's sheet CRS: the strongest point's words lead (`crs_one.comment_cells`), every member's clause is listed."""
    from app import crs_comments

    s = c["strongest"]
    return Row(
        id=f"C{c['number']}", cells=_cells(cells), field=crs_comments._field_of(s), rank=c["rank"],
        paper_value=s.get("paper_quote") or s.get("paper_value"), value_verified=bool(s.get("paper_quote")),
        absence_proven=absence_proven(s.get("_line") or {}),
        book=str(s.get("rule_book") or (s.get("rule_ref") or {}).get("name") or ""), clause=str(s.get("clause") or ""),
        clauses=tuple((str(k.get("book") or ""), str(k.get("clause") or "")) for k in c["clauses"]),
    )  # fmt: skip


def page_file(paper_id: str, scope) -> dict:
    """The paper's ONE CRS (team copy) built by `crs_one.build_team` and read back: comment rows, Evidence rows, facts."""
    from openpyxl import load_workbook

    from app import crs_comments, crs_one
    from app import review_points_service as svc
    from app.crs_completeness import _table_rows

    listing, raw, facts = svc.export_listing(paper_id, scope)
    data = crs_one.build_team(paper_id, scope, listing_raw=(listing, raw, facts))
    wb = load_workbook(BytesIO(data))
    built = {
        r[0]: r
        for r in _table_rows(wb[crs_one.TEAM_SHEET], "Comment")
        if isinstance(r[0], int)
    }
    grouped = crs_comments.group(
        raw
    )  # the builder's own grouping: comment n of the file is comment n here
    if sorted(built) != [
        c["number"] for c in sorted(grouped, key=lambda c: c["number"])
    ]:
        raise GateInputError(
            "the sheet CRS does not hold the comments its builder groups"
        )
    return {
        "rows": [_comment_row(c, built[c["number"]]) for c in grouped],
        "evidence": [_point_row(f"E{n}", p) for n, p in enumerate(raw, start=1)],
        "text": _all_text(wb), "runs": listing["runs"],
    }  # fmt: skip


def _line_row(rid: str, ln: dict, cells=()) -> Row:
    """A line of the AI run's own file. On the sheet CRS the comment quotes the rule's words (`crs_ai_workbook._item_ask`, a checklist
    line's own item wording first); every line's Evidence row shows its clause quote."""
    from app import crs_ai_workbook, crs_comments
    from app import review_points as rp
    from app.crs_ai_words import KIND_NOT_HELD

    rank = rp.rank_of_ai_line(ln)[0]
    name = rp.split_tags(crs_ai_workbook.field_name(ln))[0]
    book, clause = str(ln.get("standard") or ""), str(ln.get("clause") or "")
    asked = crs_ai_workbook._item_ask(ln) if cells else ""
    doc, page = ln.get("standard_document_id"), ln.get("clause_page")
    return Row(
        id=rid, cells=_cells(cells), field=name if crs_comments.is_field(name) else "", rank=rank,
        paper_value=ln.get("paper_quote"), value_verified=bool((ln.get("quotes_checked") or {}).get("paper")),
        absence_proven=absence_proven(ln),
        book=book, clause=clause, clauses=((book, clause),) if clause else (),
        quotes=tuple(q for q in (asked, ln.get("clause_quote")) if q), quote_docs=(doc,) if doc else (),
        quote_page=page if isinstance(page, int) and not isinstance(page, bool) else None,
        names=(book,) if book.strip() else (), shows_rule_words=bool(clause or ln.get("clause_quote") or asked),
        is_missing_listing=rank == 0 or ln.get("verdict_class") == KIND_NOT_HELD,
    )  # fmt: skip


def run_lines(conn, run_id: str) -> list[dict]:
    """The run's stored lines as every reader sees them (the reading `crs_completeness._older_expected` uses)."""
    from app import agent_review_wording as wording

    return [
        wording.read_time(
            {**json.loads(r["line_json"] or "{}"), "item_id": r["item_id"]}
        )
        for r in conn.execute(
            "SELECT item_id, line_json FROM agent_review_line WHERE run_id = ? ORDER BY rowid",
            (run_id,),
        )
    ]


def run_file(run_id: str, paper_id: str) -> dict:
    """The AI run's internal file drawn again by its own builder from the stored lines and the run's kept meta, and read back."""
    from openpyxl import load_workbook

    from app import crs_ai_workbook, crs_layout
    from app.agent_review_jobs import run_dir
    from app.crs_completeness import _table_rows
    from app.db import connect

    lines = run_lines(connect(), run_id)
    meta_path = run_dir(run_id) / "crs-meta.json"
    meta = (
        json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    )
    meta.setdefault("paper", paper_id)
    meta.setdefault("run_id", run_id)
    wb = load_workbook(
        BytesIO(
            crs_layout.build_layout_crs(
                crs_ai_workbook.layout_view(lines, meta, "internal")
            )
        )
    )
    built = _table_rows(wb[crs_layout.LAYOUT_MAIN_SHEET], "Item No")
    items = crs_ai_workbook.ordered_item_lines(lines)
    if len(built) != len(items):
        raise GateInputError(
            "the run file's sheet CRS does not hold its builder's item rows"
        )
    others = crs_ai_workbook.other_lines(lines)
    rows = [
        _line_row(f"R{n}", ln, cells)
        for n, ((ln, _s, _o), cells) in enumerate(
            zip(items, built, strict=True), start=1
        )
    ]
    evidence = rows + [
        _line_row(f"R{len(items) + k}", ln)
        for k, (ln, _kind) in enumerate(others, start=1)
    ]
    return {"rows": rows, "evidence": evidence, "text": _all_text(wb)}


# ------------------------------------------------------------------------------------------------ one run, every gate


def paper_facts(conn, run_id: str) -> dict:
    """The paper, its kind and equipment type as the AI run recorded them, and the run's missing books. Raises when the run is not found."""
    row = conn.execute(
        "SELECT submittal_document_id FROM review_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row is None:
        raise GateInputError(f"no review run {run_id}")
    ai = conn.execute(
        "SELECT paper_kind, equipment_type FROM agent_review_run WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    missing = (
        [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM agent_review_missing_book WHERE run_id = ? ORDER BY name",
                (run_id,),
            )
        ]
        if ai
        else []
    )
    return {
        "paper": row["submittal_document_id"], "ai": ai is not None,
        "kind": (ai["paper_kind"] or None) if ai else None, "equipment": (ai["equipment_type"] or None) if ai else None,
        "missing": missing,
    }  # fmt: skip


def rows_of(run_id: str, which: str, scope) -> tuple[dict, dict]:
    """(the facts, the file) for one run and one file kind. The page's CRS is drawn from the paper's LATEST runs: an older run is refused."""
    from app.db import connect

    facts = paper_facts(connect(), run_id)
    if which == FILE_RUN:
        if not facts["ai"]:
            raise GateInputError(
                f"run {run_id} is not an AI review run: it has no file of its own"
            )
        return facts, run_file(run_id, facts["paper"])
    got = page_file(facts["paper"], scope)
    if run_id not in (got["runs"] or {}).values():
        raise GateInputError(f"the paper's one CRS is drawn from its latest runs {sorted(v for v in got['runs'].values() if v)}, "
                             f"not from run {run_id}: give a copy where this run is the latest")  # fmt: skip
    return facts, got


def check(
    run_id: str,
    which: str = FILE_PAGE,
    *,
    scope=None,
    mapping_path=None,
    replay=None,
    books=None,
) -> dict:
    """Every gate on one run's file. `replay`: the second run's signatures (`{"paper", "signatures"}`) or None. Reads only."""
    from app import access
    from app import agent_review_standards as standards
    from app.db import connect
    from app.review_points import library_of

    scope = scope or access.unrestricted_scope()
    facts, got = rows_of(run_id, which, scope)
    kind, equipment = facts["kind"], facts["equipment"]
    if kind is None:
        from app import kind_standards

        kind = kind_standards.kind_of(facts["paper"])
    mapping = (
        mapping_from_file(mapping_path, kind, equipment)
        if mapping_path
        else mapping_from_app(kind, equipment)
    )
    if mapping_path and mapping is None:
        mapping = None  # the file says nothing about this kind: G2 is not run (the app's tables are not mixed in)
    sigs = [signature(r) for r in got["rows"]]
    if replay is None:
        g6 = g6_replay(None, None)
    elif replay.get("paper") != facts["paper"]:
        g6 = g6_replay(None, None, "G6 not run: the second run is of another paper")
    else:
        g6 = g6_replay(sigs, replay["signatures"])
    results = [
        g1_quotes(got["evidence"], books or standards.BookPages()),
        g2_books(got["evidence"], mapping, kind, equipment),
        g3_noise(got["rows"]),
        g4_one_per_field(got["rows"]),
        g5_firm(got["rows"]),
        g6,
        g7_missing(
            got["evidence"], facts["missing"], library_of(connect()), got["text"]
        ),
    ]
    return {"run_id": run_id, "paper": facts["paper"], "file": which, "kind": kind, "equipment": equipment,
            "comment_rows": len(got["rows"]), "evidence_rows": len(got["evidence"]), "signatures": sigs,
            "gates": [r.to_json() for r in results]}  # fmt: skip


def lines_of(report: dict, at_most: int = LIST_AT_MOST) -> list[str]:
    """The report in plain lines: one per gate, then its failing ids (at most `at_most`, the count always whole)."""
    out = [f"run {report['run_id']}  paper {report['paper']}  file {report['file']}  kind {report['kind'] or 'not recorded'}  "
           f"equipment {report['equipment'] or 'not recorded'}  comment rows {report['comment_rows']}  "
           f"rows citing books {report['evidence_rows']}"]  # fmt: skip
    for g in report["gates"]:
        counts = "; ".join(f"{n} {w}" for w, n in sorted(g["counts"].items()))
        out.append(f"{g['gate']} {g['status']:<9} checked {g['checked']}, failed {g['failed']}" + (f"  [{counts}]" if counts else "")
                   + (f"  {g['note']}" if g["note"] else ""))  # fmt: skip
        if g["ids"]:
            shown = g["ids"][:at_most]
            more = (
                f" and {len(g['ids']) - at_most} more"
                if len(g["ids"]) > at_most
                else ""
            )
            out.append("   failing: " + ", ".join(shown) + more)
    return out


# ------------------------------------------------------------------------------------------------ the command


def _point_at(db: str) -> None:
    from app.config import settings

    path = Path(db).resolve()
    if not path.is_file():
        raise SystemExit(f"no database at {path}")
    settings.data_dir, settings.db_path = path.parent, path
    settings.startup_warmup = False


def _replay(args, which: str) -> dict | None:
    if not args.replay:
        return None
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        args.replay,
        "--db",
        args.replay_db or args.db,
        "--file",
        which,
        "--signatures",
    ]
    got = subprocess.run(
        cmd, capture_output=True, text=True, check=False
    )  # this script itself, on a copy
    if got.returncode != 0:
        print(
            f"G6: the second run could not be read: {(got.stdout or got.stderr).strip().splitlines()[-1:]}"
        )
        return {"paper": None, "signatures": []}
    return json.loads(got.stdout)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_id")
    ap.add_argument("--db", required=True, help="a COPY of the database")
    ap.add_argument("--file", choices=("page", "run", "both"), default="both")
    ap.add_argument(
        "--mapping",
        help="kind-to-book JSON (format crs-gates-kind-books/1); without it the app's own tables",
    )
    ap.add_argument("--replay", help="a second run of the same paper, for G6")
    ap.add_argument(
        "--replay-db", help="the COPY holding the second run (default: --db)"
    )
    ap.add_argument("--json", help="write the whole report to this file")
    ap.add_argument(
        "--signatures", action="store_true", help=argparse.SUPPRESS
    )  # the G6 side of a replay: prints JSON only
    args = ap.parse_args(argv)
    _point_at(args.db)
    files = ("page", "run") if args.file == "both" else (args.file,)
    if args.signatures:
        try:
            got = check(args.run_id, files[0])
        except GateInputError as e:
            print(str(e))
            return 2
        print(json.dumps({"paper": got["paper"], "signatures": got["signatures"]}))
        return 0
    reports, code = [], 0
    for which in files:
        try:
            rep = check(
                args.run_id,
                which,
                mapping_path=args.mapping,
                replay=_replay(args, which),
            )
        except GateInputError as e:
            print(f"file {which}: cannot be judged: {e}")
            code = max(code, 2)
            continue
        reports.append(rep)
        print("\n".join(lines_of(rep)))
        print()
        if any(g["status"] != PASS for g in rep["gates"]):
            code = max(code, 1)
    if args.json:
        Path(args.json).write_text(
            json.dumps(
                [{k: v for k, v in r.items() if k != "signatures"} for r in reports],
                indent=1,
            ),
            encoding="utf-8",
        )
    return code


if __name__ == "__main__":
    sys.exit(main())
