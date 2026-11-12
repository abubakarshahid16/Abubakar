"""The paper's kind FIRST, then its equipment type (#1690, owner order 11 Nov 2026, step D).

The kind is decided by code from the paper's own pages and its stored classification (`paper_kind.decide_paper_kind`, via
the rule filter's reader): an engineer-confirmed kind decides; otherwise the cover and title are read. UNKNOWN STAYS
UNKNOWN: no kind is invented, no rule is asked for such a paper, and the run says so. A kind that is a guess is labelled a
guess until a person confirms it (CLAUDE.md rule 4).

The equipment type is the app's own reading (`subject_scope.read_equipment`: the stored classification, then the title, then
the type fields), in the app's vocabulary. Unknown or doubtful: none.
"""

from __future__ import annotations

from dataclasses import dataclass

from .db import connect

UNKNOWN = "unknown"
SOURCE_CONFIRMED = "confirmed by an engineer"
SOURCE_READ = "read by code from the cover and title"
SOURCE_GUESS = "guessed by code (until an engineer confirms it)"
SOURCE_NONE = "no cue found: unknown"


#: How a kind was decided, in plain words for the screen: the method code of `paper_kind` -> words. Words only, never a quote.
DECIDED_BY = {
    "engineer_confirmed": "an engineer confirmed the kind",
    "number_type_code": "the type code in the document number",
    "title_cue": "a heading on the cover or title page",
    "cover_contract_words": "the opening words of a contract on the first page",
    "title_equipment": "an equipment name in the title (a guess)",
    "blank_form": "a form with labels and no values (a guess)",
    "document_role": "the stored document role (a guess)",
    "cues_conflict": "two different headings on the cover (a data-sheet heading and a calculation or contract heading): not sure, choose (a guess)",
    "earlier_review": "the kind the earlier review of this paper used (a heading cue never changes it; an engineer may correct it)",
    "no_cue": "no cue found on the cover or title page",
    "no_pages": "the paper has no stored pages",
}


def decided_by(method: str | None, page: int | None = None, guess: bool = False) -> str:
    """'decided by: <words>[, page N][ (a guess until an engineer confirms it)]' from the method code. Words and a page number only."""
    words = DECIDED_BY.get(str(method or ""), "a cue the code could not name")
    where = f", page {page}" if isinstance(page, int) and page >= 1 else ""
    tail = (
        " (a guess until an engineer confirms it)"
        if guess and "guess" not in words
        else ""
    )
    return f"decided by: {words}{where}{tail}"


@dataclass(frozen=True)
class PaperReading:
    kind: str  # "datasheet", "procedure", ... or "unknown"
    known: bool
    source: str  # words for the screen
    method: str
    guess: bool
    equipment_type: str | None
    equipment_source: str | None
    page: int | None = None
    candidates: tuple[str, ...] = ()

    @property
    def decided_by(self) -> str:
        return decided_by(self.method, self.page, self.guess)

    def as_dict(self) -> dict:
        """The kind as the item builder takes it: {'kind', 'known', 'method', 'guess'} (kind None when unknown)."""
        return {
            "kind": self.kind if self.known else None,
            "known": self.known,
            "method": self.method,
            "guess": self.guess,
        }

    @property
    def item_kind(self) -> str | None:
        """The kind in the item builder's spelling ("test record"); None when unknown."""
        return self.kind.replace("_", " ") if self.known else None


def _earlier_review_kind(conn, held: set[str], document_id: str) -> str | None:
    """The paper kind of the paper's latest FINISHED AI review (a kind in the closed list), or None."""
    if "agent_review_run" not in held:
        return None
    row = conn.execute(
        "SELECT paper_kind FROM agent_review_run WHERE submittal_document_id = ? AND finished_at IS NOT NULL"
        " AND paper_kind IS NOT NULL ORDER BY finished_at DESC LIMIT 1",
        (document_id,),
    ).fetchone()
    from . import paper_kind as pk

    kind = row[0] if row else None
    return kind if kind in pk.PAPER_KINDS else None


def read_kind(conn, document_id: str) -> dict:
    """{'kind': str | None, 'known', 'method', 'guess'} from the stored pages and the stored classification (reads only).

    An engineer-confirmed kind (`document_kinds`) decides; else `paper_kind.decide_paper_kind` reads the cover and title.
    No cue found: `known` False and no kind (never "other" by default)."""
    from . import paper_kind as pk

    held = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    confirmed = None
    if "document_kinds" in held:
        row = conn.execute(
            "SELECT kind, state FROM document_kinds WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        if row is not None and row["state"] == "confirmed":
            confirmed = row["kind"]
    pages = [
        dict(r)
        for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        )
    ]
    if not pages and not confirmed:
        return {"kind": None, "known": False, "method": "no_pages", "guess": False}
    role = None
    if "document_classification" in held:
        row = conn.execute(
            "SELECT document_role FROM document_classification WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        role = row["document_role"] if row else None
    earlier = None if confirmed else _earlier_review_kind(conn, held, document_id)
    if (
        earlier is not None
    ):  # (a) a paper that already has a finished review keeps that review's kind: a cue never changes it
        return {
            "kind": earlier,
            "known": True,
            "method": "earlier_review",
            "guess": True,
            "page": None,
        }
    got = pk.decide_paper_kind(pages, document_role=role, confirmed_kind=confirmed)
    unknown = got.source_kind == "unknown" and got.method != "engineer_confirmed"
    return {
        "kind": None if unknown else got.paper_kind,
        "known": not unknown,
        "method": got.method,
        "guess": bool(got.guess),
        "page": got.page,
        "candidates": list(got.candidates),
    }


def read_equipment(
    document_id: str, allowed: frozenset[str]
) -> tuple[str | None, str | None]:
    """(equipment type, where it was read) by the app's one reader; (None, None) when unknown or doubtful."""
    from . import classification, datasheets, subject_scope

    facts = datasheets.list_facts(document_id, allowed_document_ids=allowed)
    record = classification.of_document(document_id) or {}
    found, source, _doubt = subject_scope.read_equipment(
        record, facts, subject_scope.vocabulary()
    )
    if not found:
        return None, source
    return sorted(found)[0], source


def decide(document_id: str, allowed: frozenset[str]) -> PaperReading:
    got = read_kind(connect(), document_id)
    known = bool(got.get("known")) and bool(got.get("kind"))
    if not known:
        kind, source = UNKNOWN, SOURCE_NONE
    elif got.get("method") == "engineer_confirmed":
        kind, source = str(got["kind"]), SOURCE_CONFIRMED
    elif got.get("guess"):
        kind, source = str(got["kind"]), SOURCE_GUESS
    else:
        kind, source = str(got["kind"]), SOURCE_READ
    equipment, equipment_source = (
        read_equipment(document_id, allowed) if known else (None, None)
    )
    return PaperReading(
        kind,
        known,
        source,
        str(got.get("method") or ""),
        bool(got.get("guess")),
        equipment,
        equipment_source,
        got.get("page"),
        tuple(got.get("candidates") or ()),
    )


def describe(document_id: str, allowed: frozenset[str]) -> dict:
    """What the review page shows BEFORE a review starts (words, ids and counts only, no paper text): the kind the code decides,
    how it decided it, whether that is a guess, which review that kind gets (from the one table, `kind_review_table`), the
    checklist slot (an empty slot says so) and the kinds a person may choose to correct it. A correction is the existing
    route `PUT /api/documents/{id}/kind` (an engineer confirms a kind); the next review reads the confirmed kind."""
    from . import doc_router, kind_review_table

    reading = decide(document_id, allowed)
    key = reading.kind if reading.known else kind_review_table.UNKNOWN
    row = kind_review_table.row(key)
    return {
        "document_id": document_id,
        "kind": reading.kind,
        "known": reading.known,
        "source": reading.source,
        "decided_by": reading.decided_by,
        "guess": reading.guess,
        "candidates": list(reading.candidates),
        "not_sure_choose": reading.method == "cues_conflict",
        "confirmed": reading.method == "engineer_confirmed",
        "review": row["review"],
        "rules_of_kind": list(row["rules_of_kind"]),
        "checklist": row["checklist_slot"],
        "equipment_type": reading.equipment_type,
        "choices": doc_router.kinds(),
        "correct_with": f"PUT /api/documents/{document_id}/kind",
    }
