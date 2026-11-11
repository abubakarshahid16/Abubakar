"""The AI reviewer's item list: build_items and batch_by_page on INVENTED data only (no real paper or standard text)."""

from __future__ import annotations

import sqlite3

import pytest

from app import agent_review_items as it
from app import agent_review_verdict as V
from app import rule_label_schema as schema
from app import rule_labels
from tests import rule_label_support as s

PAPER = "doc_paper"
STD = "doc_std"

STD_PAGES = {
    1: "1 Scope\nThis invented book covers widgets of every kind.\n2 Definitions\nA widget is a made-up part.",
    2: (
        "4 Design\n4.1 Frame Size\nThe frame width shall be at least 40 mm for every widget built.\n"
        "4.2 Coating Thickness\nThe coating shall be applied in two layers of equal depth."
    ),
    3: "Table Q-7 Invented Limits\nRow alpha 12 15 20\nRow beta 30 35 40",
}
PAPER_PAGES = {
    1: "Frame width 45 mm\nColour blue",
    2: "Coating layers two\nMaker name invented",
}


def _db(con: sqlite3.Connection) -> sqlite3.Connection:
    con.executescript(
        """
        CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT);
        CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);
        CREATE TABLE standard_requirements (id TEXT PRIMARY KEY, standard_document_id TEXT, clause TEXT,
            page INTEGER, requirement_text TEXT, source_text TEXT, requirement_type TEXT, field TEXT,
            operator TEXT, value REAL, unit TEXT, value_low REAL, value_high REAL, table_row INTEGER);
        CREATE TABLE review_runs (id TEXT PRIMARY KEY, submittal_document_id TEXT, status TEXT, created_at TEXT);
        CREATE TABLE review_scope_decisions (review_run_id TEXT, requirement_id TEXT, state TEXT,
            reason_code TEXT, PRIMARY KEY (review_run_id, requirement_id));
        """
    )
    con.execute("INSERT INTO documents VALUES (?, ?)", (STD, "INV-STD-100.pdf"))
    con.execute("INSERT INTO documents VALUES (?, ?)", (PAPER, "paper.pdf"))
    for p, t in STD_PAGES.items():
        con.execute("INSERT INTO pages VALUES (?, ?, ?)", (STD, p, t))
    for p, t in PAPER_PAGES.items():
        con.execute("INSERT INTO pages VALUES (?, ?, ?)", (PAPER, p, t))
    reqs = [
        # id, clause, page, text, source, type, field, op, value, unit, table_row
        ("r-limit", "4.1", 2, "frame width at least 40 mm", "The frame width shall be at least 40 mm",
         "numeric_limit", "frame width", ">=", 40.0, "mm", None),
        ("r-limit-twin", "4.1", 2, "Frame width at least 40 mm.", "The frame width shall be at least 40 mm",
         "numeric_limit", "frame width", ">=", 40.0, "mm", None),
        ("r-coat", None, 2, "coating applied in two layers", "The coating shall be applied in two layers of equal depth",
         "statement", None, None, None, None, None),
        ("r-table", None, 3, "row beta value", "Row beta 30 35 40", "table_value", "row beta", None, None, None, 2),
        ("r-advice", "4.2", 2, "advice only", "advice only text here", "recommendation", None, None, None, None, None),
        ("r-out", "1", 1, "about another kind", "This invented book covers widgets", "statement", None, None, None, None, None),
        ("r-query", "4.2", 2, "a raised query", "a raised query text", "recommendation", None, None, None, None, None),
        ("r-list", "4.2", 2, "coating depth equal", "layers of equal depth", "statement", None, None, None, None, None),
    ]  # fmt: skip
    for r in reqs:
        con.execute(
            "INSERT INTO standard_requirements (id, clause, page, requirement_text, source_text, requirement_type,"
            " field, operator, value, unit, table_row, standard_document_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (*r, STD),
        )
    con.execute(
        "INSERT INTO review_runs VALUES ('run-old', ?, 'completed', '2026-01-01')",
        (PAPER,),
    )
    con.execute(
        "INSERT INTO review_runs VALUES ('run-new', ?, 'completed', '2026-01-02')",
        (PAPER,),
    )
    con.execute(
        "INSERT INTO review_runs VALUES ('run-cancel', ?, 'cancelled', '2026-01-03')",
        (PAPER,),
    )
    decisions = [
        ("r-limit", "applies_not_checked", "needs_engineer"),
        (
            "r-limit-twin",
            "does_not_apply",
            "other_equipment",
        ),  # same rule text: the better group wins
        ("r-coat", "applies_not_checked", "needs_other_document"),
        ("r-table", "checked", "reached"),
        ("r-advice", "applies_not_checked", "needs_engineer"),
        ("r-out", "does_not_apply", "other_equipment"),
        ("r-query", "applies_not_checked", "recommendation_query"),
        ("r-list", "not_used", "covered_by_checklist"),
    ]
    for rid, state, code in decisions:
        con.execute(
            "INSERT INTO review_scope_decisions VALUES ('run-new', ?, ?, ?)",
            (rid, state, code),
        )
    con.execute(
        "INSERT INTO review_scope_decisions VALUES ('run-old', 'r-out', 'applies_not_checked', 'x')"
    )
    con.commit()
    return con


H = "b" * 64


def _label(con, ref, state="ai_approved", kind="datasheet", **over):
    cols = {
        "source": "requirement",
        "rule_ref": ref,
        "rule_version_id": f"v-{ref}",
        "state": state,
        "paper_kind": kind,
        "labelled_at": "2026-11-11T00:00:00Z",
        "a_model": s.MODEL_A,
    }
    if state == "ai_approved":
        cols.update(
            b_model=s.MODEL_B,
            a_prompt=rule_labels.PROMPT_VERSION,
            b_prompt=rule_labels.PROMPT_VERSION,
            a_answer_sha256=H,
            b_answer_sha256=H,
            quote_sha256=H,
            quote_page=1,
            reading_json='{"comparator": "required", "values": [], "unit": null, "strength": "shall"}',
        )
    elif state == "needs_human":
        cols.update(
            b_model=s.MODEL_B, disagreement="values", quote_page=1, quote_sha256=H
        )
    cols.update(over)
    con.execute(
        f"INSERT INTO rule_label ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        tuple(cols.values()),
    )


KIND = {"kind": "datasheet", "known": True, "method": "test", "guess": False}


@pytest.fixture()
def con(monkeypatch):
    s.switch(monkeypatch)
    c = sqlite3.connect(":memory:")
    _db(c)
    schema.create_tables(c)
    for ref in ("r-limit", "r-coat", "r-table", "r-advice"):
        _label(c, ref)
    _label(c, "r-out", kind="procedure")  # another paper kind
    return c


@pytest.fixture()
def built(con):
    cache: dict = {}
    doc = it.build_items(con, PAPER, KIND, skills=[SKILL], cache=cache)
    return doc, cache


def _by_id(doc):
    return {i["item_id"]: i for i in doc["items"]}


def test_rules_are_the_applicable_set_each_once_and_only_the_right_ones(built):
    doc, _ = built
    assert (
        doc["old_engine_run"] == "run-new"
    )  # latest COMPLETED run with stored decisions
    rules = {i["rule_version_id"] for i in doc["items"] if i["source"] == "rule"}
    assert rules == {"r-limit", "r-coat", "r-table", "r-advice"}
    assert doc["counts"] == {"skill": 2, "rule": 4}
    assert doc["rules_left_out"] == {
        "applies_not_checked:recommendation_query": 1,
        "does_not_apply:other_equipment": 1,
        "not_used:covered_by_checklist": 1,
        "stored_repeat": 1,
    }
    assert it.validate(doc, built[1]) == []


def test_every_rule_item_carries_its_tier_and_label(built):
    doc, _ = built
    for item in doc["items"]:
        if item["source"] == "rule":
            assert (
                item["rule_label"]["tier"] == "AI approved"
                and item["rule_label"]["paper_kind"] == "datasheet"
            )
            assert "rule_tier" not in item
            assert V.item_tier(item) == "AI approved"
    skill_ids = {i["item_id"] for i in doc["items"] if i["source"] == "skill"}
    assert V.item_tier(_by_id(doc)["S-K-2"], None, skill_ids) == V.NOT_A_RULE
    assert (
        V.item_tier(_by_id(doc)["S-K-2"]) == V.RULE_NOT_APPROVED
    )  # an id that is not in the app's checklist data


def test_a_rule_of_another_paper_kind_is_left_out_with_one_reason_and_counted(con):
    """Kind mismatch never asked: r-out is labelled procedure; the paper is a datasheet; r-coat's label is moved too."""
    con.execute(
        "UPDATE rule_label SET paper_kind = 'procedure' WHERE rule_ref = 'r-coat'"
    )
    doc = it.build_items(con, PAPER, KIND, skills=[SKILL], cache={})
    assert "r-coat" not in {
        i["rule_version_id"] for i in doc["items"] if i["source"] == "rule"
    }
    counts = doc["rule_labels"]["counts"]
    assert counts["needs_another_paper"]["total"] == 1 and counts[
        "needs_another_paper"
    ]["by_kind"] == {"procedure": 1}
    assert (
        doc["rule_labels"]["summary_lines"][0]
        == "needs another paper: 1 rules (procedure 1)"
    )


def test_unlabelled_rules_are_not_asked_and_counted(con):
    c2 = sqlite3.connect(":memory:")
    _db(c2)
    schema.create_tables(c2)  # no label at all
    doc = it.build_items(c2, PAPER, KIND, skills=[SKILL], cache={})
    assert doc["counts"]["rule"] == 0
    assert doc["rule_labels"]["counts"]["not_labelled_yet"] == 4


def test_an_unknown_paper_kind_asks_nothing_and_no_checklist(con):
    unknown = {"kind": None, "known": False, "method": "none", "guess": False}
    doc = it.build_items(con, PAPER, unknown, skills=[SKILL], cache={})
    assert doc["counts"] == {"skill": 0, "rule": 0} and doc["items"] == []
    assert doc["rule_labels"]["counts"]["paper_kind_unknown"] == 4
    assert doc["rule_labels"]["summary_lines"][0].startswith(
        "paper kind unknown: 4 rules NOT asked"
    )
    listed_but_unknown = {
        "kind": "datasheet",
        "known": False,
        "method": "none",
        "guess": True,
    }
    assert (
        it.build_items(con, PAPER, listed_but_unknown, skills=[SKILL], cache={})[
            "counts"
        ]["rule"]
        == 0
    )


def test_the_unapproved_mode_asks_a_needs_human_rule_with_the_marker_and_never_folds_a_checklist_item_into_it(
    con,
):
    _label(con, "r-human", state="needs_human")
    con.execute(
        "INSERT INTO standard_requirements (id, standard_document_id, clause, page, requirement_text, source_text,"
        " requirement_type) VALUES ('r-human', ?, '4.1', 2, 'frame width unapproved', 'The frame width shall be at"
        " least 40 mm for every widget built', 'statement')",
        (STD,),
    )
    con.execute(
        "INSERT INTO review_scope_decisions VALUES ('run-new', 'r-human', 'applies_not_checked', 'x')"
    )
    con.execute(
        "DELETE FROM review_scope_decisions WHERE requirement_id IN ('r-limit', 'r-limit-twin')"
    )
    off = it.build_items(con, PAPER, KIND, skills=[SKILL], cache={})
    assert "r-human" not in {
        i["rule_version_id"] for i in off["items"] if i["source"] == "rule"
    }
    on = it.build_items(
        con, PAPER, KIND, skills=[SKILL], cache={}, ask_unapproved="both"
    )
    rule = _by_id(on)["R-r-human"]
    assert (
        rule["rule_tier"] == V.RULE_NOT_APPROVED
        and rule["rule_unapproved_why"] == "values"
    )
    assert V.item_tier(rule) == V.RULE_NOT_APPROVED and not V.calls_allowed(rule)
    assert on["rule_labels"]["unapproved_asked"] == 1
    assert (
        "S-K-1" in _by_id(on) and rule["also_skill_ids"] == []
    )  # K-1 cites 4.1 but is NOT folded into the unapproved rule


SKILL = {
    "kind": "invented_datasheet",
    "version": "1",
    "items": [
        {"id": "K-2", "order": 2, "topic": "Colour", "expected": "a colour is stated",
         "acceptable_range": "any", "escalate_when": "blank", "clause_refs": []},
        {"id": "K-1", "order": 1, "topic": "Frame width", "expected": "at least the limit",
         "acceptable_range": "limit or more", "escalate_when": "no figure",
         "clause_refs": [{"standard": "INV-STD-100", "clause": "4.1"}]},
        {"id": "K-3", "order": 3, "topic": "Frame and coating", "expected": "both stated",
         "acceptable_range": "both", "escalate_when": "one missing",
         "clause_refs": [{"standard": "INV-STD-100", "clause": "4.1"},
                         {"standard": "OTHER-BOOK-9", "clause": "2"}]},
    ],
}  # fmt: skip


def test_rule_items_carry_clause_page_and_cached_text(built):
    doc, cache = built
    items = _by_id(doc)
    lim = items["R-r-limit"]
    assert (lim["standard"], lim["clause"], lim["clause_page"]) == (
        "INV-STD-100",
        "4.1",
        2,
    )
    assert (lim["rule_kind"], lim["comparator"], lim["value"], lim["unit"]) == (
        "limit",
        ">=",
        40.0,
        "mm",
    )
    assert "at least 40 mm" in cache[lim["clause_quote_ref"]]["text"]
    assert (
        "4.2" not in cache[lim["clause_quote_ref"]]["text"]
    )  # the clause ends at the next heading
    coat = items["R-r-coat"]  # no stored clause: the heading above its sentence
    assert (coat["clause"], coat["clause_from"]) == ("4.2", "placed")
    tab = items["R-r-table"]  # a table row: the caption is the clause
    assert (tab["clause"], tab["clause_from"], tab["clause_page"]) == (
        "Table Q-7",
        "table_caption",
        3,
    )
    assert "Row beta" in cache[tab["clause_quote_ref"]]["text"]
    assert items["R-r-advice"]["rule_kind"] == "advice"
    for i in doc["items"]:
        if i["source"] == "rule":
            assert cache[i["rule_quote_ref"]]["source"] == "rule_quote"


def test_skill_duplicate_of_a_rule_is_kept_once_and_rule_wins(built):
    doc, _ = built
    items = _by_id(doc)
    assert "S-K-1" not in items  # its only clause is a rule's clause
    assert items["R-r-limit"]["also_skill_ids"] == ["S-K-1"]
    assert "Skill guidance (S-K-1)" in items["R-r-limit"]["question"]
    assert doc["skill_merged_into_rules"] == [
        {"skill_item": "S-K-1", "into": ["R-r-limit"]}
    ]
    # K-3 cites a book that is not held as well: not covered by rules, so it stays
    assert items["S-K-3"]["clause_refs"][1]["clause_quote_ref"] is None
    assert items["S-K-2"]["clause_quote_ref"] is None and items["S-K-2"][
        "page_hint"
    ] == [1]


def test_page_hint_from_field_role_words(built):
    doc, _ = built
    assert _by_id(doc)["R-r-limit"]["page_hint"] == [1]
    assert _by_id(doc)["R-r-coat"]["page_hint"] == []


def test_schema_validates_and_catches_errors(built):
    doc, cache = built
    assert it.validate(doc, cache) == []
    broken = {**doc, "items": doc["items"] + [doc["items"][0]]}
    assert any("duplicate item_id" in p for p in it.validate(broken, cache))
    assert any("counts" in p for p in it.validate(broken, cache))
    bad_ref = {
        **doc,
        "items": [{**doc["items"][-1], "clause_quote_ref": "C-missing"}],
        "counts": {"skill": 0, "rule": 1},
    }
    assert any("no text in the cache" in p for p in it.validate(bad_ref, cache))


def test_skill_kinds_for_matches_the_name_ending():
    kinds = ("equip_datasheet", "study_procedure", "other_thing")
    assert it.skill_kinds_for("datasheet", kinds) == ["equip_datasheet"]
    assert it.skill_kinds_for("procedure", kinds) == ["study_procedure"]
    assert it.skill_kinds_for("contract", kinds) == []


def _item(i, pages, ref=None):
    return {"item_id": f"X-{i:02d}", "page_hint": pages, "clause_quote_ref": ref}


def test_batch_by_page_groups_pages_then_no_page_last():
    items = [
        _item(1, [2]),
        _item(2, []),
        _item(3, [1]),
        _item(4, [2]),
        _item(5, [2, 1]),
        _item(6, [1, 2]),
    ]
    groups = it.batch_by_page(items)
    assert [[i["item_id"] for i in g] for g in groups] == [
        ["X-03"],
        ["X-05", "X-06"],  # the same page set, any order
        ["X-01", "X-04"],
        ["X-02"],  # no page hint: last
    ]


def test_batch_by_page_caps_size_and_keeps_shared_clauses_together():
    items = [_item(i, [3], ref="C-b" if i % 2 else "C-a") for i in range(7)]
    groups = it.batch_by_page(items, max_items=3)
    assert [len(g) for g in groups] == [3, 3, 1]
    flat = [i["clause_quote_ref"] for g in groups for i in g]
    assert flat == sorted(flat)  # one clause's items sit next to each other
    assert sorted(i["item_id"] for g in groups for i in g) == sorted(
        i["item_id"] for i in items
    )


def test_a_procedure_is_not_filtered_by_equipment_type_and_asks_the_rules_labelled_procedure(
    con,
):
    for ref in ("r-limit", "r-coat", "r-table", "r-advice", "r-out"):
        con.execute(
            "UPDATE rule_label SET paper_kind = 'procedure' WHERE rule_ref = ?", (ref,)
        )
    kind = {"kind": "procedure", "known": True, "method": "t", "guess": False}
    doc = it.build_items(con, PAPER, kind, skills=[], cache={})
    rules = {i["rule_version_id"]: i for i in doc["items"]}
    assert (
        "r-out" in rules
    )  # left out by the run ONLY as another equipment type, which a procedure does not have
    assert rules["r-out"]["old_engine_reason"] == "equipment_filter_not_used"
    assert "r-limit-twin" not in rules and doc["rules_left_out"]["stored_repeat"] == 1


def test_the_datasheet_keeps_the_equipment_filter(built):
    assert built[0]["rules_left_out"]["does_not_apply:other_equipment"] == 1


def test_no_old_engine_run_gives_checklist_items_only(con):
    doc = it.build_items(con, "doc_never_reviewed", KIND, skills=[SKILL], cache={})
    assert doc["old_engine_run"] is None and doc["counts"] == {"skill": 3, "rule": 0}


def test_requirement_rows_chosen_by_the_caller_need_no_old_engine_run(con):
    cur = con.cursor()
    cur.row_factory = sqlite3.Row
    rows = [
        dict(r)
        for r in cur.execute(
            "SELECT * FROM standard_requirements WHERE id IN ('r-limit', 'r-coat')"
        )
    ]
    doc = it.build_items(
        con, "doc_never_reviewed", KIND, skills=[], cache={}, requirement_rows=rows
    )
    assert {i["rule_version_id"] for i in doc["items"]} == {
        "r-limit",
        "r-coat",
    } and doc["old_engine_run"] is None


def test_the_callers_connection_keeps_its_row_factory(con):
    before = con.row_factory
    it.build_items(con, PAPER, KIND, skills=[SKILL], cache={})
    assert con.row_factory is before


def _eq_label(con, ref, state, general=0, typ=None, fam=None):
    cols = {"source": "requirement", "rule_ref": ref, "equip_state": state, "equip_general": general, "equip_type": typ,
            "equip_family": fam, "labelled_at": "t", "model_a": s.MODEL_A, "model_b": s.MODEL_B,
            "prompt_version": "rule-equip-v1", "list_sha": "c" * 64}  # fmt: skip
    con.execute(
        f"INSERT INTO rule_equipment_label ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        tuple(cols.values()),
    )


def test_the_equipment_filter_only_removes_rules_and_is_counted_and_off_keeps_the_old_list(
    con,
):
    from app import rule_equipment as REQ

    REQ.create_tables(con)
    con.execute(
        "CREATE TABLE document_classification (document_id TEXT, equipment_type TEXT, title TEXT)"
    )
    con.execute(
        "INSERT INTO document_classification VALUES (?, 'Pressure Safety Valve', NULL)",
        (PAPER,),
    )
    _eq_label(con, "r-limit", "agreed", general=1)
    _eq_label(
        con, "r-coat", "agreed", typ="pump", fam="rotating"
    )  # another equipment type: left out
    _eq_label(con, "r-table", "needs_human")  # not agreed: asked as before
    off = it.build_items(con, PAPER, KIND, skills=[], cache={})
    on = it.build_items(con, PAPER, KIND, skills=[], cache={}, equipment_filter="on")
    ids = lambda d: {i["rule_version_id"] for i in d["items"] if i["source"] == "rule"}  # noqa: E731
    assert ids(on) <= ids(off) and ids(off) - ids(on) == {"r-coat"}
    block = on["rule_labels"]
    assert block["counts"]["another_equipment_type"] == {
        "total": 1,
        "by_family": {"rotating": 1},
    }
    assert any(
        x.startswith("another equipment type: 1 rules not asked (rotating 1)")
        for x in block["summary_lines"]
    )
    assert (
        block["equipment"]["paper_usable"]
        and block["equipment"]["asked_by_equipment"]["general"] == 1
    )
    assert off["rule_labels"]["equipment"] is None and "equipment" not in " ".join(
        off["rule_labels"]["summary_lines"]
    )
    assert on["items"][-1]["rule_label"]["equipment"] is not None


def test_the_equipment_filter_without_the_labels_table_asks_every_rule_as_today_and_counts_not_known(
    con,
):
    con.execute(
        "CREATE TABLE document_classification (document_id TEXT, equipment_type TEXT, title TEXT)"
    )
    con.execute(
        "INSERT INTO document_classification VALUES (?, 'Pressure Safety Valve', NULL)",
        (PAPER,),
    )
    off = it.build_items(con, PAPER, KIND, skills=[], cache={})
    on = it.build_items(
        con, PAPER, KIND, skills=[], cache={}, equipment_filter="on"
    )  # no exception
    ids = lambda d: {i["rule_version_id"] for i in d["items"] if i["source"] == "rule"}  # noqa: E731
    assert ids(on) == ids(off) and on["rule_labels"]["equipment"][
        "asked_by_equipment"
    ] == {"equipment_not_known": len(ids(on))}
