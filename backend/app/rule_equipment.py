"""The equipment label of a rule: its table, the closed taxonomy and the import (owner order 16.2 note 4, 11 Nov 2026).

WHAT IT IS. Per rule: the equipment family, type and part it is about, or "general" (it applies to all equipment), and a state:
`agreed` (two DIFFERENT models gave the same answer under one prompt version and one list of equipment, and the answer is on the
closed taxonomy), `needs_human` (they differ, or the answer is not on the list) or `unlabelled`. It lives in its OWN table
`rule_equipment_label`, keyed by (source, rule_ref) like `rule_label`, made only when `agent_review_enabled` is on, append-only
(rows are never deleted or replaced; a change appends an event). Nothing in `rule_label` or in the rule book is touched.

THE TAXONOMY and the mapping from the app's own equipment names to taxonomy type ids are DATA files
(`reference/equipment_taxonomy.json`, `reference/equipment_mapping.json`); no equipment word is written in code (rule 13).

THE IMPORT. The lab labeller wrote the equipment answers into its own table on a database COPY. `convert_lab` turns that table
into rows of an equipment label file (ids, state, models, prompt version, list hash; no rule or paper text);
`import_rows` stores them on the server (the only writer of the live database), checking every row again by code: the key, the
state, the answer on the taxonomy, two different named models and a prompt version and a list hash for `agreed`. A row that fails
is `refused` and never stored as agreed. Read side: `label_for`. Nothing here asks a model anything.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .db import schema_once
from .rule_label_schema import SOURCES, SwitchedOff, require_on, switch_on

REFERENCE = Path(__file__).resolve().parent / "reference"
TAXONOMY = REFERENCE / "equipment_taxonomy.json"
MAPPING = REFERENCE / "equipment_mapping.json"

EXPORT_FORMAT = "rule-equipment-labels-v1"
AGREED, NEEDS_HUMAN, UNLABELLED = "agreed", "needs_human", "unlabelled"
STATES = (AGREED, NEEDS_HUMAN, UNLABELLED)
TABLES = ("rule_equipment_label", "rule_equipment_label_event")
ANSWER_COLUMNS = ("answer_a_json", "answer_b_json")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_STATEMENTS = (
    f"""CREATE TABLE IF NOT EXISTS rule_equipment_label (
        source TEXT NOT NULL CHECK (source IN ({",".join(f"'{s}'" for s in SOURCES)})),
        rule_ref TEXT NOT NULL CHECK (length(rule_ref) > 0),
        equip_family TEXT, equip_type TEXT, equip_part TEXT,
        equip_general INTEGER NOT NULL DEFAULT 0 CHECK (equip_general IN (0, 1)),
        equip_state TEXT NOT NULL CHECK (equip_state IN ({",".join(f"'{s}'" for s in STATES)})),
        equip_disagreement TEXT,
        answer_a_json TEXT, answer_b_json TEXT,
        model_a TEXT, model_b TEXT, prompt_version TEXT, list_sha TEXT,
        labelled_at TEXT NOT NULL,
        PRIMARY KEY (source, rule_ref),
        CHECK (equip_state <> '{AGREED}' OR (
            model_a IS NOT NULL AND model_b IS NOT NULL
            AND length(trim(model_a)) > 0 AND length(trim(model_b)) > 0
            AND lower(trim(model_a)) <> lower(trim(model_b))
            AND prompt_version IS NOT NULL AND length(trim(prompt_version)) > 0
            AND list_sha IS NOT NULL AND length(list_sha) = 64 AND list_sha NOT GLOB '*[^0-9a-f]*'
            AND equip_disagreement IS NULL
            AND (equip_general = 1 OR equip_type IS NOT NULL OR equip_family IS NOT NULL)))
    )""",
    """CREATE TABLE IF NOT EXISTS rule_equipment_label_event (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL, rule_ref TEXT NOT NULL,
        event_type TEXT NOT NULL CHECK (event_type IN ('insert', 'relabel')),
        state TEXT NOT NULL, previous_state TEXT, at TEXT NOT NULL, detail_json TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS rule_equipment_label_event_rule ON rule_equipment_label_event (source, rule_ref)",
    """CREATE TRIGGER IF NOT EXISTS rule_equipment_label_no_delete BEFORE DELETE ON rule_equipment_label
        BEGIN SELECT RAISE(ABORT, 'rule_equipment_label: rows are never deleted'); END""",
    """CREATE TRIGGER IF NOT EXISTS rule_equipment_label_no_replace BEFORE INSERT ON rule_equipment_label
        WHEN EXISTS (SELECT 1 FROM rule_equipment_label t WHERE t.source = NEW.source AND t.rule_ref = NEW.rule_ref)
        BEGIN SELECT RAISE(ABORT, 'rule_equipment_label: a row is never replaced; update it'); END""",
    """CREATE TRIGGER IF NOT EXISTS rule_equipment_label_key_fixed BEFORE UPDATE ON rule_equipment_label
        WHEN NEW.source <> OLD.source OR NEW.rule_ref <> OLD.rule_ref
        BEGIN SELECT RAISE(ABORT, 'rule_equipment_label: the key of a row never changes'); END""",
    """CREATE TRIGGER IF NOT EXISTS rule_equipment_label_event_insert AFTER INSERT ON rule_equipment_label BEGIN
        INSERT INTO rule_equipment_label_event (source, rule_ref, event_type, state, previous_state, at, detail_json)
        VALUES (NEW.source, NEW.rule_ref, 'insert', NEW.equip_state, NULL, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
                json_object('model_a', NEW.model_a, 'model_b', NEW.model_b, 'prompt', NEW.prompt_version,
                            'list_sha', NEW.list_sha, 'type', NEW.equip_type, 'family', NEW.equip_family));
        END""",
    """CREATE TRIGGER IF NOT EXISTS rule_equipment_label_event_update AFTER UPDATE ON rule_equipment_label BEGIN
        INSERT INTO rule_equipment_label_event (source, rule_ref, event_type, state, previous_state, at, detail_json)
        VALUES (NEW.source, NEW.rule_ref, 'relabel', NEW.equip_state, OLD.equip_state,
                strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
                json_object('model_a', NEW.model_a, 'model_b', NEW.model_b, 'prompt', NEW.prompt_version,
                            'list_sha', NEW.list_sha, 'type', NEW.equip_type, 'family', NEW.equip_family));
        END""",
    """CREATE TRIGGER IF NOT EXISTS rule_equipment_label_event_no_update BEFORE UPDATE ON rule_equipment_label_event
        BEGIN SELECT RAISE(ABORT, 'rule_equipment_label_event is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS rule_equipment_label_event_no_delete BEFORE DELETE ON rule_equipment_label_event
        BEGIN SELECT RAISE(ABORT, 'rule_equipment_label_event is append-only'); END""",
)


def has_tables(conn) -> bool:
    held = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    return set(TABLES) <= held


def create_tables(conn) -> None:
    """Create what is missing, all or none. Switch off: raises `SwitchedOff` and creates nothing. Run twice it does nothing."""
    require_on()
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in _STATEMENTS:
            conn.execute(statement)
        held = {r[1] for r in conn.execute("PRAGMA table_info(rule_equipment_label)")}
        for column in (
            ANSWER_COLUMNS
        ):  # a table made before the two answers were kept gets the two columns
            if column not in held:
                conn.execute(
                    f"ALTER TABLE rule_equipment_label ADD COLUMN {column} TEXT"
                )
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


@schema_once
def _ensure(conn=None) -> None:
    from .db import connect

    create_tables(conn if conn is not None else connect())


def ensure_schema(conn=None) -> None:
    """For the app's schema walk. Switch off: does nothing, creates nothing, does not raise."""
    if not switch_on():
        return
    _ensure(conn)


# ---------------------------------------------------------------- the taxonomy (data)


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")


@dataclass
class Taxonomy:
    """The closed list of equipment: families, types, `also_applies` and the names a type goes by. Loaded from data."""

    families: dict[str, str] = field(default_factory=dict)  # family id -> name
    type_family: dict[str, str] = field(default_factory=dict)  # type id -> family id
    also: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )  # type id -> the ids it also counts as
    names: dict[str, str] = field(
        default_factory=dict
    )  # normalised id / name / synonym -> type id

    @classmethod
    def load(cls, path: Path | str = TAXONOMY) -> Taxonomy:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        tax = cls()
        for fam in data["families"]:
            tax.families[fam["id"]] = fam.get("name") or fam["id"]
            for t in fam["types"]:
                tax.type_family[t["id"]] = fam["id"]
                tax.also[t["id"]] = tuple(t.get("also_applies") or ())
                for label in (t["id"], t.get("name"), *(t.get("synonyms") or ())):
                    if label:
                        tax.names[_norm(label)] = t["id"]
        return tax

    def expand(self, type_ids: set[str]) -> set[str]:
        """The ids a set of types also stands for (its `also_applies`, transitively)."""
        out, todo = set(type_ids), list(type_ids)
        while todo:
            for parent in self.also.get(todo.pop(), ()):
                if parent not in out:
                    out.add(parent)
                    todo.append(parent)
        return out


def load_mapping(path: Path | str = MAPPING) -> dict:
    """The app's equipment names -> taxonomy type ids (`map`), optionally `related`: equipment a type is also read against."""
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


# ---------------------------------------------------------------- read side


def label_for(conn, source: str, rule_ref: str) -> dict | None:
    """The equipment label of one rule as a dict, or None (no row, or no table). Read only."""
    held = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rule_equipment_label'"
    ).fetchone()
    if held is None:
        return None
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    row = cursor.execute(
        "SELECT * FROM rule_equipment_label WHERE source = ? AND rule_ref = ?",
        (source, str(rule_ref)),
    ).fetchone()
    return None if row is None else {k: row[k] for k in row.keys()}  # noqa: SIM118 - sqlite3.Row


# ---------------------------------------------------------------- the lab table -> a label file -> the server


def _lab_answer(row, who: str, cols: set) -> dict | None:
    """One labelling model's own answer from the lab table: {family, type, part, general, valid}; None when the lab did not keep it."""
    if f"{who}_valid" not in cols or row[f"{who}_valid"] is None:
        return None
    return {
        "family": row[f"{who}_family"] or None,
        "type": row[f"{who}_type"] or None,
        "part": row[f"{who}_part"] or None,
        "general": 1 if row[f"{who}_general"] else 0,
        "valid": 1 if row[f"{who}_valid"] else 0,
    }


def answer_of(label: Any, which: str) -> dict | None:
    """The stored answer of one labelling model ("a" or "b") as a dict, or None (missing, unparseable, not valid, or off the
    list: then nobody may rely on it)."""
    raw = (label or {}).get(f"answer_{which}_json")
    try:
        got = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    if not isinstance(got, dict) or got.get("valid") not in (1, True):
        return None
    return {
        "family": got.get("family") or None,
        "type": got.get("type") or None,
        "part": got.get("part") or None,
        "general": 1 if got.get("general") in (1, True) else 0,
    }


def convert_lab(lab: sqlite3.Connection) -> list[dict]:
    """The equipment rows of the lab labeller's `rule_label` table (a database COPY) as label-file rows. A row the lab did not
    ask about (no equip_state) is skipped. No rule text, no answer text: ids, answers on the list, models, prompt, list hash."""
    cursor = lab.cursor()
    cursor.row_factory = sqlite3.Row
    cols = {r[1] for r in cursor.execute("PRAGMA table_info(rule_label)")}
    if "equip_state" not in cols:
        return []
    rows = []
    for r in cursor.execute(
        "SELECT * FROM rule_label WHERE equip_state IS NOT NULL ORDER BY source, rule_ref"
    ):
        rows.append(
            {
                "source": r["source"],
                "rule_ref": r["rule_ref"],
                "equip_family": r["equip_family"] or None,
                "equip_type": r["equip_type"] or None,
                "equip_part": r["equip_part"] or None,
                "equip_general": 1 if r["equip_general"] else 0,
                "equip_state": r["equip_state"],
                "equip_disagreement": r["equip_disagreement"] or None,
                "model_a": r["ea_model"],
                "model_b": r["eb_model"],
                "prompt_version": r["ea_prompt_version"]
                if r["ea_prompt_version"] == r["eb_prompt_version"]
                else None,
                "list_sha": r["ea_list_sha"]
                if r["ea_list_sha"] == r["eb_list_sha"]
                else None,
                "labelled_at": r["labelled_at"],
                "answer_a": _lab_answer(r, "ea", cols),
                "answer_b": _lab_answer(r, "eb", cols),
            }
        )
    return rows


def write_file(rows: list[dict], out: str | Path) -> None:
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"format": EXPORT_FORMAT, "rows": rows}, indent=1), encoding="utf-8"
    )


def read_file(path: Path) -> list[Any]:
    """The rows of an equipment label file, or ValueError("not_an_equipment_label_file")."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("not_valid_json") from None
    if (
        not isinstance(data, dict)
        or data.get("format") != EXPORT_FORMAT
        or not isinstance(data.get("rows"), list)
    ):
        raise ValueError("not_an_equipment_label_file")
    return data["rows"]


def _model_family(model: Any) -> str:
    return re.sub(r"-\d{8}$", "", str(model or "").strip().lower())


def problem(row: Any, tax: Taxonomy) -> str | None:
    """Why a row cannot be stored (None: it can). The shape and, for `agreed`, the proof the table's CHECK also holds."""
    if not isinstance(row, dict) or row.get("source") not in SOURCES:
        return "key"
    if not isinstance(row.get("rule_ref"), str) or not row["rule_ref"]:
        return "key"
    state = row.get("equip_state")
    if state not in STATES:
        return "state"
    fam, typ = row.get("equip_family") or None, row.get("equip_type") or None
    if (typ is not None and typ not in tax.type_family) or (
        fam is not None and fam not in tax.families
    ):
        return "not_on_the_list"
    if typ is not None and fam is not None and tax.type_family[typ] != fam:
        return "family_does_not_hold_the_type"
    if state != AGREED:
        return None
    a, b = row.get("model_a"), row.get("model_b")
    if (
        not str(a or "").strip()
        or not str(b or "").strip()
        or _model_family(a) == _model_family(b)
    ):
        return "models"
    if not str(row.get("prompt_version") or "").strip():
        return "prompt_version"
    if not _HEX64.match(str(row.get("list_sha") or "")):
        return "list_sha"
    if row.get("equip_disagreement"):
        return "disagreement"
    if not (row.get("equip_general") in (1, True) or typ or fam):
        return "names_nothing"
    return None


def _answer_json(answer: Any, tax: Taxonomy) -> str | None:
    """A labelling model's answer as stored text, or None when it is missing or not on the closed list (never refuses the row)."""
    if not isinstance(answer, dict):
        return None
    fam, typ = answer.get("family") or None, answer.get("type") or None
    if (typ is not None and typ not in tax.type_family) or (
        fam is not None and fam not in tax.families
    ):
        return None
    return json.dumps(
        {"family": fam, "type": typ, "part": answer.get("part") or None,
         "general": 1 if answer.get("general") else 0, "valid": 1 if answer.get("valid") else 0},
        sort_keys=True,
    )  # fmt: skip


def import_rows(conn, rows: Iterable[Any], tax: Taxonomy | None = None) -> dict:
    """Store label-file rows on the server's database: {read, stored, refused}. Every row is checked again by code; an
    identical stored row is counted and not written again; a changed row updates the stored one (the trigger appends the event).
    Switch off: raises SwitchedOff and writes nothing. Nothing in `rule_label` or the rule book is read or written."""
    require_on()
    tax = tax or Taxonomy.load()
    create_tables(conn)
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    counts = {"read": 0, "stored": 0, "refused": 0}
    cols = ("equip_family", "equip_type", "equip_part", "equip_general", "equip_state", "equip_disagreement", "model_a",
            "model_b", "prompt_version", "list_sha", "labelled_at", *ANSWER_COLUMNS)  # fmt: skip
    for row in rows:
        counts["read"] += 1
        if problem(row, tax) is not None:
            counts["refused"] += 1
            continue
        values = {
            c: (1 if row.get(c) else 0)
            if c == "equip_general"
            else (row.get(c) or None)
            for c in cols
            if c not in ANSWER_COLUMNS
        }
        for which in ("a", "b"):
            values[f"answer_{which}_json"] = _answer_json(
                row.get(f"answer_{which}"), tax
            )
        values["labelled_at"] = values["labelled_at"] or "1970-01-01T00:00:00Z"
        held = cursor.execute(
            "SELECT * FROM rule_equipment_label WHERE source = ? AND rule_ref = ?",
            (row["source"], row["rule_ref"]),
        ).fetchone()
        try:
            if held is None:
                conn.execute(
                    f"INSERT INTO rule_equipment_label (source, rule_ref, {', '.join(cols)}) VALUES (?, ?, {','.join('?' * len(cols))})",
                    (row["source"], row["rule_ref"], *values.values()),
                )
            elif any(held[c] != values[c] for c in cols):
                conn.execute(
                    f"UPDATE rule_equipment_label SET {', '.join(c + ' = ?' for c in cols)} WHERE source = ? AND rule_ref = ?",
                    (*values.values(), row["source"], row["rule_ref"]),
                )
        except sqlite3.IntegrityError:
            counts["refused"] += 1  # the table's own guard said no
            continue
        counts["stored"] += 1
    conn.commit()
    return counts


__all__ = [
    "AGREED",
    "EXPORT_FORMAT",
    "MAPPING",
    "NEEDS_HUMAN",
    "TAXONOMY",
    "UNLABELLED",
    "SwitchedOff",
    "Taxonomy",
    "answer_of",
    "convert_lab",
    "create_tables",
    "ensure_schema",
    "has_tables",
    "import_rows",
    "label_for",
    "load_mapping",
    "problem",
    "read_file",
    "write_file",
]
