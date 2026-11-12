"""C3 (order 13, owner point 9): a rule that cannot apply to the paper's equipment is left out BEFORE it is asked.

Invented equipment, rules and papers; no model, no network. Each test fails without the change: put the old `related` list
back (every rule of a related type is asked) or delete the part check, and the named assertion breaks."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app import agent_review_rules as R
from app import rule_equipment as REQ
from app import rule_label_schema as schema
from scripts import c3_check_known_rules as K
from tests import rule_label_support as s
from tests.test_agent_review_rules import label

TAX = {
    "families": [
        {"id": "valves", "name": "Valves", "types": [
            {"id": "widget_valve", "name": "Widget valve", "parts": [], "synonyms": ["WV"]},
            {"id": "gadget_valve", "name": "Gadget valve", "parts": [], "synonyms": []}]},
        {"id": "static", "name": "Static", "types": [
            {"id": "vessel", "name": "Vessel", "parts": [], "synonyms": []}]},
    ],
    "general": "applies to all equipment", "not_equipment": [], "part_ids_shared": "x",
}  # fmt: skip


def _mapping(related):
    return {
        "map": {"relief valve": "widget_valve", "pressure vessel": "vessel"},
        "unmapped": [],
        "related": related,
        "part_roles": ["valve_type"],
    }


NARROW = _mapping({"widget_valve": {"vessel": ["overpressure", "set_pressure"]}})
LEGACY = _mapping({"widget_valve": ["vessel"]})


@pytest.fixture
def tax(tmp_path):
    p = tmp_path / "tax.json"
    p.write_text(json.dumps(TAX))
    return REQ.Taxonomy.load(p)


@pytest.fixture
def conn(monkeypatch):
    s.switch(monkeypatch)
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    schema.create_tables(c)
    c.execute(
        "CREATE TABLE rulebook_approval (id TEXT PRIMARY KEY, rule_version_id TEXT, decision TEXT, approver_id TEXT,"
        " decided_at TEXT, equipment_type TEXT, tier TEXT)"
    )
    c.execute(
        "CREATE TABLE document_classification (document_id TEXT, equipment_type TEXT, title TEXT)"
    )
    c.execute(
        "INSERT INTO document_classification VALUES ('paper', 'Pressure Safety Valve', NULL)"
    )
    c.execute("CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT)")
    c.execute(
        "CREATE TABLE submittal_facts (submittal_document_id TEXT, field_name TEXT, field_label TEXT, field_value TEXT,"
        " source_text TEXT, is_blank INTEGER, validation_state TEXT, confirmed_by TEXT, superseded_at TEXT)"
    )
    REQ.create_tables(c)
    return c


def _equipment_label(
    c, ref, *, typ=None, fam=None, part=None, general=0, state="agreed"
):
    cols = {"source": "requirement", "rule_ref": ref, "equip_state": state, "equip_general": general, "equip_type": typ,
            "equip_family": fam, "equip_part": part, "labelled_at": "t"}  # fmt: skip
    if state == "agreed":
        cols.update(
            model_a=s.MODEL_A, model_b=s.MODEL_B, prompt_version="p1", list_sha="c" * 64
        )
    else:
        cols.update(equip_disagreement="type")
    c.execute(
        f"INSERT INTO rule_equipment_label ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        tuple(cols.values()),
    )


def _rule(c, ref, field, **eq):
    label(c, ref, field=field)
    _equipment_label(c, ref, **eq)


def _ctx(c, tax, mapping, mode="type"):
    return R.EquipmentCtx(
        R.paper_equipment(c, "paper", tax, mapping),
        tax,
        mapping,
        mode,
        R.load_evidence(c, "paper", mapping),
    )


def _asked(c, ctx, ref):
    return R.decide_rule(c, ref, "datasheet", equipment=ctx)


# ---------------------------------------------------------------- (a) the related line is narrowed to named fields


def test_a_related_types_rule_is_asked_only_when_the_data_line_names_its_field(
    conn, tax
):
    _rule(conn, "named", "overpressure", typ="vessel", fam="static")
    _rule(conn, "other", "joint_efficiency", typ="vessel", fam="static")
    _rule(conn, "nofield", None, typ="vessel", fam="static")
    ctx = _ctx(conn, tax, NARROW)
    named = _asked(conn, ctx, "named")
    assert named["ask"] is True and named["equipment_why"] == "same_equipment"
    for ref in ("other", "nofield"):
        got = _asked(conn, ctx, ref)
        assert got["ask"] is False and got["reason"] == R.ANOTHER_EQUIPMENT
        assert got["equipment_family"] == "static"


def test_the_old_list_form_still_asks_every_rule_of_the_related_type(conn, tax):
    _rule(conn, "other", "joint_efficiency", typ="vessel", fam="static")
    got = _asked(conn, _ctx(conn, tax, LEGACY), "other")
    assert got["ask"] is True and got["equipment_why"] == "same_equipment"


def test_the_papers_own_type_and_unlabelled_rules_are_never_narrowed(conn, tax):
    _rule(conn, "own", "joint_efficiency", typ="widget_valve", fam="valves")
    _rule(conn, "general", None, general=1)
    _rule(
        conn,
        "human",
        "joint_efficiency",
        typ="vessel",
        fam="static",
        state="needs_human",
    )
    ctx = _ctx(conn, tax, NARROW)
    assert _asked(conn, ctx, "own")["equipment_why"] == "same_equipment"
    assert _asked(conn, ctx, "general")["equipment_why"] == "general"
    assert (
        _asked(conn, ctx, "human")["equipment_why"] == "equipment_not_known"
    )  # not agreed: asked, never dropped on a guess
    # a vessel paper: vessel is its OWN type, so no field narrowing applies to its rules
    conn.execute(
        "UPDATE document_classification SET equipment_type = 'Pressure Vessel'"
    )
    ctx = _ctx(conn, tax, NARROW)
    _rule(conn, "vessel_rule", "joint_efficiency", typ="vessel", fam="static")
    assert _asked(conn, ctx, "vessel_rule")["equipment_why"] == "same_equipment"


def test_family_mode_narrows_a_related_family_the_same_way(conn, tax):
    _rule(conn, "named", "set_pressure", typ="vessel", fam="static")
    _rule(conn, "other", "mdmt", typ="vessel", fam="static")
    _rule(conn, "famonly", "mdmt", fam="static")
    ctx = _ctx(conn, tax, NARROW, "family")
    assert _asked(conn, ctx, "named")["ask"] is True
    assert _asked(conn, ctx, "other")["ask"] is False
    assert _asked(conn, ctx, "famonly")["ask"] is False


def test_a_plain_list_means_every_field_of_the_related_type(conn, tax):
    eq = R.paper_equipment(conn, "paper", tax, LEGACY)
    assert eq.related_fields["vessel"] is None


def test_the_core_types_never_enter_the_related_table(conn, tax):
    eq = R.paper_equipment(conn, "paper", tax, NARROW)
    assert "widget_valve" in eq.core_types and "widget_valve" not in eq.related_fields
    assert eq.related_fields["vessel"] == frozenset({"overpressure", "set_pressure"})


# ---------------------------------------------------------------- (b) a part the paper's own facts and pages do not name


def _fact(c, label_, value, quote, **over):
    row = {"submittal_document_id": "paper", "field_name": label_, "field_label": label_, "field_value": value,
           "source_text": quote, "is_blank": 0, "validation_state": None, "confirmed_by": None, "superseded_at": None,
           **over}  # fmt: skip
    c.execute(
        f"INSERT INTO submittal_facts ({', '.join(row)}) VALUES ({','.join('?' * len(row))})",
        tuple(row.values()),
    )


def _page(c, n, text):
    c.execute("INSERT INTO pages VALUES ('paper', ?, ?)", (n, text))


def _part_world(conn, *, type_text="Safety, balanced bellows"):
    _page(conn, 1, "Sheet one. Body WCB. Set 10 barg.")
    _page(conn, 2, "Sheet two. Notes: none.")
    _fact(conn, "Valve type", type_text, f"Valve type {type_text}")
    _rule(conn, "pilot", "valve_type", typ="widget_valve", fam="valves", part="pilot")
    _rule(conn, "nopart", "valve_type", typ="widget_valve", fam="valves")
    return REQ


def test_a_rule_about_a_part_is_left_out_when_the_sheets_state_the_type_and_name_no_such_part(
    conn, tax
):
    _part_world(conn)
    ctx = _ctx(conn, tax, NARROW)
    got = _asked(conn, ctx, "pilot")
    assert got["ask"] is False and got["reason"] == R.PART_ABSENT
    assert _asked(conn, ctx, "nopart")["ask"] is True  # no part named: nothing to check


@pytest.mark.parametrize(
    "doubt",
    [
        "fact_names_the_part", "page_names_the_part", "a_blank_value", "no_quote", "an_empty_page",
        "no_page_at_all", "no_fact_of_the_role", "field_not_a_part_role", "label_not_agreed", "no_evidence",
    ],
)  # fmt: skip
def test_in_any_doubt_the_part_rule_is_asked(conn, tax, doubt):
    _part_world(conn)
    mapping = NARROW
    if doubt == "fact_names_the_part":
        _fact(conn, "Valve type", "Pilot operated", "Valve type Pilot operated")
    elif doubt == "page_names_the_part":
        _page(conn, 3, "Note: a pilot line is fitted.")
    elif doubt == "a_blank_value":
        _fact(conn, "Valve type", "", "Valve type: By Contractor", is_blank=1)
    elif doubt == "no_quote":
        _fact(conn, "Valve type", "Safety", "")
    elif doubt == "an_empty_page":
        _page(conn, 3, "   ")
    elif doubt == "no_page_at_all":
        conn.execute("DELETE FROM pages")
    elif doubt == "no_fact_of_the_role":
        conn.execute("DELETE FROM submittal_facts")
    elif doubt == "field_not_a_part_role":
        mapping = {**NARROW, "part_roles": ["something_else"]}
    elif doubt == "label_not_agreed":
        conn.execute("UPDATE rule_equipment_label SET equip_state = 'needs_human', model_a = NULL, model_b = NULL,"
                     " prompt_version = NULL, list_sha = NULL, equip_disagreement = 'type' WHERE rule_ref = 'pilot'")  # fmt: skip
    elif doubt == "no_evidence":
        ctx = R.EquipmentCtx(
            R.paper_equipment(conn, "paper", tax, NARROW), tax, NARROW, "type"
        )
        assert _asked(conn, ctx, "pilot")["ask"] is True
        return
    got = _asked(conn, _ctx(conn, tax, mapping), "pilot")
    assert got["ask"] is True, doubt


def test_a_value_whose_geometry_check_disagrees_does_not_block_a_negative_proof_the_pages_carry(
    conn, tax
):
    _part_world(conn)
    _fact(
        conn, "Valve type", "Safety", "Valve type Safety", validation_state="conflict"
    )
    assert _asked(conn, _ctx(conn, tax, NARROW), "pilot")["reason"] == R.PART_ABSENT


def test_a_word_the_data_line_gives_as_an_alias_of_the_part_counts_as_naming_it(
    conn, tax
):
    _part_world(conn)
    _fact(conn, "Valve type", "POSRV", "Valve type POSRV")
    mapping = {**NARROW, "part_aliases": {"pilot": ["posrv"]}}
    assert _asked(conn, _ctx(conn, tax, mapping), "pilot")["ask"] is True
    assert (
        _asked(conn, _ctx(conn, tax, NARROW), "pilot")["reason"] == R.PART_ABSENT
    )  # without the alias the word is not seen


def test_a_superseded_fact_is_not_read(conn, tax):
    _part_world(conn)
    _fact(
        conn,
        "Valve type",
        "Pilot operated",
        "Valve type Pilot operated",
        superseded_at="2026-01-01",
    )
    assert _asked(conn, _ctx(conn, tax, NARROW), "pilot")["ask"] is False


def test_the_part_reason_is_counted_worded_and_in_the_summary(conn, tax):
    _part_world(conn)
    ctx = _ctx(conn, tax, NARROW)
    kept, left, _ = R.filter_rows(
        conn,
        [
            {"id": "pilot", "item_id": "R-pilot"},
            {"id": "nopart", "item_id": "R-nopart"},
        ],
        "datasheet",
        equipment=ctx,
    )
    assert [k["id"] for k in kept] == ["nopart"] and left[0]["reason"] == R.PART_ABSENT
    counts = R.count_left_out(left)
    assert counts[R.PART_ABSENT] == 1
    assert R.REASON_WORDS[R.PART_ABSENT] == "a part the paper's equipment does not have"
    assert any(
        line.startswith("a part the paper's equipment does not have: 1 rules not asked")
        for line in R.summary_lines(counts, "datasheet")
    )


# ---------------------------------------------------------------- the proof that no known-finding rule is dropped


def test_known_rules_are_read_from_a_file_of_ids_only_and_a_dropped_one_is_named(
    tmp_path,
):
    f = tmp_path / "ids.txt"
    f.write_text("# valve\nR-aaaaaaaa\nS-EQ-05  # checklist\n\nR-bbbbbbbb\n")
    known = K.read_ids(f)
    assert known == ["R-aaaaaaaa", "S-EQ-05", "R-bbbbbbbb"]
    asked = {"R-aaaaaaaa-1111-2222-3333-444444444444", "S-EQ-05"}
    assert K.missing(known, asked) == ["R-bbbbbbbb"]
    assert K.missing(known, asked | {"R-bbbbbbbb-0000"}) == []
    assert K.missing(known, set()) == known


def test_the_known_rules_file_refuses_a_line_that_is_text(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("R-aaaaaaaa\nthe sheet says something about a valve\n")
    with pytest.raises(ValueError):
        K.read_ids(f)


def test_the_plan_of_a_stored_run_is_read_for_its_asked_rules_and_checklist_items(
    tmp_path,
):
    db = tmp_path / "d.sqlite"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE agent_review_run (run_id TEXT, started_at TEXT)")
    c.execute(
        "CREATE TABLE agent_review_rule (run_id TEXT, rule_key TEXT, asked INTEGER)"
    )
    c.execute("CREATE TABLE agent_review_line (run_id TEXT, item_id TEXT)")
    c.executemany(
        "INSERT INTO agent_review_run VALUES (?,?)",
        [("old", "1"), ("new", "2"), ("none", "3")],
    )
    c.executemany(
        "INSERT INTO agent_review_rule VALUES (?,?,?)",
        [("old", "R-old", 1), ("new", "R-yes", 1), ("new", "R-no", 0)],
    )
    c.executemany(
        "INSERT INTO agent_review_line VALUES (?,?)",
        [("new", "S-EQ-01"), ("new", "R-yes"), ("old", "S-OLD")],
    )
    c.commit()
    c.close()
    assert K.asked_in_run_db(db) == {"R-yes", "S-EQ-01"}
    assert K.asked_in_run_db(db, "old") == {"R-old", "S-OLD"}


def test_a_dropped_known_rule_fails_the_check_on_a_plan_made_by_the_filter(conn, tax):
    """The mechanism end to end with invented data: a known id the filter drops is named; one it keeps is not."""
    _rule(conn, "keep", "overpressure", typ="vessel", fam="static")
    _rule(conn, "drop", "joint_efficiency", typ="vessel", fam="static")
    ctx = _ctx(conn, tax, NARROW)
    kept, _left, _ = R.filter_rows(
        conn,
        [{"id": r, "item_id": f"R-{r}"} for r in ("keep", "drop")],
        "datasheet",
        equipment=ctx,
    )
    assert K.missing(["keep", "drop"], [k["id"] for k in kept]) == ["drop"]


def test_on_a_local_trial_copy_no_known_finding_rule_is_left_out():
    """Runs only on the Mac that holds the local ids file and a closed-lane trial copy (never in CI, never vacuous there:
    the mechanism above is tested with invented data). KNOWN_RULES_FILE: ids only; KNOWN_RULES_RUN_DB: the trial's database."""
    import os

    ids, db = os.environ.get("KNOWN_RULES_FILE"), os.environ.get("KNOWN_RULES_RUN_DB")
    if not ids or not db:
        pytest.skip(
            "set KNOWN_RULES_FILE and KNOWN_RULES_RUN_DB to run the check on a local trial copy"
        )
    lost = K.missing(
        K.read_ids(ids), K.asked_in_run_db(db, os.environ.get("KNOWN_RULES_RUN_ID"))
    )
    assert lost == [], f"known-finding rules no longer asked: {lost}"
