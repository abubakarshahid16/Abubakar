"""Read-only access to the library's own metadata and text, for the general review.

What chooses books and rules here is LIBRARY METADATA only, never words shared between the paper and a rule:
  * `rule_label.paper_kind`         - which kind of paper each stored rule is checked on (two-model labels);
  * `rule_equipment_label`          - which equipment each rule is about (two-model labels; agreed rows);
  * `rule_label.reading_json`       - the subject each rule was read to be about (shown to the AI as a catalog);
  * `document_classification`       - role and committee of each held document;
  * reference/governing_standards.json, standard_roles.json, equipment_taxonomy.json, equipment_mapping.json;
  * the paper's own citations, read by code (`standard_ids.cited_standards`) and resolved by identifier.

Nothing here names an equipment type, a standard, a paper or a layout: those are the reference files' data (CLAUDE.md rule 13).
Nothing here writes, and nothing here asks a model.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

# The six reasons a book is on the plan's list, and the list's size: one home, the package (`app.aim_review`).
from . import MAX_BOOKS as MAX_CANDIDATES
from . import WHY_CITED, WHY_GOVERNS, WHY_LAST, WHY_METHOD, WHY_RULES, WHY_SAVED

log = logging.getLogger(__name__)

REF = Path(__file__).resolve().parents[1] / "reference"

#: The method's paper kinds -> the library's rule kind labels (`rule_label.paper_kind`). A specification states what a contractor
#: must meet, as a contract's scope documents do, so it is checked with the rules labelled for contracts.
KINDS = (
    "datasheet",
    "procedure",
    "contract",
    "specification",
    "drawing",
    "calculation",
    "test record",
    "other",
)
KIND_LABELS = {
    "datasheet": ("datasheet",),
    "procedure": ("procedure",),
    "contract": ("contract",),
    "specification": ("contract",),
    "drawing": ("drawing",),
    "calculation": ("calculation",),
    "test record": ("other", "datasheet"),
    "other": ("other",),
}
#: The method's kinds -> standard_roles.json kinds (for `kinds_apply` and `method_standards`).
ROLE_KIND = {
    "datasheet": "datasheet",
    "procedure": "procedure",
    "contract": "contract",
    "specification": "specification",
    "drawing": "drawing",
    "calculation": "datasheet",
    "test record": "datasheet",
    "other": None,
}
#: The app's stored paper kinds (`paper_kind.PAPER_KINDS`) -> the method's kinds.
APP_KIND = {"test_record": "test record", "transmittal": "other"}

STANDARD_ROLE = "COMPANY_STANDARD"
SUBMITTAL_ROLE = "CONTRACTOR_SUBMITTAL"


def method_kind(app_kind: str | None) -> str | None:
    """The app's stored kind in the method's spelling; None stays None (unknown is never invented)."""
    if not app_kind:
        return None
    k = APP_KIND.get(str(app_kind), str(app_kind).replace("_", " "))
    return k if k in KINDS else "other"


def _json(name: str) -> dict:
    return json.loads((REF / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def taxonomy() -> tuple[dict, ...]:
    """({id, name, family, also_applies}, ...) from equipment_taxonomy.json."""
    out = []
    for fam in _json("equipment_taxonomy.json")["families"]:
        for t in fam.get("types") or []:
            out.append(
                {
                    "id": t["id"],
                    "name": t.get("name") or t["id"],
                    "family": fam["id"],
                    "also_applies": list(t.get("also_applies") or []),
                }
            )
    return tuple(out)


def type_ids() -> frozenset[str]:
    return frozenset(t["id"] for t in taxonomy())


def type_id_of(equipment: str | None) -> str | None:
    """The app's stored equipment name (its vocabulary or a taxonomy id) -> one taxonomy id, by the reference files only."""
    if not equipment:
        return None
    e = str(equipment).strip()
    if e in type_ids():
        return e
    mapped = (_json("equipment_mapping.json").get("map") or {}).get(e.lower())
    return mapped if mapped in type_ids() else None


def type_set(type_id: str | None) -> tuple[set[str], str | None]:
    """The type, the types it also applies as (a sub-type and its parent), and its family."""
    by_id = {t["id"]: t for t in taxonomy()}
    if not type_id or type_id not in by_id:
        return set(), None
    seen, todo = set(), [type_id]
    while todo:
        t = todo.pop()
        if t in seen or t not in by_id:
            continue
        seen.add(t)
        todo.extend(by_id[t]["also_applies"])
    return seen, by_id[type_id]["family"]


# ------------------------------------------------------------------ the library's documents


def library(
    conn, *, exclude: frozenset[str] = frozenset(), within: frozenset[str] | None = None
) -> list[dict]:
    """Every held document that can serve as a book: not a contractor submittal, not in `exclude`; with `within`, only those."""
    rows = conn.execute(
        """SELECT d.id AS id, d.filename AS filename, d.page_count AS page_count, c.document_number AS document_number,
                  c.document_role AS document_role, c.discipline_canonical AS committee, c.title AS title
           FROM documents d LEFT JOIN document_classification c ON c.document_id = d.id
           WHERE COALESCE(c.document_role, '') <> ?""",
        (SUBMITTAL_ROLE,),
    ).fetchall()
    return [
        dict(r)
        for r in rows
        if r["id"] not in exclude and (within is None or r["id"] in within)
    ]


def identifier_of(entry: dict) -> str:
    from app import applicability

    name = entry.get("filename") or ""
    return (
        entry.get("document_number")
        or applicability.library_identifier(name)
        or applicability._file_identifier(name)
        or re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name)
    )


def is_public_name(name) -> bool:
    """Is this standard's identifier or name a PUBLIC one: its first word is one of the app's own publisher families
    (`standards_web_search.FAMILIES`, the table the online search uses)? Anything else (whatever its shape: a letter prefix,
    digits first) is a COMPANY standard (an owner's own rule book)."""
    from app import standards_web_search

    m = re.match(r"\s*([A-Za-z]+)", str(name or ""))
    return bool(m) and m.group(1).upper() in standards_web_search.FAMILIES


def is_public(entry: dict | None) -> bool:
    """A held book is PUBLIC by its identifier's publisher family (`is_public_name`)."""
    return bool(entry) and is_public_name(identifier_of(entry))


def is_own(entry: dict | None) -> bool:
    """A held book is one of the CLIENT'S OWN standards when its RECORDED role is a company standard (the owner's choice at upload).
    The client is a joint operation of its owner companies, so their standards are all its own (owner, 18 Nov 2026). The
    recorded role decides, never a name shape."""
    return bool(entry) and (entry.get("document_role") or "") == STANDARD_ROLE


def is_rule_book(entry: dict | None) -> bool:
    """May this held document be a RULE BOOK at all, decided from its RECORDED role first: the company-standard role (the
    client's own standards), or NO role and a public standard's name. Any other recorded role (a contract, a submittal, a
    specification, a supporting document) is never a rule book, whatever its file name or a citation says (fix check 961f7126, N2)."""
    if not entry:
        return False
    role = entry.get("document_role") or ""
    if role:
        return role == STANDARD_ROLE
    return is_public(entry)


def cited_company(conn, paper_id: str) -> frozenset[str]:
    """The ids of the cited held RULE BOOKS that are neither public nor the client's own: with today's roles (the company-
    standard role is the only rule-book role) this set is EMPTY by construction, so the checklist key keeps its plain form. Kept
    as the one home of "cited ids" (`run(cited_books=...)`, `cited_key`) should another rule-book role be recorded."""
    lib = library(conn, exclude=frozenset({str(paper_id)}))
    found = (resolve(lib, name) for name in _paper_citations(conn, str(paper_id)))
    return frozenset(
        e["id"]
        for e in found
        if e and is_rule_book(e) and not is_public(e) and not is_own(e)
    )


def usable(entry: dict | None) -> bool:
    """May this held book be used for this paper: a rule book (`is_rule_book`): the client's own standard by its recorded role,
    or an unroled public standard. Measured (head 9dee5805): judging by name shape alone kept 7 of 310 books; the role keeps the
    library. A citation never makes a document of another role a rule book."""
    return is_rule_book(entry)


def usable_ids(conn, ids, identifiers: dict | None = None) -> frozenset[str]:
    """Of `ids`, the usable held books (`usable`), read from the library. Without a database (a caller with no connection) only
    the book's identifier is known: an unroled public name."""
    ids = {str(i) for i in ids if i}
    if conn is None:
        names = identifiers or {}
        return frozenset(i for i in ids if is_public_name(names.get(i)))
    by_id = {e["id"]: e for e in library(conn)}
    return frozenset(i for i in ids if usable(by_id.get(i)))


CITED_MARK = "__cited-"


def cited_key(key: str | None, cited: frozenset[str]) -> str | None:
    """The checklist key with a short stable hash of the cited company book ids: a checklist built with those books is reused
    only for a paper citing the same set. No cited company book: the key as it was."""
    if not key or not cited:
        return key
    return (
        key
        + CITED_MARK
        + hashlib.sha256(",".join(sorted(cited)).encode()).hexdigest()[:10]
    )


def base_key(key: str) -> str:
    """The key without its cited part (what S1 is shown as a type already made)."""
    return str(key).split(CITED_MARK, 1)[0]


def not_offered_company(conn, paper_id: str, ids: set[str]) -> frozenset[str]:
    """Of `ids`, the documents that are not usable rule books for this paper (`usable`). An id no longer in the library (re-roled,
    for example to a submittal, since the checklist was saved) is NOT usable either."""
    if not ids:
        return frozenset()
    by_id = {e["id"]: e for e in library(conn, exclude=frozenset({str(paper_id)}))}
    return frozenset(b for b in ids if not usable(by_id.get(b)))


def company_books_not_cited(conn, paper_id: str, books: dict) -> frozenset[str]:
    """A checklist's books (alias -> {book}) that are not usable rule books for this paper, on the shown list or not."""
    ids = {str(b.get("book")) for b in books.values() if b.get("book")}
    return not_offered_company(conn, paper_id, ids)


def wanted_not_held(not_held) -> frozenset[str]:
    """The governing and method books a checklist was written WITHOUT (`checklist.wanted`'s not-held part, by name): when this set
    changes (a book is now held, or the governing table changed), a saved checklist is not reused. Told apart by the explicit
    `source` key (`checklist.WANTED_SOURCES`), never by the words of `why`: an AI's "needed" name never forces a rebuild. A name
    saved before the key existed has no `source` at all (an AI name always had one): it is read by its `why`."""
    from . import WHY_GOVERNS, WHY_METHOD
    from . import checklist as CL

    def table_name(n: dict) -> bool:
        if "source" in n:
            return n.get("source") in CL.WANTED_SOURCES
        return str(n.get("why") or "").startswith((WHY_GOVERNS, WHY_METHOD))

    return frozenset(
        str(n.get("name") or "")
        for n in not_held or []
        if isinstance(n, dict) and table_name(n)
    )


#: The coverage floor of a checklist for a kind with no main equipment (a procedure, a contract: long papers of many topics).
FLOOR_ITEMS = 30


def floor_for(kind: str | None) -> int:
    """The coverage floor of a type's checklist: FLOOR_ITEMS for a kind with no main equipment (`kind_review_table`), else 0. The
    table holds no expected size per kind; this is the method's own floor (the lead, 18 Nov 2026)."""
    from app import kind_review_table

    table_kind = str(kind or "").strip().lower().replace(" ", "_")
    try:
        long_kinds = kind_review_table.no_main_equipment_kinds()
    except Exception as exc:  # noqa: BLE001 - an unreadable table gives no floor, never a stop
        log.info(
            "general review: kind table not read for the floor (%s)", type(exc).__name__
        )
        return 0
    return FLOOR_ITEMS if table_kind in long_kinds else 0


def _fold(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def resolve(lib: list[dict], cited: str) -> dict | None:
    """The held document a citation names: by identifier (the app's `find_standard`), then by the cited name being the document's
    own file name (its stem, without a leading sequence number and a revision tail), compared whole. Never a partial name."""
    from app import applicability

    found = applicability.find_standard(
        [e for e in lib if (e.get("document_role") or "") == STANDARD_ROLE], cited
    )
    if found:
        return found
    want = _fold(cited)
    if len(want) < 6:
        return None
    best = None
    for e in lib:
        stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", e.get("filename") or "")
        stem = re.sub(r"^\s*\d+[a-z]?\s*-\s*", "", stem, flags=re.I)
        core = re.sub(r"\s*-\s*rev\.?\s*\d+\s*$", "", stem, flags=re.I)
        names = {_fold(core), _fold(identifier_of(e))}
        names.discard("")
        if want in names and (
            best is None or e.get("document_role") == "CONTRACT_DOCUMENT"
        ):
            best = e
    return best


def committee_role(entry: dict) -> str | None:
    """A book's role from standard_roles.json (by identifier), else the governing-books role if it governs any type."""
    from app import standard_ids

    roles = _json("standard_roles.json")
    ident = identifier_of(entry)
    for name, role in (roles.get("standards") or {}).items():
        if standard_ids.same_standard(name, ident):
            return role
    for books in _json("governing_standards.json")["equipment_types"].values():
        if any(standard_ids.same_standard(b, ident) for b in books):
            return roles.get("governing_books_role")
    return None


def role_applies(entry: dict, kind: str | None) -> bool:
    rk = ROLE_KIND.get(kind or "")
    applies = (
        (_json("standard_roles.json").get("kinds_apply") or {}).get(rk) if rk else None
    )
    role = committee_role(entry)
    return not applies or role is None or role in applies


def governing_books(
    lib: list[dict], type_id: str | None
) -> list[tuple[dict | None, str]]:
    """Held books governing the equipment type (governing_standards.json), and the unheld ones by name."""
    from app import applicability

    if not type_id:
        return []
    types, _fam = type_set(type_id)
    names = {
        app_name
        for app_name, tid in _json("equipment_mapping.json")["map"].items()
        if tid in types
    }
    gov = _json("governing_standards.json")["equipment_types"]
    stds = [e for e in lib if (e.get("document_role") or "") == STANDARD_ROLE]
    out = []
    for app_name in sorted(names):
        for ident in gov.get(app_name, []):
            out.append((applicability.find_standard(stds, ident), ident))
    return out


def method_books(lib: list[dict], kind: str | None) -> list[tuple[dict | None, str]]:
    from app import applicability

    rk = ROLE_KIND.get(kind or "")
    names = (
        (_json("standard_roles.json").get("method_standards") or {}).get(rk) or []
        if rk
        else []
    )
    stds = [e for e in lib if (e.get("document_role") or "") == STANDARD_ROLE]
    return [(applicability.find_standard(stds, n), n) for n in names]


# ------------------------------------------------------------------ rules


def _tables(conn) -> set[str]:
    return {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def rule_pool(
    conn,
    kind: str | None,
    type_id: str | None,
    *,
    books: set[str] | frozenset[str] = frozenset(),
    within: frozenset[str] | None = None,
    subjects: bool = True,
) -> list[dict]:
    """Stored rules a paper of this kind (and equipment) is checked on, by the library's labels only.

    In: the rule's kind label is one of the paper kind's labels (two models agreed); and, when the paper has an equipment type,
    the rule's agreed equipment tag is general, the type (or a type it applies as), the family with no type, or not agreed. A
    rule agreed to be about OTHER equipment is out. With `books`, every rule of those books passes the kind test (a governing
    book). With `within`, only rules of those books are read at all (the run's catalog holds only the listed books)."""
    held = _tables(conn)
    if "standard_requirements" not in held or (within is not None and not within):
        return []
    labels = KIND_LABELS.get(kind or "") or ("other",)
    types, fam = type_set(type_id)
    has_kind = "rule_label" in held
    has_equip = "rule_equipment_label" in held
    cols = [
        "sr.id AS id",
        "sr.standard_document_id AS book",
        "sr.clause AS clause",
        "sr.page AS page",
        "sr.source_text AS source_text",
        "sr.requirement_text AS requirement_text",
        "rl.reading_json AS reading_json" if has_kind else "NULL AS reading_json",
        "el.equip_state AS equip_state" if has_equip else "NULL AS equip_state",
        "el.equip_general AS equip_general" if has_equip else "0 AS equip_general",
        "el.equip_type AS equip_type" if has_equip else "NULL AS equip_type",
        "el.equip_family AS equip_family" if has_equip else "NULL AS equip_family",
    ]
    sql = "SELECT " + ", ".join(cols) + " FROM standard_requirements sr"
    if has_kind:
        sql += " LEFT JOIN rule_label rl ON rl.source = 'requirement' AND rl.rule_ref = sr.id"
    if has_equip:
        sql += " LEFT JOIN rule_equipment_label el ON el.source = 'requirement' AND el.rule_ref = sr.id"
    where, args = [], []
    if has_kind:
        where.append(
            f"(rl.paper_kind IN ({','.join('?' for _ in labels)}) AND rl.state = 'ai_approved')"
        )
        args += list(labels)
    if books:
        where.append(f"sr.standard_document_id IN ({','.join('?' for _ in books)})")
        args += sorted(books)
    if not where:
        return []
    sql += " WHERE sr.superseded_at IS NULL AND (" + " OR ".join(where) + ")"
    if within is not None:
        sql += f" AND sr.standard_document_id IN ({','.join('?' for _ in within)})"
        args += sorted(within)
    out = []
    for r in conn.execute(sql, args):
        r = dict(r)
        tagged = False
        if types and r["equip_state"] == "agreed" and not r["equip_general"]:
            if r["equip_type"] in types or (
                r["equip_type"] is None and r["equip_family"] == fam
            ):
                tagged = True
            else:
                continue  # agreed to be about other equipment
        r["tagged"] = tagged
        r["subject"] = ""
        if subjects:
            try:
                r["subject"] = str(
                    (json.loads(r["reading_json"] or "{}") or {}).get("subject") or ""
                ).strip()[:60]
            except (ValueError, AttributeError):
                r["subject"] = ""
        out.append(r)
    return out


def catalog(
    lib_by_id: dict[str, dict], pool: list[dict], top_subjects: int = 6
) -> list[dict]:
    """One line per book holding pool rules: identifier, committee, counts, its most common rule subjects (library labels)."""
    by_book: dict[str, list[dict]] = defaultdict(list)
    for r in pool:
        by_book[r["book"]].append(r)
    out = []
    for book, rows in by_book.items():
        e = lib_by_id.get(book)
        if not e:
            continue
        subj = Counter(r["subject"] for r in rows if r["subject"])
        out.append(
            {
                "book": book,
                "identifier": identifier_of(e),
                "committee": e.get("committee") or "",
                "rules": len(rows),
                "tagged": sum(1 for r in rows if r["tagged"]),
                "subjects": [s for s, _n in subj.most_common(top_subjects)],
            }
        )
    out.sort(key=lambda c: (-c["tagged"], -c["rules"], c["book"]))
    return out


class BookText:
    """The stored pages of the books of one run, each read once (`agent_review_standards.read_book`: text, else OCR)."""

    def __init__(self, conn) -> None:
        self.conn = conn
        self._pages: dict[str, dict[int, str]] = {}

    def pages(self, doc: str) -> dict[int, str]:
        if doc not in self._pages:
            from app import agent_review_standards

            self._pages[doc] = dict(
                agent_review_standards.read_book(self.conn, str(doc)).pages
            )
        return self._pages[doc]

    def page(self, doc: str, page: int) -> str | None:
        return self.pages(doc).get(int(page))


# ------------------------------------------------------------------ plan time: the books a review MAY use


def _paper_citations(conn, paper_id: str) -> list[str]:
    """The standards the paper names, read by code (names of standards only, never the paper's text)."""
    from app import agent_review_standards, standard_ids

    pages = agent_review_standards.read_book(conn, str(paper_id)).pages
    return standard_ids.cited_standards("\n".join(t for _n, t in sorted(pages.items())))


def stored_reading(
    conn, paper_id: str, allowed: frozenset[str]
) -> tuple[str | None, str | None, str]:
    """(method kind, taxonomy type id, how the app's stored reading decided the kind). Reads only; a fault is 'unknown'."""
    from app import agent_review_kind

    try:
        got = agent_review_kind.read_kind(conn, str(paper_id))
    except Exception as exc:  # noqa: BLE001 - an unreadable reading is an unknown kind, never a guess
        log.info("general review plan: kind unreadable (%s)", type(exc).__name__)
        return None, None, agent_review_kind.SOURCE_NONE
    if not (got.get("known") and got.get("kind")):
        return (
            None,
            None,
            agent_review_kind.decided_by(
                got.get("method"), got.get("page"), bool(got.get("guess"))
            ),
        )
    kind = method_kind(str(got["kind"]))
    source = agent_review_kind.decided_by(
        got.get("method"), got.get("page"), bool(got.get("guess"))
    )
    try:
        equipment, _where = agent_review_kind.read_equipment(str(paper_id), allowed)
    except Exception as exc:  # noqa: BLE001 - an unreadable equipment reading is none
        log.info("general review plan: equipment unreadable (%s)", type(exc).__name__)
        equipment = None
    from .book_names import last_run_type

    # no stored equipment: the type the paper's last review named (S1), so its governing books lead the plan
    return kind, type_id_of(equipment) or last_run_type(conn, paper_id), source


def checklist_key(
    kind: str | None, type_id: str | None, subject_key: str | None = None
) -> str | None:
    """`<kind>__<equipment type or subject>`: the key a checklist is saved and found under. None without both parts."""
    tail = (
        type_id
        or re.sub(r"[^a-z0-9]+", "_", str(subject_key or "").lower()).strip("_")[:60]
    )
    if not kind or not tail:
        return None
    return f"{kind}__{tail}"


def saved_books(checklist: dict | None) -> list[str]:
    """The document ids a saved checklist's items rest on, in first-use order."""
    out: list[str] = []
    for b in (checklist or {}).get("books") or []:
        bid = str(b.get("book") or "") if isinstance(b, dict) else ""
        if bid and bid not in out:
            out.append(bid)
    return out


def candidates(
    conn,
    paper_id: str,
    allowed: frozenset[str],
    store,
    earlier_unlisted: frozenset[str] = frozenset(),
):
    """PLAN TIME. The rule books the general review MAY use, by library metadata only. No model, no socket, no write.

    A saved checklist for the paper's key: its books, then the governing and method books now held and the books an earlier
    review of this paper wanted but could not send (so a book held after the checklist was saved is listed and "review again"
    is true for it; light check e1c61001). Otherwise: books governing the stored equipment
    type, method books of the stored kind, books an earlier review of this paper wanted but could not send, books the paper cites
    (resolved by code), then books holding the most rules labelled for the kind (and type). Intersected with `allowed` (rule 5):
    a book outside it is counted in `unreadable`, never named. A book is offered when it is public, one of the client's own
    standards (its recorded role) or cited by the paper (`usable`). At most MAX_CANDIDATES books."""
    from . import Candidates

    paper_id = str(paper_id)
    kind, type_id, source = stored_reading(conn, paper_id, allowed)
    cited = cited_company(conn, paper_id)
    key = cited_key(checklist_key(kind, type_id), cited)
    saved = store.get(key) if key and store is not None else None
    order, not_held = (
        _saved_order(conn, paper_id, saved, kind, type_id, earlier_unlisted)
        if saved is not None
        else _ordered_books(conn, paper_id, kind, type_id, earlier_unlisted)
    )
    # a book is used when it is public, one of the client's own standards (its recorded role), or cited by the paper
    by_id = {e["id"]: e for e in library(conn, exclude=frozenset({paper_id}))}
    order = [(d, w) for d, w in order if usable(by_id.get(d))]
    readable = [(d, w) for d, w in order if d in allowed]
    unreadable = sum(1 for d, _w in order if d not in allowed)
    books = [{"id": d, "why": w} for d, w in readable[:MAX_CANDIDATES]]
    return Candidates(
        kind=kind,
        equipment_type=type_id,
        kind_source=source,
        books=books,
        not_held=_unique(not_held),
        unreadable=unreadable,
        checklist_key=key,
        checklist_saved=saved is not None,
    )


def _saved_order(
    conn, paper_id: str, saved: dict, kind, type_id, earlier: frozenset[str]
) -> tuple[list[tuple[str, str]], list[dict]]:
    """With a saved checklist: its books first, then the governing / method books now held and the books an earlier review
    wanted, in that order (the caller intersects with `allowed` and caps). The not-held governing / method names are said."""
    lib = library(conn, exclude=frozenset({paper_id}))
    by_id = {e["id"]: e for e in lib}
    order: list[
        tuple[str, str]
    ] = []  # governing, method and cited books FIRST (never cut by the cap), then the saved ones
    not_held: list[dict] = []
    for e, name, why in [(e, n, WHY_GOVERNS) for e, n in governing_books(lib, type_id) if not e or role_applies(e, kind)] + [
        (e, n, WHY_METHOD) for e, n in method_books(lib, kind)
    ] + [(resolve(lib, n), n, WHY_CITED) for n in _paper_citations(conn, paper_id)]:  # fmt: skip
        if e is None:
            not_held.append({"name": name, "why": f"{why}; not held"})
        elif e["id"] not in {d for d, _w in order}:
            order.append((e["id"], why))
    order += [
        (b, WHY_SAVED)
        for b in saved_books(saved)
        if b != paper_id and b not in {d for d, _w in order}
    ]
    for b in sorted(earlier):
        if b in by_id and b not in {d for d, _w in order}:
            order.append((b, WHY_LAST))
    return order, not_held


def _ordered_books(
    conn, paper_id: str, kind: str | None, type_id: str | None, earlier: frozenset[str]
) -> tuple[list[tuple[str, str]], list[dict]]:
    """(book id, why) in priority order, and the books named but not held: governing, method, wanted earlier, cited, rules."""
    lib = library(conn, exclude=frozenset({paper_id}))
    by_id = {e["id"]: e for e in lib}
    order: list[tuple[str, str]] = []
    not_held: list[dict] = []

    def add(doc_id: str, why: str) -> None:
        if doc_id and doc_id not in {d for d, _w in order}:
            order.append((doc_id, why))

    def named(found: dict | None, name: str, why: str) -> None:
        if found:
            add(found["id"], why)
        else:
            not_held.append({"name": name, "why": f"{why}; not held"})

    for e, name in governing_books(lib, type_id):
        if not e or role_applies(e, kind):
            named(e, name, WHY_GOVERNS)
    for e, name in method_books(lib, kind):
        named(e, name, WHY_METHOD)
    for b in sorted(earlier):
        if b in by_id:
            add(b, WHY_LAST)
    for name in _paper_citations(conn, paper_id):
        named(resolve(lib, name), name, WHY_CITED)
    if kind:
        for c in catalog(by_id, rule_pool(conn, kind, type_id, subjects=False)):
            if role_applies(by_id[c["book"]], kind):
                add(c["book"], WHY_RULES)
    return order, not_held


def _unique(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        k = r["name"].casefold()
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out
