"""#1309 order 235.1: the per-run clause-check budget is SPENT, not just
counted. Of the sentences the model may be asked about (the cap), the first
go to those that print a figure, then to those that name a field THIS sheet
states, then to those of a standard this sheet cites; every document, no
per-layout rule. Invented sentences and ids only."""

from __future__ import annotations

import uuid

import pytest

from app import ai_requirements as air
from app import datasheets, db, submittal_review
from app.config import settings
from app.db import connect
from tests.test_645_clause_checks import Fake, proposal
from tests.test_w5_677_scope_ledger import NOW, _chunk, _doc


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "rank.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


CITED, OTHER = "std-cited", "std-other"


def _sentence(rid, text, standard):
    return {
        "id": rid,
        "requirement_type": "statement",
        "source_text": text,
        "standard_document_id": standard,
    }


def _run(*fields):
    """A run whose sheet states these fields and cites only `CITED`."""
    _doc(CITED, "cited.pdf", "COMPANY_STANDARD")
    _doc(OTHER, "other.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL")
    chunk = _chunk("fc", sub)
    for label in fields:
        datasheets.create_fact(
            submittal_document_id=sub,
            chunk_id=chunk,
            field_label=label,
            raw_value="1 mm",
            page=1,
        )
    run = str(uuid.uuid4())
    with connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,"
            "updated_at) VALUES (?,?,'pending',?,?)",
            (run, sub, NOW, NOW),
        )
        for std, method in ((CITED, "referenced"), (OTHER, "equipment_type")):
            conn.execute(
                "INSERT INTO review_applicable_standards (id,review_run_id,"
                "standard_document_id,selection_method,included,created_at)"
                " VALUES (?,?,?,?,1,?)",
                (str(uuid.uuid4()), run, std, method, NOW),
            )
    return run


def _asked_first(reqs, run, limit=1):
    """The ids of the sentences the model was asked about, in order."""
    by_text = {r["source_text"]: r["id"] for r in reqs}
    seen: list[str] = []

    class Recording(Fake):
        def reason(self, packet):
            seen.append(next(i for t, i in by_text.items() if t in packet.prompt))
            return super().reason(packet)

    air.propose_checks(
        reqs,
        review_run_id=run,
        limit=limit,
        provider=Recording(*[proposal()] * len(reqs)),
    )
    return seen


def test_a_sentence_naming_a_field_the_sheet_states_is_asked_before_one_that_does_not(
    storage,
):
    run = _run("Wall thickness")
    reqs = [
        _sentence(
            "elsewhere",
            "The cold differential test pressure shall not exceed 12 barg.",
            OTHER,
        ),
        _sentence("stated", "The wall thickness shall not exceed 12 barg.", OTHER),
    ]
    assert _asked_first(reqs, run) == ["stated"]


def test_a_stated_field_is_found_as_whole_words_only(storage):
    run = _run("Area")
    reqs = [
        _sentence(
            "inside", "The particular test pressure shall not exceed 12 barg.", OTHER
        ),
        _sentence(
            "whole",
            "The cold differential test pressure shall not exceed 12 barg.",
            CITED,
        ),
    ]
    # "area" is inside "particular" but is not a word of it: no tie to the field,
    # so the next rule (a standard the sheet cites) decides
    assert _asked_first(reqs, run) == ["whole"]


def test_the_standard_the_sheet_cites_goes_next(storage):
    run = _run("Wall thickness")
    reqs = [
        _sentence(
            "other",
            "The cold differential test pressure shall not exceed 12 barg.",
            OTHER,
        ),
        _sentence(
            "cited",
            "The cold differential test pressure shall not exceed 13 barg.",
            CITED,
        ),
    ]
    assert _asked_first(reqs, run) == ["cited"]


def test_a_figure_still_comes_before_a_stated_field(
    storage,
):
    run = _run("Wall thickness")
    reqs = [
        _sentence("words", "The wall thickness shall be uniform.", CITED),
        _sentence(
            "figure",
            "The cold differential test pressure shall not exceed 12 barg.",
            OTHER,
        ),
    ]
    assert _asked_first(reqs, run) == ["figure"]


def test_the_report_says_asked_and_skipped_per_standard(storage):
    run = _run("Wall thickness")
    reqs = [
        _sentence("a", "The wall thickness shall not exceed 12 barg.", CITED),
        _sentence("b", "The cold test pressure shall not exceed 12 barg.", CITED),
        _sentence("c", "The cold test pressure shall not exceed 13 barg.", OTHER),
    ]
    out = air.propose_checks(
        reqs, review_run_id=run, limit=2, provider=Fake(proposal(), proposal())
    )
    assert out["per_standard"] == {
        CITED: {"sentences": 2, "asked": 2, "skipped": 0},
        OTHER: {"sentences": 1, "asked": 0, "skipped": 1},
    }
    # the per-standard counts add up to the run's own
    assert sum(v["asked"] for v in out["per_standard"].values()) == out["asked"]
    assert (
        sum(v["skipped"] for v in out["per_standard"].values())
        == out["not_asked_budget"]
    )
