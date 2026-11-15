"""Role 1, the fact sheet: how the values of ONE paper are merged, stored per run and handed to the later roles (SPEC A.1/A.2 row 1, F.6).

Pure where it can be (`merge`, `digest`, `usable`), plus one small store (`ensure_schema`, `store`, `load`). Nothing here asks a model, opens a
socket or writes to `submittal_facts`: the sheet lives in its own tables, per run (a review never changes the live facts).

  * `merge(stored, read, pages, ...)`: the paper's STORED values (current ones only: `agent_review_calculator_reader.split_current`, #1824) and the
    values the Reader read, merged by `datasheet_ai.merge_readings` into agreed / conflict / ai_only / stored_only; a value read two ways, or the
    same field printed with two different values on two pages of one tag, is `conflict` and is never used; a stale stored value is `stale`.
  * `usable(sheet)`: the facts a later role may compare or cite (never a conflict, a stale value or a value an engineer has to decide).
  * `digest(sheet)`: the compact text later roles read, one line per usable value with its page and id, the conflicts apart.

No verdict class or word is made here (SPEC E). Ids, numbers, field labels and quotes only; a quote is kept only after code found it on the page.
"""

from __future__ import annotations

import dataclasses
import json
import re
import sqlite3
from collections.abc import Collection, Mapping, Sequence

from . import (
    agent_review_calculator_cells as cells_mod,
)
from . import (
    agent_review_calculator_reader as reader_mod,
)
from . import (
    datasheet_ai,
    datasheet_checks,
    form_reader,
    nine_record,
    numparse,
    untrusted_value,
)
from .nine_contract import Engine, Fact, FactSheet, PageRead

#: the states a later role may use (a conflict, a stale value and a value for the engineer are never used)
USABLE_STATES = frozenset({"agreed", "ai_only", "stored_only"})
STALE_WORDS = reader_mod.STALE_WORDS


def _fold(text: object) -> str:
    return " ".join(str(text or "").lower().split())


def _identity(value: object, unit: object) -> tuple[str, str]:
    return numparse.fold_numbers(str(value or "")), _fold(unit)


def _role(label: str, rules: Mapping | None) -> str | None:
    if not label or rules is None:
        return None
    return datasheet_checks.role_of(label, dict(rules))


def _stored_state(f: Mapping, agreed: bool = False) -> str:
    """A stored value an engineer has to decide (a conflict recorded at ingest, a reading conflict, a kind not confirmed) is `needs_engineer`."""
    if untrusted_value.reason(f):
        return "needs_engineer"
    return "agreed" if agreed else "stored_only"


def _fact(
    n: tuple[int, int],
    *,
    label: str,
    value: str | None,
    unit: str | None,
    quote: str,
    quote_verified: bool,
    tag: str | None,
    cell_ref: str | None,
    source: str,
    state: str,
    sha: str | None,
    model: str | None,
    rules: Mapping | None,
) -> Fact:
    page, i = n
    return Fact(
        fact_id=f"f:{page}:{i}",
        page=page,
        field_label=label,
        field_role=_role(label, rules),
        value=value or None,
        unit=unit or None,
        quote=quote,
        quote_verified=quote_verified,
        tag=tag or None,
        cell_ref=cell_ref,
        source=source,
        state=state,
        page_text_sha=sha,
        model=model,  # type: ignore[arg-type]
    )


def _cell_refs(facts: Sequence[Mapping], tables: Mapping[int, list]) -> dict[str, str]:
    """fact id -> "t<table>r<row>c<col>" for a value that has exactly one table cell (the calculator's own locator, #1814)."""
    counts = cells_mod.page_tag_counts(facts)
    return {
        fid: f"t{c.table}r{c.row}c{c.value_col}"
        for fid, c in cells_mod.cells_of(facts, tables, counts).items()
    }


def _stored_shape(f: Mapping, n: int) -> dict:
    return {**f, "id": str(f.get("id") or f"s:{f.get('page')}:{n}")}


def _read_shape(f: Mapping, n: int) -> dict:
    """A verified reading in the shape the calculator's locator reads (`raw_value`, `source_text`, `equipment_tag`)."""
    return {
        "id": f"r:{f.get('page')}:{n}",
        "page": f.get("page"),
        "field_label": f.get("field"),
        "raw_value": f.get("value"),
        "source_text": f.get("quote"),
        "equipment_tag": f.get("tag"),
        "is_blank": 0 if f.get("value") else 1,
    }


def merge(
    stored: Sequence[Mapping],
    read: Sequence[Mapping],
    pages: Mapping[int, str],
    *,
    picture_pages: Collection[int] = (),
    model: str | None = None,
    tables: Mapping[int, list] | None = None,
    rules: Mapping | None = None,
) -> tuple[tuple[Fact, ...], dict[str, int]]:
    """(the facts of the sheet, counts). `stored` are the paper's facts as `datasheets.list_facts` gives them; `read` are the Reader's verified readings
    (`field`, `value`, `unit`, `quote`, `page`, optional `tag`, `kind`). A stored value of an earlier text of the page is `stale` and not merged."""
    current = [f for f in stored if reader_mod.is_current(f, pages)]
    stale = [f for f in stored if not reader_mod.is_current(f, pages)]
    n_stale = len(stale)
    cur = [_stored_shape(f, i) for i, f in enumerate(current)]
    # a read value counts only when its quote is on the page it names: checked HERE, so no caller can hand in an unverified reading
    ais = [
        dict(f, kind=f.get("kind") or "offered")
        for f in read
        if form_reader.quote_on_page(
            str(f.get("quote") or ""), pages.get(f.get("page") or 0, "")
        )
    ]
    unverified = len(read) - len(ais)
    cells = (
        _cell_refs(cur + [_read_shape(f, i) for i, f in enumerate(ais)], tables or {})
        if tables
        else {}
    )
    rule_cell = {id(f): cells.get(f["id"]) for f in cur}
    ai_cell = {id(f): cells.get(_read_shape(f, i)["id"]) for i, f in enumerate(ais)}
    decisions = datasheet_ai.merge_readings(cur, ais)
    counts = datasheet_ai.outcome_counts(decisions)
    seq: dict[int, int] = {}
    out: list[Fact] = []

    def nxt(page: int) -> tuple[int, int]:
        seq[page] = seq.get(page, 0) + 1
        return page, seq[page]

    def from_stored(f: Mapping, state: str) -> Fact:
        page = f.get("page") or 0
        raw = None if f.get("is_blank") else f.get("raw_value")
        text = pages.get(page, "")
        quote = str(f.get("source_text") or "")
        return _fact(
            nxt(page),
            label=str(f.get("field_label") or f.get("field_name") or ""),
            value=raw,
            unit=f.get("raw_unit") or f.get("unit"),
            quote=quote,
            quote_verified=form_reader.quote_on_page(quote, text) if quote else False,
            tag=f.get("equipment_tag"),
            cell_ref=rule_cell.get(id(f)),
            source="stored",
            state=state,
            sha=f.get("page_text_sha") or reader_mod.page_sha(text),
            model=None,
            rules=rules,
        )

    def from_read(a: Mapping, state: str) -> Fact:
        page = a.get("page") or 0
        return _fact(
            nxt(page),
            label=str(a.get("field") or ""),
            value=a.get("value"),
            unit=a.get("unit"),
            quote=str(a.get("quote") or ""),
            quote_verified=True,
            tag=a.get("tag"),
            cell_ref=ai_cell.get(id(a)),
            source="ai_picture" if page in picture_pages else "ai_text",
            state=state,
            sha=reader_mod.page_sha(pages.get(page, "")),
            model=model,
            rules=rules,
        )

    for d in decisions:
        kind = d["outcome"]
        if kind == datasheet_ai.AGREED:
            out.append(from_stored(d["rule"], _stored_state(d["rule"], agreed=True)))
        elif kind == datasheet_ai.CONFLICT:
            out.extend(from_stored(r, "conflict") for r in d["rules"])
            out.extend(from_read(a, "conflict") for a in d["ai"])
        elif kind == datasheet_ai.AI_ONLY:
            out.append(from_read(d["ai"], "ai_only"))
        else:
            out.append(from_stored(d["rule"], _stored_state(d["rule"])))
    out.extend(from_stored(f, "stale") for f in stale)
    out = _cross_page(out)
    counts = {
        **counts,
        "stale": n_stale,
        "unverified_dropped": unverified,
        "conflict_facts": sum(f.state == "conflict" for f in out),
    }
    return tuple(out), counts


def _cross_page(facts: list[Fact]) -> list[Fact]:
    """The same field printed with two different values on the paper (one page or two): both are `conflict`, UNLESS both values stand under different KNOWN tags
    (`agent_review_calculator_cells.other_tags`: both tagged, identifiers that do not overlap). A value with no tag, a tag list, or a tag that starts like the
    other's is never "another tag". Code compares; the engineer decides which is meant. The field is the registry's role when code found one, else the label."""
    groups: dict[str, list[int]] = {}
    for i, f in enumerate(facts):
        if f.state in USABLE_STATES and f.value is not None:
            groups.setdefault(f.field_role or _fold(f.field_label), []).append(i)
    bad: set[int] = set()
    for idx in groups.values():
        for n, i in enumerate(idx):
            for j in idx[n + 1 :]:
                a, b = facts[i], facts[j]
                if _identity(a.value, a.unit) != _identity(
                    b.value, b.unit
                ) and not cells_mod.other_tags(
                    {"equipment_tag": a.tag}, {"equipment_tag": b.tag}
                ):
                    bad.update((i, j))
    return [
        dataclasses.replace(f, state="conflict") if i in bad else f
        for i, f in enumerate(facts)
    ]


def sheet_of(
    run_id: str,
    paper_id: str,
    pages_total: int,
    pages: Sequence[PageRead],
    facts: Sequence[Fact],
    engine: Engine,
    models: Sequence[str],
) -> FactSheet:
    return FactSheet(
        run_id=run_id,
        paper_id=paper_id,
        pages_total=pages_total,
        pages=tuple(pages),
        facts=tuple(facts),
        conflicts=sum(f.state == "conflict" for f in facts),
        engine=engine,
        models=tuple(models),
    )


def usable(sheet: FactSheet) -> tuple[Fact, ...]:
    """The values a later role may compare or cite: never a conflict, a stale value or a value an engineer has to decide."""
    return tuple(
        f for f in sheet.facts if f.state in USABLE_STATES and f.quote_verified
    )


def digest(sheet: FactSheet, max_chars: int = 8000) -> str:
    """The compact text the later roles read: one line per usable value (id, page, label, value, unit, tag, cell), then the values read two ways
    (named as such, never to be compared), then the pages not read with why. Cut at `max_chars` on a line end and says how many lines it left out."""

    def line(f: Fact) -> str:
        shown = " ".join(p for p in (f.value, f.unit) if p) or "(printed, empty)"
        extra = "".join(
            f" [{k} {v}]" for k, v in (("tag", f.tag), ("cell", f.cell_ref)) if v
        )
        return f"{f.fact_id} p{f.page} {f.field_label}: {shown}{extra}"

    rows = [line(f) for f in sorted(usable(sheet), key=lambda f: (f.page, f.fact_id))]
    clash = [line(f) + f" ({f.source})" for f in sheet.facts if f.state == "conflict"]
    notread = [
        f"p{p.page}: {p.not_read_why}"
        for p in sheet.pages
        if not p.text_read and p.not_read_why
    ]
    out: list[str] = [f"FACT SHEET: {len(rows)} values of {sheet.pages_total} pages"]
    used = len(out[0]) + 1
    left = 0
    for r in rows:
        if used + len(r) + 1 > max_chars:
            left += 1
            continue
        out.append(r)
        used += len(r) + 1
    if left:
        out.append(f"({left} more values not shown here)")
    if clash:
        out.append(f"READ TWO WAYS, NOT USED ({len(clash)}):")
        out.extend(clash[:40])
    if notread:
        out.append("PAGES NOT READ:")
        out.extend(notread[:40])
    return "\n".join(out)


# ------------------------------------------------------------------ the digest as a DERIVED block for the seam

#: the state words as short CODES (11 characters or fewer: the seam's `code` kind), so no word needs adding to the seam's enum
STATE_CODE = {
    "agreed": "agreed",
    "conflict": "conflict",
    "ai_only": "ai_only",
    "stored_only": "stored_only",
    "needs_engineer": "needs_eng",
    "stale": "stale",
}
#: the columns, each with its declared kind (`nine_call.Block.kinds`): fact id, the registry's field key, the value as printed (found on its page),
#: the page, the tag (a code, "-" when none, "multi" when the tag is spelled as a list or with spaces), and the state code
DIGEST_KINDS = ("id", "key", "source", "number", "key", "code")
_CODE = re.compile(r"^[A-Za-z0-9\-][A-Za-z0-9_.:\-]{0,39}$")


def _printed(f: Fact, pages: Mapping[int, str]) -> str | None:
    """The value as the page prints it (value and unit when they stand together), or None when the page does not hold it: a cell of kind `source`
    must be found in the paper's stored text, so a value that is not is left out of the block, and counted."""
    text = fold_text(pages.get(f.page, ""))
    for cand in (f"{f.value} {f.unit}".strip() if f.unit else "", str(f.value or "")):
        if cand and fold_text(cand) in text:
            return cand if len(cand) <= 60 and "\n" not in cand else None
    return None


def fold_text(text: object) -> str:
    return nine_record.fold(str(text or ""))


def digest_block(
    sheet: FactSheet, pages: Mapping[int, str]
) -> tuple[object | None, dict[str, int]]:
    """The fact sheet for the later roles as ONE derived block of the seam (`review_record`, name "fact_sheet", the paper its only source): a row per fact
    that is not stale and has a value the page holds. Conflicts stay in, with the state "conflict", so no later role takes them for a value. Returns
    (the block or None when there is no row, counts: rows and facts left out because the page does not print the value)."""
    rows: list[tuple[str, ...]] = []
    left_out = 0
    for f in sorted(sheet.facts, key=lambda f: (f.page, f.fact_id)):
        if f.state == "stale" or f.value is None:
            continue
        shown = _printed(f, pages)
        if shown is None:
            left_out += 1
            continue
        tag = f.tag or "-"
        tag = tag if _CODE.match(tag) else "multi"
        rows.append(
            (
                f.fact_id,
                f.field_role if f.field_role and _CODE.match(f.field_role) else "-",
                shown,
                str(f.page),
                tag,
                STATE_CODE[f.state],
            )
        )
    if not rows:
        return None, {"rows": 0, "left_out": left_out}
    from .nine_call import Block

    return Block(
        "review_record",
        name="fact_sheet",
        sources=(sheet.paper_id,),
        kinds=DIGEST_KINDS,
        items=tuple(rows),
    ), {"rows": len(rows), "left_out": left_out}


# ------------------------------------------------------------------ the store (per run; never `submittal_facts`)

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_review_fact_sheet (
        run_id TEXT PRIMARY KEY, paper_id TEXT NOT NULL, pages_total INTEGER NOT NULL, engine TEXT NOT NULL, models_json TEXT NOT NULL,
        conflicts INTEGER NOT NULL, produced_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS agent_review_fact (
        run_id TEXT NOT NULL, fact_id TEXT NOT NULL, page INTEGER NOT NULL, field_label TEXT NOT NULL, field_role TEXT, value TEXT, unit TEXT,
        quote TEXT NOT NULL, quote_verified INTEGER NOT NULL, tag TEXT, cell_ref TEXT, source TEXT NOT NULL, state TEXT NOT NULL, page_text_sha TEXT, model TEXT,
        PRIMARY KEY (run_id, fact_id))""",
    """CREATE TABLE IF NOT EXISTS agent_review_page_read (
        run_id TEXT NOT NULL, page INTEGER NOT NULL, text_read INTEGER NOT NULL, picture_read INTEGER NOT NULL, not_read_why TEXT,
        PRIMARY KEY (run_id, page))""",
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    for sql in _SCHEMA:
        conn.execute(sql)


def store(
    conn: sqlite3.Connection, sheet: FactSheet, produced: Mapping | None = None
) -> None:
    """Replace this run's sheet (a restart writes the same sheet again, never a second one). One transaction."""
    ensure_schema(conn)
    with conn:
        for t in (
            "agent_review_fact",
            "agent_review_page_read",
            "agent_review_fact_sheet",
        ):
            conn.execute(f"DELETE FROM {t} WHERE run_id = ?", (sheet.run_id,))
        conn.execute(
            "INSERT INTO agent_review_fact_sheet VALUES (?,?,?,?,?,?,?)",
            (
                sheet.run_id,
                sheet.paper_id,
                sheet.pages_total,
                sheet.engine,
                json.dumps(list(sheet.models)),
                sheet.conflicts,
                json.dumps(dict(produced or {})),
            ),
        )
        conn.executemany(
            "INSERT INTO agent_review_fact VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    sheet.run_id,
                    f.fact_id,
                    f.page,
                    f.field_label,
                    f.field_role,
                    f.value,
                    f.unit,
                    f.quote,
                    int(f.quote_verified),
                    f.tag,
                    f.cell_ref,
                    f.source,
                    f.state,
                    f.page_text_sha,
                    f.model,
                )
                for f in sheet.facts
            ],
        )
        conn.executemany(
            "INSERT INTO agent_review_page_read VALUES (?,?,?,?,?)",
            [
                (
                    sheet.run_id,
                    p.page,
                    int(p.text_read),
                    int(p.picture_read),
                    p.not_read_why,
                )
                for p in sheet.pages
            ],
        )


def load(conn: sqlite3.Connection, run_id: str) -> FactSheet | None:
    """The stored sheet of a run, or None when the Reader did not store one (an older run, or the role did not run)."""
    try:
        head = conn.execute(
            "SELECT paper_id, pages_total, engine, models_json FROM agent_review_fact_sheet WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if head is None:
            return None
        facts = conn.execute(
            "SELECT fact_id, page, field_label, field_role, value, unit, quote, quote_verified, tag, cell_ref, source, state, page_text_sha, model "
            "FROM agent_review_fact WHERE run_id = ? ORDER BY page, rowid",
            (run_id,),
        ).fetchall()
        pages = conn.execute(
            "SELECT page, text_read, picture_read, not_read_why FROM agent_review_page_read WHERE run_id = ? ORDER BY page",
            (run_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return None  # the tables do not exist: a review made before the Reader
    return sheet_of(
        run_id,
        head[0],
        head[1],
        [PageRead(r[0], bool(r[1]), bool(r[2]), r[3]) for r in pages],
        [
            Fact(
                r[0],
                r[1],
                r[2],
                r[3],
                r[4],
                r[5],
                r[6],
                bool(r[7]),
                r[8],
                r[9],
                r[10],
                r[11],
                r[12],
                r[13],
            )
            for r in facts
        ],
        head[2],
        json.loads(head[3]),
    )
