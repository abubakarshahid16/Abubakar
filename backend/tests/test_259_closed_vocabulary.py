"""Order 259.5: a standard's numeric limit is named ONCE against a closed vocabulary of quantities
(the synonym table's canonical phrases plus the numeric checklist roles), offline, and a sheet fact
is named by rule. Invented text only; the model is a fake that answers a vocabulary number."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app import comparison, db, field_naming, field_vocabulary, submittal_review
from app.config import settings
from app.reasoning_provider import Response
from tests.test_field_naming import _world

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import name_numeric_limits

REQUIREMENT_KIND = field_vocabulary.REQUIREMENT


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "vocab.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


class Fake:
    """Answers each item with the vocabulary number of `name_for(text)`, quoting `quote_for(text)`."""

    name = "ollama"

    def __init__(self, name_for, quote_for):
        self.name_for, self.quote_for, self.packets = name_for, quote_for, []

    def reason(self, packet):
        self.packets.append(packet)
        vocab = field_vocabulary.vocabulary()
        out = []
        for item in json.loads(packet.prompt)["items"]:
            name = self.name_for(item["text"])
            out.append(
                {
                    "i": item["i"],
                    "field": vocab.index(name) if name else None,
                    "quote": self.quote_for(item["text"]) if name else "",
                }
            )
        return Response(
            text=json.dumps({"names": out}),
            provider="ollama",
            model_tag="fake:1",
            digest="d",
            finish_reason="stop",
            prompt_sha256=packet.sha256,
        )


def test_the_vocabulary_is_closed_sorted_and_stable():
    vocab = field_vocabulary.vocabulary()
    assert vocab == sorted(vocab) and len(vocab) == len(set(vocab))
    for name in (
        "rated speed",
        "mawp",
        "design pressure",
        "npsh required",
        "motor rating",
    ):
        assert name in vocab, name
    assert field_vocabulary.vocabulary() == vocab


def test_a_quote_with_another_spelling_names_the_quantity_but_another_quantity_does_not():
    vocab = field_vocabulary.vocabulary()
    items = [("k", "The max allowable working pressure shall not exceed 10 bar.")]
    mawp = vocab.index("mawp")
    ok = field_vocabulary.verify(
        {"i": 0, "field": mawp, "quote": "max allowable working pressure"},
        items,
        vocab,
        {"k": ("10", "bar")},
    )
    assert ok == (0, {"field_name": "mawp", "quote": "max allowable working pressure"})
    other = [("k", "The design pressure shall not exceed 10 bar.")]
    no = field_vocabulary.verify(
        {"i": 0, "field": mawp, "quote": "design pressure"},
        other,
        vocab,
        {"k": ("10", "bar")},
    )
    assert no[1]["field_name"] is None
    absent = field_vocabulary.verify(
        {"i": 0, "field": mawp, "quote": "maximum permitted load"},
        items,
        vocab,
        {"k": ("10", "bar")},
    )
    assert absent[1]["field_name"] is None


def test_the_answer_is_stored_once_and_not_asked_again():
    reqs = [
        {
            "id": "r1",
            "requirement_type": "numeric_limit",
            "raw_value": "10",
            "raw_unit": "bar",
            "requirement_text": "The max allowable working pressure shall not exceed 10 bar.",
        }
    ]
    fake = Fake(lambda t: "mawp", lambda t: "max allowable working pressure")
    got = field_vocabulary.name_requirements(reqs, fake)
    assert got["r1"]["field_name"] == "mawp"
    field_vocabulary.name_requirements(reqs, fake)
    assert len(fake.packets) == 1


def test_a_sheet_fact_is_named_by_rule_and_a_free_label_is_not():
    assert (
        field_vocabulary.fact_name(
            {"field_name": "rated speed", "field_label": "RATED SPEED"}
        )
        == "rated speed"
    )
    assert (
        field_vocabulary.fact_name(
            {
                "field_name": "max allowable working pressure",
                "field_label": "Max allowable working pressure",
            }
        )
        == "mawp"
    )
    assert (
        field_vocabulary.fact_name({"field_name": "remarks", "field_label": "REMARKS"})
        is None
    )


def test_with_nothing_stored_a_review_makes_no_model_call_unless_the_geometry_reader_is_on(
    monkeypatch,
):
    seen = []
    monkeypatch.setattr(
        field_naming,
        "ensure_names",
        lambda *a, **k: seen.append(1) or {"requirements": {}, "facts": {}},
    )
    reqs = [{"id": "r9", "requirement_type": "numeric_limit", "requirement_text": "x"}]
    monkeypatch.setattr(settings, "geometry_reader_enabled", False)
    out = field_vocabulary.names_for(reqs, [])
    assert seen == [] and out["requirements"] == {} and out["requirements_named"] == 0
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    field_vocabulary.names_for(reqs, [])
    assert seen == [1]


def test_a_stored_name_pairs_through_the_run_and_never_carries_a_verdict(monkeypatch):
    """Stored closed-vocabulary name on the requirement + the rule name of the fact: paired by
    name equality, held for an engineer, no model call during the run."""
    req, fact, run, scope = _world("Max allowable working pressure", "12 bar")
    monkeypatch.setattr(settings, "field_naming_enabled", True)
    fake = Fake(lambda t: "mawp", lambda t: "maximum allowable working pressure")
    field_vocabulary.name_requirements(
        [
            {
                "id": req["id"],
                "requirement_type": "numeric_limit",
                "raw_value": "10",
                "raw_unit": "bar",
                "requirement_text": "The maximum allowable working pressure shall be 10 bar.",
            }
        ],
        fake,
    )

    def explode(*_a, **_k):
        raise AssertionError("the run asked a model")

    monkeypatch.setattr(field_naming, "ensure_names", explode)
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    found = result["findings"][0]
    assert found["match_method"] == comparison.METHOD_FIELD_NAME
    assert found["fact_id"] == fact["id"]
    assert found["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert result["field_naming"]["requirements_named"] == 1


def test_the_script_refuses_the_live_database_and_counts_a_copy(monkeypatch, tmp_path):
    live = (
        Path(name_numeric_limits.REPO) / "backend" / "data" / "rag_intelligence.sqlite"
    )
    with pytest.raises(SystemExit):
        name_numeric_limits.run(live)
    out = name_numeric_limits.run(tmp_path / "vocab.sqlite", dry_run=True)
    assert (
        out["numeric_requirements"] == 0
        and out["to_ask"] == 0
        and out["refused"] is None
    )


def test_the_script_names_a_copys_numeric_limits_and_reports_counts_only(tmp_path):
    _req, _fact, _run, _scope = _world("Max allowable working pressure", "12 bar")
    fake = Fake(lambda t: "mawp", lambda t: "maximum allowable working pressure")
    out = name_numeric_limits.run(tmp_path / "vocab.sqlite", provider=fake)
    assert (
        out["numeric_requirements"] == 1 and out["named"] == 1 and out["unmapped"] == 0
    )
    assert list(out["by_standard"].values()) == [{"numeric": 1, "named": 1}]
    again = name_numeric_limits.run(tmp_path / "vocab.sqlite", provider=fake)
    assert again["already_stored"] == 1 and again["to_ask"] == 0
    assert "maximum allowable" not in json.dumps(out)


# ----------------------------------------------- cloud's review of #1389: gate, staleness, bad replies


@pytest.mark.parametrize(
    ("quote", "name", "expected"),
    [
        ("min flow", "max flow", False),
        ("max flow", "max flow", True),
        ("NPSH margin", "npsh required", False),
        ("design pressure drop", "design pressure", False),
        ("flow", "max flow", False),
        ("set pressure tolerance", "set pressure", False),
        ("operating pressure at suction", "operating pressure", False),
        ("max allowable working pressure", "mawp", True),
        ("wind speed", "rated speed", False),
        ("design pressure", "mawp", False),
        ("temperature", "design temperature", False),
        ("the design pressure", "design pressure", True),
    ],
)
def test_the_gate_refuses_another_or_opposite_quantity(quote, name, expected):
    assert field_vocabulary.names_the_quantity(quote, name) is expected


def _store_a_name(req_id, text, name, quote):
    reqs = [
        {
            "id": req_id,
            "requirement_type": "numeric_limit",
            "raw_value": "10",
            "raw_unit": "bar",
            "requirement_text": text,
        }
    ]
    field_vocabulary.name_requirements(reqs, Fake(lambda t: name, lambda t: quote))
    return reqs


def test_an_edited_sentence_loses_its_stored_name():
    reqs = _store_a_name(
        "r1",
        "The max allowable working pressure shall not exceed 10 bar.",
        "mawp",
        "max allowable working pressure",
    )
    assert field_vocabulary.names_for(reqs, [])["requirements"] == {"r1": "mawp"}
    edited = [
        {**reqs[0], "requirement_text": "The design pressure shall not exceed 10 bar."}
    ]
    assert field_vocabulary.names_for(edited, [])["requirements"] == {}


def test_a_changed_gate_drops_a_name_the_old_gate_let_through(monkeypatch):
    reqs = _store_a_name(
        "r1",
        "The max allowable working pressure shall not exceed 10 bar.",
        "mawp",
        "max allowable working pressure",
    )
    monkeypatch.setattr(field_vocabulary, "names_the_quantity", lambda *_a: False)
    assert field_vocabulary.names_for(reqs, [])["requirements"] == {}


class Unreadable(Fake):
    def reason(self, packet):
        self.packets.append(packet)
        return Response(
            text="{",
            provider="ollama",
            model_tag="fake:1",
            digest="d",
            finish_reason="length",
            prompt_sha256=packet.sha256,
        )


def test_a_reply_that_cannot_be_read_stores_nothing_and_is_asked_again():
    reqs = [
        {
            "id": "r1",
            "requirement_type": "numeric_limit",
            "raw_value": "10",
            "raw_unit": "bar",
            "requirement_text": "The max allowable working pressure shall not exceed 10 bar.",
        }
    ]
    stats = {}
    got = field_vocabulary.name_requirements(
        reqs, Unreadable(lambda t: None, lambda t: ""), stats
    )
    assert got == {} and stats["unreadable"] == 1
    assert (
        field_naming.stored_names(
            REQUIREMENT_KIND, ["r1"], field_vocabulary.vocabulary()
        )
        == {}
    )
    good = Fake(lambda t: "mawp", lambda t: "max allowable working pressure")
    again = field_vocabulary.name_requirements(reqs, good)
    assert again["r1"]["field_name"] == "mawp" and len(good.packets) == 1


def test_a_populated_copy_is_idempotent_and_an_interrupted_run_resumes(tmp_path):
    for i in range(3):
        _world_extra(i)
    first = name_numeric_limits.run(
        tmp_path / "vocab.sqlite",
        provider=Fake(lambda t: "mawp", lambda t: "max allowable working pressure"),
        limit=2,
    )
    assert first["asked"] == 2
    rest = Fake(lambda t: "mawp", lambda t: "max allowable working pressure")
    second = name_numeric_limits.run(tmp_path / "vocab.sqlite", provider=rest)
    assert (
        second["already_stored"] == 2
        and second["to_ask"] == 1
        and len(rest.packets) == 1
    )
    third = name_numeric_limits.run(tmp_path / "vocab.sqlite", provider=rest)
    assert third["to_ask"] == 0 and len(rest.packets) == 1


def test_the_script_exits_non_zero_when_the_model_was_refused(tmp_path, monkeypatch):
    _world_extra(0)

    class Refuses:
        name = "ollama"

        def reason(self, packet):
            raise RuntimeError("engine down")

    monkeypatch.setattr(
        name_numeric_limits,
        "run",
        lambda *a, **k: {"refused": "RuntimeError", "unreadable": 0},
    )
    assert name_numeric_limits.main(["--db", str(tmp_path / "vocab.sqlite")]) == 2


def _world_extra(i):
    """The first call builds the invented world (one standard, one numeric limit); each later call adds
    one more numeric limit to the same standard."""
    if i == 0:
        return _world("Max allowable working pressure", "12 bar")
    from app import standards

    return standards.create_requirement(
        standard_document_id="std-1",
        chunk_id="sc",
        requirement_text=f"The max allowable working pressure shall be 10 bar (item {i}).",
        source_text=f"The max allowable working pressure shall be 10 bar (item {i}).",
        clause=f"6.4.{i + 1}",
        page=1,
        structured={
            "subject": "the maximum allowable working pressure",
            "operator": "<=",
            "raw_value": "10",
            "raw_unit": "bar",
            "requirement_type": "numeric_limit",
        },
    )


# ---------------------------------------- gate 4 (s2's 259.5 measure: 11 of 30 names were right)


@pytest.mark.parametrize(
    ("text", "quote", "name", "value", "unit", "expected"),
    [
        # right: the number follows the name with limit words, in the name's kind of unit
        (
            "The design temperature shall not exceed 120 degC.",
            "design temperature",
            "design temperature",
            "120",
            "degC",
            True,
        ),
        (
            "The max allowable working pressure shall be at least 10 bar.",
            "max allowable working pressure",
            "mawp",
            "10",
            "bar",
            True,
        ),
        (
            "A 30 bar design pressure is required.",
            "design pressure",
            "design pressure",
            "30",
            "bar",
            True,
        ),
        (
            "The compressibility shall be at least 0.8.",
            "compressibility",
            "compressibility",
            "0.8",
            None,
            True,
        ),
        # a DURATION is not a pressure
        (
            "The test pressure shall be held for at least 30 minutes.",
            "test pressure",
            "test pressure",
            "30",
            "minutes",
            False,
        ),
        # a number that only says WHEN the clause applies, in a unit of the right kind
        (
            "Tanks larger than 30 m shall have a manway size of 600 mm.",
            "manway size",
            "manway size",
            "30",
            "m",
            False,
        ),
        (
            "Tanks larger than 30 m shall have a manway size of 600 mm.",
            "manway size",
            "manway size",
            "600",
            "mm",
            True,
        ),
        # a number with no unit for a quantity that has one (a formula, a multiplier)
        (
            "The test pressure shall be 1.5 times the design pressure.",
            "test pressure",
            "test pressure",
            "1.5",
            None,
            False,
        ),
        # another number sits between the name and the figure
        (
            "The design pressure at 20 degC shall be 10 bar.",
            "design pressure",
            "design pressure",
            "10",
            "bar",
            False,
        ),
        # a ratio with a unit, a name the table cannot check, no value, a number not in the sentence
        (
            "The compressibility shall be at least 0.8 bar.",
            "compressibility",
            "compressibility",
            "0.8",
            "bar",
            False,
        ),
        (
            "The molecular weight shall be 28 kg.",
            "molecular weight",
            "molecular weight",
            "28",
            "kg",
            False,
        ),
        (
            "The design pressure shall be 10 bar.",
            "design pressure",
            "design pressure",
            None,
            "bar",
            False,
        ),
        (
            "The design pressure shall be 10 bar.",
            "design pressure",
            "design pressure",
            "12",
            "bar",
            False,
        ),
        # the sentence names the quantity AFTER the figure with other words between
        (
            "Design for 30 bar and keep the design pressure noted.",
            "design pressure",
            "design pressure",
            "30",
            "bar",
            False,
        ),
    ],
)
def test_the_number_must_be_the_limit_of_the_named_quantity(
    text, quote, name, value, unit, expected
):
    assert field_vocabulary.number_fits(text, quote, name, value, unit) is expected


def test_a_name_whose_number_is_a_duration_is_not_stored_as_a_name():
    reqs = [
        {
            "id": "r1",
            "requirement_type": "numeric_limit",
            "raw_value": "30",
            "raw_unit": "minutes",
            "requirement_text": "The test pressure shall be held for at least 30 minutes.",
        }
    ]
    fake = Fake(lambda t: "test pressure", lambda t: "test pressure")
    got = field_vocabulary.name_requirements(reqs, fake)
    assert got["r1"]["field_name"] is None


def test_a_stored_name_is_dropped_when_the_number_no_longer_fits():
    reqs = _store_a_name(
        "r1",
        "The max allowable working pressure shall not exceed 10 bar.",
        "mawp",
        "max allowable working pressure",
    )
    assert field_vocabulary.names_for(reqs, [])["requirements"] == {"r1": "mawp"}
    other_unit = [{**reqs[0], "raw_unit": "minutes"}]
    assert field_vocabulary.names_for(other_unit, [])["requirements"] == {}
