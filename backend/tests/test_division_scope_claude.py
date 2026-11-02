"""Division scope's Claude route: its own engine setting, every Claude gate, no local engine.

Fake transport only; no socket, no real call. Invented standard text and values (rule 13).
"""

from __future__ import annotations

import json

import httpx
import pytest

from app import (
    ai_applicability,
    ai_task_runner,
    claude_answer_cache,
    claude_approved,
    claude_spend,
    comparison,
    db,
    division_claude,
    division_text,
    local_engine_bar,
    model_transport,
    reader_transport,
    review_jobs,
    subject_scope,
)
from app import reasoning_provider as rp
from app.config import Settings, settings
from tests.test_141_division_scope import (
    GENERAL,
    LIMITED,
    LIMITED_TT,
    NOT_GRAPHITE,
    NOT_LIMITED,
    PAGES,
    SPECIAL,
    STEEL,
    TITAN,
    TT_SCOPE,
    ZZ_SCOPE,
)
from tests.test_p3_review_jobs import (  # noqa: F401 - fixtures
    _enqueue,
    temp_storage,
    world,
)

STEP = division_text.CLAUDE_STEP
AA_SCOPE = "The rules of Part AA apply to all vessels of this code."
NO_SENTENCE = "PART QQ\nGENERAL NOTES\nQQ-1 Bolts shall be tight.\n"
UNSURE = {"limited": "unsure", "construction": None, "quote": None}


def _reply_to(prompt: str) -> dict:
    if "\nSTATED:\n" in prompt:
        return NOT_GRAPHITE
    if '"titles"' in prompt:
        return {"titles": []}
    if ZZ_SCOPE in prompt:
        return {**LIMITED, "scope_sentence": ZZ_SCOPE}
    if TT_SCOPE in prompt:
        return {**LIMITED_TT, "scope_sentence": TT_SCOPE}
    return {**NOT_LIMITED, "scope_sentence": AA_SCOPE}


def _prompt(body: dict) -> str:
    return str(body["messages"][0]["content"])


@pytest.fixture
def send():
    def fake(url, *, headers, body, timeout):
        fake.bodies.append(body)
        return {
            "model": body["model"],
            "stop_reason": "end_turn",
            "content": [
                {
                    "type": "text",
                    "text": fake.wrap(json.dumps(fake.reply(_prompt(body)))),
                }
            ],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

    fake.bodies = []
    fake.wrap = lambda text: text
    fake.reply = _reply_to
    fake.usage = {}
    return fake


@pytest.fixture
def engine_calls(monkeypatch):
    calls = []

    def raising(path, *a, **k):
        calls.append(path)
        raise AssertionError(f"the local engine was reached: {path}")

    for name in ("post_json", "post_json_retrying", "stream_json", "get_json"):
        monkeypatch.setattr(model_transport, name, raising)
    monkeypatch.setattr(ai_task_runner, "_tags_cache", {})
    monkeypatch.setattr(ai_task_runner, "_IDENTITY_MEMO", {})
    return calls


@pytest.fixture(autouse=True)
def lane(tmp_path, monkeypatch, send):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.setattr(settings, "ai_division_scope_engine", "claude")
    monkeypatch.setattr(settings, "ai_division_scope_enabled", True)
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-invented")
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "claude_cache")
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    for name in (
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
        "ANTHROPIC_API_KEY",
        "STANDARDS_READER_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(subject_scope, "standard_pages", lambda sid: PAGES)
    monkeypatch.setattr(reader_transport, "transport", lambda: send)
    return monkeypatch


def _gate():
    return ai_applicability.division_gate_for_run(
        [dict(r) for r in (GENERAL, SPECIAL, TITAN)],
        {"equipment_type": "Pressure vessel"},
        STEEL,
        {"std": "XYZ code"},
    )


def _ids(rows):
    return sorted(r.get("id") or r["requirement"]["id"] for r in rows)


# ------------------------------------------------------------------- the setting


def test_the_engine_is_local_by_default_and_is_in_the_config_version(monkeypatch):
    from app.config import ANSWER_AFFECTING_SETTINGS

    monkeypatch.delenv("AI_DIVISION_SCOPE_ENGINE", raising=False)
    assert Settings.model_fields["ai_division_scope_engine"].default == "ollama"
    assert "ai_division_scope_engine" in ANSWER_AFFECTING_SETTINGS


# ------------------------------------------------------------------- setting on


def test_with_the_setting_on_no_rule_is_held_for_lack_of_the_local_engine(
    send, engine_calls
):
    with local_engine_bar.bar():
        out = _gate()
        assert local_engine_bar.stated() == []
    summary = out["summary"]
    assert engine_calls == []
    assert send.bodies, "Claude was not asked"
    assert summary["could_not_read"] == 0 and summary["read"] > 0
    assert (
        "stopped" not in summary and "requirements_held_scope_not_read" not in summary
    )
    assert "aa" in _ids(out["kept"])
    assert {b["model"] for b in send.bodies} == {settings.claude_reasoning_model}


def test_every_call_is_on_one_step_under_the_ledger(send):
    _gate()
    lines = [e for e in claude_spend.entries() if e.get("settles")]
    assert len(lines) == len(send.bodies) and {e["step"] for e in lines} == {STEP}
    assert claude_spend.spent(STEP) > 0


def test_only_the_passage_is_sent_never_the_whole_standard(send):
    _gate()
    for body in send.bodies:
        prompt = _prompt(body)
        assert not (ZZ_SCOPE in prompt and TT_SCOPE in prompt)
    assert not any(
        "Titanium welds" in _prompt(b) and ZZ_SCOPE in _prompt(b) for b in send.bodies
    )


def test_a_repeat_run_is_answered_from_the_cache_at_no_cost(send):
    first = _gate()
    asked, paid = len(send.bodies), claude_spend.spent()
    second = _gate()
    assert len(send.bodies) == asked and claude_spend.spent() == paid
    assert _ids(second["kept"]) == _ids(first["kept"])
    report = claude_spend.cache_report()
    assert report["hits"] == asked


def test_a_stored_answer_is_only_in_the_gated_store_not_the_task_table(send):
    """The task table has no approved-list gate: a Claude answer must not be kept there."""
    _gate()
    assert list(claude_answer_cache._root().rglob("*.json"))
    rows = (
        ai_task_runner.connect()
        .execute("SELECT COUNT(*) FROM ai_task_cache")
        .fetchone()[0]
    )
    assert rows == 0


def test_a_fenced_reply_reads_as_the_answer(send):
    send.wrap = lambda text: f"```json\n{text}\n```"
    out = _gate()
    assert out["summary"]["could_not_read"] == 0


# ------------------------------------------------------------------- setting off


def test_with_the_setting_off_nothing_goes_to_claude_and_the_skip_counts_every_part(
    send, engine_calls, monkeypatch
):
    monkeypatch.setattr(settings, "ai_division_scope_engine", "ollama")
    with local_engine_bar.bar():
        out = _gate()
        stated = local_engine_bar.stated()
    assert send.bodies == [] and engine_calls == []
    unread = out["summary"]["could_not_read"]
    assert unread == 3 and out["summary"]["requirements_held_scope_not_read"] == 3
    assert stated == [
        {
            "step": "ai_task:division_scope",
            "calls_not_made": unread,
            "note": local_engine_bar.NOTE,
        }
    ]
    assert out["kept"] == []


def test_the_provider_switch_on_ollama_wins_over_the_setting(send, monkeypatch):
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    assert division_text.claude_reader() is None
    assert send.bodies == []


def test_with_egress_off_claude_is_not_used(send, monkeypatch):
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", False)
    assert division_text.claude_reader() is None


def test_an_unapproved_document_gets_no_claude_reader(monkeypatch):
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    monkeypatch.setattr(
        claude_approved, "_hashes_of", lambda ids: dict.fromkeys(ids, "aaa")
    )
    monkeypatch.setattr(claude_approved, "_blocked_ids", lambda hashes: frozenset())
    with claude_approved.carrying(["std"]):
        assert division_text.claude_reader() is None


def test_a_blocked_document_gets_no_claude_reader_even_with_the_guard_off(monkeypatch):
    monkeypatch.setattr(
        claude_approved, "_hashes_of", lambda ids: dict.fromkeys(ids, "aaa")
    )
    monkeypatch.setattr(
        claude_approved, "_blocked_ids", lambda hashes: frozenset(hashes)
    )
    with claude_approved.carrying(["std"]):
        assert division_text.claude_reader() is None


# ------------------------------------------------------------------- a failed call


def test_a_failed_call_holds_the_rules_says_so_and_is_charged(lane):
    calls = []

    def fails(url, *, headers, body, timeout):
        calls.append(body)
        raise httpx.ReadTimeout("late")

    lane.setattr(reader_transport, "transport", lambda: fails)
    out = _gate()
    summary = out["summary"]
    assert len(calls) == 1, "a model that stopped answering was asked again"
    assert out["kept"] == [] and sorted(
        r["requirement"]["id"] for r in out["held"]
    ) == [
        "aa",
        "tt",
        "zz",
    ]
    assert summary["requirements_held_scope_not_read"] == 3 and summary["stopped"]
    assert claude_spend.spent(STEP) > 0, (
        "a call that may have been billed was not charged"
    )


def test_a_usd_cap_holds_the_rules_and_sends_nothing(send, monkeypatch):
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 0.0000001)
    out = _gate()
    assert send.bodies == []
    assert out["kept"] == [] and out["summary"]["requirements_held_scope_not_read"] == 3
    said = out["summary"]["stopped"]
    assert (
        ai_task_runner.STOPPED_BY_BUDGET in said and "could not be reached" not in said
    )


def test_the_approved_list_stopping_a_call_says_so_not_unreachable(send, monkeypatch):
    def refused(*a, **k):
        raise claude_spend.DocumentNotApproved(claude_approved.NOT_APPROVED, "ids only")

    monkeypatch.setattr(claude_spend, "_refuse_unapproved", refused)
    out = _gate()
    assert send.bodies == [] and out["kept"] == []
    said = out["summary"]["stopped"]
    assert ai_task_runner.STOPPED_BY_LIST in said and "could not be reached" not in said


def test_an_invalid_reply_holds_that_part_and_is_never_asked_twice(send):
    send.wrap = lambda text: "not json at all"
    out = _gate()
    assert out["summary"]["could_not_read"] == 3
    assert len(send.bodies) == 3, "a repeat read on the Claude lane costs money (#1288)"
    assert out["kept"] == []


def test_no_document_text_reaches_the_log(send, caplog):
    with caplog.at_level("DEBUG"):
        _gate()
    assert ZZ_SCOPE not in caplog.text and TT_SCOPE not in caplog.text
    assert ZZ_SCOPE not in settings.claude_spend_log.read_text("utf-8")


# ------------------------------------------------- the claim about the scope sentence


def _claude_task():
    return division_claude.for_provider(
        ai_applicability.SCOPE_TASK, rp.ClaudeProvider("m")
    )


@pytest.mark.parametrize(
    ("reply", "text", "wanted"),
    [
        ({**NOT_LIMITED, "scope_sentence": None}, NO_SENTENCE, None),
        ({**NOT_LIMITED, "scope_sentence": AA_SCOPE}, AA_SCOPE, None),
        ({**UNSURE, "scope_sentence": AA_SCOPE}, AA_SCOPE, None),
        ({**UNSURE, "scope_sentence": None}, NO_SENTENCE, "unsure needs"),
        ({**NOT_LIMITED, "scope_sentence": None}, AA_SCOPE, "words of scope"),
        (
            {**NOT_LIMITED, "scope_sentence": "An invented sentence."},
            NO_SENTENCE,
            "not in the TEXT",
        ),
    ],
)
def test_code_checks_the_claim_about_the_scope_sentence(reply, text, wanted):
    said = _claude_task().check(reply, text)
    assert (said == []) if wanted is None else (wanted in said[0])


def _sentence_of(prompt: str) -> dict:
    sentence = next(s for s in (ZZ_SCOPE, TT_SCOPE, AA_SCOPE) if s in prompt)
    return {**NOT_LIMITED, "scope_sentence": sentence}


def test_a_rejected_reply_gets_one_corrective_ask_is_charged_and_the_reason_is_recorded(
    send,
):
    calls = []

    def reply(prompt):
        if '"titles"' in prompt:
            return {"titles": []}
        calls.append(prompt)
        wrong = {**UNSURE, "scope_sentence": None}
        return (
            _sentence_of(prompt) if "previous answer was rejected" in prompt else wrong
        )

    send.reply = reply
    out = _gate()
    summary = out["summary"]
    assert len(calls) == 6, "each of 3 parts: one ask, one corrective ask"
    assert summary["could_not_read"] == 0
    assert list(summary["replies_rejected_by_code"].values()) == [3]
    assert sum(1 for e in claude_spend.entries() if e.get("settles")) == 9  # 3 screens
    assert ZZ_SCOPE not in json.dumps(summary["replies_rejected_by_code"])


def test_two_rejections_hold_the_part_and_there_is_never_a_third_ask(send):
    send.reply = lambda prompt: {**UNSURE, "scope_sentence": None}
    out = _gate()
    assert len(send.bodies) == 6
    assert out["summary"]["could_not_read"] == 3 and out["kept"] == []
    assert list(out["summary"]["replies_rejected_by_code"].values()) == [6]


def test_a_rejected_reply_is_not_stored_and_a_repeat_pays_only_for_that(send):
    def reply(prompt):
        if '"titles"' in prompt:
            return {"titles": []}
        wrong = {**UNSURE, "scope_sentence": None}
        return (
            _sentence_of(prompt) if "previous answer was rejected" in prompt else wrong
        )

    send.reply = reply
    _gate()
    assert len(send.bodies) == 9  # 3 rejected, 3 corrected, 3 screens
    _gate()
    assert len(send.bodies) == 12, (
        "the rejected first asks are bought again, the answers are not"
    )
    assert claude_spend.cache_report()["hits"] == 6


def test_a_reply_that_does_not_parse_earns_no_corrective_ask(send):
    send.wrap = lambda text: "not json at all"
    _gate()
    assert len(send.bodies) == 3


def test_a_construction_rejection_gets_one_corrective_ask(send):
    stated = (
        '{"equipment_is": "x", "quote": "Not a stated line at all", "is_that": "no"}'
    )
    send.reply = lambda prompt: (
        json.loads(stated) if "\nSTATED:\n" in prompt else _reply_to(prompt)
    )
    _gate()
    asked = [b for b in send.bodies if "\nSTATED:\n" in _prompt(b)]
    assert len(asked) == 4, "two limited parts, each asked at most twice"


FRAGMENT_TEXT = (
    "PART QQ\nQQ-1 SCOPE\nThis part is limited to vessels of invented alloy Z.\n"
)
WHOLE = "This part is limited to vessels of invented alloy Z."


@pytest.mark.parametrize(
    ("sentence", "wanted"),
    [
        ("is limited", "not in the TEXT"),  # under the length: a bare fragment
        ("limited to vessels of invented", "not a whole sentence"),
        ("vessels of invented alloy Z.", "carries no words of scope"),
        (None, "words of scope"),
    ],
)
def test_no_on_a_scope_worded_passage_needs_the_whole_sentence_that_carries_the_words(
    sentence, wanted
):
    reply = {**NOT_LIMITED, "scope_sentence": sentence}
    assert wanted in _claude_task().check(reply, FRAGMENT_TEXT)[0]


def test_limited_to_counts_as_words_of_scope():
    assert _claude_task().check({**NOT_LIMITED, "scope_sentence": None}, WHOLE)


@pytest.mark.parametrize(
    "text",
    [
        "This annex applies only to vessels of invented alloy Z in this code.",
        "The scope of this part is limited to vessels of invented alloy Z.",
    ],
)
def test_a_sentence_that_limits_the_part_cannot_be_read_as_no(text):
    said = _claude_task().check({**NOT_LIMITED, "scope_sentence": text}, text)
    assert "cannot be no" in said[0]
    assert _claude_task().check({**UNSURE, "scope_sentence": text}, text) == []


def test_a_sentence_that_applies_to_all_is_a_good_no():
    assert (
        _claude_task().check({**NOT_LIMITED, "scope_sentence": AA_SCOPE}, AA_SCOPE)
        == []
    )


def test_a_passage_with_scope_words_and_no_such_sentence_holds_the_part(send):
    """Asked twice, then held: the rule never reaches comparison on that reply."""

    def reply(prompt):
        if '"titles"' in prompt:
            return {"titles": []}
        return {**NOT_LIMITED, "scope_sentence": None}

    send.reply = reply
    out = _gate()
    assert out["kept"] == [] and _ids(out["held"]) == ["aa", "tt", "zz"]
    assert out["summary"]["requirements_held_scope_not_read"] == 3
    assert len(send.bodies) == 6


# ------------------------------------------------- the local path stays as it was


def test_the_local_path_is_unchanged():
    local = ai_applicability.SCOPE_TASK
    assert division_claude.for_provider(local, rp.OllamaProvider()) is local
    assert local.version == "v1" and local.claude_retries == 0
    assert "scope_sentence" not in local.schema["properties"]
    assert "scope_sentence" not in local.instruction


def test_a_local_rejection_keeps_its_two_attempts_and_records_nothing_new():
    class Local:
        name = "ollama"
        requested_model = "local-m"
        asked = 0

        def reason(self, packet):
            assert packet.keep_if is None
            Local.asked += 1
            return rp.Response(
                text='{"limited": "yes", "construction": "x", "quote": "not there at all, no"}',
                provider="ollama",
                model_tag="local-m",
                digest="d",
                finish_reason="stop",
                prompt_sha256="p",
            )

    result = ai_task_runner.run_task(
        ai_applicability.SCOPE_TASK,
        "Some invented text.",
        provider=Local(),
        use_cache=False,
    )
    assert Local.asked == 2 and result.rejected == ()
    assert "replies_rejected_by_code" not in division_claude.rejections({})


# ------------------------------------------------- "no" decides nothing about a rule


def test_no_scope_sentence_keeps_the_rule_for_comparison_and_says_nothing_about_it(
    send,
):
    send.reply = lambda prompt: (
        {"titles": []}
        if '"titles"' in prompt
        else {**NOT_LIMITED, "scope_sentence": None}
    )
    lane_pages = [(1, NO_SENTENCE)]
    req = {
        "id": "qq",
        "standard_document_id": "std",
        "page": 1,
        "requirement_text": "Bolts shall be tight.",
        "source_text": "QQ-1 Bolts shall be tight.",
    }
    out = ai_applicability.division_gate(
        [dict(req)],
        classification={"equipment_type": "Pressure vessel"},
        facts=STEEL,
        standard_labels={"std": "XYZ code"},
        provider=division_text.claude_reader(),
        pages_of=lambda sid: lane_pages,
    )
    assert out["kept"] == [req], "the rule goes on to comparison, unchanged"
    assert out["items"] == [] and out["held"] == [] and out["notes"] == {}


def test_a_rule_that_comes_through_on_no_is_never_a_pass_with_nothing_to_compare(
    temp_storage,  # noqa: F811
    world,  # noqa: F811
):
    """Comparison decides, from a value. Here the only value is about something else."""
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next("w")
    with db.connect() as conn:
        conn.execute(
            "UPDATE submittal_facts SET field_name = 'flange rating', field_label = 'Flange rating',"
            " raw_value = '10', field_value = '10', unit = 'bar', raw_unit = 'bar'"
        )
    assert review_jobs.run(job_id, "w") == "done"
    rows = (
        db.connect()
        .execute(
            "SELECT compliance_status, requirement FROM review_findings WHERE review_run_id = ?",
            (run_id,),
        )
        .fetchall()
    )
    noise = [
        r["compliance_status"] for r in rows if "noise" in r["requirement"].lower()
    ]
    assert noise and comparison.COMPLIANT not in noise
