"""Order 124 item 9: a finding's text never pastes a long raw table chunk.

A fact's stored value has no length cap; a reader sometimes stores a whole
table row run together. The finding's sentence (the comment sheet's
Observation) quotes a long value as a marked excerpt ending " …"; a short
value is quoted exactly as before. TEXT ONLY: every verdict is still worked out
from the full value, and the full value stays on the fact. Invented data only;
no model, no socket.
"""

from __future__ import annotations

import pytest

from app import comparison, datasheet_checks, db, stated_value, submittal_review
from app.config import settings

#: A run-together table row, far longer than one value.
ROW = (
    "TRAVEL AT NORMAL FLOW   VALVE BODY WCB  TRIM 316 SS  PACKING PTFE  ACTUATOR "
    "SPRING DIAPHRAGM  FAIL CLOSE  POSITIONER SMART HART  LIMIT SWITCHES NONE"
)
MARK = stated_value.EXCERPT_MARK


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "r.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _whole(monkeypatch):
    """The behaviour before the fix: every value quoted whole."""
    monkeypatch.setattr(stated_value, "stated", lambda value: value)
    monkeypatch.setattr(datasheet_checks, "_said", datasheet_checks._shown)


def _same_verdict(capped: dict, whole: dict, *text_keys: str) -> None:
    def strip(r):
        return {k: v for k, v in r.items() if k not in text_keys}

    assert strip(capped) == strip(whole)


def _excerpt_in(text: str, value: str) -> None:
    flat = " ".join(value.split())
    assert flat not in text  # never the whole chunk
    shown = stated_value.stated(flat)
    assert shown.endswith(MARK) and shown in text
    assert flat.startswith(shown[: -len(MARK)])  # the start, word for word


# ------------------------------------------------------------------ the helper
@pytest.mark.parametrize("value", ["24 V DC", "  CF8M\n", "", "x" * 80, None, 12.5])
def test_a_short_value_is_quoted_exactly_as_it_is(value):
    assert stated_value.stated(value) is value


def test_a_long_value_is_cut_at_a_word_and_marked_as_an_excerpt():
    shown = stated_value.stated(ROW)
    flat = " ".join(ROW.split())
    assert shown.endswith(" …")
    head = shown[: -len(MARK)]
    assert len(head) <= stated_value.EXCERPT_CHARS
    assert flat.startswith(head) and flat[len(head)] == " "  # cut between words
    assert stated_value.stated("x" * 81) == "x" * 80 + MARK  # one long word


# ------------------------------------------------------------------ comparison.py
def _statement(text):
    return {
        "id": "req-1",
        "standard_document_id": "doc_std",
        "clause": "7.2",
        "requirement_type": "statement",
        "requirement_text": text,
        "source_text": text,
        "subject": "body material",
    }


def _fact(value, *, number=None, unit=None, **more):
    return {
        "id": "f1",
        "document_id": "doc_sheet",
        "submittal_document_id": "doc_sheet",
        "field_name": "body material",
        "field_label": "Body material",
        "field_value": value,
        "raw_value": number,
        "raw_unit": unit,
        "is_blank": 0,
        "page": 3,
        "extraction_method": "geometry",
        "equipment_tag": None,
        **more,
    }


def _judge(req, fact):
    return comparison._compare(req, fact, submittal_facts=[fact])


STATED = "The body material shall be stated on the datasheet."
NAMED = "The body material shall be WCB or CF8M."


@pytest.mark.parametrize("clause", [STATED, NAMED])
def test_a_statement_quotes_a_long_value_as_an_excerpt(clause, monkeypatch):
    capped = _judge(_statement(clause), _fact(ROW))
    _excerpt_in(capped["rationale"], ROW)
    assert capped["observed"] == " ".join(ROW.split())  # the full value stays
    _whole(monkeypatch)
    whole = _judge(_statement(clause), _fact(ROW))
    assert " ".join(ROW.split()) in whole["rationale"]
    _same_verdict(capped, whole, "rationale")


@pytest.mark.parametrize("clause, value", [(STATED, "Carbon steel"), (NAMED, "Bronze")])
def test_a_statement_quotes_a_short_value_whole(clause, value):
    assert value in _judge(_statement(clause), _fact(value))["rationale"]


def _nominal():
    return {
        "id": "r1",
        "standard_document_id": "doc_std",
        "requirement_type": "nominal_value",
        "operator": "nominal",
        "raw_value": "24",
        "raw_unit": "V",
        "value": 24.0,
        "unit": "V",
        "value_low": 23.5,
        "value_high": 24.5,
        "subject": "loop supply",
        "clause": "5.2",
        "requirement_text": "x",
        "source_text": "x",
    }


@pytest.mark.parametrize("number", ["24", "12"])
def test_a_nominal_value_quotes_a_long_value_as_an_excerpt(number, monkeypatch):
    long_value = f"{number} V DC LOOP POWERED " + ROW
    fact = _fact(long_value, number=number, unit="V")
    capped = _judge(_nominal(), fact)
    assert capped["status"] == (
        comparison.COMPLIANT if number == "24" else comparison.NEEDS_ENGINEER_REVIEW
    )
    _excerpt_in(capped["rationale"], long_value)
    _whole(monkeypatch)
    _same_verdict(capped, _judge(_nominal(), fact), "rationale")


def test_a_nominal_value_quotes_a_short_value_whole():
    verdict = _judge(_nominal(), _fact("12 V DC", number="12", unit="V"))
    assert "the datasheet states 12 V DC." in verdict["rationale"]


def _limit(operator):
    return {
        "id": "r2",
        "standard_document_id": "doc_std",
        "requirement_type": "numeric_limit",
        "operator": operator,
        "raw_value": "60",
        "raw_unit": "C",
        "subject": "design temperature",
        "clause": "6.1",
        "requirement_text": "x",
        "source_text": "x",
    }


@pytest.mark.parametrize("operator", ["=", "<="])
def test_a_submitted_range_quotes_a_long_value_as_an_excerpt(operator, monkeypatch):
    long_value = "-3 to 55 C " + ROW
    fact = _fact(long_value, number="55", unit="C", value_min=-3.0, value_max=55.0)
    capped = _judge(_limit(operator), fact)
    _excerpt_in(capped["rationale"], long_value)
    _whole(monkeypatch)
    _same_verdict(capped, _judge(_limit(operator), fact), "rationale")


@pytest.mark.parametrize("operator", ["=", "<="])
def test_a_submitted_range_quotes_a_short_value_whole(operator):
    fact = _fact("-3 to 55 C", number="55", unit="C", value_min=-3.0, value_max=55.0)
    assert "-3 to 55 C" in _judge(_limit(operator), fact)["rationale"]


def test_a_value_that_is_not_a_number_is_quoted_as_an_excerpt(monkeypatch):
    fact = _fact(ROW, number=ROW, unit="C")
    capped = _judge(_limit("<="), fact)
    assert capped["status"] == comparison.NEEDS_ENGINEER_REVIEW
    _excerpt_in(capped["rationale"], ROW)
    assert capped["observed"]["raw_value"] == ROW  # stored whole
    _whole(monkeypatch)
    _same_verdict(capped, _judge(_limit("<="), fact), "rationale")


# ------------------------------------------------------------- datasheet_checks.py
def _item(kind, **rule):
    return {
        "id": "T-1",
        "text": "The body material is given",
        "rule": {"kind": kind, "field": "body_material", **rule},
        "source": {"standard": "STD-1", "clause": "4"},
    }


def _check(item, fact):
    roles = {"body_material": [fact]}
    rules = datasheet_checks.load_rules()
    return datasheet_checks.evaluate_item(item, roles, {}, None, rules, draft=False)


# "CF8M" is past the excerpt's end: the check must still read the whole value.
LONG_BODY = "BODY " + ROW + " CF8M"


@pytest.mark.parametrize(
    "item",
    [
        _item("required"),
        _item("allowed", values=["CF8M"]),
        _item("allowed", values=["Bronze"]),
    ],
)
def test_a_checklist_item_quotes_a_long_value_as_an_excerpt(item, monkeypatch):
    capped = _check(item, _fact(LONG_BODY))
    _excerpt_in(capped["detail"], LONG_BODY)
    assert capped["value"] == LONG_BODY  # the fact's value travels whole
    _whole(monkeypatch)
    _same_verdict(capped, _check(item, _fact(LONG_BODY)), "detail")


def test_the_whole_value_decides_a_checklist_item():
    assert (
        _check(_item("allowed", values=["CF8M"]), _fact(LONG_BODY))["status"]
        == "COMPLIANT"
    )
    assert (
        _check(_item("allowed", values=["Bronze"]), _fact(LONG_BODY))["status"]
        == "NON_COMPLIANT"
    )


def test_a_checklist_item_quotes_a_short_value_whole():
    detail = _check(_item("required"), _fact("CF8M"))["detail"]
    assert detail.startswith("Body material CF8M (page 3) is stated.")
