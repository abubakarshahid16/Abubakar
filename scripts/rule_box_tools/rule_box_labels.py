"""#805 rule boxes, STEP 1: label every compiled rule with a document kind, an equipment type and one of five boxes.

AI READS, CODE VERIFIES. Claude (the labelling model, `settings.claude_labelling_model`) reads many rules of a standard
per prompt and answers one small record each. Code keeps a record only when it has the fixed shape: a document kind and
an equipment type from the closed lists below, a box in `a`..`e`, and, for box `d`, a short plain document name (the
other document the rule needs). Anything else is not stored; the rule stays unlabelled and a later run asks again. No
free text reaches the database unchecked.

THE BOXES (owner order, 3 Nov 2026)
  a  a number or a material rule: a limit or an allowed/excluded list on one value.
  b  a sentence rule: an obligation that needs reading, with no single value to compare.
  c  a condition first: "when / if / for ... the limit is ..."; the condition decides whether it applies.
  d  needs another document to be checked (the document is named).
  e  does not apply to a document under review (definitions, scope, references, administrative text).

STANDARDS TEXT ONLY: the prompt carries the compiled rule's own quote, clause and the standard's label, never a
datasheet, procedure, CRS or any submittal. It leaves only through `rule_box_run` (metered, approved list first).

ON A COPY: `refuse_live` is the caller's. A rule already labelled under this prompt version is skipped (idempotent,
resumable). Counts only in a report.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from pathlib import Path

from app import datasheet_checks
from app.ai.json_reply import unfenced
from app.config import settings
from rule_box_tools import rule_box_run

PROMPT_VERSION = "box-label-v2"
TABLE = "rule_box_labels"
BOXES = ("a", "b", "c", "d", "e")
REFERENCE = Path(__file__).resolve().parents[2] / "backend" / "app" / "reference"
#: Words that are not a kind or a type but are a real answer.
ANY_KIND, OTHER = "any", "other"
GENERAL = "general"
PER_PROMPT = 5
QUOTE_CHARS = 700
TOKENS_PER_RULE = 55
_NAME_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._/&()\-,]{2,119}")

BOX_WORDS = (
    "a = a number or material rule: a limit, or an allowed / excluded list, on ONE value. Any material or dimension rule"
    " with checkable content belongs here, not in b, c or d;\n"
    "b = a sentence rule: an obligation that must be read, with no single value to compare. Requirements to keep records,"
    " rank, list or document something are b, not e;\n"
    "c = a condition first: it applies only when something actually gates it, and then gives a limit or list. A trigger"
    ' word ("if", "where", a scope phrase) makes it c only when it truly gates the rule; a rule that is gated without an'
    " opening trigger word is still c;\n"
    "d = needs ANOTHER NAMED document to be checked (a drawing, a calculation, a procedure, a test report, another"
    " standard); name that document in document_name. A dimension symbol or a table label is not a document;\n"
    "e = does not apply to a document under review, and ONLY these: a definition, a scope statement, a note, the history"
    " of the standard"
)


def document_kinds() -> tuple[str, ...]:
    kinds = json.loads((REFERENCE / "document_kinds.json").read_text(encoding="utf-8"))[
        "kinds"
    ]
    return (*sorted(kinds), ANY_KIND, OTHER)


def equipment_types() -> tuple[str, ...]:
    types = json.loads(
        (REFERENCE / "equipment_vocabulary.json").read_text(encoding="utf-8")
    )["types"]
    return (*sorted(types), GENERAL, OTHER)


#: A type of the vocabulary whose checklist is named otherwise. A table of names, nothing about a layout.
CHECKLIST_OF = {"relief valve": "Pressure Safety Valve"}


def checklist_name(equipment_type: str | None) -> str | None:
    """The checklist (fixed field list) key of an equipment type, or None: then the field list is 'to confirm'."""
    if not equipment_type or equipment_type in (GENERAL, OTHER):
        return None
    table = datasheet_checks.load_rules().get("checklists") or {}
    name = CHECKLIST_OF.get(equipment_type) or datasheet_checks.table_key(
        equipment_type, table
    )
    return name if name in table and not name.startswith("_") else None


def ensure_schema(conn) -> None:
    with contextlib.suppress(
        Exception
    ):  # the column exists, or the table is made below
        conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN box_v1 TEXT")
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {TABLE} ("
        " rule_id TEXT PRIMARY KEY, document_kind TEXT NOT NULL, equipment_type TEXT NOT NULL,"
        " box TEXT NOT NULL, needs_document_name TEXT, model TEXT NOT NULL, prompt_version TEXT NOT NULL,"
        " created_at TEXT NOT NULL, box_v1 TEXT)"
    )
    conn.commit()


def system_text() -> str:
    kinds = ", ".join(document_kinds())
    types = ", ".join(equipment_types())
    return (
        "You label requirements quoted from engineering standards. For each numbered requirement answer ONE record.\n"
        f"document_kind: the kind of submitted document the requirement is checked against, one of: {kinds}.\n"
        f"equipment_type: the equipment the requirement is about, one of: {types} ('{GENERAL}' when it applies to any"
        f" equipment or to none in particular, '{OTHER}' when it is about something not listed).\n"
        f"box: one letter.\n{BOX_WORDS}.\n"
        "document_name: for box d only, the other document needed, in a few plain words; null for every other box.\n"
        'Answer ONLY a JSON array, one object per requirement: [{"i": 1, "document_kind": "...", "equipment_type":'
        ' "...", "box": "a", "document_name": null}, ...] in the same order, every number once. No other text.'
    )


def _clean(text: str | None, limit: int) -> str:
    words = " ".join(str(text or "").split())
    return words if len(words) <= limit else words[: limit - 1] + "…"


def prompt_for(rows: list, label: str) -> str:
    lines = [
        f"{n}. [{label}, clause {_clean(r['clause'], 30)}] {_clean(r['quote'], QUOTE_CHARS)}"
        for n, r in enumerate(rows, 1)
    ]
    return system_text() + "\n\nREQUIREMENTS:\n" + "\n".join(lines)


def verify(record, rule_index: int) -> tuple[dict | None, str | None]:
    """(clean record, None) or (None, a fixed reason word). Code's word on one record of a reply."""
    if not isinstance(record, dict) or record.get("i") != rule_index:
        return None, "wrong_index"
    kind, eq, box = (
        record.get("document_kind"),
        record.get("equipment_type"),
        record.get("box"),
    )
    if kind not in document_kinds():
        return None, "document_kind_not_in_list"
    if eq not in equipment_types():
        return None, "equipment_type_not_in_list"
    if box not in BOXES:
        return None, "box_not_in_set"
    name = record.get("document_name")
    if box == "d":
        if not isinstance(name, str) or not _NAME_OK.fullmatch(name.strip()):
            return None, "box_d_without_a_document_name"
        name = " ".join(name.split())
    elif name not in (None, ""):
        return None, "name_on_a_box_that_needs_none"
    else:
        name = None
    return {
        "document_kind": kind,
        "equipment_type": eq,
        "box": box,
        "needs_document_name": name,
    }, None


def parse(text: str) -> list | None:
    try:
        data = json.loads(unfenced(text))
    except (ValueError, TypeError):
        return None
    if isinstance(data, dict):
        data = data.get("labels") or data.get("records")
    return data if isinstance(data, list) else None


def standard_labels(conn) -> dict[str, str]:
    """{standard document id: its number, else its file name}, for the standards that have compiled rules."""
    rows = conn.execute(
        "SELECT d.id, COALESCE(c.document_number, d.filename) AS label FROM documents d"
        " LEFT JOIN document_classification c ON c.document_id = d.id"
        " WHERE d.id IN (SELECT DISTINCT standard_document_id FROM compiled_rules)"
    ).fetchall()
    return {r["id"]: r["label"] for r in rows}


def todo(conn) -> list:
    return conn.execute(
        "SELECT r.id, r.standard_document_id, r.clause, r.page, r.quote FROM compiled_rules r"
        f" WHERE NOT EXISTS (SELECT 1 FROM {TABLE} l WHERE l.rule_id = r.id AND l.prompt_version = '{PROMPT_VERSION}')"
        " ORDER BY r.standard_document_id, r.page, r.quote_start, r.id"
    ).fetchall()


def jobs(
    conn, gate, per_prompt: int = PER_PROMPT
) -> tuple[list[rule_box_run.Job], dict, dict]:
    """(jobs, by_key, counts). `gate(document_id, label)` returns None to allow or a fixed word that refuses it."""
    labels = standard_labels(conn)
    refused: dict[str, str | None] = {}
    by_doc: dict[str, list] = {}
    skipped = 0
    for r in todo(conn):
        doc = r["standard_document_id"]
        if doc not in refused:
            refused[doc] = gate(doc, labels.get(doc, ""))
        if refused[doc] is not None:
            skipped += 1
            continue
        by_doc.setdefault(doc, []).append(r)
    out: list[rule_box_run.Job] = []
    members: dict[str, list] = {}
    for doc, rows in by_doc.items():
        for n in range(0, len(rows), per_prompt):
            chunk = rows[n : n + per_prompt]
            key = f"{doc}:{n // per_prompt:05d}"
            out.append(
                rule_box_run.Job(
                    key,
                    prompt_for(chunk, labels.get(doc, "")),
                    frozenset({doc}),
                    TOKENS_PER_RULE * len(chunk) + 200,
                )
            )
            members[key] = chunk
    why: dict[str, int] = {}
    for word in refused.values():
        if word is not None:
            why[word] = why.get(word, 0) + 1
    counts = {
        "rules_total": conn.execute("SELECT COUNT(*) FROM compiled_rules").fetchone()[
            0
        ],
        "rules_to_label": sum(len(v) for v in members.values()),
        "rules_in_refused_standards": skipped,
        "standards_refused_by_reason": dict(sorted(why.items())),
        "prompts": len(out),
    }
    return out, members, counts


def storer(conn, members: dict, model: str, version: str = PROMPT_VERSION):
    """The `apply` for `rule_box_run.run`: stores each record that passes `verify`; True if any was stored."""
    tally = {"records_stored": 0, "records_rejected": 0, "rejected_by_reason": {}}

    def apply(job, text: str) -> bool:
        records = parse(text)
        rules = members[job.key]
        if records is None:
            tally["records_rejected"] += len(rules)
            tally["rejected_by_reason"]["reply_not_a_list"] = tally[
                "rejected_by_reason"
            ].get("reply_not_a_list", 0) + len(rules)
            return False
        by_index = {r.get("i"): r for r in records if isinstance(r, dict)}
        stored = 0
        for n, rule in enumerate(rules, 1):
            clean, why = verify(by_index.get(n), n)
            if clean is None:
                tally["records_rejected"] += 1
                tally["rejected_by_reason"][why] = (
                    tally["rejected_by_reason"].get(why, 0) + 1
                )
                continue
            old = conn.execute(
                f"SELECT box, box_v1, prompt_version FROM {TABLE} WHERE rule_id = ?",
                (rule["id"],),
            ).fetchone()
            first = None if old is None else old["box"]
            if old is not None and old["prompt_version"] == version:
                continue
            conn.execute(
                f"INSERT OR REPLACE INTO {TABLE} (rule_id, document_kind, equipment_type, box, needs_document_name,"
                " model, prompt_version, created_at, box_v1) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    rule["id"],
                    clean["document_kind"],
                    clean["equipment_type"],
                    clean["box"],
                    clean["needs_document_name"],
                    model,
                    version,
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    first,
                ),
            )
            stored += 1
        conn.commit()
        tally["records_stored"] += stored
        return stored == len(rules)

    apply.tally = tally
    return apply


def model_name() -> str:
    return settings.claude_labelling_model
