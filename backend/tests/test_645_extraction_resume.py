"""#645 slice 4: with `ai_requirement_extraction_resume_enabled`, each run of
the chunk extraction reads only chunks THIS model has not read yet, so runs
walk the whole standard instead of reading its first chunks again. A fake
model stands in for the local one. Invented clauses only."""

from __future__ import annotations

import dataclasses

import pytest

from app import ai_requirement_chunks as arc
from app import ai_requirements as air
from app.config import settings
from app.db import connect
from app.reasoning_provider import Response
from tests.test_645_clause_checks import Fake
from tests.test_w5_677_scope_ledger import (  # noqa: F401 - fixture
    _doc,
    review_run,
    temp_storage,
)

EMPTY = {"requirements": []}
TEXTS = [f"Clause {n}: the vessel shall be painted grey number {n}." for n in range(3)]


class Recording(Fake):
    """The fake model, keeping the prompts it was sent."""

    def __init__(self, *replies, model="test-model", requested="same"):
        super().__init__(*replies, model=model)
        self.prompts: list[str] = []
        if requested != "same":  # the model named in the request, not in the reply
            self.requested_model = requested

    def reason(self, packet):
        self.prompts.append(packet.prompt)
        text = self.replies.pop(0)
        return Response(
            text=text,
            provider="ollama",
            model_tag="test-model",
            digest="d",
            finish_reason="stop",
            prompt_sha256=packet.sha256,
        )


@pytest.fixture
def standard(monkeypatch):
    monkeypatch.setattr(settings, "ai_requirement_extraction_enabled", True)
    monkeypatch.setattr(settings, "ai_requirement_extraction_resume_enabled", True)
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", False)
    _doc("std", "STD-1.pdf", "COMPANY_STANDARD")
    with connect() as conn:
        for n, text in enumerate(TEXTS):
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,"
                "section,kind,text,token_count,content_hash,retrievable)"
                " VALUES (?,?,?,?,1,1,NULL,'prose',?,1,?,1)",
                (f"c{n}", "std", "f.pdf", n, text, f"h-c{n}"),
            )
    return "std"


def run(provider, max_chunks=2):
    return arc.extract_standard(
        "std",
        allowed_document_ids=frozenset({"std"}),
        max_chunks=max_chunks,
        provider=provider,
        unload=lambda provider: None,
    )


def read(provider) -> list[int]:
    """Which of TEXTS the model was sent, in order."""
    return [n for p in provider.prompts for n, t in enumerate(TEXTS) if t in p]


def test_the_next_run_carries_on_where_the_last_stopped(standard):
    first = Recording(EMPTY, EMPTY)
    report = run(first)
    assert read(first) == [0, 1]
    assert (report["chunks"], report["standard_chunks"], report["not_yet_read"]) == (
        2,
        3,
        1,
    )

    second = Recording(EMPTY)
    report = run(second)
    assert read(second) == [2]
    assert (report["chunks"], report["not_yet_read"]) == (1, 0)

    third = Recording()
    report = run(third)
    assert third.prompts == [] and report["chunks"] == 0 and report["not_yet_read"] == 0


def test_switch_off_reads_the_first_chunks_every_run(standard, monkeypatch):
    monkeypatch.setattr(settings, "ai_requirement_extraction_resume_enabled", False)
    for _ in range(2):
        provider = Recording(EMPTY, EMPTY)
        report = run(provider)
        assert read(provider) == [0, 1]
        # null, not 0: the counts are not kept with the switch off
        assert report["standard_chunks"] is None and report["not_yet_read"] is None


def test_a_chunk_with_a_passage_the_model_could_not_read_is_read_again(standard):
    # chunk 0: two answers that are not JSON (the reply is retried once)
    first = Recording("not json", "not json", EMPTY)
    report = run(first)
    assert report["could_not_read"] == 1 and report["not_yet_read"] == 2

    second = Recording(EMPTY, EMPTY)
    run(second)
    assert read(second) == [0, 2]


def test_another_model_reads_every_chunk_afresh(standard):
    run(Recording(EMPTY, EMPTY))
    stronger = Recording(EMPTY, EMPTY, model="stronger-model")
    report = run(stronger)
    assert read(stronger) == [0, 1]
    assert report["not_yet_read"] == 1


def test_a_standard_the_caller_may_not_read_records_nothing(standard):
    provider = Recording()
    report = arc.extract_standard(
        "std",
        allowed_document_ids=frozenset({"other"}),
        max_chunks=2,
        provider=provider,
        unload=lambda provider: None,
    )
    assert provider.prompts == [] and report["chunks"] == 0
    assert report["not_yet_read"] is None


BAD = {
    "requirements": [
        {
            "quote": "words that are not in the chunk",
            "subject": "vessel",
            "operator": "<=",
            "value": "1",
            "value_to": None,
            "unit": None,
            "condition": None,
            "standard": None,
        }
    ]
}


def test_a_chunk_that_keeps_failing_is_given_up_and_the_run_moves_on(standard):
    # a check_item rejection counts as could-not-read; with answer reuse the
    # same reply would come back, so after MAX_ATTEMPTS the chunk is given up
    for _ in range(arc.MAX_ATTEMPTS):
        provider = Recording(BAD)
        report = run(provider, max_chunks=1)
        assert read(provider) == [0]
    assert report["gave_up"] == 1 and report["not_yet_read"] == 2
    provider = Recording(EMPTY)
    report = run(provider, max_chunks=1)
    assert read(provider) == [1]
    assert (report["gave_up"], report["not_yet_read"]) == (1, 1)


def test_a_new_task_version_reads_every_chunk_afresh(standard, monkeypatch):
    run(Recording(EMPTY, EMPTY))
    # the prompt changed: the task's own version moves (its cache key too)
    monkeypatch.setattr(air, "TASK", dataclasses.replace(air.TASK, version="v2"))
    provider = Recording(EMPTY, EMPTY)
    run(provider)
    assert read(provider) == [0, 1]


def test_a_provider_with_no_model_name_marks_nothing(standard):
    for _ in range(2):
        provider = Recording(EMPTY, EMPTY, requested=None)
        report = run(provider)
        assert read(provider) == [0, 1]
        assert report["not_yet_read"] is None
    arc.ensure_reads_schema()
    marks = connect().execute("SELECT COUNT(*) FROM ai_requirement_chunk_reads")
    assert marks.fetchone()[0] == 0


def test_a_standard_with_no_chunks_says_null_not_0_of_0(standard):
    _doc("empty", "STD-2.pdf", "COMPANY_STANDARD")
    report = arc.extract_standard(
        "empty",
        allowed_document_ids=frozenset({"empty"}),
        max_chunks=2,
        provider=Recording(),
        unload=lambda provider: None,
    )
    assert report["chunks"] == 0
    counts = (report["standard_chunks"], report["not_yet_read"], report["gave_up"])
    assert counts == (None, None, None)


def test_read_marks_go_with_the_deleted_standard(standard):
    run(Recording(EMPTY, EMPTY))
    with connect() as conn:
        conn.execute("DELETE FROM documents WHERE id = 'std'")
    marks = connect().execute("SELECT COUNT(*) FROM ai_requirement_chunk_reads")
    assert marks.fetchone()[0] == 0
