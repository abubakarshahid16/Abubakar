"""R26 step 8 (#763): the AI words each machine CRS comment like a reviewing
engineer; a code lock refuses any rewrite that changes a fact.

What must hold: a rewrite that keeps every number, unit, clause, page and
standard is kept and printed in the INTERNAL copy's "AI Review Comments"
column only; one that invents or drops a fact, adds a claim, or reverses the
row is refused with its reason and the template stays; the issue copy is
byte-for-byte what it was without the AI; a model that fails stops the step
for the run (recorded), never the review; off means no model is asked.
Invented rows and synthetic documents only.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app import access, crs_export, crs_wording, main, review_jobs
from app.config import settings
from tests.test_p3_review_jobs import W, _enqueue, temp_storage, world  # noqa: F401 - fixtures

TEMPLATE = ("API 610 cl. 6.1.14: requires noise level not more than 85 dB(A). Datasheet p.3, "
            "Noise level states 92. Contractor to revise Noise level to meet the requirement, "
            "or submit a deviation request with justification for Company approval.")
ROW = {"row_kind": "non_compliant", "comment": TEMPLATE, "crs_row_key": "k1",
       "standard_reference": "API 610 cl. 6.1.14 (p.12)", "page_section": "p.3 - Noise level"}
GOOD = ("Per API 610 cl. 6.1.14, the noise level is required to be not more than 85 dB(A); "
        "the datasheet (p.3) states 92. Please revise the noise level to meet the requirement, "
        "or submit a deviation request with justification for Company approval.")


@pytest.mark.parametrize("text, reason", [
    (GOOD, None),
    (GOOD.replace("states 92", "states 93"), crs_wording.NUMBER_CHANGED),
    (GOOD.replace("85 dB(A)", "85 psi"), crs_wording.UNIT_CHANGED),
    (GOOD.replace("Per API 610 cl. 6.1.14, the", "Per API 610, the"), crs_wording.CLAUSE_DROPPED),
    (GOOD.replace("Per API 610 cl. 6.1.14,", "Per API 610 cl. 6.1.14 and ISO 3744,"),
     crs_wording.STANDARD_CHANGED),
    (GOOD + " This is caused by excessive bearing vibration from the impeller.",
     crs_wording.CLAIM_ADDED),
    (GOOD + " The noise level is acceptable.", crs_wording.STATUS_REVERSED),
    ("x" * (crs_wording.MAX_CHARS + 1), crs_wording.TOO_LONG),
    ("   ", crs_wording.NO_COMMENT),
])
def test_the_lock_keeps_a_faithful_rewrite_and_names_why_it_refuses_one(text, reason):
    assert crs_wording.lock(text, ROW) == reason


def test_the_lock_refuses_dropping_the_standard_the_template_cites():
    assert crs_wording.lock(GOOD.replace("Per API 610 cl. 6.1.14, the", "Per cl. 6.1.14, the"),
                            ROW) == crs_wording.STANDARD_CHANGED


class _Fake:
    """A provider that answers from a script, recording what it was asked."""

    def __init__(self, answers):
        self.answers, self.asked = list(answers), []

    def reason(self, packet):
        self.asked.append(packet)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(text=json.dumps({"comment": answer}), provider="fake",
                               model_tag="fake-1", schema_errors=())


@pytest.fixture
def wording_on(monkeypatch):
    monkeypatch.setattr(settings, "crs_ai_wording_enabled", True)


def test_accepted_rewrites_are_stored_and_refusals_counted(wording_on):
    second = dict(ROW, crs_row_key="k2")
    summary = crs_wording.word_run("run-a", [ROW, second],
                                   provider=_Fake([GOOD, GOOD.replace("92", "93")]))
    assert crs_wording.stored("run-a") == {"k1": GOOD}
    assert (summary["tried"], summary["accepted"], summary["refused"]) == (
        2, 1, {crs_wording.NUMBER_CHANGED: 1})
    assert summary["model"] == "fake:fake-1" and summary["stopped"] is None
    assert crs_wording.summary_of("run-a") == summary


def test_engineer_words_and_ai_items_are_never_reworded(wording_on):
    fake = _Fake([GOOD])
    rows = [dict(ROW, crs_row_key="e", comment_by="Edited by Eng One"),
            dict(ROW, crs_row_key="a", row_kind="ai_engineering_check"),
            dict(ROW, crs_row_key="m")]
    crs_wording.word_run("run-b", rows, provider=fake)
    assert len(fake.asked) == 1 and crs_wording.stored("run-b") == {"m": GOOD}


def test_a_failing_model_stops_the_step_and_keeps_every_template(wording_on):
    fake = _Fake([TimeoutError("slow"), GOOD])
    summary = crs_wording.word_run("run-c", [ROW, dict(ROW, crs_row_key="k2")], provider=fake)
    assert len(fake.asked) == 1 and crs_wording.stored("run-c") == {}
    assert "TimeoutError" in summary["stopped"] and summary["tried"] == 0


def test_off_asks_no_model_and_says_so(monkeypatch):
    monkeypatch.setattr(settings, "crs_ai_wording_enabled", False)
    fake = _Fake([GOOD])
    summary = crs_wording.word_run("run-d", [ROW], provider=fake)
    assert fake.asked == [] and crs_wording.stored("run-d") == {}
    assert summary["enabled"] is False and "off" in summary["stopped"]


def test_a_malformed_answer_is_refused():
    class Bad(_Fake):
        def reason(self, packet):
            return SimpleNamespace(text="not json", provider="fake", model_tag="f", schema_errors=())
    text, reason, _ = crs_wording._ask(Bad([]), ROW)
    assert text is None and reason == crs_wording.MALFORMED


def _views(world, run_id):
    scope = access.AccessScope(user_id="adm", allowed_document_ids=world["scope"])
    out = {}
    for copy in ("internal", "issue"):
        rows, meta, _n, _s = main._crs_content(run_id, scope, copy)
        out[copy] = crs_export.build_crs_view(rows, meta)["rows"]
    return out


def _review(world, monkeypatch, fake):
    monkeypatch.setattr(crs_wording, "_provider", lambda: fake)
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
    return run_id


def _worded(row):
    """A faithful rewrite of a world row: its own template, re-voiced."""
    return "Please: " + row["comment"]


def test_a_finished_review_prints_the_ai_wording_in_the_internal_copy_only(
        world, monkeypatch, wording_on):
    class Echo(_Fake):
        def reason(self, packet):
            self.asked.append(packet)
            comment = packet.prompt.split("Comment: ", 1)[1].strip()
            return SimpleNamespace(text=json.dumps({"comment": _worded({"comment": comment})}),
                                   provider="fake", model_tag="fake-1", schema_errors=())
    fake = Echo([])
    run_id = _review(world, monkeypatch, fake)
    assert fake.asked, "the review asked the model to word its CRS comments"
    views = _views(world, run_id)
    internal = [r for r in views["internal"] if r["row_kind"] == "non_compliant"]
    assert internal and internal[0]["ai_review_comment"].startswith("Please: ")
    # the template is untouched beside it
    assert not internal[0]["comment"].startswith("Please note")
    assert crs_wording.summary_of(run_id)["accepted"] == len(fake.asked)
    assert all(not r["ai_review_comment"] for r in views["issue"])


def _confirm_noise_row(world, monkeypatch, run_id):
    """Store AI wording for the noise row, then make that row an engineer's
    (a permanent number on record, read through `crs_numbers.lookup`)."""
    scope = access.AccessScope(user_id="adm", allowed_document_ids=world["scope"])
    rows, _m, _n, _s = main._crs_content(run_id, scope, "internal")
    key = next(r["crs_row_key"] for r in rows if r["row_kind"] == "non_compliant")
    from app.db import connect
    crs_wording.ensure_schema()
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO crs_ai_wording (review_run_id,row_key,ai_text,model,"
                     "prompt_version,created_at) VALUES (?,?,?,?,?,?)",
                     (run_id, key, "worded", "fake", "v", "now"))
    monkeypatch.setattr(main.crs_numbers_mod, "lookup",
                        lambda scope, keys: {key: {"ref": "CRS-X-001", "status": "open",
                                                   "row_key": key}} if key in keys else {})
    monkeypatch.setattr(main.crs_numbers_mod, "resolution_cell", lambda r: "Open")
    monkeypatch.setattr(main.crs_numbers_mod, "response_cell", lambda r: "")
    return key


def test_a_confirmed_row_never_shows_ai_wording(world, monkeypatch, wording_on):
    run_id = _review(world, monkeypatch, _Fake([]))
    key = _confirm_noise_row(world, monkeypatch, run_id)
    rows, _m, _n, _s = main._crs_content(
        run_id, access.AccessScope(user_id="adm", allowed_document_ids=world["scope"]), "internal")
    row = next(r for r in rows if r["crs_row_key"] == key)
    assert row["engineer_confirmed"] and not row.get("ai_review_comment")


def test_stored_wording_never_drops_a_confirmed_comment_from_the_issue_copy(
        world, monkeypatch, wording_on):
    """The issue copy drops any row carrying AI text as a draft: wording on a
    confirmed row would silently remove an engineer's comment from what the
    contractor receives."""
    run_id = _review(world, monkeypatch, _Fake([]))
    _confirm_noise_row(world, monkeypatch, run_id)
    issued = _views(world, run_id)["issue"]
    assert [r["crs_ref"] for r in issued] == ["CRS-X-001"]
    from app.db import connect
    with connect() as conn:
        conn.execute("DELETE FROM crs_ai_wording WHERE review_run_id = ?", (run_id,))
    assert _views(world, run_id)["issue"] == issued


def test_a_wording_failure_never_fails_the_review(world, monkeypatch, wording_on):
    def boom(*a, **k):
        raise RuntimeError("synthetic wording failure")
    monkeypatch.setattr(crs_wording, "word_run", boom)
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
