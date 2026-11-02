"""Specification grade to material family, owner-signed, for a rule that forbids a material. Off by default (#1584).

MATERIAL_REFERENCE_ENABLED is for the proof run only. Until an engineer confirms it, every finding that rests on it
says "owner-signed reference" and that it is not engineer-confirmed.

AI PROPOSES, A PERSON SIGNS, CODE DECIDES. One call from general knowledge, sending no document text and no value from any
sheet (`propose`). Each entry lands unsigned; only the owner's tick on the checklist's "Material reference" sheet signs it,
and an entry without one never decides. A value matches when its whole tokens are the entry's specification and grade,
nothing else: no substring, and a bare grade only where the signed entry says that is unambiguous. A value listing several
specifications is split on its list separator and each part must match. Words beside a grade are no match, so a Query.
Generic: nothing here knows a sheet or layout.

On a COPY only: `ensure_schema` refuses a live-shaped file, and the tables grant nothing (CLAUDE.md rule 5).
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from . import claude_approved, claude_batch_run, live_guard
from .ai.json_reply import unfenced
from .compile_budget import _room_gate
from .config import settings
from .reasoning_provider import ClaudeProvider, Packet, schema_errors

LABEL = "owner-signed reference"
NOT_CONFIRMED = f"{LABEL}, not engineer-confirmed"
#: v1 asked for no limit, and its one answer stopped at the output limit. v3 asks for the written variants as rows.
PROMPT_VERSION = "material-reference-v3"
STEP = "material-reference"
ENGINE_CLAUDE = "claude"
SOURCE = "AI proposed"
OWNER = "owner"
APPROVE, REJECT = "approve", "reject"
CAST_IRON = "cast iron"
FAMILIES = (
    "carbon steel",
    "low-alloy steel",
    "stainless steel",
    "duplex stainless steel",
    CAST_IRON,
    "copper alloy",
    "nickel alloy",
    "titanium alloy",
)
#: The words a specification or grade is written with that say nothing about which one it is.
_NO_MEANING = frozenset({"astm", "asme", "gr", "grade", "type", "uns"})
#: How an entry says its specification has no grade. A lone "N" is a real grade, so it is not here.
_NO_GRADE = frozenset({"", "n a", "na", "none", "not applicable"})
_LIST_SEPARATOR = re.compile(r"\s*[/;,]\s*|\s+and\s+", re.IGNORECASE)
MAX_ENTRIES = 200
MAX_OUTPUT_TOKENS = 16000
SHEET = "Material reference"
COVER_STAMP = "Material reference stamp"
C_SPEC, C_GRADE, C_FAMILY, C_BARE, C_SOURCE = (
    "Specification",
    "Grade",
    "Family",
    "Bare grade unambiguous",
    "Source",
)
C_ID, C_CHECK, C_TICK, C_COMMENT = (
    "Entry id",
    "Row check",
    "Owner tick",
    "Owner comment",
)
COLUMNS = (
    C_SPEC,
    C_GRADE,
    C_FAMILY,
    C_BARE,
    C_SOURCE,
    C_ID,
    C_CHECK,
    C_TICK,
    C_COMMENT,
)
_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS material_reference_entry (
        id TEXT PRIMARY KEY, specification TEXT NOT NULL, grade TEXT NOT NULL, family TEXT NOT NULL,
        bare_grade_unambiguous INTEGER NOT NULL, source TEXT NOT NULL, model TEXT NOT NULL,
        prompt_version TEXT NOT NULL, created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS material_reference_decision (
        id TEXT PRIMARY KEY, entry_id TEXT NOT NULL REFERENCES material_reference_entry(id),
        decision TEXT NOT NULL CHECK (decision IN ('approve','reject')), signer TEXT NOT NULL,
        tier TEXT NOT NULL, decided_at TEXT NOT NULL, source_sha256 TEXT)""",
    *(
        f"CREATE TRIGGER IF NOT EXISTS {table}_no_{verb} BEFORE {verb} ON {table}"
        f" BEGIN SELECT RAISE(ABORT, 'material reference: {table} is append-only'); END"
        for table in ("material_reference_entry", "material_reference_decision")
        for verb in ("UPDATE", "DELETE")
    ),
)
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "specification": {"type": "string"},
                    "grade": {"type": "string"},
                    "family": {"type": "string"},
                    "bare_grade_unambiguous": {"type": "boolean"},
                },
                "required": [
                    "specification",
                    "grade",
                    "family",
                    "bare_grade_unambiguous",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["entries"],
    "additionalProperties": False,
}
#: General knowledge only: this text names no document, and nothing is added to it.
SYSTEM = (
    "You know materials engineering. List the material specifications and grades commonly used for the bodies of"
    " pressure relief valves, as a reference table. Include both the ASTM and the ASME SA designation as separate"
    " entries, castings and forgings, and the iron grades too. A designation commonly written in another form, such as"
    " with a letter after it for its heat-treatment condition, gets its own entry for each form. A specification with"
    " no grade gets an empty grade. Each entry gives its family, exactly one of: "
    f"{', '.join(FAMILIES)}. The family {CAST_IRON} includes grey, ductile and malleable iron. Set"
    " bare_grade_unambiguous true only when the grade alone, with no specification, names one material whatever"
    f" specification it appears under. Leave out anything you are not sure of. At most {MAX_ENTRIES} entries, the most"
    " common first. Answer JSON only, with no other words."
)


class SwitchedOff(RuntimeError):
    """MATERIAL_REFERENCE_ENGINE is off, so nothing was sent."""


class RefusedLive(RuntimeError):
    """This file is shaped like a live database; the table goes on a copy."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def has_schema(conn) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'material_reference_decision'"
        ).fetchone()
    )


def ensure_schema(conn) -> None:
    path = next(
        (r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), ""
    )
    if path and live_guard.is_live_shaped(path):
        raise RefusedLive("this is a live-shaped database; run on a copy")
    with conn:
        for statement in _SCHEMA:
            conn.execute(statement)


# ------------------------------------------------------------------------------------------------- the match


def tokens(text: str | None) -> tuple[str, ...]:
    """Whole tokens, folded. A letter prefix and its number are one token however they were spaced ("A 216", "A-216",
    "A216"), and words with no meaning here are dropped. The match is on these, never on a substring."""
    words = re.findall(r"[a-z0-9]+", str(text or "").casefold())
    out: list[str] = []
    for word in (w for w in words if w not in _NO_MEANING):
        if out and word.isdigit() and out[-1].isalpha() and len(out[-1]) <= 2:
            out[-1] += word
        else:
            out.append(word)
    return tuple(out)


@dataclass(frozen=True)
class Entry:
    specification: str
    grade: str
    family: str
    bare: bool


@dataclass(frozen=True)
class Table:
    """Only what the owner has signed. `version` names exactly those signatures."""

    version: str
    entries: tuple[Entry, ...]


def _no_grade(grade: str | None) -> bool:
    """A specification with no grade: its entry's grade is empty, or a word for nothing ("N/A")."""
    return " ".join(tokens(grade)) in _NO_GRADE


def _family_of_tokens(table: Table, said: tuple[str, ...]) -> str | None:
    if not said:
        return None
    hits = set()
    for e in table.entries:
        grade = () if _no_grade(e.grade) else tokens(e.grade)
        if said == tokens(e.specification) + grade or (
            e.bare and grade and said == grade
        ):
            hits.add(e.family)
    return next(iter(hits)) if len(hits) == 1 else None


def family_of(table: Table, stated: str | None) -> str | None:
    """The one family this value's whole tokens name, or None: not in the signed table, or it could be two."""
    return _family_of_tokens(table, tokens(stated))


def parts_of(stated: str | None) -> list[tuple[str, ...]]:
    """The tokens of each specification a value lists, split on its list separator. A later part that starts with the
    number keeps the letters the part before it started with, inside this value only ("SA 1 / 2" is SA1 and SA2). Any
    other change to a designation is a row of the table, signed like any row, never a rule here."""
    out: list[tuple[str, ...]] = []
    for part in _LIST_SEPARATOR.split(str(stated or "")):
        said = tokens(part)
        if not said:
            continue
        letters = re.match(r"[a-z]+", out[-1][0]) if out else None
        if letters and said[0][0].isdigit():
            said = (letters.group(0) + said[0], *said[1:])
        out.append(said)
    return out


def families_of(table: Table, stated: str | None) -> list[str | None]:
    """One family, or None, per listed part."""
    return [_family_of_tokens(table, said) for said in parts_of(stated)]


def is_not(table: Table, forbidden: list[str], stated: str) -> tuple[str | None, str]:
    """(COMPLIANT or NON_COMPLIANT, words), or (None, words). Any listed part in a forbidden family fails. A Pass needs
    every part in the signed table and a family named by the rule itself: a narrower word in the rule ("ductile iron")
    is not a family, so it decides nothing."""
    families = families_of(table, stated)
    named = [" ".join(v.casefold().split()) for v in forbidden]
    where = f"{NOT_CONFIRMED}, version {table.version}"
    if not all(n in FAMILIES for n in named):
        return None, f"the rule's words are not one family of the {where}"
    said = f"the sheet states {stated}, by the {where}, family {'; '.join(str(f) for f in families)}"
    if any(f in named for f in families):
        return "NON_COMPLIANT", f"{said}; the rule forbids {'; '.join(named)}"
    if not families or None in families:
        return None, f"the sheet states {stated}; a part of it is not in the {where}"
    return "COMPLIANT", f"{said}; the rule forbids {'; '.join(named)}"


def signed(conn) -> Table:
    """The entries whose last decision is an approval, by the owner. Empty on a copy with no table: nothing decides."""
    if not has_schema(conn):
        return Table("none", ())
    entries, proof = [], []
    for row in conn.execute(
        "SELECT e.id, e.specification, e.grade, e.family, e.bare_grade_unambiguous, d.id, d.decision, d.tier"
        " FROM material_reference_entry e JOIN material_reference_decision d ON d.entry_id = e.id"
        " WHERE d.rowid = (SELECT MAX(rowid) FROM material_reference_decision WHERE entry_id = e.id)"
        " ORDER BY e.id"
    ):
        if row[6] == APPROVE and row[7] == OWNER:
            entries.append(Entry(row[1], row[2], row[3], bool(row[4])))
            proof.append([row[0], row[5]])
    digest = hashlib.sha256(json.dumps(proof).encode("utf-8")).hexdigest()[:12]
    return Table(digest if entries else "none", tuple(entries))


# --------------------------------------------------------------------------------------------------- proposing


def _entry_id(specification: str, grade: str, family: str, bare: bool) -> str:
    body = json.dumps([specification, grade, family, bare])
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]


def _reply(answer: dict | None) -> dict | None:
    text = (answer or {}).get("text") or ""
    if (answer or {}).get("finish_reason") == "length" or schema_errors(
        text, ANSWER_SCHEMA
    ):
        return None
    try:
        return json.loads(unfenced(text))
    except (ValueError, TypeError):
        return None


def _packet() -> Packet:
    return Packet(
        prompt="List the table now.",
        num_ctx=0,
        num_predict=MAX_OUTPUT_TOKENS,
        json_schema=ANSWER_SCHEMA,
        system=SYSTEM,
        step=STEP,
        prompt_version=PROMPT_VERSION,
    )


def store_proposal(conn, reply: dict, model: str) -> dict:
    """Code's word on each entry: a family off the list, or a specification with no token, is dropped and
    counted. Everything kept is unsigned."""
    kept = dropped = 0
    with conn:
        for item in reply.get("entries") or []:
            spec, grade = str(item["specification"]).strip(), str(item["grade"]).strip()
            family = " ".join(str(item["family"]).casefold().split())
            bare = bool(item["bare_grade_unambiguous"])
            if family not in FAMILIES or not tokens(spec):
                dropped += 1
                continue
            conn.execute(
                "INSERT OR IGNORE INTO material_reference_entry (id, specification, grade, family,"
                " bare_grade_unambiguous, source, model, prompt_version, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    _entry_id(spec, grade, family, bare),
                    spec,
                    grade,
                    family,
                    int(bare),
                    SOURCE,
                    model,
                    PROMPT_VERSION,
                    _now(),
                ),
            )
            kept += 1
    return {"kept": kept, "dropped": dropped}


def propose(
    conn,
    *,
    estimate_only: bool = False,
    send=None,
    max_usd: float | None = None,
    **wait,
) -> dict:
    """The one call. An estimate writes nothing and needs no key. Counts only."""
    model = settings.material_reference_model
    packets = {"material-reference": _packet()}
    base = {"prompt_version": PROMPT_VERSION, "model": model, "document_text_sent": 0}
    worst = claude_batch_run.worst_usd(model, packets["material-reference"])
    if estimate_only:
        return {**base, "status": "estimate", "worst_usd": round(worst, 4)}
    if settings.material_reference_engine != ENGINE_CLAUDE:
        raise SwitchedOff("MATERIAL_REFERENCE_ENGINE is off; nothing was sent")
    ensure_schema(conn)
    limit = settings.standards_compiler_max_usd_per_day if max_usd is None else max_usd
    job = f"material-reference:{PROMPT_VERSION}"
    with claude_approved.carrying(()):  # true: this call carries no document
        outcome = claude_batch_run.run_many(
            conn,
            ClaudeProvider(model, transport=send),
            {job: packets},
            room=_room_gate(float(limit)),
            usable=lambda answer: _reply(answer) is not None,
            **wait,
        )[job]
    answer = outcome.answers.get("material-reference")
    reply = _reply(answer)
    if outcome.waiting:
        return {**base, "status": "waiting"}
    if outcome.over_budget:
        return {
            **base,
            "status": "over_budget",
            "why": "the request did not fit the USD free, nothing sent. --max-usd limits today's whole Claude spend"
            " plus this send's worst case",
        }
    if reply is None:
        stopped = (answer or {}).get("finish_reason")
        return {
            **base,
            "status": "no_usable_answer",
            "why": f"the answer could not be read; it ended with {stopped}",
        }
    return {**base, "status": "done", **store_proposal(conn, reply, model)}


# ------------------------------------------------------------------------------------- the checklist's sheet


def row_check(row: dict) -> str:
    """A hash of what the signer read, so an edited cell shows."""
    body = json.dumps(
        [str(row.get(c) if row.get(c) is not None else "") for c in COLUMNS[:6]]
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def sheet_rows(conn) -> list[dict]:
    """One row per entry, with no tick: no approval by default."""
    rows = []
    for r in conn.execute(
        "SELECT id, specification, grade, family, bare_grade_unambiguous, source FROM material_reference_entry"
        " ORDER BY specification, grade, id"
    ):
        row = {
            C_SPEC: r[1],
            C_GRADE: r[2],
            C_FAMILY: r[3],
            C_BARE: "yes" if r[4] else "no",
            C_SOURCE: r[5],
            C_ID: r[0],
        }
        rows.append({**row, C_CHECK: row_check(row), C_TICK: None, C_COMMENT: None})
    return rows


def stamp(rows: list[dict]) -> str:
    body = sorted(str(r[C_ID]) for r in rows)
    return "mr-" + hashlib.sha256(json.dumps(body).encode("utf-8")).hexdigest()[:24]


def add_sheet(book, conn) -> int:
    """Add the sheet, and its stamp on the cover, to an open checklist workbook. Returns the rows written."""
    rows = sheet_rows(conn)
    sheet = book.create_sheet(SHEET)
    sheet.append(list(COLUMNS))
    for row in rows:
        sheet.append([row[c] for c in COLUMNS])
    book["Cover"].append([COVER_STAMP, stamp(rows)])
    return len(rows)


def record(conn, decisions: list[dict], signer: str, tier: str, digest: str) -> None:
    """Write the decisions inside the caller's transaction."""
    for one in decisions:
        conn.execute(
            "INSERT INTO material_reference_decision (id, entry_id, decision, signer, tier, decided_at, source_sha256)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                uuid.uuid4().hex,
                one["entry_id"],
                one["decision"],
                signer,
                tier,
                _now(),
                digest,
            ),
        )


def last_decision(conn, entry_id: str) -> tuple | None:
    return conn.execute(
        "SELECT decision, signer, tier FROM material_reference_decision WHERE entry_id = ?"
        " ORDER BY rowid DESC LIMIT 1",
        (entry_id,),
    ).fetchone()
