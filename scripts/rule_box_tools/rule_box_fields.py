"""#805 rule boxes: a fixed field list for every equipment type that has none, built by Claude from public reference data.

The four types with a checklist (`datasheet_checks.json`) keep their approved lists. Every other type gets a list built
here, stored as DATA (a table on the copy, and a JSON the caller exports); no code names a type or a layout (rule 13).
Every such list carries the state `FIELD_LIST_STATE` wherever it is stored or shown, until a person confirms it.

WHAT IS SENT: the property names of the type's class in CFIHOS (public reference data on disk; the caller supplies the
folder, nothing is downloaded), the generic role names the repo's checklists already use, and up to `QUOTES` quotes of the
type's rules from approved standards. Never a datasheet, procedure, CRS or any client document. The checklist workbooks
under the mirror are engineers' working files and are NOT read here.

AI PROPOSES, CODE VERIFIES: each field needs a snake_case role, a kind from the closed list the existing roles use, a short
plain label, and a CFIHOS property that is exactly one of those supplied (or null). Anything else is dropped; a reply with
fewer than `MIN_FIELDS` good fields stores nothing.
"""

from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path

from app import datasheet_checks
from app.ai.json_reply import unfenced
from rule_box_tools import rule_box_labels, rule_box_run

PROMPT_VERSION = "field-list-v1"
TABLE = "rule_box_field_lists"
FIELD_LIST_STATE = "field list: AI-built, to confirm"
FIXED_STATE = "fixed (approved checklist)"
QUOTES = 80
QUOTE_CHARS = 320
MAX_PROPS = 150
MIN_FIELDS, MAX_FIELDS = 3, 60
FIELD_TOKENS = 3000
KINDS = (
    "text",
    "number",
    "pressure",
    "length",
    "flow",
    "temperature",
    "area",
    "percent",
    "density",
    "viscosity",
)
_ROLE = re.compile(r"[a-z][a-z0-9_]{2,48}")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ()/%,.\-]{1,59}")


def ensure_schema(conn) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {TABLE} (equipment_type TEXT NOT NULL, role TEXT NOT NULL, kind TEXT NOT NULL,"
        " label TEXT NOT NULL, cfihos_property TEXT, state TEXT NOT NULL, model TEXT NOT NULL,"
        " prompt_version TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (equipment_type, role))"
    )
    conn.commit()


def stored(conn, equipment_type: str) -> dict[str, str] | None:
    """{role: kind} of an AI-built list for this type, or None."""
    try:
        rows = conn.execute(
            f"SELECT role, kind FROM {TABLE} WHERE equipment_type = ? ORDER BY role",
            (equipment_type,),
        ).fetchall()
    except Exception:  # noqa: BLE001 - no table yet
        return None
    return {r["role"]: r["kind"] for r in rows} or None


# ------------------------------------------------------------------------------------------------ CFIHOS on disk
def _rows(folder: Path, name: str) -> list[dict]:
    path = next(folder.glob(f"CFIHOS CORE {name} v*.csv"))
    with path.open(encoding="cp1252", newline="") as fh:
        return list(csv.DictReader(fh))


def _words(name: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", name.lower())


def _contains(big: list[str], small: list[str]) -> bool:
    return any(
        big[i : i + len(small)] == small for i in range(len(big) - len(small) + 1)
    )


class Cfihos:
    """The class and property tables of a CFIHOS CORE csv folder. Reads local files only."""

    def __init__(self, folder: Path):
        self.parent: dict[str, str] = {}
        for table in ("equipment class", "tag class"):
            for r in _rows(folder, table):
                name = r[f"{table} name"].strip().lower()
                self.parent[name] = r[f"parent {table} name"].strip().lower()
        self.props: dict[str, set[str]] = {}
        for table in ("equipment class property", "tag class property"):
            for r in _rows(folder, table):
                self.props.setdefault(
                    r[f"{table.split(' property')[0]} name"].strip().lower(), set()
                ).add(r["property name"].strip())
        self.kind_of: dict[str, str] = {}
        for r in _rows(folder, "property"):
            self.kind_of[r["property name"].strip()] = f"{r['property data type']}" + (
                f", {r['unit of measure dimension code'].lower()}"
                if r["unit of measure dimension code"]
                else ""
            )

    def classes_for(self, equipment_type: str) -> list[str]:
        """Classes named as the type, or containing its words, and their direct children. General name matching."""
        want = _words(equipment_type)
        chosen = [c for c in self.parent if _contains(_words(c), want)]
        children = [
            c for c, p in self.parent.items() if p in chosen and c not in chosen
        ]
        return sorted(set(chosen + children))

    def properties_for(self, equipment_type: str) -> list[str]:
        count: dict[str, int] = {}
        for c in self.classes_for(equipment_type):
            for p in self.props.get(c, ()):
                count[p] = count.get(p, 0) + 1
        ranked = sorted(count, key=lambda p: (-count[p], p.lower()))
        return ranked[:MAX_PROPS]


# ------------------------------------------------------------------------------------------------ the prompt
def existing_roles() -> dict[str, str]:
    return {
        role: v["kind"]
        for role, v in sorted(datasheet_checks.load_rules()["roles"].items())
    }


def types_without_a_list(conn) -> list[str]:
    """Types the labels used (never general or other) that have no approved checklist and no stored list yet."""
    rows = conn.execute(
        f"SELECT DISTINCT equipment_type FROM {rule_box_labels.TABLE} WHERE box IN ('a','c') ORDER BY 1"
    ).fetchall()
    return [
        r[0]
        for r in rows
        if r[0] not in (rule_box_labels.GENERAL, rule_box_labels.OTHER)
        and rule_box_labels.checklist_name(r[0]) is None
        and stored(conn, r[0]) is None
    ]


def _sample(rows: list) -> list:
    if len(rows) <= QUOTES:
        return rows
    step = len(rows) / QUOTES
    return [rows[int(i * step)] for i in range(QUOTES)]


def prompt_for(
    equipment_type: str, props: list[str], kinds: dict[str, str], quotes: list[str]
) -> str:
    listed = (
        "\n".join(f"- {p} ({kinds.get(p, 'Text')})" for p in props)
        or "(none: CFIHOS has no class for this type)"
    )
    roles = ", ".join(f"{r} ({k})" for r, k in existing_roles().items())
    said = "\n".join(f"{n}. {q}" for n, q in enumerate(quotes, 1)) or "(none)"
    return (
        f"You build the FIXED FIELD LIST of a datasheet for one equipment type: '{equipment_type}'. A reader will fill"
        " these fields from a datasheet, and code will check requirements of engineering standards against them, so each"
        " field is one value a datasheet states and a standard can limit.\n"
        f"Allowed kinds: {', '.join(KINDS)} (text for words and materials, number for a plain count or ratio).\n"
        f"Prefer these existing role names when the meaning is the same: {roles}.\n\n"
        f"CFIHOS PROPERTIES FOR THIS TYPE (public reference data):\n{listed}\n\n"
        f"REQUIREMENTS OF STANDARDS ABOUT THIS TYPE (each is a quote; cover the values they limit):\n{said}\n\n"
        f'Answer ONLY one JSON object: {{"fields": [{{"role": "snake_case_name", "kind": "...",'
        f' "label": "short plain label", "cfihos_property": <exactly one name from the CFIHOS list above, or null>}}]}}'
        f" with {MIN_FIELDS} to {MAX_FIELDS} fields, the most important first. No other text."
    )


def jobs(conn, cfihos: Cfihos, gate) -> tuple[list[rule_box_run.Job], dict, dict]:
    labels = rule_box_labels.standard_labels(conn)
    refused: dict[str, str | None] = {}
    out, members, no_class = [], {}, 0
    for equipment_type in types_without_a_list(conn):
        rows = conn.execute(
            "SELECT r.standard_document_id AS doc, r.quote FROM compiled_rules r"
            f" JOIN {rule_box_labels.TABLE} l ON l.rule_id = r.id"
            " WHERE l.equipment_type = ? AND l.box IN ('a','c') ORDER BY length(r.quote), r.id",
            (equipment_type,),
        ).fetchall()
        ok = []
        for r in rows:
            if r["doc"] not in refused:
                refused[r["doc"]] = gate(r["doc"], labels.get(r["doc"], ""))
            if refused[r["doc"]] is None:
                ok.append(r)
        picked = _sample(ok)
        quotes = [" ".join(r["quote"].split())[:QUOTE_CHARS] for r in picked]
        props = cfihos.properties_for(equipment_type)
        no_class += not props
        key = f"fld:{equipment_type}"
        out.append(
            rule_box_run.Job(
                key,
                prompt_for(equipment_type, props, cfihos.kind_of, quotes),
                frozenset(r["doc"] for r in picked),
                FIELD_TOKENS,
            )
        )
        members[key] = (equipment_type, set(props))
    return (
        out,
        members,
        {"types_to_build": len(out), "types_with_no_cfihos_class": no_class},
    )


def verify(reply, allowed_props: set[str]) -> tuple[list[dict] | None, str | None]:
    try:
        data = json.loads(unfenced(reply))
    except (ValueError, TypeError):
        return None, "reply_not_json"
    fields = data.get("fields") if isinstance(data, dict) else None
    if not isinstance(fields, list):
        return None, "no_fields_list"
    good, seen = [], set()
    for f in fields:
        if not isinstance(f, dict):
            continue
        role, kind, label, prop = (
            f.get("role"),
            f.get("kind"),
            f.get("label"),
            f.get("cfihos_property"),
        )
        if not (isinstance(role, str) and _ROLE.fullmatch(role)) or role in seen:
            continue
        if kind not in KINDS or not (
            isinstance(label, str) and _LABEL.fullmatch(label.strip())
        ):
            continue
        if prop is not None and prop not in allowed_props:
            prop = None
        seen.add(role)
        good.append(
            {
                "role": role,
                "kind": kind,
                "label": label.strip(),
                "cfihos_property": prop,
            }
        )
    if len(good) < MIN_FIELDS:
        return None, "too_few_good_fields"
    return good[:MAX_FIELDS], None


def storer(conn, members: dict, model: str):
    tally = {"lists_stored": 0, "fields_stored": 0, "rejected_by_reason": {}}

    def apply(job, text: str) -> bool:
        equipment_type, props = members[job.key]
        good, why = verify(text, props)
        if good is None:
            tally["rejected_by_reason"][why] = (
                tally["rejected_by_reason"].get(why, 0) + 1
            )
            return False
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn.executemany(
            f"INSERT OR IGNORE INTO {TABLE} VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    equipment_type,
                    f["role"],
                    f["kind"],
                    f["label"],
                    f["cfihos_property"],
                    FIELD_LIST_STATE,
                    model,
                    PROMPT_VERSION,
                    now,
                )
                for f in good
            ],
        )
        conn.commit()
        tally["lists_stored"] += 1
        tally["fields_stored"] += len(good)
        return True

    apply.tally = tally
    return apply


def export(conn, path: Path) -> int:
    """The lists as a JSON for the owner, each marked with its state."""
    out: dict[str, dict] = {}
    for r in conn.execute(f"SELECT * FROM {TABLE} ORDER BY equipment_type, role"):
        entry = out.setdefault(
            r["equipment_type"],
            {"state": r["state"], "model": r["model"], "fields": []},
        )
        entry["fields"].append(
            {
                "role": r["role"],
                "kind": r["kind"],
                "label": r["label"],
                "cfihos_property": r["cfihos_property"],
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return len(out)
