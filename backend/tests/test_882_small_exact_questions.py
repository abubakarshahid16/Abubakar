"""#882 technique 2 (planner-approved 13 Oct): one small exact question to the
local model per requirement still left without a value.

The question carries the requirement's own words and the few datasheet lines
naming its subject - never its limit, never a whole document. CODE verifies
the answer on the page; comparison decides; in this first version every
verdict resting on an asked value is held for the engineer, so the step can
never produce a false Meets. A fake local model stands in; invented documents
only.
"""
from __future__ import annotations

import json

import pytest

from app import ai_requirements as air
from app import ai_task_runner, comparison, db
from app.config import settings
from app.reasoning_provider import Response
from tests.test_model_matching import (  # noqa: F401 - fixtures
    MODEL_SUBJECT,
    _world,
    stub,
    temp_storage,
)

PAGE = "\n".join([
    "PRESSURE VESSEL DATASHEET",
    "Tag: V-100",
    "Operating temperature 80 degC",
    "Shell DP 12 bar",
    "Corrosion allowance 3 mm",
])


class Fake:
    """The local model, answering from a script; records every prompt."""

    def __init__(self, *replies, model="local-test:2b"):
        self.requested_model = model
        self.replies = [r if isinstance(r, str) else json.dumps(r) for r in replies]
        self.prompts: list[str] = []

    def reason(self, packet):
        self.prompts.append(packet.prompt if hasattr(packet, "prompt") else str(packet))
        text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return Response(text=text, provider="ollama", model_tag=self.requested_model,
                        digest="d", finish_reason="stop", prompt_sha256=packet.sha256)


def answer(**over) -> dict:
    base = {"stated": True, "field": "Shell DP", "value": "12", "unit": "bar", "page": 1,
            "quote": "Shell DP 12 bar"}
    return {**base, **over}


@pytest.fixture()
def local(monkeypatch):
    def install(*replies):
        fake = Fake(*replies)
        monkeypatch.setattr(ai_task_runner, "make_provider", lambda *a, **k: fake)
        return fake
    monkeypatch.setattr(settings, "match_ask_max_per_run", 20)
    return install


def _page(sub: str, text: str = PAGE) -> None:
    with db.connect() as conn:
        conn.execute("INSERT INTO pages (document_id, page_no, text, char_count, batch_no)"
                     " VALUES (?, 1, ?, ?, 0)", (sub, text, len(text)))


def _run(monkeypatch, stub, *, field_label="Nozzle schedule", raw_value="200 mm",
         matcher=(None, "no candidate is that quantity")):
    stub(matcher)
    _std, sub, run, scope = _world(monkeypatch, subject=MODEL_SUBJECT,
                                   field_label=field_label, raw_value=raw_value)
    _page(sub)
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    return run, scope, result


def _finding(run):
    rows = db.connect().execute(
        "SELECT compliance_status, ai_rationale, fact_id FROM review_findings"
        " WHERE review_run_id = ? AND origin IS NULL", (run,)).fetchall()
    assert len(rows) == 1
    return dict(rows[0])


def _questions(run, scope):
    return comparison.run_outcome(run, allowed_document_ids=scope)["ai_matcher"]["questions"]


# ---------------------------------------------------------- the whole step

def test_a_value_the_readers_missed_is_found_checked_and_held_never_decided(stub, monkeypatch, local):
    fake = local(answer(), answer())
    run, scope, _ = _run(monkeypatch, stub)
    finding = _finding(run)
    # 12 bar against "shall be 10 bar" reads as a breach - and is NOT stated
    # as one: the value came from the model's question
    assert finding["compliance_status"] == "NEEDS_ENGINEER_REVIEW"
    assert comparison.ASKED_PREFIX in finding["ai_rationale"]
    fact = db.connect().execute("SELECT extraction_method, page FROM submittal_facts WHERE id = ?",
                                (finding["fact_id"],)).fetchone()
    assert (fact["extraction_method"], fact["page"]) == ("model", 1)
    q = _questions(run, scope)
    assert (q["eligible"], q["asked"], q["verified"]) == (1, 1, 1)
    # asked twice (the answers must agree); the limit is never sent
    assert len(fake.prompts) == 2
    assert "10 bar" not in fake.prompts[0] and "p1: Shell DP 12 bar" in fake.prompts[0]


def test_a_readers_value_the_rules_could_not_pair_is_held_too(stub, monkeypatch, local):
    """The code-read fact 'Shell DP 12 bar' exists; containment misses it and
    the matcher declines. The question finds it: the arithmetic reads a
    breach, and it is held for the engineer, not stated."""
    local(answer(), answer())
    run, scope, _ = _run(monkeypatch, stub, field_label="Shell DP", raw_value="12 bar")
    finding = _finding(run)
    assert finding["compliance_status"] == "NEEDS_ENGINEER_REVIEW"
    assert "The numbers read NON_COMPLIANT, held for an engineer" in finding["ai_rationale"]


def test_an_answer_code_cannot_find_on_the_page_is_refused_and_not_an_absence(stub, monkeypatch, local):
    local(answer(quote="Shell DP 14 bar", value="14"))
    run, scope, _ = _run(monkeypatch, stub)
    finding = _finding(run)
    assert finding["compliance_status"] == "NEEDS_ENGINEER_REVIEW"
    assert comparison.PAIRING_NOT_CHECKED in finding["ai_rationale"]
    assert finding["fact_id"] is None
    assert _questions(run, scope)["refused"] == {"quote_not_on_page": 1}


def test_two_answers_that_disagree_are_refused(stub, monkeypatch, local):
    local(answer(), answer(value="13", quote="Shell DP 13 bar"))
    run, scope, _ = _run(monkeypatch, stub)
    assert _questions(run, scope)["refused"] == {air.ANSWERS_DISAGREED: 1}


def test_not_stated_leaves_the_requirement_as_it_was(stub, monkeypatch, local):
    local(answer(stated=False, field=None, value=None, unit=None, page=None, quote=None))
    run, scope, _ = _run(monkeypatch, stub)
    assert _finding(run)["fact_id"] is None
    assert _questions(run, scope)["not_stated"] == 1


def test_the_per_run_cap_is_counted_never_silent(stub, monkeypatch, local):
    fake = local(answer())
    monkeypatch.setattr(settings, "match_ask_max_per_run", 0)
    run, scope, _ = _run(monkeypatch, stub)
    assert fake.prompts == []
    q = _questions(run, scope)
    assert (q["eligible"], q["asked"], q["not_asked_budget"]) == (1, 0, 1)
    line = air.ask_report_line(q)
    assert line.endswith("1 not asked (the per-run cap).")


def test_the_run_card_states_every_count_out_of_its_whole(stub, monkeypatch, local):
    local(answer(), answer())
    run, scope, _ = _run(monkeypatch, stub)
    line = air.ask_report_line(_questions(run, scope))
    assert line == ("Local model questions: 1 of 1 requirement(s) with no value read were asked; "
                    "1 answer(s) verified on the page (held for the engineer), 0 not stated, "
                    "0 refused by code, 0 not read by the model, 0 with no datasheet line "
                    "naming the subject.")


# ------------------------------------------------------ only a few lines

def test_only_the_lines_naming_the_subject_are_sent_never_the_page():
    req = {"subject": "the pressure for the design of the shell"}
    filler = "\n".join(f"Unrelated row {n} value {n}" for n in range(40))
    page_texts = {1: filler + "\nShell DP 12 bar", 2: "Design pressure note\n" + filler}
    lines = air.evidence_lines(req, page_texts)
    assert len(lines) <= air.ASK_MAX_LINES
    assert (1, "Shell DP 12 bar") in lines and (2, "Design pressure note") in lines
    assert not any(text.startswith("Unrelated row 5 ") for _, text in lines)


def test_no_line_naming_the_subject_means_no_question():
    out = air.ask_value({"subject": "impeller diameter"}, {1: PAGE}, provider=Fake(answer()))
    assert out["state"] == air.ASKED_NO_EVIDENCE


def test_a_page_that_was_not_sent_is_refused():
    out = air.ask_value({"subject": "shell pressure"}, {1: PAGE},
                        provider=Fake(answer(page=2), answer(page=2)))
    assert (out["state"], out["why"]) == (air.ASKED_REFUSED, air.PAGE_NOT_SENT)


def test_the_small_questions_are_off_by_default_until_their_before_after():
    """Planner order 51 (17 Oct): #909 ships OFF (0 = never asked), the #985
    pattern; the default flips to 20 in its own PR after the ON before/after
    on the real PF1 sheets. The env-isolated test settings pin 0 too, so this
    reads the class default, not the fixture."""
    from app.config import Settings
    assert Settings.model_fields["match_ask_max_per_run"].default == 0
