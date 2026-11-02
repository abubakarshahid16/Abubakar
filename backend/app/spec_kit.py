"""#1479 SPECIFICATION KIT (preparation): what a specification must contain.

For a submittal whose kind is `specification`, a per-discipline must-contain list
(`reference/spec_kit/<discipline>.json`, DRAFT until an engineer approves it; each
item names the HELD standard clause that asks for it, or says it needs a standard we
do not hold) is looked up in the specification's OWN stored page text. No model.

What code may say, and no more:

  * found      -> NEEDS_ENGINEER_REVIEW: "covered on page n: <quote>; engineer to
                  confirm". The quote is a verified slice of the stored page text.
  * not found  -> NEEDS_ENGINEER_REVIEW, counted in ONE review note. Never
                  MISSING_INFORMATION (a keyword search that finds nothing says what it
                  searched, not that the document lacks it).
  * numbers    -> when the library holds a datasheet for the same document number or
                  equipment tag (inside the review's own scope: narrows, never widens,
                  rule 5), a limit the specification states for a quantity the
                  datasheet also states is compared with the unit code. A difference is
                  an engineer row "specification says X, datasheet says Y" with both
                  pages. Never a verdict.
  * NEVER COMPLIANT.

SWITCH: `settings.spec_kit_enabled`, OFF by default.

PARKED KINDS (#1484 drawing; #1482 transmittal and #1483 contract wait, see
docs/parked-kits-waiting.md): the same mechanism, routed by the document's KIND instead of a
discipline. `reference/kind_kits/<kind>.json` holds a DRAFT must-contain list for a kind a held
standard covers; the rows, notes and CRS hooks are the ones above with the kind's noun in the
words ("A drawing states: ..."). No numeric cross-check for these kinds. SWITCH:
`settings.parked_kits_draft_enabled`, OFF by default and independent of `spec_kit_enabled`.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from . import claims, procedure_text
from .config import settings
from .crs_draft_lanes import KIND_NOUNS, SPEC_LANE
from .db import connect

log = logging.getLogger(__name__)

KIT_DIR = Path(__file__).parent / "reference" / "spec_kit"
KIND_KIT_DIR = Path(__file__).parent / "reference" / "kind_kits"
ORIGIN = "spec_kit"
LANE = SPEC_LANE
KIND = "specification"

FOUND = "spec_kit_found"
NOT_FOUND = "spec_kit_not_found"
MISMATCH = "spec_kit_numeric_mismatch"
NOT_RUN = "spec_kit_not_run"
TRANSMITTAL = "spec_kit_transmittal"  # #1482, rows made by transmittal_kit.py
REASON_CODES = (FOUND, NOT_FOUND, MISMATCH, NOT_RUN, TRANSMITTAL)

MAX_QUOTE = 400
#: Two values are "the same" within this relative tolerance after unit conversion.
TOLERANCE = 0.005
NOTE = "Specification check - not covered by keyword search; engineer to check"
NOT_RUN_NOTE = (
    "Specification kit not run: no discipline recognised "
    "(looked at equipment type, title, file name)"
)


@lru_cache(maxsize=1)
def kits() -> dict[str, dict]:
    """discipline -> kit, in a fixed order (the first whose words the document carries wins)."""
    out = {}
    for path in sorted(KIT_DIR.glob("*.json")):
        kit = json.loads(path.read_text())
        out[kit["discipline"]] = kit
    return out


@lru_cache(maxsize=1)
def kind_kits() -> dict[str, dict]:
    """document kind -> DRAFT kit, for the parked kinds a held standard covers."""
    out = {}
    for path in sorted(KIND_KIT_DIR.glob("*.json")):
        kit = json.loads(path.read_text())
        out[kit["kind"]] = kit
    return out


def held_count(kit: dict) -> tuple[int, int]:
    held = sum(1 for i in kit["items"] if i.get("held"))
    return held, len(kit["items"]) - held


def identify(document_id: str) -> dict | None:
    """The kit for this specification, from its equipment type, title and file name; None
    when no discipline's words are there (nothing runs: a guess is not made)."""
    row = (
        connect()
        .execute(
            "SELECT d.filename, c.equipment_type, c.title FROM documents d"
            " LEFT JOIN document_classification c ON c.document_id = d.id WHERE d.id = ?",
            (document_id,),
        )
        .fetchone()
    )
    if row is None:
        return None
    named = " ".join(str(x or "") for x in (row[0], row[1], row[2])).lower()
    for kit in kits().values():
        if any(word in named for word in kit["identify"]):
            return kit
    return None


def _fold(text: str) -> str:
    return " ".join(text.lower().split())


#: a contents-page line ("Scope ........ 6"): a heading's address, not the clause itself
_LEADER = re.compile(r"\.{4,}")


def _has(word: str, folded: str) -> bool:
    """One word of a term group: `re:<pattern>` is a regex, a word of three letters or fewer
    (rt, ut) must stand alone, any other is a substring."""
    if word.startswith("re:"):
        return re.search(word[3:], folded) is not None
    if len(word) <= 3 and word.isalnum():
        return re.search(rf"\b{re.escape(word)}\b", folded) is not None
    return word in folded


def find_item(item: dict, pages: list[tuple[int, str]]) -> dict | None:
    """{page, quote} of the first passage holding every word of one of the item's word
    groups, or None. The quote is cut from the stored page text and checked to be in it."""
    stored = dict(pages)
    for page_no, text in pages:
        for part in procedure_text.sentences(text):
            folded = _fold(procedure_text.reading_text(part))
            if (
                not folded
                or _LEADER.search(part)
                or not any(
                    all(_has(word, folded) for word in group) for group in item["terms"]
                )
            ):
                continue
            quote = " ".join(part.split())[:MAX_QUOTE]
            if _fold(quote) in _fold(stored[page_no]):
                return {"page": page_no, "quote": quote}
    return None


def _source(item: dict) -> str:
    held = item.get("held")
    if held:
        return f"{held['standard']} cl. {held['clause']} (p.{held['page']})"
    return "DRAFT item, no held standard clause"


def item_row(
    item: dict, pages: list[tuple[int, str]], noun: str = "specification"
) -> dict:
    found = find_item(item, pages)
    source = _source(item)
    if found:
        rationale = (
            f'{FOUND}: covered on page {found["page"]}: "{found["quote"]}" - the closest '
            f"passage by its words, not a finding that the item is adequate; engineer to confirm"
        )
        text = (
            f"{item['topic']}: covered on page {found['page']} of the {noun}; "
            f"engineer to confirm ({source})."
        )
    else:
        rationale = (
            f"{NOT_FOUND}: a keyword search of the {noun}'s pages found no passage "
            f"for '{item['topic']}'; engineer to check (it may be stated in other words)"
        )
        text = (
            f"{item['topic']}: no passage found by keyword search of the {noun} "
            f"({source}); engineer to check."
        )
    return {
        "item": item["id"],
        "requirement": f"A {noun} states: {item['topic']} ({source}).",
        "finding": text,
        "rationale": rationale,
        "page": found["page"] if found else None,
        "quote": found["quote"] if found else None,
        "clause": f"{item['held']['standard']} {item['held']['clause']}"
        if item.get("held")
        else None,
    }


# ---------------------------------------------------------------- numbers


def _facts(document_id: str) -> list[dict]:
    return [
        dict(r)
        for r in connect().execute(
            "SELECT field_label, field_name, field_value, raw_unit, unit, page FROM submittal_facts"
            " WHERE submittal_document_id = ? AND superseded_at IS NULL"
            " AND COALESCE(is_blank, 0) = 0 AND page IS NOT NULL",
            (document_id,),
        )
    ]


def _tags(raw: str | None) -> set[str]:
    try:
        values = json.loads(raw or "[]")
    except ValueError:
        return set()
    return {re.sub(r"[\s\-_/]+", "", str(v)).lower() for v in values if str(v).strip()}


def matching_datasheets(spec_id: str, scope: frozenset[str]) -> list[str]:
    """Documents of this review's scope that carry datasheet facts and share the
    specification's document number or an equipment tag. Nothing else is matched."""
    conn = connect()
    me = conn.execute(
        "SELECT document_number, equipment_tags FROM document_classification WHERE document_id = ?",
        (spec_id,),
    ).fetchone()
    if me is None:
        return []
    number = re.sub(r"\s+", "", me["document_number"] or "").lower()
    tags = _tags(me["equipment_tags"])
    if not number and not tags:
        return []
    found = []
    for doc in sorted(scope - {spec_id}):
        other = conn.execute(
            "SELECT document_number, equipment_tags FROM document_classification WHERE document_id = ?",
            (doc,),
        ).fetchone()
        if other is None:
            continue
        same_number = (
            number
            and number == re.sub(r"\s+", "", other["document_number"] or "").lower()
        )
        if (same_number or tags & _tags(other["equipment_tags"])) and _facts(doc):
            found.append(doc)
    return found


def _label_words(label: str) -> list[str]:
    return [
        w
        for w in re.findall(r"[a-z]{3,}", label.lower())
        if w not in {"the", "and", "for"}
    ]


def _differs(spec: claims.Measurement, sheet: claims.Measurement) -> bool | None:
    """True/False when both are comparable, None when they are not (another quantity,
    gauge against absolute, a unit the unit code does not know)."""
    if spec.normalized_value is None or sheet.normalized_value is None:
        return None
    if (
        spec.normalized_unit != sheet.normalized_unit
        or spec.reference != sheet.reference
    ):
        return None
    s, d = spec.normalized_value, sheet.normalized_value
    if spec.comparator in (">=", "min", ">"):
        return d < s
    if spec.comparator in ("<=", "max", "<"):
        return d > s
    return abs(s - d) > TOLERANCE * max(abs(s), abs(d), 1e-12)


def numeric_rows(
    pages: list[tuple[int, str]],
    facts: list[dict],
    datasheet_name: str = "the datasheet",
    sheet_id: str = "",
) -> list[dict]:
    """One row per datasheet fact whose label (all its words) a specification sentence also
    carries, with a number of the same quantity that differs. Each side's number is shown as
    written, with its page."""
    rows = []
    for fact in facts:
        label = fact["field_label"] or fact["field_name"] or ""
        words = _label_words(label)
        unit = fact["raw_unit"] or fact["unit"] or ""
        if len(words) < 2 or not unit or not fact["field_value"]:
            continue
        sheet = claims.normalise(str(fact["field_value"]), unit)
        if sheet.normalized_value is None:
            continue
        hit = None
        for page_no, text in pages:
            for part in procedure_text.sentences(text):
                folded = _fold(procedure_text.reading_text(part))
                if not all(w in folded for w in words):
                    continue
                # one number of this quantity in the sentence, or none is taken: with two
                # (design 10 bar, test 15 bar) nothing says which one the label belongs to
                same = [
                    m
                    for m in claims.extract_measurements(part)
                    if _differs(m, sheet) is not None
                ]
                if len(same) == 1 and _differs(same[0], sheet):
                    hit = (page_no, " ".join(part.split())[:MAX_QUOTE], same[0])
                    break
                if same:
                    break
            if hit:
                break
        if hit is None or _fold(hit[1]) not in _fold(dict(pages)[hit[0]]):
            continue
        spec_says = f"{hit[2].raw_value} {hit[2].raw_unit}".strip()
        sheet_says = f"{fact['field_value']} {unit}".strip()
        rows.append(
            {
                "item": f"numeric:{label}:{sheet_id}",
                "requirement": f"The specification and the datasheet state the same {label}.",
                "finding": (
                    f"{label}: specification says {spec_says} (page {hit[0]}), "
                    f"{datasheet_name} says {sheet_says} (page {fact['page']}); engineer to resolve."
                ),
                "rationale": (
                    f'{MISMATCH}: specification says {spec_says} on page {hit[0]}: "{hit[1]}"; '
                    f"{datasheet_name} says {sheet_says} on page {fact['page']}; "
                    f"not a verdict, engineer to resolve"
                ),
                "page": hit[0],
                "quote": hit[1],
                "clause": None,
            }
        )
    return rows


# ---------------------------------------------------------------- the run


def applies(document_id: str | None) -> bool:
    if not document_id:
        return False
    kind = procedure_text.document_kind(document_id)
    if kind == KIND:
        return bool(settings.spec_kit_enabled)
    return bool(settings.parked_kits_draft_enabled and kind in kind_kits())


def _name(document_id: str) -> str:
    """A datasheet is named by its document number, else its id: never text from it."""
    row = (
        connect()
        .execute(
            "SELECT document_number FROM document_classification WHERE document_id = ?",
            (document_id,),
        )
        .fetchone()
    )
    return (row[0] if row and row[0] else "") or document_id


def not_run_row(noun: str = "specification", note: str = NOT_RUN_NOTE) -> dict:
    return {
        "item": "not_run",
        "requirement": f"The {noun} kit ran.",
        "finding": note + f"; engineer to check the {noun}.",
        "rationale": f"{NOT_RUN}: {note}",
        "page": None,
        "quote": None,
        "clause": None,
    }


def kind_rows(kit: dict, document_id: str) -> list[dict]:
    """A parked kind's rows: nothing runs when the document has no stored page text (nothing
    was searched), else one row per item. No numeric cross-check."""
    noun = kit["noun"]
    pages = procedure_text.load_pages(document_id)
    if not any(text.strip() for _, text in pages):
        return [
            not_run_row(
                noun,
                f"{noun.capitalize()} kit not run: no page text is stored for the {noun} "
                f"(a scan not read yet?)",
            )
        ]
    return [item_row(i, pages, noun) for i in kit["items"]]


def rows_for(document_id: str, scope: frozenset[str]) -> list[dict]:
    kit = kind_kits().get(procedure_text.document_kind(document_id) or "")
    if kit is not None:
        return kind_rows(kit, document_id)
    kit = identify(document_id)
    if kit is None:
        return [not_run_row()]
    pages = procedure_text.load_pages(document_id)
    out = [item_row(i, pages) for i in kit["items"]]
    for sheet in matching_datasheets(document_id, scope):
        out.extend(
            numeric_rows(pages, _facts(sheet), f"datasheet {_name(sheet)}", sheet)
        )
    return out


def for_review(review_run_id: str, scope: frozenset[str]) -> None:
    """The review job's call, after the comparison. A failure never fails the review."""
    try:
        row = (
            connect()
            .execute(
                "SELECT submittal_document_id FROM review_runs WHERE id = ?",
                (review_run_id,),
            )
            .fetchone()
        )
        doc = row[0] if row else None
        if applies(doc):
            _store(review_run_id, doc, rows_for(doc, scope))
    except Exception as exc:  # noqa: BLE001 - the kit is optional; the review stands
        log.warning("specification kit skipped: %s", type(exc).__name__)


def _store(review_run_id: str, doc: str, rows: list[dict]) -> None:
    from . import review as rv

    conn = connect()
    kind = procedure_text.document_kind(doc)
    # a parked kind's rows carry the kind in their requirement id: the one place the noun is read from
    prefix = (
        f"{ORIGIN}:{kind}:"
        if kind in kind_kits() or kind in KIND_NOUNS
        else f"{ORIGIN}:"
    )
    with conn:
        conn.execute(
            "DELETE FROM review_findings WHERE review_run_id = ? AND origin = ?"
            f" AND {rv.UNDECIDED_SQL}",
            (review_run_id, ORIGIN),
        )
        for r in rows:
            made = rv.create(
                {
                    "document_id": doc,
                    "category": "technical_query",
                    "severity": "minor",
                    "confidence": "low",
                    "requirement": r["requirement"][:4000],
                    "finding": r["finding"],
                    "required_action": "",
                    "status": "open",
                    "approval_status": "pending",
                    "review_run_id": review_run_id,
                    "origin": ORIGIN,
                    "compliance_status": "NEEDS_ENGINEER_REVIEW",
                    "contractor_page": r["page"],
                    "contractor_evidence_text": r["quote"],
                    "requirement_source_text": r["requirement"][:4000],
                    "ai_rationale": r["rationale"],
                    "standard_clause": r["clause"],
                },
                created_by=None,
                conn=conn,
            )
            conn.execute(
                "UPDATE review_findings SET requirement_id = ? WHERE id = ?",
                (f"{prefix}{r['item']}", made["id"]),
            )
            if source := r.get("source"):
                # a row citing ANOTHER document (#1482: the required-submissions list): its
                # document, page and verified text, as a requirement source - not evidence
                conn.execute(
                    "UPDATE review_findings SET standard_document_id = ?, standard_page = ?,"
                    " requirement_source_text = ? WHERE id = ?",
                    (source[0], source[1], source[2][:4000], made["id"]),
                )


# ---------------------------------------------------------------- CRS hooks


def _code(finding: dict) -> str:
    return str(finding.get("reason_code") or finding.get("ai_rationale") or "")


def is_row(finding: dict) -> bool:
    return finding.get("origin") == ORIGIN and _code(finding).startswith(REASON_CODES)


def is_unfound(finding: dict) -> bool:
    """Searched and nothing found: counted in ONE note, not a CRS line each."""
    return is_row(finding) and _code(finding).startswith((NOT_FOUND, NOT_RUN))


def noun_of(finding: dict) -> str:
    """The noun of the document kind a kit row was written for ("specification" for the
    discipline kits), from its requirement id `spec_kit:<kind>:<item>`."""
    parts = str(finding.get("requirement_id") or "").split(":")
    if len(parts) >= 3 and parts[0] == ORIGIN and parts[1] in kind_kits():
        return kind_kits()[parts[1]]["noun"]
    if len(parts) >= 3 and parts[0] == ORIGIN and parts[1] in KIND_NOUNS:
        return parts[1]
    return "specification"


def notes(findings: list[dict]) -> list[dict]:
    """ONE review note per run for the items no passage was found for."""
    not_run = [f for f in findings if is_row(f) and _code(f).startswith(NOT_RUN)]
    if not_run:
        out = []
        for f in not_run:  # one note per not-run row (#1482: a run may have several)
            said = str(f.get("ai_rationale") or "")
            text = (
                said.split(": ", 1)[1]
                if said.startswith(NOT_RUN + ": ")
                else NOT_RUN_NOTE
            )
            out.append({"note": text, "standard": "", "count": 1, "detail": text + "."})
        return out
    rows = [f for f in findings if is_unfound(f)]
    if not rows:
        return []
    noun = noun_of(rows[0])
    lead = f"A {noun} states: "
    topics = [
        (f.get("requirement") or "").removeprefix(lead).split(" (")[0] for f in rows
    ]
    listed = "; ".join(topics[:8]) + (
        f"; and {len(topics) - 8} more" if len(topics) > 8 else ""
    )
    plural = "s" if len(rows) != 1 else ""
    return [
        {
            "note": NOTE
            if noun == "specification"
            else f"{noun.capitalize()} check - not covered by keyword search; engineer to check",
            "standard": "",
            "count": len(rows),
            "detail": (
                f"{len(rows)} item{plural} of the {noun} must-contain list (a DRAFT list) "
                f"have no passage found by a keyword search of the document's pages; the "
                f"document may state them in other words. Each is a finding of this run "
                f"(reason code {NOT_FOUND}): {listed}."
            ),
        }
    ]
