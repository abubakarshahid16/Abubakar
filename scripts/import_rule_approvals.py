"""#805 plan change 6: record a signer's ticks from a returned checklist as decisions in the rulebook, on a COPY.

    RULEBOOK_V2_ENABLED=1 python scripts/import_rule_approvals.py --db <copy> --file <returned.xlsx> \
        --signed-by <user id or email> --tier owner

The ticks are read, never retyped, and it changes no rule's text. "Checked OK" is an approval for the equipment type
the file's kind names. "Wrong" and "Not applicable" are recorded as rejections. An empty tick is nothing at all. Who
signed and in what capacity come only from the two flags, and the signer must be an active user of this database;
--tier owner also needs the `admin` role there, the one record of who may sign for the owner.

All or none. Refused, with nothing written: a live-shaped --db; a file whose stamp differs from the current rules (the
changed rows are listed, ids only); a row whose words were edited; a tick outside the list; a tick on a row with no
rule id; an approval of a context-dependent rule with no comment saying what was checked. A file showing another
limit or unit than the rule's own is refused as edited, whatever its row check says.

Stdout is one line of JSON, counts and ids only. Sends nothing, calls no model.
Exit: 0 recorded; 2 bad input or signer; 3 stamp differs; 4 file edited or a tick refused; 6 switch off.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

import openpyxl  # noqa: E402
from rehearse_requirement_reextraction import refuse_live  # noqa: E402

from app import numparse  # noqa: E402
from app.rulebook_v2_check import DEFERS_TO, LIMIT, NO_UNIT, RANGE  # noqa: E402

EXIT_BAD, EXIT_STALE, EXIT_EDITED, EXIT_OFF = 2, 3, 4, 6
OK, WRONG, NOT_APPLICABLE = "Checked OK", "Wrong", "Not applicable"
TICKS = (OK, WRONG, NOT_APPLICABLE)
C_RULE, C_VERSION, C_SNAPSHOT = (
    "Rulebook rule id",
    "Rulebook version",
    "Rulebook snapshot",
)
C_CHECK, C_TICK, C_COMMENT, C_QUOTE = (
    "Row check",
    "Engineer tick",
    "Engineer comment",
    "Exact quote",
)
#: What the signer read: `Row check` is a hash of these as they were written, so an edited cell shows.
READ_COLUMNS = (
    "What to check",
    "Limit",
    "Unit",
    "When it applies",
    "Clause",
    "Page",
    C_QUOTE,
    C_RULE,
    C_VERSION,
    C_SNAPSHOT,
)
COVER_STAMP, COVER_TYPE = "Rulebook v2 stamp", "Equipment type"


def _text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return "" if value is None else " ".join(str(value).split())


def row_check(row: dict) -> str:
    joined = "\x1f".join(_text(row.get(c)) for c in READ_COLUMNS)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def read_file(path: Path) -> tuple[dict, list[dict]]:
    book = openpyxl.load_workbook(path, data_only=True)
    cover: dict = {}
    for row in book["Cover"].iter_rows(values_only=True):
        if row and row[0] is not None and row[0] not in cover:
            cover[row[0]] = row[1] if len(row) > 1 else None
    rows = book["Rules"].iter_rows(values_only=True)
    header = [_text(x) for x in next(rows)]
    return cover, [
        dict(zip(header, r, strict=False))
        for r in rows
        if any(x not in (None, "") for x in r)
    ]


def _signer(conn, who: str) -> str | None:
    row = conn.execute(
        "SELECT id FROM users WHERE (id = ? OR lower(email) = lower(?)) AND is_active = 1",
        (who, who),
    ).fetchone()
    return row[0] if row else None


def _rows_now(conn, snapshots: set[str]) -> tuple[set[tuple], list[str]]:
    """((rule, version, snapshot) of these snapshots' compiles as the database holds them, snapshots no longer newest)."""
    now, old = set(), []
    for snapshot in sorted(snapshots):
        found = conn.execute(
            "SELECT compile_run_id, standard_document_id FROM rulebook_snapshot WHERE id = ?",
            (snapshot,),
        ).fetchone()
        if found is None:
            old.append(snapshot)
            continue
        newest = conn.execute(
            "SELECT id FROM rulebook_snapshot WHERE standard_document_id = ? ORDER BY rowid DESC LIMIT 1",
            (found[1],),
        ).fetchone()
        if newest[0] != snapshot:
            old.append(snapshot)
        for row in conn.execute(
            "SELECT v.rule_id, v.version_no FROM rulebook_compiled_row c"
            " JOIN rulebook_version v ON v.id = c.rule_version_id WHERE c.compile_run_id = ?",
            (found[0],),
        ):
            now.add((row[0], row[1], snapshot))
    return now, old


def _holds_owner_role(conn, signer: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = ? AND r.name = 'admin'",
            (signer,),
        ).fetchone()
        is not None
    )


def _version_of(conn, rule_id: str, version: int):
    return conn.execute(
        "SELECT id, quote_sha256, strength, (SELECT MAX(version_no) FROM rulebook_version WHERE rule_id = ?),"
        " kind, comparator, value, value_text, unit"
        " FROM rulebook_version WHERE rule_id = ? AND version_no = ?",
        (rule_id, rule_id, version),
    ).fetchone()


def _version_number(row: dict) -> int | None:
    try:
        return int(_text(row.get(C_VERSION)))
    except ValueError:
        return None


def _shows_the_rules_limit(row: dict, version) -> bool:
    """The Limit and Unit cells say what this version holds: what the signer saw is what is approved."""
    kind, comparator, value, words, unit = version[4:9]
    cell = _text(row.get("Limit"))
    if kind == LIMIT:
        said = cell.split(None, 1)
        return (
            len(said) == 2
            and said[0] == comparator
            and numparse.as_limit(said[1]) == value
            and _text(row.get("Unit")) == ("" if unit == NO_UNIT else _text(unit))
        )
    written = _text(words)
    if kind == RANGE and _text(row.get("Unit")) != (
        "" if unit == NO_UNIT else _text(unit)
    ):
        return False
    if not any(c.isdigit() for c in written) or kind == DEFERS_TO:
        # The generator prints a figure only: no figure, no limit cell.
        return cell == ""
    return cell == written or cell.endswith(f" {written}")


def _edited(conn, rows: list[dict]) -> list[str]:
    """Rows whose cells are not what the generator wrote, or whose quote is not the rule's."""
    out = []
    for row in rows:
        version = _version_of(conn, _text(row[C_RULE]), _version_number(row))
        words = _text(row.get(C_QUOTE))
        digest = hashlib.sha256(words.encode("utf-8")).hexdigest()
        if (
            _text(row.get(C_CHECK)) != row_check(row)
            or version is None
            or version[1] != digest
            or not _shows_the_rules_limit(row, version)
        ):
            out.append(_text(row[C_RULE]))
    return out


def _stale(conn, cover: dict, rows: list[dict]) -> dict | None:
    """What changed since the file was made, ids only. None when its stamp is the current one."""
    from app import rulebook_v2

    in_file = {
        (_text(r[C_RULE]), _version_number(r), _text(r[C_SNAPSHOT])) for r in rows
    }
    now, old = _rows_now(conn, {x[2] for x in in_file})
    superseded = [
        x[0]
        for x in in_file
        if (v := _version_of(conn, x[0], x[1])) is not None and v[3] != x[1]
    ]
    stamp = rulebook_v2.checklist_stamp(_text(cover.get(COVER_TYPE)), now)
    if stamp == _text(cover.get(COVER_STAMP)) and not old and not superseded:
        return None
    return {
        "file_stamp": _text(cover.get(COVER_STAMP)),
        "current_stamp": stamp,
        "snapshots_no_longer_newest": old,
        "rows_added_since_file": sorted(x[0] for x in now - in_file),
        "rows_gone_since_file": sorted(x[0] for x in in_file - now),
        "rows_superseded": sorted(superseded),
    }


def _refused_ticks(conn, rows: list[dict]) -> dict:
    out: dict = {
        "tick_not_on_the_list": [],
        "ticked_row_has_no_rule_id": [],
        "needs_a_comment": [],
    }
    for row in rows:
        tick = row.get(C_TICK)
        name = _text(row.get(C_RULE)) or _text(row.get("ID"))
        if tick in (None, ""):
            continue
        if tick not in TICKS:
            out["tick_not_on_the_list"].append(name)
        elif not _text(row.get(C_RULE)):
            out["ticked_row_has_no_rule_id"].append(name)
        elif tick == OK and not _text(row.get(C_COMMENT)):
            version = _version_of(conn, _text(row[C_RULE]), _version_number(row))
            if version is not None and version[2] == "context_dependent":
                out["needs_a_comment"].append(name)
    return {k: v for k, v in out.items() if v}


def _sources_shown(conn, version: str, row: dict) -> tuple[str, ...]:
    """The source this row showed: its compile's document, and its page. Another edition's source was shown to no one."""
    found = conn.execute(
        "SELECT p.id, p.page FROM rulebook_provenance p WHERE p.rule_version_id = ? AND p.standard_document_id ="
        " (SELECT standard_document_id FROM rulebook_snapshot WHERE id = ?) ORDER BY p.rowid",
        (version, _text(row.get(C_SNAPSHOT))),
    ).fetchall()
    page = re.match(r"\d+", _text(row.get("Page")))
    on_page = [s[0] for s in found if page and s[1] == int(page.group())]
    return tuple(on_page or [s[0] for s in found])


def _decisions(
    conn, ticked, signer, tier, equipment_type, digest
) -> tuple[list[dict], int]:
    from app import rulebook_v2

    out, already = [], 0
    for row in ticked:
        version = _version_of(conn, _text(row[C_RULE]), _version_number(row))[0]
        word = rulebook_v2.APPROVE if row[C_TICK] == OK else rulebook_v2.REJECT
        if rulebook_v2.last_decision(conn, version, equipment_type) == (word, signer):
            already += 1
            continue
        sources = _sources_shown(conn, version, row)
        comment = _text(row.get(C_COMMENT))
        out.append(
            {
                "version_id": version,
                "decision": word,
                "engineer_id": signer,
                "tier": tier,
                "equipment_type": equipment_type,
                "provenance_viewed": sources,
                "note": f"{row[C_TICK]}: {comment}" if comment else row[C_TICK],
                "source_sha256": digest,
            }
        )
    return out, already


def run(
    db_path: Path, file_path: Path, signed_by: str, tier: str, *, emit=print
) -> int:
    """Everything is checked before anything is written; the writing is one transaction."""
    from app.config import settings

    def stop(code: int, why: str, **detail) -> int:
        emit(json.dumps({"refused": why, **detail}, sort_keys=True))
        return code

    if not settings.rulebook_v2_enabled:
        return stop(
            EXIT_OFF, "RULEBOOK_V2_ENABLED is off: nothing was read or written."
        )
    settings.db_path = refuse_live(db_path)
    from app import rulebook_v2
    from app.db import connect

    if tier not in rulebook_v2.TIERS:
        return stop(EXIT_BAD, f"--tier must be one of {rulebook_v2.TIERS}")
    conn = connect()
    rulebook_v2.ensure_schema(conn)
    signer = _signer(conn, signed_by)
    if signer is None:
        return stop(EXIT_BAD, "--signed-by is not an active user of this database")
    try:
        cover, rows = read_file(file_path)
    except (OSError, KeyError, StopIteration, ValueError) as exc:
        return stop(EXIT_BAD, f"cannot read this file ({type(exc).__name__})")
    equipment_type = _text(cover.get(COVER_TYPE))
    if not equipment_type or not _text(cover.get(COVER_STAMP)):
        return stop(
            EXIT_BAD, "the file names no equipment type or rulebook stamp; rebuild it"
        )
    if tier == rulebook_v2.OWNER and not _holds_owner_role(conn, signer):
        return stop(EXIT_BAD, "--tier owner needs a signer with the admin role here")
    with_rule = [r for r in rows if _text(r.get(C_RULE))]
    changed = _stale(conn, cover, with_rule)
    if changed:
        return stop(EXIT_STALE, "this file was made from different rules", **changed)
    edited = _edited(conn, with_rule)
    if edited:
        return stop(
            EXIT_EDITED, "the words of these rows were edited", rows=sorted(edited)
        )
    bad = _refused_ticks(conn, rows)
    if bad:
        return stop(EXIT_EDITED, "these ticks cannot be recorded", **bad)
    ticked = [r for r in with_rule if r.get(C_TICK) not in (None, "")]
    digest = hashlib.sha256(Path(file_path).read_bytes()).hexdigest()
    decisions, already = _decisions(conn, ticked, signer, tier, equipment_type, digest)
    rulebook_v2.record_decisions(conn, decisions)
    words = [d["decision"] for d in decisions]
    emit(
        json.dumps(
            {
                "boundary": "this file's rows in this database copy",
                "rows_in_file": len(rows),
                "empty_ticks_not_recorded": len(rows) - len(ticked),
                "approved": words.count(rulebook_v2.APPROVE),
                "rejected": words.count(rulebook_v2.REJECT),
                "already_recorded": already,
                "signer": signer,
                "tier": tier,
                "equipment_type": equipment_type,
                "version_stamp": _text(cover.get(COVER_STAMP)),
            },
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    ap.add_argument(
        "--db", required=True, type=Path, help="a COPY; a live-shaped path is refused"
    )
    ap.add_argument("--file", required=True, type=Path, help="the returned checklist")
    ap.add_argument("--signed-by", required=True, help="the signer: a user id or email")
    ap.add_argument(
        "--tier",
        required=True,
        choices=("owner", "engineer"),
        help="the capacity they sign in",
    )
    args = ap.parse_args(argv)
    return run(args.db, args.file, args.signed_by, args.tier)


if __name__ == "__main__":
    sys.exit(main())
