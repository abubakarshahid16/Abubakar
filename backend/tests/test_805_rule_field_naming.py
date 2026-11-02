"""#805 plan change 6: name a compiled rule's field from the type's fixed list. Invented text; fake Batch; no real call."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app import (
    db,
    rule_field_naming,
    rulebook_v2,
    rulebook_v2_ingest,
    rulebook_v2_review,
    standards_compiler,
)
from app.config import settings
from app.rule_field_naming import (
    COMPARATOR_DOES_NOT_FIT,
    NOT_ON_DATASHEET,
    ROLE_NOT_ON_TYPE,
    UNIT_DOES_NOT_FIT,
    UNVERIFIED,
    VERIFIED,
)
from tests.test_1584_standards_compiler import (
    DOC,
    LABEL,
    FakeBatches,
    _document,
    _rule,
    lane,  # noqa: F401 - a temporary copy, the compiler's switches on
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import name_rule_fields

TYPE = "Pressure Safety Valve"


@pytest.fixture(autouse=True)
def on(lane, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "rule_field_naming_engine", "claude")
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", True)


def _row(**over):
    return {
        "id": "r1",
        "field": "invented words",
        "comparator": "<=",
        "limit_value": 10.0,
        "unit": "barg",
        "quote": "Invented.",
        **over,
    }


FIELDS = rule_field_naming.fixed_fields(TYPE)


def test_the_list_is_the_checklists_own_and_a_type_with_none_is_refused():
    assert "set_pressure" in FIELDS and "bearing_type" not in FIELDS
    with pytest.raises(rule_field_naming.NoFieldList):
        rule_field_naming.fixed_fields("Invented Gadget")


@pytest.mark.parametrize(
    ("row", "answer", "state", "reason", "role"),
    [
        (
            {},
            {"field_role": "set_pressure", "reason": None},
            VERIFIED,
            None,
            "set_pressure",
        ),
        (
            {},
            {"field_role": "no_such_role", "reason": None},
            UNVERIFIED,
            ROLE_NOT_ON_TYPE,
            None,
        ),
        (
            {"unit": "mm"},
            {"field_role": "set_pressure", "reason": None},
            UNVERIFIED,
            UNIT_DOES_NOT_FIT,
            None,
        ),
        (
            {"unit": "%"},
            {"field_role": "set_pressure", "reason": None},
            UNVERIFIED,
            UNIT_DOES_NOT_FIT,
            None,
        ),
        (
            {},
            {"field_role": "body_material", "reason": None},
            UNVERIFIED,
            COMPARATOR_DOES_NOT_FIT,
            None,
        ),
        (
            {"limit_value": None, "unit": None, "comparator": None},
            {"field_role": "body_material", "reason": None},
            VERIFIED,
            None,
            "body_material",
        ),
        (
            {},
            {"field_role": None, "reason": "installation_or_piping"},
            NOT_ON_DATASHEET,
            "installation_or_piping",
            None,
        ),
        (
            {},
            {"field_role": None, "reason": "free words from a reply"},
            NOT_ON_DATASHEET,
            "another_property_not_listed",
            None,
        ),
        ({}, None, UNVERIFIED, rule_field_naming.REPLY_UNREADABLE, None),
    ],
)
def test_code_verifies_every_reply(row, answer, state, reason, role):
    assert rule_field_naming.verify(_row(**row), answer, FIELDS) == (
        role,
        state,
        reason,
    )


class Roles(FakeBatches):
    """The fake Batch API, answering each rule's question."""

    def __init__(self, answer):
        super().__init__([])
        self.answer = answer

    def batch_results(self, url, *, headers):
        rows = []
        for request in self.created[-1]:
            rows.append(
                {
                    "custom_id": request["custom_id"],
                    "result": {
                        "type": "succeeded",
                        "message": {
                            "model": "claude-haiku-5-5",
                            "stop_reason": "end_turn",
                            "content": [
                                {"type": "text", "text": json.dumps(self.answer)}
                            ],
                            "usage": {"input_tokens": 100, "output_tokens": 20},
                        },
                    },
                }
            )
        return rows


def _compiled():
    _document()
    standards_compiler.compile_standard(
        db.connect(), DOC, LABEL, client=FakeBatches([_rule()]), sleep=lambda _s: None
    )
    return db.connect()


def _stored(conn):
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, field_role, field_role_state, field_role_reason, field_role_prompt, field_role_model,"
            " prompt_version, field, quote FROM compiled_rules"
        )
    ]


def _name(conn, client, **kw):
    return rule_field_naming.name_fields(
        conn, {DOC: LABEL}, TYPE, client=client, sleep=lambda _s: None, **kw
    )


def test_an_estimate_sends_nothing_needs_no_key_and_says_the_cost(monkeypatch):
    conn = _compiled()
    monkeypatch.setattr(settings, "rule_field_naming_engine", "off")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    client = Roles({"field_role": "set_pressure", "reason": None})
    report = _name(conn, client, estimate_only=True)[0]
    assert client.created == [] and report["status"] == "estimate"
    assert report["estimate"]["model"] == "claude-haiku-5-5"
    assert report["estimate"]["requests"] == report["rules"] == 1
    assert report["estimate"]["worst_usd_per_100_rules"] > 0


def test_engine_off_sends_nothing(monkeypatch):
    conn = _compiled()
    monkeypatch.setattr(settings, "rule_field_naming_engine", "off")
    client = Roles({"field_role": "set_pressure", "reason": None})
    with pytest.raises(rule_field_naming.SwitchedOff):
        _name(conn, client)
    assert client.created == []


def test_a_verified_role_is_stored_on_the_row_and_compile_v2_is_left_alone():
    conn = _compiled()
    report = _name(conn, Roles({"field_role": "set_pressure", "reason": None}))[0]
    assert report["stored"][VERIFIED] == 1
    row = _stored(conn)[0]
    assert row["field_role"] == "set_pressure" and row["field_role_state"] == VERIFIED
    assert row["field_role_prompt"] == rule_field_naming.PROMPT_VERSION
    assert row["prompt_version"] == standards_compiler.PROMPT_VERSION
    assert row["field_role_model"] == "claude-haiku-5-5"


def test_a_rule_no_field_answers_is_kept_and_says_why():
    conn = _compiled()
    before = conn.execute("SELECT COUNT(*) FROM compiled_rules").fetchone()[0]
    _name(conn, Roles({"field_role": None, "reason": "test_or_inspection"}))
    rows = _stored(conn)
    assert len(rows) == before
    assert rows[0]["field_role_state"] == NOT_ON_DATASHEET
    assert rows[0]["field_role_reason"] == "test_or_inspection"


def test_run_again_sends_nothing_and_changes_nothing():
    conn = _compiled()
    _name(conn, Roles({"field_role": "set_pressure", "reason": None}))
    first = _stored(conn)
    again = Roles({"field_role": None, "reason": "test_or_inspection"})
    _name(conn, again)
    assert again.created == [] and _stored(conn) == first


def test_an_answer_on_file_is_not_paid_for_again():
    conn = _compiled()
    _name(conn, Roles({"field_role": "set_pressure", "reason": None}))
    with conn:
        conn.execute("UPDATE compiled_rules SET field_role_prompt = NULL")
    second = Roles({"field_role": None, "reason": "test_or_inspection"})
    report = _name(conn, second)[0]
    assert second.created == [] and report["answered"] == 1
    assert _stored(conn)[0]["field_role"] == "set_pressure"


def test_nothing_goes_out_but_the_rule_and_the_list():
    conn = _compiled()
    client = Roles({"field_role": "set_pressure", "reason": None})
    _name(conn, client)
    assert len(client.created) == 1 and len(client.created[0]) == 1
    sent = json.dumps(client.created[0][0])
    assert "set_pressure" in sent and _stored(conn)[0]["quote"] in sent


def test_the_review_and_the_checklist_pair_through_the_stored_role():
    verified = {
        "field": "long invented phrase of a sentence",
        "quote": "Invented.",
        "unit": "barg",
        "field_role": "set_pressure",
        "field_role_state": VERIFIED,
    }
    facts = [
        {
            "id": "f",
            "field_name": "Set pressure",
            "raw_value": "9",
            "raw_unit": "barg",
            "page": 1,
        }
    ]
    assert rulebook_v2_review.pair(verified, facts, TYPE).fact["id"] == "f"
    plain = {k: v for k, v in verified.items() if not k.startswith("field_role")}
    assert (
        rulebook_v2_review.pair(plain, facts, TYPE).reason
        == rulebook_v2_review.NO_SUCH_FIELD
    )


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (NOT_ON_DATASHEET, rulebook_v2_review.NOT_ON_DATASHEET),
        (UNVERIFIED, rulebook_v2_review.ROLE_NOT_VERIFIED),
    ],
)
def test_a_role_not_verified_never_pairs_even_if_the_words_would(state, reason):
    rule = {
        "field": "Set pressure",
        "quote": "Invented.",
        "field_role": "set_pressure",
        "field_role_state": state,
    }
    facts = [
        {
            "id": "f",
            "field_name": "Set pressure",
            "raw_value": "9",
            "raw_unit": "barg",
            "page": 1,
        }
    ]
    found = rulebook_v2_review.pair(rule, facts, TYPE)
    assert found.fact is None and found.reason == reason


def test_an_estimate_writes_nothing():
    conn = _compiled()
    columns = {r[1] for r in conn.execute("PRAGMA table_info(compiled_rules)")}
    _name(conn, Roles({"field_role": None, "reason": None}), estimate_only=True)
    assert {r[1] for r in conn.execute("PRAGMA table_info(compiled_rules)")} == columns
    assert "field_role" not in columns


def test_the_role_reaches_the_rulebook_tables_and_a_person_s_rule(monkeypatch):
    monkeypatch.setattr(settings, "rulebook_v2_enabled", True)
    conn = _compiled()
    _name(conn, Roles({"field_role": "set_pressure", "reason": None}))
    rulebook_v2_ingest.ingest_latest(conn, DOC)
    version = conn.execute("SELECT id FROM rulebook_version").fetchone()[0]
    assert rulebook_v2.field_role_of(conn, version) == {
        "field_role": "set_pressure",
        "field_role_state": VERIFIED,
        "field_role_reason": None,
    }


def test_a_book_on_a_copy_where_the_step_has_not_run_says_nothing(monkeypatch):
    monkeypatch.setattr(settings, "rulebook_v2_enabled", True)
    conn = _compiled()
    rulebook_v2_ingest.ingest_latest(conn, DOC)
    version = conn.execute("SELECT id FROM rulebook_version").fetchone()[0]
    assert rulebook_v2.field_role_of(conn, version)["field_role_state"] is None


def test_the_counts_say_what_pairs_what_is_not_on_a_sheet_and_what_could_decide():
    facts = [
        {
            "id": "f",
            "field_name": "Set pressure",
            "raw_value": "9",
            "raw_unit": "barg",
            "page": 1,
        },
    ]
    good = {
        "field": "long invented phrase",
        "comparator": "<=",
        "limit_value": 10.0,
        "unit": "barg",
        "quote": "The invented set pressure shall not exceed 10 barg.",
        "strength": "shall",
        "field_role": "set_pressure",
        "field_role_state": VERIFIED,
    }
    conditional = {
        **good,
        "condition_text": "where the invented flux capacitor is fitted",
    }
    duty = {**good, "limit_value": None, "comparator": None, "unit": None}
    away = {
        "field": "words",
        "quote": "Invented.",
        "field_role_state": NOT_ON_DATASHEET,
        "field_role_reason": "design_method",
    }
    said = rulebook_v2_review.counts_for_document(
        [good, conditional, duty, away], facts, TYPE
    )
    assert said == {
        "rules": 4,
        "pair_with_a_value": 3,
        "not_on_datasheet": 1,
        "hold_a_figure": 2,
        "could_decide_if_approved": 1,
        "stopped_by": {
            rulebook_v2_review.CONDITION_NOT_VERIFIED: 1,
            rulebook_v2_review.NO_FIGURE: 2,
        },
    }


def test_the_script_estimates_with_one_line_of_counts(tmp_path, monkeypatch):
    _compiled()
    said = []
    monkeypatch.setattr(settings, "rule_field_naming_engine", "off")
    code = name_rule_fields.run(
        settings.db_path, TYPE, [DOC], emit=said.append, estimate_only=True
    )
    assert code == 0 and len(said) == 1
    report = json.loads(said[0])["reports"][0]
    assert report["status"] == "estimate"
    assert _rule()["quote"] not in said[0]
