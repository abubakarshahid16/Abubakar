"""The paid read of each Part's scope sentence, with an injected transport: nothing leaves. Invented text only."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from app import claude_spend, db, rule_part_scope
from app.config import settings
from app.rule_part_scope import GENERAL, OUTSIDE, UNKNOWN
from tests.test_1584_standards_compiler import (
    _document,
    lane,  # noqa: F401
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import read_part_scopes
from read_part_scopes import JOB_CAP_USD, read_standard

DOC = "std-parts"
LABEL = "SAES-Z-901"
TYPE = "Pressure Relief Valve"
MODEL = "claude-sonnet-5-5"
OPEN = "The rules of Part XG apply to all invented equipment and to its parts."
DRUMS = "The rules of Part XD apply to glazed drums made of lined plate and strip."
OPEN_RULE = "Each invented valve shall carry an invented mark."
DRUM_RULE = "Each glazed drum shall carry an invented mark."
PAGES = (
    f"PART XG\nGENERAL RULES\nXG-1\nSCOPE\n{OPEN}\nXG-2\n{OPEN_RULE}",
    f"PART XD\nGLAZED DRUMS\nXD-1\nSCOPE\n{DRUMS}\nXD-2\n{DRUM_RULE}",
)
GENERAL_REPLY = {
    "limited": "no",
    "construction": None,
    "quote": None,
    "scope_sentence": OPEN,
}
LIMITED_REPLY = {
    "limited": "yes",
    "construction": "glazed drums",
    "quote": DRUMS,
    "scope_sentence": DRUMS,
}


class Fake:
    """The Messages transport, answering by which Part's text the prompt holds."""

    def __init__(self, drums=LIMITED_REPLY, usage=None):
        self.bodies = []
        self.drums = drums
        self.usage_of_reply = usage or {"input_tokens": 100, "output_tokens": 50}

    def __call__(self, url, *, headers, body, timeout):
        self.bodies.append(body)
        prompt = body["messages"][0]["content"]
        reply = self.drums if "PART XD" in prompt else GENERAL_REPLY
        if callable(reply):
            reply = reply(len(self.bodies))
        return {
            "model": body["model"],
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(reply)}],
            "usage": self.usage_of_reply,
        }


@pytest.fixture
def standard(monkeypatch):
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.setattr(settings, "ai_division_scope_engine", "claude")
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    _document(DOC, LABEL, pages=PAGES)
    conn = db.connect()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS compiled_rules (id TEXT, standard_document_id TEXT, clause TEXT, page INT, quote TEXT)"
    )
    with conn:
        conn.executemany(
            "INSERT INTO compiled_rules (id, standard_document_id, clause, page, quote) VALUES (?,?,?,?,?)",
            [
                ("r1", DOC, "XG-2", 1, OPEN_RULE),
                ("r2", DOC, "XD-2", 2, DRUM_RULE),
            ],
        )
    return conn


def _read(conn, fake, **kw):
    return read_standard(conn, DOC, LABEL, TYPE, dry_run=False, send=fake, **kw)


def _scope(conn, clause, page, quote):
    rule = {"document_id": DOC, "clause": clause, "page": page, "quote": quote}
    return rule_part_scope.of_rule(conn, rule, TYPE)


def test_a_dry_run_sends_nothing_prints_the_worst_case_and_needs_no_key(
    standard, monkeypatch
):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    fake = Fake()
    report = read_standard(standard, DOC, LABEL, TYPE, send=fake)
    assert fake.bodies == [] and report["status"] == "dry"
    assert (report["parts"], report["parts_to_ask"]) == (2, 2)
    assert 0 < report["worst_usd"] < report["cap_usd"] == JOB_CAP_USD
    assert (
        report["worst_usd_if_every_part_also_needs_a_corrective_ask"]
        > report["worst_usd"]
    )
    assert claude_spend.entries() == []


def test_the_read_goes_through_the_ledger_and_stores_what_the_scope_reads(standard):
    fake = Fake()
    report = _read(standard, fake)
    assert (
        report["status"] == "done" and report["stored"] == 2 and len(fake.bodies) == 2
    )
    assert {b["model"] for b in fake.bodies} == {MODEL}
    steps = {e["step"] for e in claude_spend.entries()}
    assert steps == {f"{read_part_scopes.STEP_PREFIX}{DOC}"}
    assert _scope(standard, "XG-2", 1, OPEN_RULE).state == GENERAL
    assert _scope(standard, "XD-2", 2, DRUM_RULE).state == OUTSIDE
    assert report["rules_by_state"] == {GENERAL: 1, OUTSIDE: 1}


def test_a_second_run_asks_nothing(standard):
    _read(standard, Fake())
    again = Fake()
    report = _read(standard, again)
    assert again.bodies == [] and report["parts_to_ask"] == 0


def test_a_worst_case_above_the_cap_stops_before_sending(standard):
    fake = Fake()
    report = _read(standard, fake, cap=0.00001)
    assert report["status"] == "over_cap" and fake.bodies == []
    assert claude_spend.entries() == []


def test_the_cap_cannot_be_raised():
    with pytest.raises(ValueError):
        read_standard(None, DOC, LABEL, TYPE, cap=JOB_CAP_USD + 1)


def test_a_call_that_could_cross_the_job_cap_is_not_made(standard, monkeypatch):
    """The first asks fit; what is on the ledger by then does not leave room for the next."""
    fake = Fake(usage={"input_tokens": 100, "output_tokens": 50})
    first = read_standard(standard, DOC, LABEL, TYPE, send=fake)["worst_usd"]
    real = claude_spend.step_spent
    monkeypatch.setattr(
        read_part_scopes.claude_spend,
        "step_spent",
        lambda step: real(step) + (first if fake.bodies else 0.0),
    )
    report = _read(standard, fake, cap=first + 0.001)
    assert report["status"] == "partial" and len(fake.bodies) == 1


def test_a_document_off_the_approved_list_is_refused_and_nothing_is_sent(
    standard, monkeypatch
):
    from app import claude_approved

    claude_approved.list_path().unlink()
    fake = Fake()
    report = _read(standard, fake)
    assert report["status"] == "refused" and report["sent"] == 0 and fake.bodies == []


def test_the_engine_setting_off_is_refused(standard, monkeypatch):
    monkeypatch.setattr(settings, "ai_division_scope_engine", "ollama")
    fake = Fake()
    assert _read(standard, fake)["status"] == "refused" and fake.bodies == []


def test_a_rejected_reply_gets_one_corrective_ask_then_is_not_stored(standard):
    wrong = {**LIMITED_REPLY, "quote": "Words that are not in the text at all here."}
    fake = Fake(drums=wrong)
    report = _read(standard, fake)
    asked = [b for b in fake.bodies if "PART XD" in b["messages"][0]["content"]]
    assert len(asked) == 2 and "previous answer was rejected" in str(asked[1])
    assert report["status"] == "partial" and report["not_stored"] == 1
    assert _scope(standard, "XD-2", 2, DRUM_RULE).state == UNKNOWN


def test_a_no_whose_sentence_does_not_say_all_is_rejected(standard):
    fake = Fake(drums={**GENERAL_REPLY, "scope_sentence": DRUMS})
    report = _read(standard, fake)
    assert report["not_stored"] == 1
    assert _scope(standard, "XD-2", 2, DRUM_RULE).state == UNKNOWN


def test_a_corrective_ask_can_be_accepted(standard):
    wrong = {**LIMITED_REPLY, "quote": "Words that are not in the text at all here."}
    seen = []

    def once_wrong(_n):
        seen.append(1)
        return wrong if len(seen) == 1 else LIMITED_REPLY

    report = _read(standard, Fake(drums=once_wrong))
    assert report["status"] == "done" and report["rejected_by_code"] == 1
    assert _scope(standard, "XD-2", 2, DRUM_RULE).state == OUTSIDE


def test_a_stored_reading_that_disagrees_leaves_the_rule_unknown_and_is_counted(
    standard,
):
    from app import ai_applicability, ai_task_runner

    ai_task_runner.ensure_schema()
    passage = next(
        p["passage"]
        for p in rule_part_scope.parts_of(standard, DOC)
        if p["label"] == "Part XD"
    )
    spec = ai_applicability.SCOPE_TASK
    with standard:
        standard.execute(
            "INSERT INTO ai_task_cache (key, task, version, model, result_json, created_at) VALUES (?,?,?,?,?,?)",
            (
                ai_task_runner.cache_key(spec, "local-model", passage),
                spec.name,
                spec.version,
                "local-model",
                json.dumps({"limited": "no", "construction": None, "quote": DRUMS}),
                "2026-11-02",
            ),
        )
    report = _read(standard, Fake())
    said = _scope(standard, "XD-2", 2, DRUM_RULE)
    assert said.state == UNKNOWN and said.disagreement
    assert report["rules_held_by_a_disagreement"] == 1
    assert report["parts_with_a_disagreement"] == 1


def test_a_sentence_not_on_the_page_stays_unknown(standard):
    """Past the passage's check, the page's check still stands: nothing stored can be taken on its word."""
    from app import ai_task_runner

    part = next(
        p for p in rule_part_scope.parts_of(standard, DOC) if p["label"] == "Part XD"
    )
    ai_task_runner.ensure_schema()
    read_part_scopes._store(
        standard,
        MODEL,
        part["passage"],
        {**LIMITED_REPLY, "quote": "A sentence of no page of this invented code."},
    )
    assert _scope(standard, "XD-2", 2, DRUM_RULE).state == UNKNOWN


def test_the_report_carries_no_document_text(standard):
    report = json.dumps(_read(standard, Fake()))
    for words in ("glazed", "invented", "Part XD", "Part XG"):
        assert words not in report


def test_the_script_is_dry_without_send_and_refuses_a_missing_copy(
    standard, tmp_path, capsys
):
    said = []
    fake = Fake()
    code = read_part_scopes.main(
        ["--db", str(settings.db_path), "--standard", DOC, "--type", TYPE],
        send=fake,
        emit=said.append,
    )
    assert code == 0 and fake.bodies == []
    assert json.loads(said[0])["status"] == "dry"
    with pytest.raises(SystemExit):
        read_part_scopes.main(
            ["--db", str(tmp_path / "none.sqlite"), "--standard", DOC, "--type", TYPE]
        )


def test_the_script_sends_only_when_told(standard):
    said = []
    fake = Fake()
    code = read_part_scopes.main(
        ["--db", str(settings.db_path), "--standard", DOC, "--type", TYPE, "--send"],
        send=fake,
        emit=said.append,
    )
    assert code == 0 and len(fake.bodies) == 2


def test_nothing_here_names_a_standard_or_a_part():
    root = Path(__file__).resolve().parents[2]
    for path in (
        root / "backend/app/rule_part_scope.py",
        root / "scripts/read_part_scopes.py",
    ):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b(ASME|SAES|UCL|UG-\d|VIII|kettle)", text), path
