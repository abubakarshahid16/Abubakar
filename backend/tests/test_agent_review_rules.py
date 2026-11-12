"""Rule choice for the AI reviewer. Invented rows; read only; no model, no network."""

from __future__ import annotations

import sqlite3

import pytest

from app import agent_review_rules as R
from app import agent_review_verdict as V
from app import rule_label_schema as schema
from app import rule_labels
from tests import rule_label_support as s

H = "b" * 64


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
    return c


def label(c, ref, state="ai_approved", kind="datasheet", field=None, **over):
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
            field=field,
            reading_json='{"comparator": "required", "values": [], "unit": null, "strength": "shall"}',
        )
    elif state == "needs_human":
        cols.update(
            b_model=s.MODEL_B, disagreement="values", quote_page=1, quote_sha256=H
        )
    elif state == "quote_not_found":
        cols.update(paper_kind=None)
    cols.update(over)
    c.execute(
        f"INSERT INTO rule_label ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        tuple(cols.values()),
    )


def asked(c, ref, kind="datasheet", known=True, **kw):
    return R.decide_rule(c, ref, kind, known, **kw)


def test_a_rule_is_asked_only_when_its_kind_is_the_papers_and_its_tier_is_usable(conn):
    label(conn, "ok")
    label(conn, "other", kind="procedure")
    label(conn, "human", state="needs_human")
    label(conn, "nofind", state="quote_not_found")
    label(conn, "onepass", state="labelled_a")
    got = {
        r: asked(conn, r)
        for r in ("ok", "other", "human", "nofind", "onepass", "unlabelled")
    }
    assert (got["ok"]["ask"], got["ok"]["tier"]) == (True, "AI approved")
    assert (
        got["other"]["ask"],
        got["other"]["reason"],
        got["other"]["needs_kind"],
    ) == (False, R.ANOTHER_PAPER, "procedure")
    assert got["human"]["reason"] == R.NEEDS_HUMAN
    assert got["nofind"]["reason"] == R.QUOTE_NOT_FOUND
    assert (
        got["onepass"]["reason"] == R.NOT_LABELLED
        and got["unlabelled"]["reason"] == R.NOT_LABELLED
    )
    assert not any(
        got[k]["ask"] for k in ("other", "human", "nofind", "onepass", "unlabelled")
    )


def test_a_rule_of_another_kind_is_never_asked_whatever_its_tier_kind_mismatch(conn):
    """Kind mismatch is never asked: not an AI approved one, not an engineer approved one, not an unapproved one."""
    label(conn, "ai", kind="contract")
    label(conn, "eng", kind="contract", state="needs_human")
    conn.execute(
        "INSERT INTO rulebook_approval VALUES ('a1', 'v-eng', 'approve', 'u1', '2026-11-01', NULL, 'engineer')"
    )
    label(conn, "unap", kind="drawing", state="needs_human")
    for ref in ("ai", "eng", "unap"):
        for mode in ("off", "both"):
            out = asked(conn, ref, ask_unapproved=mode)
            assert out["ask"] is False and out["reason"] == R.ANOTHER_PAPER


def test_an_unknown_paper_kind_asks_no_rule_and_says_so(conn):
    label(conn, "ok")
    for kind, known in ((None, True), ("", True), ("datasheet", False)):
        out = asked(conn, "ok", kind, known)
        assert out["ask"] is False and out["reason"] == R.KIND_UNKNOWN
    rows = [{"id": "ok", "item_id": "R-ok"}]
    kept, left, _ = R.filter_rows(conn, rows, None, False)
    assert kept == [] and left[0]["reason"] == R.KIND_UNKNOWN
    counts = R.count_left_out(left)
    assert counts[R.KIND_UNKNOWN] == 1
    assert R.summary_lines(counts, None, False)[0].startswith(
        "paper kind unknown: 1 rules NOT asked"
    )


def test_engineer_and_owner_approvals_make_a_needs_human_rule_usable_and_a_refusal_blocks_an_ai_one(
    conn,
):
    label(conn, "h1", state="needs_human")
    label(conn, "h2", state="needs_human")
    label(conn, "ai")
    conn.execute(
        "INSERT INTO rulebook_approval VALUES ('a1', 'v-h1', 'approve', 'u1', '2026-11-01', 'kind_x', 'engineer')"
    )
    conn.execute(
        "INSERT INTO rulebook_approval VALUES ('a2', 'v-h2', 'approve', 'u1', '2026-11-01', 'kind_x', 'owner')"
    )
    conn.execute(
        "INSERT INTO rulebook_approval VALUES ('a3', 'v-ai', 'retire', 'u1', '2026-11-02', NULL, NULL)"
    )
    assert (asked(conn, "h1")["ask"], asked(conn, "h1")["tier"]) == (True, "engineer")
    assert asked(conn, "h2")["tier"] == "owner"
    declined = asked(conn, "ai")
    assert declined["ask"] is False and declined["reason"] == R.NEEDS_HUMAN


def test_every_left_out_rule_is_counted_never_dropped_silently(conn):
    label(conn, "ok")
    label(conn, "other", kind="procedure")
    label(conn, "other2", kind="procedure")
    label(conn, "human", state="needs_human", disagreement="values,unit")
    label(conn, "nofind", state="quote_not_found")
    rows = [
        {"id": r, "item_id": f"R-{r}", "standard": "Book", "clause": "1"}
        for r in ("ok", "other", "other2", "human", "nofind", "none")
    ]
    kept, left, why = R.filter_rows(conn, rows, "datasheet")
    assert [k["id"] for k in kept] == ["ok"] and set(why) == {"ok"}
    assert len(kept) + len(left) == len(rows)
    counts = R.count_left_out(left)
    assert counts[R.ANOTHER_PAPER] == {"total": 2, "by_kind": {"procedure": 2}}
    assert (
        counts[R.NEEDS_HUMAN],
        counts[R.QUOTE_NOT_FOUND],
        counts[R.NOT_LABELLED],
    ) == (1, 1, 1)
    assert counts["needs_a_human_by_disagreement"] == {"unit": 1, "values": 1}
    lines = R.summary_lines(counts, "datasheet")
    assert lines[0] == "needs another paper: 2 rules (procedure 2)"
    assert (
        lines[1]
        == "rules not asked: needs a human 1, quote not found 1, not labelled yet 1"
    )


@pytest.mark.parametrize(
    "over,asked_flag",
    [
        ({}, True),
        ({"disagreement": "values,unit"}, True),
        ({"disagreement": "ocr_low_confidence"}, False),
        ({"disagreement": "values,unreadable_quote"}, False),
        (
            {"paper_kind": None},
            False,
        ),  # the two models did not agree on a kind: never "both"
        ({"paper_kind": "procedure"}, False),
        ({"quote_page": None}, False),  # the quote was not found
    ],
)
def test_the_not_ai_approved_tier_in_mode_both(conn, over, asked_flag):
    label(conn, "u", state="needs_human", **over)
    out = asked(conn, "u", ask_unapproved="both")
    assert out["ask"] is asked_flag
    if asked_flag:
        assert out["tier"] == V.TIER_NOT_APPROVED and out["unapproved_why"]
        assert R.tier_fields(out) == {
            "rule_tier": V.RULE_NOT_APPROVED,
            "rule_unapproved_why": out["unapproved_why"],
        }
    assert asked(conn, "u", ask_unapproved="off")["ask"] is False  # off: never


def test_mode_both_never_asks_quote_not_found_unlabelled_one_pass_or_a_declined_rule(
    conn,
):
    label(conn, "nf", state="quote_not_found")
    label(conn, "one", state="labelled_a")
    label(conn, "dec", state="needs_human")
    conn.execute(
        "INSERT INTO rulebook_approval VALUES ('a1', 'v-dec', 'reject', 'u1', '2026-11-02', NULL, NULL)"
    )
    for ref in ("nf", "one", "dec", "missing"):
        assert asked(conn, ref, ask_unapproved="both")["ask"] is False
    with pytest.raises(ValueError):
        asked(conn, "nf", ask_unapproved="one")


def test_an_approved_rule_is_unaffected_by_the_unapproved_mode(conn):
    label(conn, "ok")
    assert asked(conn, "ok", ask_unapproved="both")["tier"] == "AI approved"


def test_a_tampered_ai_label_is_not_asked(conn):
    label(conn, "ok")
    assert asked(conn, "ok")["ask"] is True
    conn.execute(
        "UPDATE rule_label SET field = 'a_field_not_on_the_list' WHERE rule_ref = 'ok'"
    )  # the read guard refuses it
    out = asked(conn, "ok")
    assert out["ask"] is False and out["reason"] == R.NEEDS_HUMAN


def test_the_quote_bridge_is_off_a_sibling_rules_label_is_never_used(conn):
    label(
        conn, "sib", source="rulebook", rule_ref="sib"
    )  # a rule-book row; the requirement itself has no label
    out = asked(conn, "req-other")
    assert out["ask"] is False and out["reason"] == R.NOT_LABELLED


def test_no_label_table_asks_nothing_and_says_not_labelled():
    bare = sqlite3.connect(":memory:")
    out = R.decide_rule(bare, "r1", "datasheet")
    assert (out["ask"], out["reason"]) == (False, R.NOT_LABELLED)


def test_the_tiers_are_read_only(conn):
    label(conn, "h", state="needs_human")
    conn.execute(
        "INSERT INTO rulebook_approval VALUES ('a1', 'v-h', 'approve', 'u1', '2026-11-01', NULL, 'engineer')"
    )
    before = s.table_hash(conn, "rulebook_approval")
    asked(conn, "h", ask_unapproved="both")
    assert s.table_hash(conn, "rulebook_approval") == before


def test_rules_used_lists_asked_left_out_and_not_held_without_any_text(conn):
    label(conn, "ok")
    label(conn, "u", state="needs_human")
    rows = [
        {"id": r, "item_id": f"R-{r}", "standard": "Book"} for r in ("ok", "u", "gone")
    ]
    kept, left, why = R.filter_rows(conn, rows, "datasheet", ask_unapproved="both")
    items = [
        {
            "source": "rule",
            "rule_version_id": k["id"],
            "standard": "Book",
            "clause": "4",
            "rule_label": R.rule_label_of(why[k["id"]]),
            **R.tier_fields(why[k["id"]]),
        }
        for k in kept
    ]
    block = R.label_block(
        R.count_left_out(left),
        left,
        {"kind": "datasheet", "known": True},
        [{"rule_book": "Book Z", "why": "cited by the paper"}],
        1,
    )
    used = R.rules_used([*items, {"source": "skill"}], block)
    assert used["asked_by_tier"] == {"AI approved": 1, "not AI approved": 1}
    assert [a["rule_id"] for a in used["asked"]] == ["ok", "u"] and used["asked"][1][
        "not_approved_why"
    ] == "values"
    assert used["left_out"][0]["reason"] == R.NOT_LABELLED
    assert used["rule_books_not_held"] == [
        {"rule_book": "Book Z", "why": "cited by the paper"}
    ]
    assert block["summary_lines"][-1].startswith(
        "rules asked though not AI approved: 1"
    )
    assert not any("quote_text" in a for a in used["asked"])  # ids and references only


# ---------------------------------------------------------------- F2: a checklist item for the paper's own equipment type

GOVERNING = {"equipment_types": {"type_x": ["STD-X-1"], "type_y": ["STD-Y-1"]}}


def skill(item_id, *standards):
    return {
        "item_id": item_id,
        "source": "skill",
        "clause_refs": [{"standard": n} for n in standards],
    }


def test_a_checklist_item_is_asked_only_for_the_papers_own_equipment_type(conn):
    items = [
        skill("S-x", "STD-X-1"),
        skill("S-y", "STD-Y-1"),
        skill("S-none"),
        skill("S-both", "STD-X-1", "STD-Y-1"),
    ]
    kept, dropped = R.filter_skill_items(conn, items, {"type_x"}, GOVERNING)
    assert [i["item_id"] for i in kept] == ["S-x", "S-none", "S-both"]
    assert dropped == [{"item_id": "S-y", "reason": R.ANOTHER_TYPE}]


def test_a_paper_of_unknown_type_gets_no_type_specific_checklist_item_and_the_crs_says_so(
    conn,
):
    items = [skill("S-x", "STD-X-1"), skill("S-none")]
    kept, dropped = R.filter_skill_items(conn, items, set(), GOVERNING)
    assert [i["item_id"] for i in kept] == ["S-none"]
    assert dropped == [{"item_id": "S-x", "reason": R.TYPE_UNKNOWN}]
    block = {"summary_lines": []}
    R.add_skill_block(block, dropped)
    assert block["summary_lines"] == [
        "equipment type unknown: 1 type-specific checklist items NOT asked"
    ]
    assert block["skills_left_out"][R.TYPE_UNKNOWN] == 1
    block2 = {}
    R.add_skill_block(block2, [{"item_id": "S-y", "reason": R.ANOTHER_TYPE}])
    assert block2["summary_lines"] == [
        "checklist items for another equipment type: 1 not asked"
    ]


def test_a_checklist_item_is_asked_only_for_a_paper_of_its_own_kind():
    assert R.skill_fits("pump_datasheet", "datasheet") and R.skill_fits(
        "datasheet", "datasheet"
    )
    assert not R.skill_fits("pump_datasheet", "procedure") and not R.skill_fits(
        "pump_datasheet", None
    )
    assert not R.skill_fits("pump_datasheets", "datasheet")


def test_the_papers_equipment_type_is_empty_when_nothing_is_stored(conn):
    conn.execute(
        "CREATE TABLE document_classification (document_id TEXT, equipment_type TEXT, title TEXT, discipline TEXT)"
    )
    assert R.paper_equipment_types(conn, "d1") == set()
    assert (
        R.paper_equipment_types(sqlite3.connect(":memory:"), "d1") == set()
    )  # no table at all


def test_missing_rule_books_are_the_cited_and_needed_ones_the_library_lacks(conn):
    conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT)")
    conn.execute(
        "CREATE TABLE standard_requirements (id TEXT PRIMARY KEY, standard_document_id TEXT)"
    )
    conn.execute("CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT)")
    conn.execute("INSERT INTO documents VALUES ('d-held', 'ABC-100.pdf')")
    conn.execute("INSERT INTO standard_requirements VALUES ('r1', 'd-held')")
    conn.execute(
        "INSERT INTO pages VALUES ('paper', 1, 'The design shall comply with ZZQ-777 and ABC-100.')"
    )
    got = R.missing_rule_books(
        conn,
        "paper",
        "type_x",
        {"equipment_types": {"type_x": ["ABC-100", "NEED-900"]}},
    )
    names = {b["rule_book"]: b["why"] for b in got}
    assert "NEED-900" in names and names["NEED-900"].startswith(
        "needed by the paper kind or type"
    )
    assert not any("ABC-100" in n for n in names)  # a held book is not listed


def test_the_tier_lookup_reads_the_label_table_now_and_final_cap_uses_it(conn):
    from app import agent_review_wording as W

    label(conn, "ok")
    label(conn, "u", state="needs_human")
    lookup = R.tier_lookup(conn, "datasheet")
    assert lookup({"rule_version_id": "ok"}) == "AI approved"
    assert (
        lookup({"rule_version_id": "u"}) is None
        and lookup({"rule_version_id": "gone"}) is None
    )
    both = R.tier_lookup(conn, "datasheet", ask_unapproved="both")
    assert (
        both({"rule_version_id": "u"}) == V.TIER_NOT_APPROVED
    )  # asked, but not a usable tier
    stored = {
        "item_id": "R-ok",
        "source": "rule",
        "verdict": "Fail",
        "ai_verdict": "Fail",
        "decided_by": "decided by code",
    }
    item = {
        "item_id": "R-ok",
        "source": "rule",
        "rule_version_id": "ok",
        "rule_label": {"tier": "AI approved"},
    }
    assert W.final_cap(stored, item, lookup)["verdict"] == "Fail"
    conn.execute(
        "UPDATE rule_label SET paper_kind = 'procedure' WHERE rule_ref = 'ok'"
    )  # moved to another kind since
    assert W.final_cap(stored, item, lookup)["verdict"] == "Query"


def test_an_ai_approved_label_that_carries_a_disagreement_is_never_asked_as_approved():
    """#1744's table refuses this row today; a table made another way must not break it (doubt means not approved)."""
    bare = sqlite3.connect(":memory:")
    bare.row_factory = sqlite3.Row
    bare.execute(
        "CREATE TABLE rule_label (source TEXT, rule_ref TEXT, rule_version_id TEXT, paper_kind TEXT, field TEXT, state TEXT,"
        " disagreement TEXT, a_model TEXT, a_prompt TEXT, a_answer_sha256 TEXT, b_model TEXT, b_prompt TEXT,"
        " b_answer_sha256 TEXT, reading_json TEXT, quote_page INTEGER, quote_sha256 TEXT, quote_recovery TEXT,"
        " a_answer_json TEXT, b_answer_json TEXT, labelled_at TEXT)"
    )
    row = {
        "source": "requirement",
        "rule_ref": "x",
        "rule_version_id": "v-x",
        "paper_kind": "datasheet",
        "state": "ai_approved",
        "a_model": s.MODEL_A,
        "b_model": s.MODEL_B,
        "a_prompt": rule_labels.PROMPT_VERSION,
        "b_prompt": rule_labels.PROMPT_VERSION,
        "a_answer_sha256": H,
        "b_answer_sha256": H,
        "quote_sha256": H,
        "quote_page": 1,
        "labelled_at": "2026-11-11",
        "reading_json": '{"comparator": "required", "values": [], "unit": null, "strength": "shall"}',
    }
    for ref, disagreement in (("clean", None), ("x", "values")):
        cols = {
            **row,
            "rule_ref": ref,
            "rule_version_id": f"v-{ref}",
            "disagreement": disagreement,
        }
        bare.execute(
            f"INSERT INTO rule_label ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            tuple(cols.values()),
        )
    assert (
        R.decide_rule(bare, "clean", "datasheet")["tier"] == "AI approved"
    )  # the same row without the text is asked
    for mode in ("off", "both"):
        out = R.decide_rule(bare, "x", "datasheet", ask_unapproved=mode)
        assert (
            out["ask"] is False
            and out["reason"] == R.NEEDS_HUMAN
            and out["tier"] is None
        )


# ---------------------------------------------------------------- the equipment filter: only ever REMOVES rules

import json  # noqa: E402

from app import rule_equipment as REQ  # noqa: E402

TAX = {
    "families": [
        {"id": "rotating", "name": "Rotating", "types": [
            {"id": "pump", "name": "Pump (kind not stated)", "parts": [], "synonyms": []},
            {"id": "centrifugal_pump", "name": "Centrifugal pump", "parts": [], "synonyms": [], "also_applies": ["pump"]},
            {"id": "dosing_pump", "name": "Dosing pump", "parts": [], "synonyms": [], "also_applies": ["pump"]},
            {"id": "compressor", "name": "Compressor", "parts": [], "synonyms": []}]},
        {"id": "pressure_relief", "name": "Relief", "types": [
            {"id": "relief_valve", "name": "Relief valve", "parts": [], "synonyms": ["PSV"]}]},
    ],
    "general": "applies to all equipment", "not_equipment": [], "part_ids_shared": "x",
}  # fmt: skip
MAP = {
    "map": {"pump": "pump", "relief valve": "relief_valve", "compressor": "compressor"},
    "unmapped": [],
}


@pytest.fixture
def tax(tmp_path):
    path = tmp_path / "tax.json"
    path.write_text(json.dumps(TAX))
    return REQ.Taxonomy.load(path)


def _paper(tax, *types, named=True):
    ids = tax.expand(set(types))
    return R.PaperEquipment(
        frozenset(ids),
        frozenset(tax.type_family[t] for t in types),
        named,
        (),
        "read",
        frozenset(ids),
    )


def _erow(state="agreed", general=0, type_=None, family=None):
    return {
        "equip_state": state,
        "equip_general": general,
        "equip_type": type_,
        "equip_family": family,
    }


def test_the_equipment_rules(tax):
    cp = _paper(
        tax, "centrifugal_pump"
    )  # a centrifugal pump paper also counts as a pump
    d = lambda row, eq=cp: R.equipment_decision(row, eq, tax)  # noqa: E731
    assert d(_erow(general=1))[:2] == (True, "general")
    assert d(_erow(type_="centrifugal_pump"))[:2] == (True, "same_equipment")
    assert d(_erow(type_="pump"))[:2] == (
        True,
        "same_equipment",
    )  # the paper's type is listed under the rule's type
    assert d(_erow(family="rotating"))[:2] == (
        True,
        "same_equipment",
    )  # a whole-family rule
    assert d(_erow(type_="dosing_pump")) == (False, R.ANOTHER_EQUIPMENT, "rotating")
    assert d(_erow(type_="relief_valve")) == (
        False,
        R.ANOTHER_EQUIPMENT,
        "pressure_relief",
    )
    assert d(_erow(family="pressure_relief")) == (
        False,
        R.ANOTHER_EQUIPMENT,
        "pressure_relief",
    )
    # the reverse is NOT taken: a generic pump paper does not get a centrifugal-pump rule
    assert d(_erow(type_="centrifugal_pump"), _paper(tax, "pump")) == (
        False,
        R.ANOTHER_EQUIPMENT,
        "rotating",
    )
    for state in (
        "needs_human",
        "unlabelled",
        None,
    ):  # doubt: an equipment label that is not agreed is asked as today
        assert d(_erow(state=state, type_="relief_valve"))[:2] == (
            True,
            "equipment_not_known",
        )
    assert d(_erow())[:2] == (
        True,
        "equipment_not_known",
    )  # agreed but names nothing: no ground to remove it


def test_a_paper_that_names_no_equipment_gets_only_general_rules_and_rules_of_unknown_equipment(
    tax,
):
    none = R.PaperEquipment(frozenset(), frozenset(), False, ())
    assert R.equipment_decision(_erow(general=1), none, tax)[:2] == (True, "general")
    assert R.equipment_decision(_erow(state="needs_human", type_="pump"), none, tax)[
        :2
    ] == (True, "equipment_not_known")
    assert R.equipment_decision(_erow(type_="pump"), none, tax) == (
        False,
        R.NO_EQUIPMENT,
        "rotating",
    )
    assert R.equipment_decision(_erow(family="rotating"), none, tax) == (
        False,
        R.NO_EQUIPMENT,
        "rotating",
    )


def test_the_family_mode_leaves_out_only_another_family_and_on_is_an_alias_of_type(tax):
    cp = _paper(tax, "centrifugal_pump")
    fam = lambda row: R.equipment_decision(row, cp, tax, "family")  # noqa: E731
    assert fam(_erow(type_="dosing_pump"))[:2] == (
        True,
        "same_equipment",
    )  # a sibling type of the same family is asked
    assert fam(_erow(type_="relief_valve")) == (
        False,
        R.ANOTHER_EQUIPMENT,
        "pressure_relief",
    )
    assert R.equipment_decision(_erow(type_="dosing_pump"), cp, tax, "type") == (
        False,
        R.ANOTHER_EQUIPMENT,
        "rotating",
    )
    none = R.PaperEquipment(frozenset(), frozenset(), False, ())
    assert R.equipment_decision(_erow(type_="pump"), none, tax, "family") == (
        False,
        R.NO_EQUIPMENT,
        "rotating",
    )
    assert (
        R.norm_mode("on") == "type"
        and R.norm_mode("type") == "type"
        and R.norm_mode("family") == "family"
    )
    assert R.norm_mode("off") is None and R.norm_mode(None) is None
    with pytest.raises(ValueError):
        R.norm_mode("sideways")


def _classified(conn, rows):
    conn.execute(
        "CREATE TABLE document_classification (document_id TEXT, equipment_type TEXT, title TEXT)"
    )
    conn.executemany("INSERT INTO document_classification VALUES (?,?,?)", rows)


def test_the_paper_equipment_is_read_by_the_app_and_mapped_by_the_data_file(conn, tax):
    _classified(conn, [("cp", "Centrifugal Pump", None), ("psv", "Pressure Safety Valve", None), ("none", None, None),
                       ("unmapped", "Heat Exchanger", None)])  # fmt: skip
    cp = R.paper_equipment(conn, "cp", tax, MAP)
    assert cp.types == {"centrifugal_pump", "pump"} and cp.usable
    assert R.paper_equipment(conn, "psv", tax, MAP).types == {"relief_valve"}
    none = R.paper_equipment(conn, "none", tax, MAP)
    assert not none.usable and not none.named
    um = R.paper_equipment(conn, "unmapped", tax, MAP)
    assert (
        not um.usable and um.named
    )  # the reader found equipment the mapping does not know


def test_a_mapping_file_may_name_equipment_a_type_is_also_read_against(conn, tax):
    _classified(conn, [("p", "Pressure Safety Valve", None)])
    base = R.paper_equipment(conn, "p", tax, MAP)
    rel = R.paper_equipment(
        conn, "p", tax, {**MAP, "related": {"relief_valve": ["compressor"]}}
    )
    assert base.types == {"relief_valve"} and rel.types == {
        "relief_valve",
        "compressor",
    }
    assert rel.families == {"pressure_relief", "rotating"}
    assert R.equipment_decision(_erow(type_="compressor"), base, tax)[0] is False
    assert R.equipment_decision(_erow(type_="compressor"), rel, tax)[0] is True


def _equipment_world(conn, tax, paper_type, labels):
    """AI approved datasheet rules r<i>; `labels`: (ref, state, general, type, family) rows of the equipment table."""
    _classified(conn, [("paper", paper_type, None)])
    REQ.create_tables(conn)
    for ref, state, general, typ, fam in labels:
        label(conn, ref)
        if state is not None:
            cols = {"source": "requirement", "rule_ref": ref, "equip_state": state, "equip_general": general,
                    "equip_type": typ, "equip_family": fam, "labelled_at": "t"}  # fmt: skip
            if state == "agreed":
                cols.update(
                    model_a=s.MODEL_A,
                    model_b=s.MODEL_B,
                    prompt_version="rule-equip-v1",
                    list_sha="c" * 64,
                )
            else:
                cols.update(equip_disagreement="type")
            conn.execute(
                f"INSERT INTO rule_equipment_label ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                tuple(cols.values()),
            )
    return R.EquipmentCtx(R.paper_equipment(conn, "paper", tax, MAP), tax, MAP, "type")


def test_the_filter_only_removes_rules_counts_by_family_and_says_so_on_the_crs(
    conn, tax
):
    labels = [("r1", "agreed", 1, None, None), ("r2", "agreed", 0, "relief_valve", "pressure_relief"),
              ("r3", "needs_human", 0, "relief_valve", "pressure_relief"), ("r4", "agreed", 0, "pump", "rotating"),
              ("r5", None, 0, None, None)]  # fmt: skip
    ctx = _equipment_world(conn, tax, "Centrifugal Pump", labels)
    rows = [{"id": r[0], "item_id": f"R-{r[0]}", "standard": "Book"} for r in labels]
    off_kept, _, _ = R.filter_rows(conn, rows, "datasheet")
    kept, left, why = R.filter_rows(conn, rows, "datasheet", equipment=ctx)
    assert {k["id"] for k in off_kept} - {k["id"] for k in kept} == {
        "r2"
    }  # it only removes
    assert {k["id"] for k in kept} <= {k["id"] for k in off_kept}
    counts = R.count_left_out(left)
    assert counts[R.ANOTHER_EQUIPMENT] == {
        "total": 1,
        "by_family": {"pressure_relief": 1},
    }
    block = R.label_block(
        counts,
        left,
        {"kind": "datasheet", "known": True},
        [],
        0,
        R.equipment_block(ctx, why),
    )
    assert (
        "another equipment type: 1 rules not asked (pressure relief 1)"
        in block["summary_lines"]
    )
    assert block["equipment"]["asked_by_equipment"] == {
        "general": 1,
        "equipment_not_known": 2,
        "same_equipment": 1,
    }
    assert (
        block["equipment"]["paper_types"] == ["centrifugal_pump", "pump"]
        and block["equipment"]["paper_usable"]
    )
    items = [
        {
            "source": "rule",
            "rule_version_id": k["id"],
            "rule_label": R.rule_label_of(why[k["id"]]),
        }
        for k in kept
    ]
    used = R.rules_used(items, block)
    assert (
        used["equipment"]["paper_families"] == ["rotating"]
        and used["asked"][0]["equipment"]["equip_state"] == "agreed"
    )
    assert (
        left[0]["reason"] == R.ANOTHER_EQUIPMENT
        and left[0]["equipment_family"] == "pressure_relief"
    )


def test_a_paper_that_names_no_equipment_loses_the_named_equipment_rules_and_says_so(
    conn, tax
):
    labels = [
        ("r1", "agreed", 1, None, None),
        ("r2", "agreed", 0, "pump", "rotating"),
        ("r3", "unlabelled", 0, None, None),
    ]
    ctx = _equipment_world(conn, tax, None, labels)
    kept, left, _ = R.filter_rows(
        conn,
        [{"id": r[0], "item_id": r[0]} for r in labels],
        "datasheet",
        equipment=ctx,
    )
    assert {k["id"] for k in kept} == {"r1", "r3"}
    counts = R.count_left_out(left)
    assert counts[R.NO_EQUIPMENT] == 1
    assert any(
        x.startswith("the paper names no equipment: 1 rules")
        for x in R.summary_lines(counts, "datasheet")
    )


def test_the_filter_never_asks_a_rule_the_label_decision_left_out(conn, tax):
    labels = [("r1", "agreed", 1, None, None)]
    ctx = _equipment_world(conn, tax, "Centrifugal Pump", labels)
    label(conn, "wrongkind", kind="procedure")
    got = R.decide_rule(conn, "wrongkind", "datasheet", equipment=ctx)
    assert (
        got["ask"] is False
        and got["reason"] == R.ANOTHER_PAPER
        and "equipment_why" not in got
    )
    assert (
        R.decide_rule(conn, "r1", "datasheet", equipment=ctx)["equipment_why"]
        == "general"
    )


def test_a_missing_equipment_table_means_equipment_not_known_for_every_rule_never_an_exception(
    conn,
):
    assert R.load_equipment(conn, "paper", "off") is None
    _classified(conn, [("paper", "Pressure Safety Valve", None)])
    ctx = R.load_equipment(
        conn, "paper", "on"
    )  # the table is not there: no error; the real taxonomy and mapping data files
    assert (
        ctx.mode == "type"
        and ctx.eq.usable
        and R.load_equipment(conn, "paper", "family").mode == "family"
    )
    label(conn, "r1")
    got = R.decide_rule(conn, "r1", "datasheet", equipment=ctx)
    assert got["ask"] is True and got["equipment_why"] == "equipment_not_known"
    kept, _left, why = R.filter_rows(
        conn, [{"id": "r1", "item_id": "R-1"}], "datasheet", equipment=ctx
    )
    assert len(kept) == 1 and R.equipment_block(ctx, why)["asked_by_equipment"] == {
        "equipment_not_known": 1
    }


def test_checklist_items_use_the_same_taxonomy_notion_of_same_equipment(conn, tax):
    ctx = R.EquipmentCtx(_paper(tax, "centrifugal_pump"), tax, MAP, "type")
    gov = {"equipment_types": {"pump": ["STD-P-1"], "relief valve": ["STD-V-1"]}}
    items = [skill("S-A", "STD-P-1"), skill("S-B", "STD-V-1"), skill("S-N")]
    kept, dropped = R.filter_skill_items(conn, items, {"pump"}, gov, ctx)
    assert [i["item_id"] for i in kept] == ["S-A", "S-N"] and dropped == [
        {"item_id": "S-B", "reason": R.ANOTHER_TYPE}
    ]
    none = R.EquipmentCtx(
        R.PaperEquipment(frozenset(), frozenset(), False, ()), tax, MAP, "type"
    )
    kept, dropped = R.filter_skill_items(conn, items, set(), gov, none)
    assert [i["item_id"] for i in kept] == ["S-N"] and {
        d["reason"] for d in dropped
    } == {R.TYPE_UNKNOWN}


# ---------------------------------------------------------------- R11: the equipment decide order and the three true sentences


def _state(tax, state):
    return R.PaperEquipment(
        frozenset(), frozenset(), state in ("unmapped",), (), state, frozenset()
    )


@pytest.mark.parametrize(
    "state,reason",
    [
        ("none", R.NO_EQUIPMENT),
        ("unmapped", R.NOT_IN_LIST),
        ("unreadable", R.UNREADABLE),
    ],
)
def test_when_the_papers_equipment_is_not_usable_only_a_rule_that_names_an_equipment_is_removed(
    tax, state, reason
):
    eq = _state(tax, state)
    d = lambda row: R.equipment_decision(row, eq, tax)  # noqa: E731
    assert d(_erow(general=1))[:2] == (True, "general")
    assert d(_erow())[:2] == (
        True,
        "equipment_not_known",
    )  # agreed, general 0, names nothing: asked
    assert d(_erow(state="needs_human", type_="pump"))[:2] == (
        True,
        "equipment_not_known",
    )
    assert d(_erow(type_="pump")) == (False, reason, "rotating")
    assert d(_erow(family="rotating")) == (False, reason, "rotating")


def test_the_paper_equipment_state_is_read_as_none_unmapped_unreadable_or_read(
    conn, tax
):
    _classified(
        conn,
        [
            ("cp", "Centrifugal Pump", None),
            ("none", None, None),
            ("um", "Heat Exchanger", None),
        ],
    )
    assert R.paper_equipment(conn, "cp", tax, MAP).state == "read"
    assert R.paper_equipment(conn, "none", tax, MAP).state == "none"
    um = R.paper_equipment(conn, "um", tax, MAP)
    assert um.state == "unmapped" and um.named and not um.usable


def test_each_paper_equipment_state_gets_its_own_true_sentence_and_family_counts():
    left = [
        {"reason": R.NO_EQUIPMENT, "equipment_family": "rotating"}, {"reason": R.NO_EQUIPMENT, "equipment_family": None},
        {"reason": R.NOT_IN_LIST, "equipment_family": "rotating"}, {"reason": R.UNREADABLE, "equipment_family": "valves"},
        {"reason": R.UNREADABLE, "equipment_family": "valves"},
    ]  # fmt: skip
    counts = R.count_left_out(left)
    assert counts["paper_equipment_left_out_by_family"] == {
        R.NO_EQUIPMENT: {"rotating": 1, "unnamed": 1}, R.NOT_IN_LIST: {"rotating": 1}, R.UNREADABLE: {"valves": 2},
    }  # fmt: skip
    lines = R.summary_lines(counts, "datasheet")
    assert (
        "the paper names no equipment: 2 rules that name an equipment were not asked; only general rules and rules of unknown equipment are asked"
        in lines
    )
    assert (
        "the paper names equipment the equipment list does not know: 1 rules that name an equipment were not asked"
        in lines
    )
    assert (
        "the paper's equipment could not be read: 2 rules that name an equipment were not asked"
        in lines
    )
    only = R.summary_lines(R.count_left_out(left[2:3]), "datasheet")
    assert (
        len(only) == 1 and "names no equipment" not in only[0]
    )  # the unmapped state never says "names no equipment"


def test_the_equipment_block_names_the_state(conn, tax):
    _classified(conn, [("um", "Heat Exchanger", None)])
    ctx = R.EquipmentCtx(R.paper_equipment(conn, "um", tax, MAP), tax, MAP, "type")
    block = R.equipment_block(ctx, {})
    assert (
        block["paper_equipment_state"] == "unmapped"
        and block["paper_named_equipment"]
        and not block["paper_usable"]
    )


GOV = {
    "equipment_types": {
        "pump": ["STD-P-1"],
        "relief valve": ["STD-V-1"],
        "other thing": ["STD-O-1"],
    }
}


def test_an_equipment_mode_can_only_remove_checklist_items_never_add_one(conn, tax):
    items = [
        skill("S-A", "STD-P-1"),
        skill("S-B", "STD-V-1"),
        skill("S-O", "STD-O-1"),
        skill("S-N"),
    ]
    related_map = {
        **MAP,
        "related": {"relief_valve": ["pump"]},
    }  # rules may read a relief-valve paper against a pump
    _classified(conn, [("p", "Pressure Safety Valve", None)])
    eq = R.paper_equipment(conn, "p", tax, related_map)
    assert (
        "pump" in eq.types and "pump" not in eq.core_types
    )  # related applies to rules only
    ctx = R.EquipmentCtx(eq, tax, related_map, "type")
    plain = {"relief valve", "other thing"}
    off, _ = R.filter_skill_items(conn, items, plain, GOV)
    on, dropped = R.filter_skill_items(conn, items, plain, GOV, ctx)
    assert {i["item_id"] for i in on} <= {
        i["item_id"] for i in off
    }  # on is a subset of off
    assert "S-A" not in {
        i["item_id"] for i in on
    }  # the related map never ADDS a pump checklist item
    assert "S-O" in {
        i["item_id"] for i in on
    }  # an unmapped name leaves the plain decision standing
    assert {d["item_id"] for d in dropped} <= {"S-A", "S-B", "S-O"}


def test_a_checklist_item_the_plain_test_dropped_is_never_brought_back(conn, tax):
    items = [skill("S-A", "STD-P-1"), skill("S-B", "STD-V-1")]
    ctx = R.EquipmentCtx(_paper(tax, "centrifugal_pump"), tax, MAP, "type")
    off, _dropped = R.filter_skill_items(conn, items, {"pump"}, GOV)
    on, _ = R.filter_skill_items(conn, items, {"pump"}, GOV, ctx)
    assert [i["item_id"] for i in off] == ["S-A"] and [i["item_id"] for i in on] == [
        "S-A"
    ]
    off2, _ = R.filter_skill_items(
        conn, items, {"relief valve"}, GOV
    )  # the paper is a relief valve for the plain test
    on2, _ = R.filter_skill_items(
        conn, items, {"relief valve"}, GOV, ctx
    )  # but the taxonomy says it is a pump paper
    assert {i["item_id"] for i in on2} <= {i["item_id"] for i in off2}


def test_the_related_map_never_keeps_a_checklist_item_for_a_related_equipment(
    conn, tax
):
    """The plain test keeps a pump item for this paper; the paper's OWN types do not include a pump, so the filter removes it."""
    related_map = {**MAP, "related": {"relief_valve": ["pump"]}}
    _classified(conn, [("p", "Pressure Safety Valve", None)])
    eq = R.paper_equipment(conn, "p", tax, related_map)
    assert "pump" in eq.types and "pump" not in eq.core_types
    ctx = R.EquipmentCtx(eq, tax, related_map, "type")
    items = [skill("S-A", "STD-P-1"), skill("S-B", "STD-V-1")]
    plain = {"relief valve", "pump"}
    off, _ = R.filter_skill_items(conn, items, plain, GOV)
    on, dropped = R.filter_skill_items(conn, items, plain, GOV, ctx)
    assert [i["item_id"] for i in off] == ["S-A", "S-B"] and [
        i["item_id"] for i in on
    ] == ["S-B"]
    assert dropped == [{"item_id": "S-A", "reason": R.ANOTHER_TYPE}]
    assert R.equipment_decision(_erow(type_="pump"), eq, tax)[:2] == (
        True,
        "same_equipment",
    )  # rules DO use related


def test_summary_line_names_equipment_families_in_words_not_keys():
    counts = {R.ANOTHER_EQUIPMENT: {"total": 4, "by_family": {"pressure_relief": 2, "static": 2}}}
    line = [x for x in R.summary_lines(counts, "datasheet") if x.startswith("another equipment type")][0]
    assert line == "another equipment type: 4 rules not asked (pressure relief 2, static 2)"
    assert "_" not in line
