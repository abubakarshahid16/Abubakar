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

from app import agent_review_equipment as E
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


EXCLUSION = {
    "role": "valve_type",
    "type": "widget_valve",
    "ignore": ["safety"],
    "values": ["conventional", "balanced bellows"],
    "excludes": ["pilot"],
}


def _mapping(related):
    return {
        "map": {"relief valve": "widget_valve", "pressure vessel": "vessel"},
        "unmapped": [],
        "related": related,
        "part_exclusions": [EXCLUSION],
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
    c.execute(
        "CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT, needs_ocr INTEGER DEFAULT 0)"
    )
    c.execute(
        "CREATE TABLE page_ledger (document_id TEXT, page_no INTEGER, native_status TEXT, ocr_status TEXT)"
    )
    c.execute(
        "CREATE TABLE submittal_facts (submittal_document_id TEXT, field_name TEXT, field_label TEXT, field_value TEXT,"
        " page INTEGER, source_text TEXT, is_blank INTEGER, validation_state TEXT, confirmed_by TEXT, superseded_at TEXT)"
    )
    REQ.create_tables(c)
    return c


def _answer(typ=None, fam=None, general=0, valid=1):
    return json.dumps(
        {"family": fam, "type": typ, "part": None, "general": general, "valid": valid}
    )


def _equipment_label(
    c, ref, *, typ=None, fam=None, part=None, general=0, state="agreed", a=None, b=None
):
    cols = {"source": "requirement", "rule_ref": ref, "equip_state": state, "equip_general": general, "equip_type": typ,
            "equip_family": fam, "equip_part": part, "labelled_at": "t"}  # fmt: skip
    if state == "agreed":
        cols.update(
            model_a=s.MODEL_A, model_b=s.MODEL_B, prompt_version="p1", list_sha="c" * 64
        )
    else:
        cols.update(equip_disagreement="type")
    cols.update(answer_a_json=a, answer_b_json=b)
    c.execute(
        f"INSERT INTO rule_equipment_label ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        tuple(cols.values()),
    )


def _disagree(c, ref, a, b, field=None):
    label(c, ref, field=field)
    _equipment_label(c, ref, state="needs_human", a=a, b=b)


def _disagree(c, ref, a, b, field=None):
    label(c, ref, field=field)
    _equipment_label(c, ref, state="needs_human", a=a, b=b)


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


# ---------------------------------------------------------------- (b) a part a STATED value excludes (positive evidence only)

FILLER = " Body material is carbon steel. Set pressure is stated in the table. Notes follow on the next line."


def _page(c, n, text, *, needs_ocr=0, native="text", ocr="not_required", ledger=True):
    c.execute(
        "INSERT INTO pages (document_id, page_no, text, needs_ocr) VALUES ('paper', ?, ?, ?)",
        (n, text, needs_ocr),
    )
    if ledger:
        c.execute("INSERT INTO page_ledger VALUES ('paper', ?, ?, ?)", (n, native, ocr))


def _fact(c, value, *, page=1, quote=None, **over):
    row = {"submittal_document_id": "paper", "field_name": "Valve type", "field_label": "Valve type", "field_value": value,
           "page": page, "source_text": value if quote is None else quote, "is_blank": 0, "validation_state": None,
           "confirmed_by": None, "superseded_at": None, **over}  # fmt: skip
    c.execute(
        f"INSERT INTO submittal_facts ({', '.join(row)}) VALUES ({','.join('?' * len(row))})",
        tuple(row.values()),
    )


def _part_world(conn, stated="Safety, balanced bellows"):
    _page(conn, 1, f"Sheet one. Valve type {stated}." + FILLER)
    _page(conn, 2, "Sheet two. Notes: none." + FILLER)
    _fact(conn, stated)
    _rule(conn, "pilot", "valve_type", typ="widget_valve", fam="valves", part="pilot")
    _rule(conn, "nopart", "valve_type", typ="widget_valve", fam="valves")


def test_a_rule_about_a_part_is_left_out_only_on_a_stated_value_the_data_line_says_excludes_it(
    conn, tax
):
    _part_world(conn)
    got = _asked(conn, _ctx(conn, tax, NARROW), "pilot")
    assert got["ask"] is False and got["reason"] == R.PART_EXCLUDED
    assert got["part_note"] == {
        "part": "pilot",
        "role": "valve_type",
        "stated": [("Safety, balanced bellows", 1)],
    }
    assert (
        _asked(conn, _ctx(conn, tax, NARROW), "nopart")["ask"] is True
    )  # no part named: nothing to check


@pytest.mark.parametrize(
    "stated",
    [
        "POPRV",
        "Pilots",
        "Piloted",
        "PO",
        "Safety, balanced bellows PO",
        "Pilot operated",
        "Spring",
    ],
)
def test_a_value_that_is_not_in_the_table_or_says_more_never_leaves_the_rule_out(
    conn, tax, stated
):
    _part_world(conn, stated)
    assert _asked(conn, _ctx(conn, tax, NARROW), "pilot")["ask"] is True


@pytest.mark.parametrize(
    "doubt",
    ["needs_ocr_page", "ledger_not_text", "ocr_pending", "no_ledger_row", "empty_page", "a_gap_in_the_pages", "no_page_at_all",
     "quote_not_on_page", "no_quote", "blank_value", "one_fact_unlisted", "no_fact_of_the_role", "role_not_in_a_line",
     "part_not_excluded_by_the_line", "type_differs", "label_not_agreed", "field_differs", "no_evidence", "malformed_line"],
)  # fmt: skip
def test_in_any_doubt_the_part_rule_is_asked(conn, tax, doubt):
    _part_world(conn)
    mapping = NARROW
    if doubt == "needs_ocr_page":
        conn.execute("UPDATE pages SET needs_ocr = 1 WHERE page_no = 2")
    elif doubt == "ledger_not_text":
        conn.execute("UPDATE page_ledger SET native_status = 'image' WHERE page_no = 2")
    elif doubt == "ocr_pending":
        conn.execute("UPDATE page_ledger SET ocr_status = 'pending' WHERE page_no = 2")
    elif doubt == "no_ledger_row":
        conn.execute("DELETE FROM page_ledger WHERE page_no = 2")
    elif doubt == "empty_page":
        conn.execute("UPDATE pages SET text = '  ' WHERE page_no = 2")
    elif doubt == "a_gap_in_the_pages":
        _page(conn, 4, "Sheet four." + FILLER)
    elif doubt == "no_page_at_all":
        conn.execute("DELETE FROM pages")
    elif doubt == "quote_not_on_page":
        conn.execute(
            "UPDATE submittal_facts SET source_text = 'Safety, balanced bellows and more words'"
        )
    elif doubt == "no_quote":
        conn.execute("UPDATE submittal_facts SET source_text = ''")
    elif doubt == "blank_value":
        conn.execute("UPDATE submittal_facts SET is_blank = 1")
    elif doubt == "one_fact_unlisted":
        _fact(conn, "Safety, Pilot", page=2, quote="Safety, Pilot")
    elif doubt == "no_fact_of_the_role":
        conn.execute("DELETE FROM submittal_facts")
    elif doubt == "role_not_in_a_line":
        mapping = {
            **NARROW,
            "part_exclusions": [{**EXCLUSION, "role": "something_else"}],
        }
    elif doubt == "part_not_excluded_by_the_line":
        mapping = {**NARROW, "part_exclusions": [{**EXCLUSION, "excludes": ["spring"]}]}
    elif doubt == "type_differs":
        mapping = {**NARROW, "part_exclusions": [{**EXCLUSION, "type": "gadget_valve"}]}
    elif doubt == "label_not_agreed":
        conn.execute("UPDATE rule_equipment_label SET equip_state = 'needs_human', model_a = NULL, model_b = NULL,"
                     " prompt_version = NULL, list_sha = NULL, equip_disagreement = 'type' WHERE rule_ref = 'pilot'")  # fmt: skip
    elif doubt == "field_differs":
        conn.execute(
            "UPDATE rule_label SET field = 'set_pressure' WHERE rule_ref = 'pilot'"
        )
    elif doubt == "no_evidence":
        ctx = R.EquipmentCtx(
            R.paper_equipment(conn, "paper", tax, NARROW), tax, NARROW, "type"
        )
        assert _asked(conn, ctx, "pilot")["ask"] is True
        return
    elif doubt == "malformed_line":
        mapping = {
            **NARROW,
            "part_exclusions": [{"role": "valve_type", "type": "widget_valve"}],
        }
    assert _asked(conn, _ctx(conn, tax, mapping), "pilot")["ask"] is True, doubt


def test_a_superseded_fact_is_not_read_and_a_geometry_conflict_does_not_matter(
    conn, tax
):
    _part_world(conn)
    _fact(
        conn, "Safety, Pilot", page=2, quote="Safety, Pilot", superseded_at="2026-01-01"
    )
    conn.execute(
        "UPDATE submittal_facts SET validation_state = 'conflict' WHERE superseded_at IS NULL"
    )
    assert _asked(conn, _ctx(conn, tax, NARROW), "pilot")["reason"] == R.PART_EXCLUDED


def test_the_left_out_words_are_a_true_sentence_built_from_the_fact(conn, tax):
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
    assert [k["id"] for k in kept] == ["nopart"] and left[0][
        "reason"
    ] == R.PART_EXCLUDED
    assert R.count_left_out(left)[R.PART_EXCLUDED] == 1
    assert (
        R.REASON_WORDS[R.PART_EXCLUDED] == "a part excluded by a value the paper states"
    )
    block = R.label_block(
        R.count_left_out(left), left, {"kind": "datasheet", "known": True}, []
    )
    assert (
        "the paper states valve type = Safety, balanced bellows (page 1), which has no pilot: 1 rules about that part were not asked"
        in block["summary_lines"]
    )


def test_the_real_data_line_is_well_formed_and_every_excluded_part_is_on_the_taxonomy():
    mapping = REQ.load_mapping()
    taxonomy = json.loads(REQ.TAXONOMY.read_text())
    parts = {
        t["id"]: set(t.get("parts") or [])
        for f in taxonomy["families"]
        for t in f["types"]
    }
    rows = mapping["part_exclusions"]
    assert rows and len(E.exclusion_rows(mapping)) == len(rows)  # none is malformed
    for row in rows:
        assert set(row) <= {"role", "type", "ignore", "values", "excludes"}
        assert row["type"] in parts and set(row["excludes"]) <= parts[row["type"]]
        assert all(
            isinstance(v, str) and v.strip()
            for v in [*row["values"], *row.get("ignore", [])]
        )
        assert not (
            {w for v in row["values"] for w in E._tokens(v)}
            & {w for p in row["excludes"] for w in E._tokens(p)}
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


def test_with_the_current_code_on_a_local_data_copy_no_known_finding_rule_is_left_out(
    tmp_path,
):
    """Local only (never CI; the mechanism above is tested with invented data). KNOWN_RULES_FILE: ids only;
    KNOWN_RULES_DATA_DIR + KNOWN_RULES_DOCUMENT: a data folder and a paper; the plan is made now, by this code, on a clone.
    KNOWN_RULES_RUN_DB alone checks a stored run instead (it proves the code that made that run)."""
    import os

    ids = os.environ.get("KNOWN_RULES_FILE")
    data, doc, db = (
        os.environ.get(k)
        for k in ("KNOWN_RULES_DATA_DIR", "KNOWN_RULES_DOCUMENT", "KNOWN_RULES_RUN_DB")
    )
    if not ids or not ((data and doc) or db):
        pytest.skip(
            "set KNOWN_RULES_FILE and KNOWN_RULES_DATA_DIR + KNOWN_RULES_DOCUMENT (or KNOWN_RULES_RUN_DB)"
        )
    asked = (
        K.fresh_plan(data, doc, tmp_path / "clone")
        if data and doc
        else K.asked_in_run_db(db)
    )
    assert asked, "the plan asked nothing"
    lost = K.missing(K.read_ids(ids), asked)
    assert lost == [], f"known-finding rules no longer asked: {lost}"


# ---------------------------------------------------------------- two readers who disagree but both name other equipment

OTHER_A = _answer(
    "gadget_valve", "valves"
)  # not the paper's (a widget valve) and not related
OTHER_B = _answer(
    None, "static"
)  # a family the paper has only through the field-narrowed related line


def test_both_readers_name_other_equipment_so_the_rule_is_left_out_with_its_own_words(
    conn, tax
):
    _disagree(
        conn, "both", OTHER_A, _answer("gadget_valve", "valves"), field="overpressure"
    )
    got = _asked(conn, _ctx(conn, tax, NARROW), "both")
    assert got["ask"] is False and got["reason"] == R.TWO_READERS_OTHER
    assert (
        R.REASON_WORDS[R.TWO_READERS_OTHER]
        == "both labelling readers named other equipment"
    )
    counts = R.count_left_out([{"reason": R.TWO_READERS_OTHER}])
    assert counts[R.TWO_READERS_OTHER] == 1
    assert any(
        x.startswith("both labelling readers named other equipment: 1")
        for x in R.summary_lines(counts, "datasheet")
    )


def test_a_related_family_whose_field_is_not_named_counts_as_other_equipment_for_a_reader(
    conn, tax
):
    _disagree(conn, "rel", OTHER_A, OTHER_B, field="joint_efficiency")
    assert _asked(conn, _ctx(conn, tax, NARROW), "rel")["reason"] == R.TWO_READERS_OTHER
    _disagree(conn, "relnamed", OTHER_A, OTHER_B, field="overpressure")
    assert (
        _asked(conn, _ctx(conn, tax, NARROW), "relnamed")["ask"] is True
    )  # the data line names this field: not other


@pytest.mark.parametrize(
    "a,b",
    [
        (_answer("widget_valve", "valves"), OTHER_A),  # one names the paper's own type
        (
            _answer(None, "valves"),
            OTHER_A,
        ),  # one names the paper's... family is valves: the paper's family
        (_answer(general=1), OTHER_A),  # one says general
        (None, OTHER_A),  # one missing
        (OTHER_A, "not json {"),  # one unparseable
        (OTHER_A, _answer("gadget_valve", "valves", valid=0)),  # one not valid
        (OTHER_A, _answer()),  # one names nothing
    ],
)
def test_in_any_doubt_about_the_two_answers_the_rule_is_asked(conn, tax, a, b):
    _disagree(conn, "x", a, b)
    got = _asked(conn, _ctx(conn, tax, NARROW), "x")
    assert got["ask"] is True and got["equipment_why"] == "equipment_not_known"


def test_the_answers_are_kept_by_the_import_and_a_paper_without_usable_equipment_asks_the_rule(
    conn, tax, monkeypatch
):
    good = {"source": "requirement", "rule_ref": "imp", "equip_state": "needs_human", "equip_disagreement": "type",
            "answer_a": {"family": "valves", "type": "gadget_valve", "part": None, "general": 0, "valid": 1},
            "answer_b": {"family": "static", "type": "nope", "part": None, "general": 0, "valid": 1}}  # fmt: skip
    got = REQ.import_rows(conn, [good], tax)
    assert got["stored"] == 1 and got["refused"] == 0
    row = REQ.label_for(conn, "requirement", "imp")
    assert REQ.answer_of(row, "a")["type"] == "gadget_valve"
    assert (
        REQ.answer_of(row, "b") is None
    )  # off the closed list: not kept, so the rule is asked
    # an older table without the two columns gets them
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE rule_equipment_label (source TEXT, rule_ref TEXT)")
    c.execute("DROP TABLE rule_equipment_label")
    REQ.create_tables(c)
    assert {r[1] for r in c.execute("PRAGMA table_info(rule_equipment_label)")} >= set(
        REQ.ANSWER_COLUMNS
    )
    # no usable paper equipment: nothing is left out for two readers
    conn.execute("UPDATE document_classification SET equipment_type = NULL")
    _disagree(conn, "z", OTHER_A, OTHER_A)
    assert _asked(conn, _ctx(conn, tax, NARROW), "z")["ask"] is True


def test_importing_an_older_file_with_no_answers_keeps_the_answers_already_stored(
    conn, tax
):
    row = {"source": "requirement", "rule_ref": "keep", "equip_state": "needs_human", "equip_disagreement": "type",
           "answer_a": {"family": "valves", "type": "gadget_valve", "part": None, "general": 0, "valid": 1},
           "answer_b": {"family": "static", "type": "vessel", "part": None, "general": 0, "valid": 1}}  # fmt: skip
    REQ.import_rows(conn, [row], tax)
    old = {k: v for k, v in row.items() if not k.startswith("answer_")}
    REQ.import_rows(conn, [old], tax)
    stored = REQ.label_for(conn, "requirement", "keep")
    assert (
        REQ.answer_of(stored, "a")["type"] == "gadget_valve"
        and REQ.answer_of(stored, "b")["type"] == "vessel"
    )
