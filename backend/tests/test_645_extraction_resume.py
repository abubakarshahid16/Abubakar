"""#645 slice 4: with `ai_requirement_extraction_resume_enabled`, each run of
the chunk extraction reads only chunks THIS model has not read yet, so runs
walk the whole standard instead of reading its first chunks again. A fake
model stands in for the local one. Invented clauses only."""

from __future__ import annotations

import pytest

from app import ai_requirement_chunks as arc
from app.config import settings
from app.db import connect
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

    def __init__(self, *replies, model="test-model"):
        super().__init__(*replies, model=model)
        self.prompts: list[str] = []

    def reason(self, packet):
        self.prompts.append(packet.prompt)
        return super().reason(packet)


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
