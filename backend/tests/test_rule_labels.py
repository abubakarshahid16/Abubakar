"""Rule labels (owner decision 1, 11 Nov 2026): the decision, the tables, the tier. Invented data only; no model."""

from __future__ import annotations

import sqlite3

import pytest

from app import rule_label_schema as schema
from app import rule_labels as rl
from app.db import connect
from tests import r2_security_support as support
from tests import rule_label_support as s

temp_storage = support.temp_storage  # the app's own database for the schema test


def decide(a, b, quote=s.QUOTE_NUM, found=True, **kw):
    return rl.decide(a, b, quote_found=found, quote_text=quote, **kw)


# ---------------------------------------------------------------- the decision


def test_two_different_models_that_agree_approve():
    d = decide(s.answer(s.MODEL_A), s.answer(s.MODEL_B))
    assert (d.state, d.paper_kind, d.field, d.disagreement) == (
        "ai_approved",
        "datasheet",
        "a_field",
        None,
    )
    assert d.reading["values"] == [10.0]


def test_a_disagreement_goes_to_a_human():
    d = decide(
        s.answer(s.MODEL_A),
        s.answer(s.MODEL_B, rd=s.reading(values=(12.0,))),
        quote=s.QUOTE_NUM + " 12",
    )
    assert d.state == "needs_human" and "values" in d.disagreement


def test_different_paper_kinds_go_to_a_human_and_agree_on_nothing():
    d = decide(s.answer(s.MODEL_A), s.answer(s.MODEL_B, kind="procedure"))
    assert (
        d.state == "needs_human"
        and d.disagreement.startswith("kind")
        and d.paper_kind is None
    )


def test_a_quote_not_on_the_page_is_never_approved_even_when_both_agree():
    d = decide(s.answer(s.MODEL_A), s.answer(s.MODEL_B), found=False)
    assert d.state == "quote_not_found" and d.paper_kind is None


def test_empty_readings_cannot_approve_a_rule_that_states_a_quantity():
    empty = s.reading(values=(), comparator="statement", unit=None)
    a, b = s.answer(s.MODEL_A, rd=empty), s.answer(s.MODEL_B, rd=empty)
    d = decide(a, b)
    assert d.state == "needs_human" and "numbers_unread" in d.disagreement
    # the same two bare readings of a rule that states no quantity are fine: the guard is about the quote
    assert decide(a, b, quote=s.QUOTE_TXT).state == "ai_approved"


def test_the_same_model_twice_never_approves_not_even_under_another_date_suffix():
    assert "same_model" in decide(s.answer(s.MODEL_A), s.answer(s.MODEL_A)).disagreement
    assert (
        "same_model"
        in decide(
            s.answer("claude-opus-5-5-20261101"), s.answer(s.MODEL_B)
        ).disagreement
    )
    assert decide(s.answer(""), s.answer(s.MODEL_B)).state == "needs_human"


def test_mixed_or_old_prompt_versions_never_approve():
    a, b = s.answer(s.MODEL_A, prompt="rule-label-v2"), s.answer(s.MODEL_B)
    assert "prompt_version" in decide(a, b).disagreement
    both_old = decide(
        s.answer(s.MODEL_A, prompt="rule-label-v2"),
        s.answer(s.MODEL_B, prompt="rule-label-v2"),
    )
    assert both_old.state == "needs_human" and "prompt_version" in both_old.disagreement


def test_a_quote_on_a_low_confidence_ocr_page_never_approves():
    d = decide(s.answer(s.MODEL_A), s.answer(s.MODEL_B), quote_ocr_low=True)
    assert d.state == "needs_human" and "ocr_low_confidence" in d.disagreement
    assert rl.page_is_low_confidence_ocr(
        {"page_source": "recognised", "page_min_conf": 0.2}
    )
    assert rl.page_is_low_confidence_ocr(
        {"page_source": "recognised", "page_min_conf": None}
    )
    assert not rl.page_is_low_confidence_ocr(
        {"page_source": "recognised", "page_min_conf": 0.99}
    )
    assert not rl.page_is_low_confidence_ocr(
        {"page_source": "native", "page_min_conf": None}
    )


def test_a_number_the_quote_does_not_hold_or_a_unit_it_does_not_write_is_an_invalid_reading():
    bad_number = s.answer(s.MODEL_A, rd=s.reading(values=(99.0,)), valid=False)
    assert "invalid_reading" in decide(bad_number, s.answer(s.MODEL_B)).disagreement
    ok, rd = rl.check_reading({**s.reading(unit="MPa"), "values": [10]}, s.QUOTE_NUM)
    assert ok is False and rd["unit"] == "MPa"  # "MPa" is not written in the quote
    assert rl.check_reading({**s.reading(), "values": [10]}, s.QUOTE_NUM)[0] is True


def test_a_datasheet_rule_with_no_field_goes_to_a_human():
    d = decide(s.answer(s.MODEL_A, field=None), s.answer(s.MODEL_B, field=None))
    assert d.state == "needs_human" and "field" in d.disagreement


def test_one_pass_is_labelled_a_and_pass_b_alone_is_refused():
    assert decide(s.answer(s.MODEL_A), None).state == "labelled_a"
    assert decide(None, None) is None
    with pytest.raises(ValueError):
        decide(None, s.answer(s.MODEL_B))


def _approved_row(**over):
    h = "a" * 64
    row = {
        "state": "ai_approved",
        "a_model": s.MODEL_A,
        "b_model": s.MODEL_B,
        "a_prompt": rl.PROMPT_VERSION,
        "b_prompt": rl.PROMPT_VERSION,
        "a_answer_sha256": h,
        "b_answer_sha256": h,
        "paper_kind": "contract",
        "field": None,
        "quote_page": 1,
        "quote_sha256": rl.quote_hash(s.QUOTE_NUM),
        "reading_json": '{"comparator": "le", "values": [10.0], "unit": "bar", "strength": "shall"}',
    }
    row.update(over)
    return row


@pytest.mark.parametrize(
    "mutate,cause",
    [
        ({"b_model": "claude-sonnet-5-5"}, "same_model"),
        ({"b_prompt": "rule-label-v2"}, "prompt_version"),
        ({"a_answer_sha256": "zz"}, "hash_missing"),
        ({"quote_page": None}, "quote_page_missing"),
        ({"reading_json": None}, "reading_missing"),
        ({"paper_kind": "datasheet", "field": None}, "kind_or_field"),
    ],
)
def test_a_row_that_claims_approval_is_refused_when_any_guard_fails(mutate, cause):
    assert rl.approval_guard(_approved_row(**mutate)) == cause
    assert rl.approval_guard(_approved_row()) is None


def test_the_guard_reproves_the_reading_against_the_stored_quote():
    row = _approved_row()
    assert rl.approval_guard(row, s.QUOTE_NUM) is None
    assert rl.approval_guard(row, s.QUOTE_NUM + " Changed.") == "quote_changed"
    row["reading_json"] = (
        '{"comparator": "le", "values": [11.0], "unit": "bar", "strength": "shall"}'
    )
    assert rl.approval_guard(row, s.QUOTE_NUM) == "value_not_in_quote"


# ---------------------------------------------------------------- the tables


def _row_sql(**over):
    cols = {
        "source": "requirement",
        "rule_ref": "r1",
        "state": "labelled_a",
        "a_model": s.MODEL_A,
        "labelled_at": "2026-11-11T00:00:00Z",
    }
    cols.update(over)
    return (
        f"INSERT INTO rule_label ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        tuple(cols.values()),
    )


def _approved_cols(**over):
    h = "b" * 64
    cols = {
        "state": "ai_approved",
        "a_model": s.MODEL_A,
        "b_model": s.MODEL_B,
        "a_prompt": rl.PROMPT_VERSION,
        "b_prompt": rl.PROMPT_VERSION,
        "a_answer_sha256": h,
        "b_answer_sha256": h,
        "paper_kind": "contract",
        "quote_sha256": h,
        "quote_page": 1,
        "reading_json": '{"comparator": "required", "values": [], "unit": null, "strength": "shall"}',
    }
    cols.update(over)
    return cols


def _tables(conn):
    return {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def test_the_switch_off_creates_no_table_and_the_switch_on_creates_both(monkeypatch):
    conn = connect()
    s.switch(monkeypatch, False)
    schema.ensure_schema()
    assert "rule_label" not in _tables(conn) and "rule_label_event" not in _tables(conn)
    with pytest.raises(schema.SwitchedOff):
        schema.create_tables(conn)
    assert "rule_label" not in _tables(conn)
    s.switch(monkeypatch, True)
    schema.ensure_schema()
    schema.ensure_schema()  # twice does nothing
    assert schema.has_tables(conn)


@pytest.fixture
def labels(tmp_path, monkeypatch):
    s.switch(monkeypatch)
    conn = sqlite3.connect(str(tmp_path / "copy.sqlite"))
    schema.create_tables(conn)
    return conn


def test_the_table_itself_refuses_an_approval_without_two_different_models(labels):
    for bad in (
        {"b_model": s.MODEL_A},
        {"b_prompt": "other"},
        {"b_answer_sha256": None},
        {"quote_sha256": None},
        {"quote_page": None},
        {"paper_kind": None},
        {"paper_kind": "datasheet", "field": None},
    ):
        sql, args = _row_sql(**_approved_cols(**bad))
        with pytest.raises(sqlite3.IntegrityError):
            labels.execute(sql, args)
    sql, args = _row_sql(**_approved_cols())
    labels.execute(sql, args)  # the same row with every guard met is accepted


def test_a_row_is_never_deleted_or_replaced_and_its_key_never_changes(labels):
    labels.execute(*_row_sql())
    with pytest.raises(sqlite3.DatabaseError):
        labels.execute("DELETE FROM rule_label")
    with pytest.raises(sqlite3.DatabaseError):
        labels.execute(
            "INSERT OR REPLACE INTO rule_label (source, rule_ref, state, a_model, labelled_at)"
            " VALUES ('requirement', 'r1', 'labelled_a', 'x', 't')"
        )
    with pytest.raises(sqlite3.DatabaseError):
        labels.execute("UPDATE rule_label SET rule_ref = 'other'")
    assert labels.execute("SELECT COUNT(*) FROM rule_label").fetchone()[0] == 1


def test_a_relabel_appends_an_event_and_the_history_is_append_only(labels):
    labels.execute(*_row_sql())
    labels.execute(
        "UPDATE rule_label SET state = 'needs_human', disagreement = 'kind' WHERE rule_ref = 'r1'"
    )
    events = labels.execute(
        "SELECT event_type, state, previous_state FROM rule_label_event ORDER BY id"
    ).fetchall()
    assert events == [
        ("insert", "labelled_a", None),
        ("relabel", "needs_human", "labelled_a"),
    ]
    with pytest.raises(sqlite3.DatabaseError):
        labels.execute("UPDATE rule_label_event SET state = 'ai_approved'")
    with pytest.raises(sqlite3.DatabaseError):
        labels.execute("DELETE FROM rule_label_event")


# ---------------------------------------------------------------- the tier


@pytest.fixture
def book(tmp_path, monkeypatch):
    s.switch(monkeypatch)
    conn = sqlite3.connect(str(s.make_db(tmp_path / "book.sqlite", with_book=True)))
    conn.row_factory = sqlite3.Row
    schema.create_tables(conn)
    return conn


def _label(conn, state="ai_approved", ref="r1", version="v1", **over):
    if state == "ai_approved":
        cols = _approved_cols(**over)
    elif state == "quote_not_found":
        cols = {"state": state}
    else:
        cols = {
            "state": state,
            "a_model": s.MODEL_A,
            "disagreement": "kind" if state == "needs_human" else None,
        }
    sql, args = _row_sql(rule_ref=ref, rule_version_id=version, **cols)
    conn.execute(sql, args)


def test_an_engineer_or_owner_approval_is_the_tier_and_is_never_written(book):
    before = s.table_hash(book, "rulebook_approval")
    assert rl.usable_tier(book, rule_version_id="v1").tier == "engineer"
    assert (
        s.table_hash(book, "rulebook_approval") == before
    )  # reading it changed nothing
    book.execute(
        "INSERT INTO rulebook_approval VALUES ('a2', 'v1', 'approve', 'u2', '2026-11-02', 'kind_x', 'owner')"
    )
    book.commit()
    mid = s.table_hash(book, "rulebook_approval")
    assert (
        rl.usable_tier(book, rule_version_id="v1").tier == "owner"
    )  # an owner outranks an engineer
    _label(book)
    assert (
        rl.usable_tier(book, requirement_id="r1").tier == "owner"
    )  # a label never lowers or replaces it
    assert s.table_hash(book, "rulebook_approval") == mid != before


def test_an_ai_approved_label_is_the_third_tier(book):
    _label(book, version=None)
    t = rl.usable_tier(book, requirement_id="r1")
    assert (t.tier, t.reason) == ("AI approved", None)
    assert rl.label_for(book, requirement_id="r1")["state"] == "ai_approved"


def test_a_persons_refusal_of_the_exact_version_is_never_overridden_by_an_ai_label(
    book,
):
    book.execute(
        "INSERT INTO rulebook_approval VALUES ('a2', 'v1', 'retire', 'u2', '2026-11-02', NULL, NULL)"
    )
    _label(book)
    t = rl.usable_tier(book, requirement_id="r1")
    assert (t.tier, t.reason) == (None, "person_declined")


def test_an_approval_for_another_equipment_type_is_not_this_types(book):
    assert (
        rl.usable_tier(book, rule_version_id="v1", equipment_type="kind_x").tier
        == "engineer"
    )
    assert (
        rl.usable_tier(book, rule_version_id="v1", equipment_type="kind_y").reason
        == "not_labelled"
    )


@pytest.mark.parametrize(
    "state,reason",
    [
        ("needs_human", "needs_a_human"),
        ("labelled_a", "one_pass_only"),
        ("quote_not_found", "quote_not_found"),
    ],
)
def test_a_rule_that_is_not_usable_says_why_in_one_word(book, state, reason):
    book.execute("DELETE FROM rulebook_approval")
    _label(book, state=state, version=None)
    t = rl.usable_tier(book, requirement_id="r1")
    assert (t.tier, t.reason) == (None, reason)


def test_no_label_and_no_table_are_told_apart(book, tmp_path):
    assert rl.usable_tier(book, requirement_id="nothing").reason == "not_labelled"
    bare = sqlite3.connect(str(tmp_path / "bare.sqlite"))
    assert rl.usable_tier(bare, requirement_id="r1").reason == "no_label_table"
    with pytest.raises(ValueError):
        rl.label_for(bare)


def test_a_label_is_found_by_its_bridged_rule_version(book):
    book.execute("DELETE FROM rulebook_approval")
    _label(book, ref="r1", version="v1")
    assert rl.label_for(book, rule_version_id="v1")["rule_ref"] == "r1"
    assert rl.bridge_map(book) == {("d1", 1, s.QUOTE_NUM): "v1"}


def test_a_tampered_approved_label_is_not_the_third_tier(book):
    book.execute("DELETE FROM rulebook_approval")
    _label(book, version=None)
    # a row the table accepts (different strings) but whose models are one family: the read side refuses it too
    book.execute(
        "UPDATE rule_label SET b_model = 'claude-sonnet-5-5-20261101' WHERE rule_ref = 'r1'"
    )
    t = rl.usable_tier(book, requirement_id="r1")
    assert (t.tier, t.reason) == (None, "label_refused")


@pytest.mark.parametrize(
    "quote,quantity",
    [
        ("The item shall be 5 mm thick.", True),
        ("5 mm minimum is required.", True),
        ("At least 3 stages shall be used.", True),
        ("Parts shall comply with the invented standard 610.", True),
        ("4.2.1 The supplier shall provide a written statement.", False),
        ("(1) The supplier shall provide it.", False),
        ("See Table 5 and Note 2 of the invented annex.", False),
        ("Use the invented item T-29 where listed.", False),
        ("Class 300 items shall be marked.", False),
        ("The supplier shall provide a written statement.", False),
    ],
)
def test_a_quote_states_a_quantity_unless_its_numbers_are_only_references(
    quote, quantity
):
    assert rl.quote_states_a_quantity(quote) is quantity
