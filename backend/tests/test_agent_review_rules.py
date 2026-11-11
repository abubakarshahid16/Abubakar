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
