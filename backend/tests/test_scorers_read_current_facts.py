"""#193: the two scoring scripts read CURRENT facts only.

Since ADR-0024 a re-read SUPERSEDES the old `submittal_facts` rows instead of
deleting them, and every production reader filters `superseded_at IS NULL`.
The two scorers did not (honesty audit 52): after the #179 re-extraction each
vessel field was present twice, `gold_pairs_score` saw a tie and reported 0/3
pairings while production made 1/3; `eval_extraction` would have counted
every re-read field twice. Both must also still read a copy made before the
column existed.

Synthetic databases only. Mutations: M480, M481.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_under_test",
                                                  REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _db(tmp_path, *, with_column: bool) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "facts.sqlite")
    conn.row_factory = sqlite3.Row
    extra = ", superseded_at TEXT" if with_column else ""
    conn.execute(f"""CREATE TABLE submittal_facts (id TEXT, submittal_document_id TEXT,
        field_name TEXT, field_label TEXT, field_value TEXT, unit TEXT, page INT,
        raw_value TEXT, raw_unit TEXT, is_blank INT, blank_marker TEXT,
        equipment_tag TEXT{extra})""")
    rows = [("new", "doc", "internal design pressure", "3.5", 4, None)]
    if with_column:
        rows.append(("old", "doc", "internal design pressure", "3.5", 4, "2026-09-24T00:00:00Z"))
    for fid, doc, name, value, page, superseded in rows:
        cols = "id, submittal_document_id, field_name, field_label, field_value, page," \
               " raw_value, raw_unit, is_blank" + (", superseded_at" if with_column else "")
        vals = [fid, doc, name, name, value, page, value, "bar (ga)", 0]
        if with_column:
            vals.append(superseded)
        conn.execute(f"INSERT INTO submittal_facts ({cols}) VALUES ({','.join('?' * len(vals))})", vals)
    conn.commit()
    return conn


@pytest.mark.parametrize("with_column", [True, False])
def test_eval_extraction_scores_current_facts_only(tmp_path, with_column):
    ev = _load("eval_extraction")
    got = ev.facts_from_db(_db(tmp_path, with_column=with_column), "doc")
    assert len(got) == 1, "a superseded row was scored as an extracted fact"


def test_eval_extraction_compares_the_printed_label(tmp_path):
    """B4: the answer key records each field AS PRINTED ("CASING TYPE:
    (6.3.10)"); the product's normalised name drops the clause reference.
    Scoring the normalised name against the printed key would count a
    correctly-read field as missed - so the printed label is compared."""
    ev = _load("eval_extraction")
    conn = _db(tmp_path, with_column=True)
    conn.execute("UPDATE submittal_facts SET field_name = 'casing type',"
                 " field_label = 'CASING TYPE: (6.3.10)' WHERE id = 'new'")
    [got] = ev.facts_from_db(conn, "doc")
    assert ev.norm_name(got["field_name"]) == ev.norm_name("CASING TYPE: (6.3.10)")


def test_gold_pairs_score_hands_the_matcher_current_facts_only(tmp_path):
    gp = _load("gold_pairs_score")
    conn = _db(tmp_path, with_column=True)
    conn.execute("""CREATE TABLE documents (id TEXT, filename TEXT)""")
    conn.execute("INSERT INTO documents VALUES ('std', 'SAES-D-001.pdf')")
    conn.execute("""CREATE TABLE standard_requirements (id TEXT, standard_document_id TEXT,
        clause TEXT, requirement_type TEXT, raw_value TEXT, raw_unit TEXT, subject TEXT)""")
    conn.execute("INSERT INTO standard_requirements VALUES ('r', 'std', '6.2.3', 'numeric_limit',"
                 " '6900', 'kPa', 'internal design pressure')")
    conn.commit()
    seen: list[int] = []

    def matcher(requirement, facts):
        seen.append(len(facts))
        return {"fact": facts[0] if len(facts) == 1 else None}

    made = gp.run_matcher(matcher, conn, "doc", ["std"])

    assert seen == [1], "the matcher was handed superseded facts beside current ones"
    assert len(made) == 1
