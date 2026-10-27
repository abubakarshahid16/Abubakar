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
        {"i": 0, "field": mawp, "quote": "max allowable working pressure"}, items, vocab
    )
    assert ok == (0, {"field_name": "mawp", "quote": "max allowable working pressure"})
    other = [("k", "The design pressure shall not exceed 10 bar.")]
    no = field_vocabulary.verify(
        {"i": 0, "field": mawp, "quote": "design pressure"}, other, vocab
    )
    assert no[1]["field_name"] is None
    absent = field_vocabulary.verify(
        {"i": 0, "field": mawp, "quote": "maximum permitted load"}, items, vocab
    )
    assert absent[1]["field_name"] is None


def test_the_answer_is_stored_once_and_not_asked_again():
    reqs = [
        {
            "id": "r1",
            "requirement_type": "numeric_limit",
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


def test_names_for_falls_back_to_the_per_sheet_naming_when_nothing_is_stored(
    monkeypatch,
):
    seen = []
    monkeypatch.setattr(
        field_naming,
        "ensure_names",
        lambda *a, **k: seen.append(1) or {"requirements": {}, "facts": {}},
    )
    out = field_vocabulary.names_for(
        [{"id": "r9", "requirement_type": "numeric_limit"}], []
    )
    assert seen == [1] and out["requirements"] == {}


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
    req, _fact, _run, _scope = _world("Max allowable working pressure", "12 bar")
    fake = Fake(lambda t: "mawp", lambda t: "maximum allowable working pressure")
    out = name_numeric_limits.run(tmp_path / "vocab.sqlite", provider=fake)
    assert (
        out["numeric_requirements"] == 1 and out["named"] == 1 and out["unmapped"] == 0
    )
    assert list(out["by_standard"].values()) == [{"numeric": 1, "named": 1}]
    again = name_numeric_limits.run(tmp_path / "vocab.sqlite", provider=fake)
    assert again["already_stored"] == 1 and again["to_ask"] == 0
    assert "maximum allowable" not in json.dumps(out)
