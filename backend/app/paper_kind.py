"""Paper kind first (owner order 11 Nov 2026, step 2; part of #805).

Before the equipment type, every paper gets ONE kind from a closed list:
datasheet, procedure, contract, drawing, test record, other. A procedure or a
contract never gets an equipment type as its MAIN label; it may keep one as a
secondary label.

The kind comes from general signals in the paper itself: the type code of its
document number and its cover and title words, exactly as `document_kind`
reads them (#1474, #1476), plus one cue that list lacks (a test record). Never
from a file name, a tag or one sheet's layout (rule 13). No model, no network.

An engineer's confirmed kind (`document_kinds`, state `confirmed`) decides. A
kind outside the closed list (specification, transmittal, FEED, standard,
unknown) is `other`; when the document number says such a kind and the title
names a kind of the closed list, the title's kind is used, marked a guess.

Classification is NOT access control (rule 5): this names what a paper is and
never changes who may read it. Behind `settings.paper_kind_first_enabled`, OFF.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

from . import document_kind, kind_review_table
from .classification import _now, suggest_equipment_type_from_title, title_block_lines
from .db import connect, schema_once

_log = logging.getLogger(__name__)

PAPER_KIND_VERSION = "paper-kind-v1"

#: The closed list. `other` is a real answer, never a hidden default.
PAPER_KINDS: tuple[str, ...] = (
    "datasheet",
    "procedure",
    "contract",
    "calculation",
    "specification",
    "transmittal",
    "drawing",
    "test_record",
    "other",
)
#: Plain words for each kind (the owner's words).
WORDS: dict[str, str] = {k: k.replace("_", " ") for k in PAPER_KINDS}
#: Kinds whose MAIN label is never an equipment type.
NO_MAIN_EQUIPMENT: frozenset[str] = frozenset(kind_review_table.no_main_equipment_kinds())  # the one table

#: A record of a test or inspection that was done (its result), named in the
#: title. A test PLAN or test PROCEDURE says how a test is done: a procedure.
_TEST_RECORD = re.compile(
    r"\b(?:test(?:ing)?|inspection|calibration|examination)\s+"
    r"(?:reports?|records?|certificates?|results?|logs?)\b"
    r"|\bcertificates?\s+of\s+(?:conformity|conformance|compliance|calibration"
    r"|inspection|testing|tests?)\b",
    re.I,
)
#: `document_kind`'s title cues with the test-record cue after "procedure", so
#: a "test report procedure" is a procedure and a "test report" a test record.
#: A calculation names itself ("sizing calculation", "calculation sheet", "calc"): it is read BEFORE the datasheet cue, so a
#: calculation titled with an equipment name is a calculation, never a datasheet (K1b; a procedure, a test record, a contract, a
#: specification, a drawing and a FEED title still come first).
_CALCULATION = re.compile(r"\bcalculations?\b|\bcalcs?\b", re.I)
#: A contract that names itself by its subject ("Contract for ...", "Supply contract", "Subcontract"): the router's contract cue
#: reads agreement / general conditions / terms and conditions only. "Contract No." is a label naming a number, never the title.
_CONTRACT_HEADING = re.compile(
    r"\bcontract\s+(?:for|between|of)\b|\b(?:sub-?contract|supply\s+contract|service\s+contract"
    r"|construction\s+contract|master\s+contract)\b|^\W*(?:the\s+)?contract\W*$",
    re.I,
)


#: A transmittal is identified by its own number ("Transmittal No. TR-7"). The router's reading skips a kind word followed by
#: "No." (a label naming ANOTHER document, "P&ID No."); a transmittal's own number is consumed here, so the line is read.
_TRANSMITTAL_NUMBER = re.compile(r"\btransmittal\s+(?:no\b\.?|number|nr\b\.?|#)\s*[A-Z0-9][\w/.-]*", re.I)


def _paper_cues() -> tuple[tuple[str, re.Pattern[str]], ...]:
    out: list[tuple[str, re.Pattern[str]]] = []
    for kind, pattern in document_kind._KIND_CUES:
        if kind == "contract":
            pattern = re.compile(pattern.pattern + "|" + _CONTRACT_HEADING.pattern, re.I)
        if kind == "datasheet":
            out.append(("calculation", _CALCULATION))
        if kind == "transmittal":
            pattern = re.compile(_TRANSMITTAL_NUMBER.pattern + "|" + pattern.pattern, re.I)
        out.append((kind, pattern))
        if kind == "procedure":
            out.append(("test_record", _TEST_RECORD))
    return tuple(out)


PAPER_CUES: tuple[tuple[str, re.Pattern[str]], ...] = _paper_cues()
#: `document_kind` kinds (and the router's, `reference/document_kinds.json`, which
#: an engineer may confirm) that are kinds of the closed list.
_SAME = set(PAPER_KINDS) - {"other"}
#: Every other kind is `other`, on purpose: specification, transmittal, FEED,
#: standard, study, report, letter and unknown. The owner's list is closed (order
#: 11 Nov step 2); none of them is a datasheet, procedure, contract, drawing or
#: test record, and a new name must never silently become one of those. "other"
#: is not a procedure or contract, so its equipment type is left as it was.


def to_paper_kind(kind: str | None) -> str:
    """The closed-list kind of any stored or decided kind; anything else is `other`."""
    k = (kind or "").strip().lower().replace(" ", "_")
    return k if k in _SAME else "other"


@dataclass(frozen=True)
class PaperKind:
    paper_kind: str
    page: int | None
    quote: str | None
    method: str
    guess: bool
    source_kind: str | None
    version: str = PAPER_KIND_VERSION

    def as_dict(self) -> dict:
        return {
            "paper_kind": self.paper_kind,
            "page": self.page,
            "quote": self.quote,
            "method": self.method,
            "guess": self.guess,
            "source_kind": self.source_kind,
            "version": self.version,
        }


def decide_paper_kind(
    pages: Sequence[dict],
    *,
    document_role: str | None = None,
    confirmed_kind: str | None = None,
) -> PaperKind:
    """The paper kind of ONE paper from its own pages; pure, no I/O.

    `confirmed_kind`: a kind an engineer confirmed, which decides. Otherwise the
    cover and title, read by `document_kind.decide_document_kind` with
    `PAPER_CUES`."""
    if confirmed_kind:
        return PaperKind(
            to_paper_kind(confirmed_kind),
            None,
            None,
            "engineer_confirmed",
            False,
            confirmed_kind,
        )
    found = document_kind.decide_document_kind(
        pages, document_role=document_role, cues=PAPER_CUES
    )
    kind = to_paper_kind(found.kind)
    guess = found.guess
    if kind in ("other", "specification") and to_paper_kind(found.conflict) not in (
        "other",
        "specification",
    ):
        # The number names a kind outside the list, the title one inside it:
        # the title's kind, a guess.
        kind, guess = to_paper_kind(found.conflict), True
    return PaperKind(kind, found.page, found.quote, found.method, guess, found.kind)


# ------------------------------------------------------------------ storage


@schema_once
def ensure_schema(conn=None) -> None:
    c = conn or connect()
    with c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS paper_kinds ("
            " document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,"
            " paper_kind TEXT NOT NULL,"
            " evidence TEXT NOT NULL,"
            " decided_at TEXT NOT NULL)"
        )


def stored(document_id: str) -> str | None:
    """The stored paper kind, or None."""
    ensure_schema()
    row = (
        connect()
        .execute(
            "SELECT paper_kind FROM paper_kinds WHERE document_id = ?", (document_id,)
        )
        .fetchone()
    )
    return None if row is None else row["paper_kind"]


def classify_paper_kind(document_id: str) -> PaperKind | None:
    """Decide and store the paper kind. None, writing nothing, when the switch is off."""
    from .config import settings

    if not settings.paper_kind_first_enabled:
        return None
    ensure_schema()
    conn = connect()
    pages = [
        dict(r)
        for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        )
    ]
    role = conn.execute(
        "SELECT document_role FROM document_classification WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    confirmed = document_kind.stored_kind(document_id)
    decided = decide_paper_kind(
        pages,
        document_role=role["document_role"] if role else None,
        confirmed_kind=confirmed[0]
        if confirmed and confirmed[1] == "confirmed"
        else None,
    )
    if decided.paper_kind not in PAPER_KINDS:  # the list is closed
        raise ValueError(f"not a paper kind: {decided.paper_kind}")
    with conn:
        conn.execute(
            "INSERT INTO paper_kinds (document_id, paper_kind, evidence, decided_at)"
            " VALUES (?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET"
            " paper_kind = excluded.paper_kind, evidence = excluded.evidence,"
            " decided_at = excluded.decided_at",
            (document_id, decided.paper_kind, json.dumps(decided.as_dict()), _now()),
        )
    return decided


def classify_quietly(document_id: str) -> PaperKind | None:
    """`classify_paper_kind`; a failure is logged (no text) and never blocks the caller."""
    try:
        return classify_paper_kind(document_id)
    except Exception as exc:  # noqa: BLE001 - a label must not block ingestion
        _log.warning(
            "the paper kind of %s was not written (%s)", document_id, type(exc).__name__
        )
        return None


# ------------------------------------------------- equipment type, secondary


def secondary_equipment(pages: Sequence[dict]) -> dict | None:
    """The equipment type the title block names, kept as a SECONDARY label of a
    procedure or contract: from heading-shaped title lines only, never the body."""
    lines = [
        (pg, ln)
        for pg, ln in title_block_lines(pages)
        if len(ln.split()) <= document_kind._TITLE_WORDS_MAX
        and not ln.rstrip().endswith(".")
    ]
    found = suggest_equipment_type_from_title(lines)
    if found is None:
        return None
    return {
        "equipment_type": found.equipment_type,
        "page": found.page,
        "quote": found.quote,
    }


def no_main_equipment(document_id: str, pages: Sequence[dict]) -> bool:
    """Called before the equipment type is decided: True when no main type may be
    stored (a procedure or a contract; or the kind could not be decided, logged).
    Switch off: False, nothing written."""
    try:
        return hold_main_equipment(document_id, pages) is not None
    except Exception as exc:  # noqa: BLE001 - no kind, no guessed type
        _log.warning(
            "the paper kind of %s was not decided (%s); no equipment type stored",
            document_id,
            type(exc).__name__,
        )
        return True


def hold_main_equipment(document_id: str, pages: Sequence[dict]) -> str | None:
    """With the switch on: the paper kind when it is one that never takes an
    equipment type as its MAIN label (then the stored type is cleared and any
    title-block type kept as secondary, the old value audited); else None and
    nothing is written. Called before the equipment type is decided."""
    from . import classification
    from .config import settings

    if not settings.paper_kind_first_enabled:
        return None
    decided = classify_paper_kind(document_id)
    if decided is None or decided.paper_kind not in NO_MAIN_EQUIPMENT:
        return None
    conn = connect()
    old = conn.execute(
        "SELECT equipment_type FROM document_classification WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    now = _now()
    evidence = {
        "page": None,
        "quote": None,
        "method": "paper_kind_first",
        "main_label": decided.paper_kind,
        "secondary_equipment": secondary_equipment(pages),
        "confidence": None,
        "classifier_version": PAPER_KIND_VERSION,
        "classified_at": now,
    }
    with conn:
        conn.execute(
            "UPDATE document_classification SET equipment_type = NULL,"
            " equipment_type_evidence = ? WHERE document_id = ?",
            (json.dumps(evidence), document_id),
        )
    if old is not None and old["equipment_type"] is not None:
        classification._audit_equipment_type_change(
            document_id,
            old_value=old["equipment_type"],
            evidence=classification.EquipmentTypeEvidence(
                equipment_type=f"none ({WORDS[decided.paper_kind]})",
                page=None,
                quote="",
                method="paper_kind_first",
                confidence=0.0,
                classifier_version=PAPER_KIND_VERSION,
                classified_at=now,
            ),
            classified_by="paper_kind_first",
        )
    return decided.paper_kind


def after_confirm(document_id: str) -> str | None:
    """An engineer confirmed the document's kind (`doc_router.confirm`). Switch on:
    the paper kind is derived again from that kind (it always wins) and the main
    label rule applied: a procedure or contract has its main equipment type cleared
    (audited); any other kind has its type decided again for a submittal. Returns
    the stored paper kind; switch off: None, nothing written."""
    from . import classification
    from .config import settings

    if not settings.paper_kind_first_enabled:
        return None
    pages = [
        dict(r)
        for r in connect().execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        )
    ]
    if hold_main_equipment(document_id, pages) is None:
        classification.classify_equipment_type_for_submittal(document_id)
    return stored(document_id)


def main_label(document_id: str) -> str | None:
    """The paper's main label: its equipment type, except for a procedure or a
    contract (or a paper with no type), whose main label is its paper kind."""
    kind = stored(document_id)
    if kind is None:
        return None
    row = (
        connect()
        .execute(
            "SELECT equipment_type FROM document_classification WHERE document_id = ?",
            (document_id,),
        )
        .fetchone()
    )
    equipment = row["equipment_type"] if row is not None else None
    if kind in NO_MAIN_EQUIPMENT or not equipment:
        return WORDS[kind]
    return equipment
