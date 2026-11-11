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


@dataclass(frozen=True)
class PaperReading:
    kind: str  # "datasheet", "procedure", ... or "unknown"
    known: bool
    source: str  # words for the screen
    method: str
    guess: bool
    equipment_type: str | None
    equipment_source: str | None

    @property
    def item_kind(self) -> str | None:
        """The kind in the item builder's spelling ("test record"); None when unknown."""
        return self.kind.replace("_", " ") if self.known else None


def read_kind(conn, document_id: str) -> dict:
    """{'kind': str | None, 'known', 'method', 'guess'} from the stored pages (reads only)."""
    from . import agent_review_rules as rules

    return rules.paper_kind_of(conn, document_id)


def read_equipment(document_id: str, allowed: frozenset[str]) -> tuple[str | None, str | None]:
    """(equipment type, where it was read) by the app's one reader; (None, None) when unknown or doubtful."""
    from . import classification, datasheets, subject_scope

    facts = datasheets.list_facts(document_id, allowed_document_ids=allowed)
    record = classification.of_document(document_id) or {}
    found, source, _doubt = subject_scope.read_equipment(record, facts, subject_scope.vocabulary())
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
    equipment, equipment_source = read_equipment(document_id, allowed) if known else (None, None)
    return PaperReading(kind, known, source, str(got.get("method") or ""), bool(got.get("guess")), equipment,
                        equipment_source)
