"""#845 (Stage B, #805 rule 7 "AI numbers first"): a finished run's card
shows the AI numbers - reader, matcher, AI engineering check, AI wording -
each with its denominator and "local model" or "cloud model", from what the
run stored. No model is called to show them, and a step with no record is
null (shown as nothing, never 0). Invented documents and a stub model only.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import ai_numbers, comparison, crs_wording, datasheets, db
from app.config import settings
from app.main import app
from tests.test_model_matching import (  # noqa: F401 - fixtures
    MODEL_SUBJECT,
    _world,
    stub,
    temp_storage,
)


@pytest.fixture(autouse=True)
def local_matcher(monkeypatch):
    monkeypatch.setattr(settings, "match_engine", "ollama")
    monkeypatch.setattr(settings, "answer_model", "test-model:1b")


def _matched_run(stub, monkeypatch, *answers, **over):
    stub(*answers, **over)
    _std, _sub, run, scope = _world(monkeypatch, subject=MODEL_SUBJECT,
                                    field_label="Shell design pressure")
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    return run, scope, result


def _stored_matcher(run, scope):
    return comparison.run_outcome(run, allowed_document_ids=scope)["ai_matcher"]


def _card(run):
    client = TestClient(app)
    runs = client.get("/api/reviews/runs").json()["runs"]
    return next(r for r in runs if r["review_run_id"] == run)


# ----------------------------------------------------------- the matcher

def test_a_used_pairing_is_stored_on_the_run_with_its_denominators(stub, monkeypatch):
    run, scope, result = _matched_run(stub, monkeypatch, (0, "both are the shell design pressure"))
    stored = _stored_matcher(run, scope)
    assert stored == result["ai_matcher"]
    assert stored["enabled"] is True and stored["model"] == "ollama:test-model:1b"
    assert (stored["sent"], stored["asked"], stored["proposed"], stored["used"],
            stored["held"], stored["refused_by_rule"]) == (1, 1, 1, 1, 0, 0)

    card = _card(run)["ai_numbers"]["matcher"]
    assert card["where"] == "local model"
    assert card["lines"][0] == "Asked about 1 of 1 requirement(s) the match rules could not pair."
    assert card["lines"][1] == ("Of 1 pairing(s) proposed: 1 used (0 held for the engineer), "
                                "0 refused by a match rule.")


def test_a_proposal_a_rule_refused_is_counted_as_proposed_and_refused(stub, monkeypatch):
    from app import match_rules
    monkeypatch.setattr(match_rules, "refusal", lambda *a, **k: match_rules.QUALIFIER)
    run, scope, _ = _matched_run(stub, monkeypatch, (0, "same quantity"))
    stored = _stored_matcher(run, scope)
    assert (stored["proposed"], stored["used"], stored["refused_by_rule"]) == (1, 0, 1)
    assert "1 refused by a match rule" in _card(run)["ai_numbers"]["matcher"]["lines"][1]


def test_a_declined_requirement_is_counted_among_those_asked(stub, monkeypatch):
    run, scope, _ = _matched_run(stub, monkeypatch, (None, "no candidate is that quantity"))
    stored = _stored_matcher(run, scope)
    assert (stored["asked"], stored["proposed"], stored["declined"]) == (1, 0, 1)
    assert _card(run)["ai_numbers"]["matcher"]["lines"][2] == (
        "Of 1 asked: 0 proposed, 1 declined, 0 unavailable (time-out or model down).")


def test_an_unavailable_model_makes_the_step_incomplete(stub, monkeypatch):
    run, scope, _ = _matched_run(stub, monkeypatch, raises=RuntimeError("timed out"))
    assert _stored_matcher(run, scope)["unavailable"] == 1
    card = _card(run)["ai_numbers"]["matcher"]
    assert card["state"] == "incomplete"
    assert "1 unavailable (time-out or model down)" in card["lines"][2]


def test_a_spent_budget_is_not_counted_as_asked(stub, monkeypatch):
    monkeypatch.setattr(settings, "match_max_calls_per_run", 0)
    run, scope, _ = _matched_run(stub, monkeypatch, (0, "same quantity"))
    stored = _stored_matcher(run, scope)
    assert (stored["sent"], stored["asked"], stored["not_asked_budget"]) == (1, 0, 1)
    assert "1 not asked: the call budget was spent" in _card(run)["ai_numbers"]["matcher"]["lines"][0]


def test_a_requirement_with_no_candidate_field_is_not_counted_as_asked(stub, monkeypatch):
    asked = stub((0, "never asked"))
    _std, _sub, run, scope = _world(monkeypatch, subject=MODEL_SUBJECT,
                                    field_label="Shell design pressure", raw_value="200 mm")
    comparison.run_comparison(run, allowed_document_ids=scope)
    stored = _stored_matcher(run, scope)
    assert asked.calls == 0
    assert (stored["sent"], stored["asked"], stored["no_candidates"]) == (1, 0, 1)
    assert "(1 had no candidate field)" in _card(run)["ai_numbers"]["matcher"]["lines"][0]


def test_the_matcher_switched_off_says_off_not_zero(stub, monkeypatch):
    monkeypatch.setattr(settings, "match_enabled", False)
    run, scope, _ = _matched_run(stub, monkeypatch, (0, "never asked"))
    assert _stored_matcher(run, scope) == {"enabled": False}
    card = _card(run)["ai_numbers"]["matcher"]
    assert card["state"] == "off" and "0" not in " ".join(card["lines"])


# ------------------------------------------------- the route, and no record

def test_the_route_reads_the_stored_numbers_and_calls_no_model(stub, monkeypatch):
    run, _scope, _ = _matched_run(stub, monkeypatch, (0, "same quantity"))
    asked = stub((0, "must not be asked again"))
    body = TestClient(app).get(f"/api/reviews/runs/{run}/ai-numbers").json()
    assert asked.calls == 0
    assert body["review_run_id"] == run
    assert body["matcher"]["lines"][1].startswith("Of 1 pairing(s) proposed: 1 used")
    # NO RECORD IS NULL, NEVER A ZERO: this run had no AI check and no wording.
    assert body["engineering_check"] is None and body["wording"] is None


def test_a_run_with_no_ai_record_shows_nothing(stub, monkeypatch):
    """A run stored before #845 (no `ai_matcher`) and with no other AI step:
    the card carries no AI numbers at all, rather than a row of zeros."""
    run, _scope, _ = _matched_run(stub, monkeypatch, (0, "same quantity"))
    with db.connect() as conn:
        stored = json.loads(conn.execute("SELECT outcome_json FROM review_runs WHERE id = ?",
                                         (run,)).fetchone()["outcome_json"])
        stored.pop("ai_matcher")
        conn.execute("UPDATE review_runs SET outcome_json = ? WHERE id = ?",
                     (json.dumps(stored), run))
    assert _card(run)["ai_numbers"] is None
    body = TestClient(app).get(f"/api/reviews/runs/{run}/ai-numbers").json()
    assert all(body[k] is None for k in ("reader", "matcher", "engineering_check", "wording"))


def test_an_unknown_run_is_404():
    assert TestClient(app).get("/api/reviews/runs/no-such-run/ai-numbers").status_code == 404


def test_the_ai_check_and_the_wording_come_from_their_stored_records(stub, monkeypatch):
    run, _scope, _ = _matched_run(stub, monkeypatch, (0, "same quantity"))
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET ai_check_status = ? WHERE id = ?", (json.dumps({
            "ran": True, "complete": True, "proposed_items": 5, "kept_items": 3,
            "model": "ollama:local-check", "local_instead": "ran on the local model",
            "plain": "AI engineering check complete: 3 of 5 proposed item(s) kept, over 1 call."}),
            run))
    crs_wording._store_summary(run, {"enabled": True, "model": "claude:sonnet", "tried": 4,
                                     "accepted": 3, "refused": {"number changed": 1},
                                     "not_tried": 0, "stopped": None, "local_instead": None})
    numbers = _card(run)["ai_numbers"]
    check = numbers["engineering_check"]
    assert check["where"] == "local model" and check["local_instead"] == "ran on the local model"
    assert check["lines"] == ["AI engineering check complete: 3 of 5 proposed item(s) kept, over 1 call."]
    words = numbers["wording"]
    assert words["where"] == "cloud model"
    assert words["lines"] == ["Of 4 row(s) worded: 3 kept, 1 refused by the lock (1 number changed)."]


# --------------------------------------------------------------- the reader

def test_the_reader_summary_counts_what_the_code_gate_refused():
    run = {"engine": "ollama", "model": "m", "pages": {1: {}, 2: {"error": "timed out"}},
           "reasons": {2: "timed out"}, "timed_out": [2]}
    stats = {"agreed": 4, "conflicts": 1, "ai_only": 2, "unconfirmed": 3,
             "proposals_rejected": {"quote not on the page": 2}, "dropped": {"duplicate": 1}}
    summary = datasheets.reader_summary(run, stats, pages=[1, 2])
    assert summary["refused_by_gate"] == 3 and summary["unconfirmed"] == 3


def test_the_reader_line_states_each_count_out_of_its_whole():
    step = ai_numbers.reader({"engine": "ollama", "model": "qwen", "pages": 3, "pages_read": 2,
                              "code_only": {"3": "timed out"}, "timed_out": [3],
                              "agreed": 4, "conflicts": 1, "ai_only": 2, "refused_by_gate": 3})
    assert step["where"] == "local model"
    assert step["lines"] == [
        "2 of 3 page(s) read by the AI; 1 timed out; 1 left to the code readers (1 timed out).",
        "Of 7 value(s) the AI read: 4 agreed with the code readers, 1 in conflict, 2 read by the AI only.",
        "3 of 10 AI reading(s) refused by the code gate.",
    ]


def test_a_reader_summary_from_before_the_gate_count_prints_no_gate_line():
    step = ai_numbers.reader({"engine": "claude", "pages": 1, "pages_read": 1,
                              "agreed": 1, "conflicts": 0, "ai_only": 0})
    assert step["where"] == "cloud model"
    assert not any("gate" in line for line in step["lines"])


def test_the_reader_off_says_the_code_readers_read_every_page():
    step = ai_numbers.reader({"engine": "off", "pages": 4})
    assert step["state"] == "off" and step["where"] is None
    assert step["lines"] == ["Off: the code readers read all 4 page(s)."]
