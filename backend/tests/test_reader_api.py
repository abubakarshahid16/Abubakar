"""The gate, and the four ways a reader of standards gets a clause wrong.

Every test here runs against a FAKE MODEL and no transport: the reader takes
its model as a callable, so the whole gate is exercised with no API key, no
network and no Ollama - `extraction_llm.py`'s arrangement, kept deliberately.

THE FOUR TRAPS EACH HAVE A TEST, and all four are real clauses from this
corpus rather than invented examples:

  * TRIGGER vs LIMIT - "...in excess of 85 dB(A) shall submit Form 7305-ENG"
    is paperwork. Read as a ceiling it fails a compliant submittal at 90.
  * MINIMUM - "the minimum cement content shall be 370 kg/m3" is `>= 370`.
    Stored as `= 370` it fails every design that exceeds the minimum.
  * BARE EQUALITY - "The allowable concrete bearing stress shall be 8,300
    kPa" genuinely is `=`, and must survive the gate; a gate tuned only to
    reject would pass its trap tests by rejecting everything.
  * FABRICATION - a quote that is not in the sentence cannot pass, however
    plausible it sounds.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app import reader_api as app_reader_api
from app.reader_api import (
    API_KEY_ENV,
    ReaderRefused,
    ReaderSettings,
    Reason,
    accept,
    build_request,
    direction_of_quote,
    looks_like_a_trigger,
    model_call_via,
    parse_response,
    read_sentence,
    read_sentences,
    requirement_type_of,
)

# -------------------------------------------------- the clauses, as written

NOISE_TRIGGER = ("Equipment generating noise in excess of 85 dB(A) shall "
                 "submit Form 7305-ENG to the Proponent.")
CEMENT = "The minimum cement content shall be 370 kg/m3."
BEARING = "The allowable concrete bearing stress shall be 8,300 kPa."
NOISE_LIMIT = "The noise level shall not exceed 90 dB(A)."


def fake(proposals):
    """A model that always answers the same thing. Deterministic on purpose:
    rule 5 asks two runs to agree, and a fake that drifted would make every
    test in this file intermittent."""
    return lambda prompt: json.dumps({"proposals": proposals})


def limit(**over):
    base = {"kind": "limit", "operator": ">=", "value": "370", "unit": "kg/m3",
            "subject": "cement content",
            "quote": "The minimum cement content shall be 370 kg/m3"}
    return {**base, **over}


def only(out):
    """The single accepted proposal, or an assertion naming why there is
    none. A bare `out["accepted"][0]` on an empty list says IndexError, which
    tells a reader nothing about the gate."""
    assert out["accepted"], f"nothing survived the gate: {out['rejected']}"
    assert len(out["accepted"]) == 1
    return out["accepted"][0]


def reasons(out):
    return [r["reason"] for r in out["rejected"]]


# ------------------------------------------------------ trap 1: the trigger

def test_a_trigger_shaped_sentence_is_kept_as_a_trigger():
    """The 85 dB(A) is who files a form, not a ceiling - and the row is still
    worth keeping, so `trigger` must be acceptable rather than merely
    refused."""
    out = read_sentence(NOISE_TRIGGER, fake([{
        "kind": "trigger", "value": "85", "unit": "dB(A)",
        "subject": "noise",
        "quote": "generating noise in excess of 85 dB(A) shall submit Form 7305-ENG",
    }]))
    kept = only(out)
    assert kept["kind"] == "trigger"
    assert requirement_type_of(kept) == "applicability_trigger"


def test_the_same_sentence_read_as_a_limit_is_refused():
    """THE DEFECT THIS FILE EXISTS FOR. Everything else about this proposal is
    true - the quote is in the sentence, 85 is in the quote, the subject is in
    the quote - and it must still be thrown away, because a ceiling of 85
    dB(A) reports a compliant 90 dB(A) submittal as non-compliant against a
    rule the standard does not state."""
    out = read_sentence(NOISE_TRIGGER, fake([{
        "kind": "limit", "operator": "<=", "value": "85", "unit": "dB(A)",
        "subject": "noise",
        "quote": "generating noise in excess of 85 dB(A) shall submit Form 7305-ENG",
    }]))
    assert out["accepted"] == []
    assert reasons(out) == [Reason.LIMIT_ON_TRIGGER_SENTENCE.value]


def test_a_cross_reference_threshold_is_trigger_shaped_too():
    """SAES-D-001 9.2.5: "temperatures greater than 260 C shall be in
    accordance with PIP VEFV1100". The parser once read `> 260 C` from this
    and reported a contractor NON_COMPLIANT for NOT exceeding 260."""
    assert looks_like_a_trigger(
        "Temperatures greater than 260 C shall be in accordance with PIP VEFV1100.")
    assert not looks_like_a_trigger(CEMENT)
    assert not looks_like_a_trigger(NOISE_LIMIT)


# ------------------------------------------------------ trap 2: the minimum

def test_a_minimum_is_a_floor():
    assert only(read_sentence(CEMENT, fake([limit()])))["operator"] == ">="


def test_a_minimum_reported_as_equality_is_refused():
    """`= 370` fails every compliant submittal that exceeds the minimum, and
    most of them do. The words of the clause say which direction it is, so
    Python can check the model against them."""
    out = read_sentence(CEMENT, fake([limit(operator="=")]))
    assert reasons(out) == [Reason.OPERATOR_CONTRADICTS_QUOTE.value]


def test_a_flipped_comparator_on_a_ceiling_is_refused():
    """The mirror case, and the worse one: "shall not exceed 90 dB(A)" read as
    `>= 90` is a confident wrong verdict rather than a missing row."""
    out = read_sentence(NOISE_LIMIT, fake([{
        "kind": "limit", "operator": ">=", "value": "90", "unit": "dB(A)",
        "subject": "noise level",
        "quote": "The noise level shall not exceed 90 dB(A)",
    }]))
    assert reasons(out) == [Reason.OPERATOR_CONTRADICTS_QUOTE.value]


def test_the_direction_test_reads_the_negation_not_the_comparative():
    """"shall not be less than 45 m" is a FLOOR. A pattern that saw the bare
    "less than" and missed the "not" four characters earlier is how a
    comparator gets flipped in the first place."""
    assert direction_of_quote("shall not be less than 45 m") == ">="
    assert direction_of_quote("shall not exceed 90 dB(A)") == "<="
    assert direction_of_quote("shall be 8,300 kPa") is None


# ------------------------------------------------ trap 3: the bare equality

def test_a_genuine_equality_survives_the_gate():
    """A gate that rejected everything would pass every other test in this
    file. This clause states a value with no direction words at all, and it is
    a real rule that must arrive intact - including across the thousands
    separator, which the standard prints and the model does not."""
    kept = only(read_sentence(BEARING, fake([{
        "kind": "limit", "operator": "=", "value": "8300", "unit": "kPa",
        "subject": "concrete bearing stress",
        "quote": "The allowable concrete bearing stress shall be 8,300 kPa",
    }])))
    assert (kept["operator"], kept["value"]) == ("=", "8300")
    assert requirement_type_of(kept) == "numeric_limit"


# ----------------------------------------------- trap 4: fabrication

def test_an_invented_quote_cannot_pass():
    """The fake model returns a quote that reads exactly like a standard and
    appears in no standard. There is no plausibility test here and there does
    not need to be one: the words are either in the sentence or they are
    not."""
    out = read_sentence(CEMENT, fake([limit(
        quote="The minimum cement content shall be 370 kg/m3 for sulphate-resisting mixes",
        subject="cement content")]))
    assert out["accepted"] == []
    assert reasons(out) == [Reason.QUOTE_NOT_IN_SENTENCE.value]


def test_a_value_that_is_not_in_its_own_quote_is_refused():
    """A true quote with a substituted number: the commonest shape of a
    hallucination that survives a quote-only check."""
    out = read_sentence(CEMENT, fake([limit(value="420")]))
    assert reasons(out) == [Reason.VALUE_NOT_IN_QUOTE.value]


def test_a_subject_that_is_not_in_its_own_quote_is_refused():
    """A subject the model supplied from its own knowledge of concrete rather
    than from the clause. It would match a datasheet field and attach this
    limit to something the sentence never mentioned."""
    out = read_sentence(CEMENT, fake([limit(subject="water cement ratio")]))
    assert reasons(out) == [Reason.SUBJECT_NOT_IN_QUOTE.value]


def test_a_limit_with_no_subject_is_refused():
    """MEASURED, NOT ASSUMED. `comparison.match_by_containment` joins a
    requirement to a datasheet value through its subject and has no other
    join; 313 rows promoted with subject NULL produced ZERO new matches on a
    real datasheet. An operator and a value with no subject is a row nothing
    can ever be compared against."""
    out = read_sentence(CEMENT, fake([limit(subject=None)]))
    assert reasons(out) == [Reason.SUBJECT_MISSING.value]


# -------------------------------------------------------- the other rules

def test_a_statement_needs_no_operator_and_is_kept():
    sentence = "The Contractor shall maintain records of all concrete pours."
    kept = only(read_sentence(sentence, fake([{
        "kind": "statement", "subject": "records",
        "quote": "The Contractor shall maintain records of all concrete pours",
    }])))
    assert requirement_type_of(kept) == "statement"


def test_a_limit_with_no_value_or_no_operator_is_refused():
    assert reasons(read_sentence(CEMENT, fake([limit(value=None)]))) == [
        Reason.VALUE_MISSING.value]
    assert reasons(read_sentence(CEMENT, fake([limit(operator=None)]))) == [
        Reason.OPERATOR_MISSING.value]


def test_a_kind_or_operator_outside_the_vocabulary_is_refused():
    """The model may not extend either list. A kind nobody has seen cannot be
    mapped to a stored requirement type, and a comparator nobody has seen
    cannot be checked against the clause."""
    assert reasons(read_sentence(CEMENT, fake([limit(kind="ceiling")]))) == [
        Reason.KIND_UNKNOWN.value]
    assert reasons(read_sentence(CEMENT, fake([limit(operator="~=")]))) == [
        Reason.OPERATOR_UNKNOWN.value]


def test_a_quote_broken_across_lines_still_matches():
    """Clauses arrive from the chunker wrapped; the model answers in one
    line. Rule 1 is about the WORDS, not the typesetting."""
    wrapped = "The minimum cement content\n   shall be 370 kg/m3."
    assert only(read_sentence(wrapped, fake([limit()])))["value"] == "370"


def test_two_runs_must_agree_and_the_disagreement_is_reported():
    """RULE 5. A proposal only one run produced is not one the sentence
    compels - and it is REPORTED as unstable, not dropped in silence."""
    out = read_sentence(CEMENT, fake([limit()]),
                        fake([limit(value="380", quote=limit()["quote"])]))
    assert out["accepted"] == []
    assert reasons(out) == [Reason.MODEL_UNSTABLE.value]


def test_a_malformed_answer_yields_a_reason_never_a_guess():
    out = read_sentence(CEMENT, lambda prompt: "I think the limit is 370.")
    assert out["accepted"] == [] and out["rejected"] == []
    assert out["error"] == Reason.MODEL_MALFORMED.value


def test_a_single_proposal_answered_as_a_bare_object_is_read():
    """One sentence usually states one rule and the model writes what the
    sentence looks like. Losing that shape as malformed would report a clause
    as unread when it was read correctly."""
    proposals, err = parse_response(json.dumps(limit()))
    assert err is None and len(proposals) == 1


def test_an_entry_with_no_quote_is_not_a_proposal_at_all():
    """Nothing to keep and nothing to report: an entry naming no words in the
    standard is not a rejected proposal, it is an absence."""
    proposals, err = parse_response(
        json.dumps({"proposals": [{"kind": "limit", "value": "9"}, limit()]}))
    assert err is None and len(proposals) == 1


# --------------------------------------------------- counting the refusals

def test_every_refusal_is_counted_by_name():
    """THE REPORTING REQUIREMENT. A caller must be able to say "4 proposals
    rejected: 2 quote-not-in-sentence, 1 value-not-in-quote, 1 subject-
    missing". A silent zero and a zero after four refusals are different facts
    about a standard."""
    out = accept([
        limit(quote="a quote from no standard at all"),
        limit(quote="another quote from no standard at all"),
        limit(value="420"),
        limit(subject=None),
        limit(),
    ], CEMENT)
    assert len(out["accepted"]) == 1
    assert out["counts"] == {
        Reason.QUOTE_NOT_IN_SENTENCE.value: 2,
        Reason.VALUE_NOT_IN_QUOTE.value: 1,
        Reason.SUBJECT_MISSING.value: 1,
    }


def test_many_sentences_keep_their_clause_with_every_reason():
    """A reason without the clause it belongs to cannot be acted on."""
    out = read_sentences([CEMENT, NOISE_TRIGGER], fake([limit()]))
    assert [p["sentence"] for p in out["accepted"]] == [CEMENT]
    assert out["counts"] == {Reason.QUOTE_NOT_IN_SENTENCE.value: 1}
    assert out["rejected"][0]["sentence"] == NOISE_TRIGGER


def test_the_prompt_states_the_traps_it_was_written_for():
    """The gate enforces these and the prompt must still ASK for them:
    rejecting a clause reports it as unread, which is a loss even when the
    rejection is correct. If a trap is ever removed from the prompt, this
    fails and somebody has to say why."""
    from app.reader_api import PROMPT
    assert "7305-ENG" in PROMPT
    assert "370" in PROMPT and ">= 370" in PROMPT
    assert "8,300" in PROMPT
    assert "MANDATORY" in PROMPT


# ------------------------------------------------------ the outbound lane

@pytest.mark.parametrize("wrapped", [
    "```json\n{BODY}\n```",
    "```\n{BODY}\n```",
    "  ```json\r\n{BODY}\r\n```  \n",
])
def test_a_fenced_answer_is_unwrapped_and_still_parsed_strictly(wrapped):
    """THE FIRST REAL CALL. 35 sentences of SAES-A-105 came back 35 times as
    model_malformed: every answer was well-formed JSON inside a ```json
    fence. The fence is a wrapper around the whole answer, not content, and
    removing it is not the module inventing anything."""
    raw = wrapped.replace("{BODY}", json.dumps({"proposals": [limit()]}))
    proposals, err = parse_response(raw)
    assert err is None
    assert len(proposals) == 1 and proposals[0]["value"] == "370"


@pytest.mark.parametrize("raw", [
    # broken JSON inside a fence is still broken
    "```json\n{\"proposals\": [\n```",
    # prose around the JSON: the fence does not enclose the whole answer, so
    # nothing is hunted for between braces
    "Here is the reading:\n```json\n{\"proposals\": []}\n```\nHope this helps.",
    # a fence that never closes
    "```json\n{\"proposals\": []}",
])
def test_unwrapping_a_fence_does_not_weaken_the_strict_parse(raw):
    proposals, err = parse_response(raw)
    assert proposals == [] and err == Reason.MODEL_MALFORMED.value


def test_a_fresh_install_calls_nothing(monkeypatch):
    """OFF BY DEFAULT, and the default is what a client machine runs. Both
    flags absent means the request is never even built.

    Absent from the ENVIRONMENT AND false on the SETTINGS MODEL: `from_env`
    falls back to `backend/.env` when the environment says nothing, so
    clearing the environment alone left this test reading the developer's
    file - and the day both flags were switched on there for the first real
    call, it went red. A fresh install has neither, which is what is
    simulated here."""
    from app.config import settings as live
    monkeypatch.delenv("STANDARDS_READER_ENABLED", raising=False)
    monkeypatch.delenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", raising=False)
    monkeypatch.setattr(live, "standards_reader_enabled", False)
    monkeypatch.setattr(live, "standards_reader_allow_public_egress", False)
    cfg = ReaderSettings.from_env()
    assert cfg.enabled is False and cfg.allow_public_egress is False
    with pytest.raises(ReaderRefused, match="switched off"):
        build_request("anything", cfg=cfg, env={API_KEY_ENV: "sk-test"})


def test_the_feature_flag_alone_does_not_open_egress():
    """TWO SETTINGS, on the market lane's precedent: "the feature is built"
    and "this machine may send clause text out" are different questions and
    one careless edit must not answer both."""
    cfg = ReaderSettings(enabled=True)
    with pytest.raises(ReaderRefused, match="leave the machine"):
        build_request("anything", cfg=cfg, env={API_KEY_ENV: "sk-test"})


def test_no_key_in_the_environment_refuses_rather_than_sends():
    cfg = ReaderSettings(enabled=True, allow_public_egress=True)
    with pytest.raises(ReaderRefused, match=API_KEY_ENV):
        build_request("anything", cfg=cfg, env={})


def test_the_destination_is_parsed_and_allowlisted():
    """`https://evil.test?@api.anthropic.com/` has the authority `evil.test` -
    the `?` starts the query, so the `@` is inside it. A hand-rolled split
    reports the permitted name and requests the other one, which is why the
    host comes from a real parser (`config.model_host_of`)."""
    env = {API_KEY_ENV: "sk-test"}
    for base in ("https://evil.test?@api.anthropic.com/",
                 "https://api.anthropic.com.evil.test",
                 "http://api.anthropic.com"):
        cfg = ReaderSettings(enabled=True, allow_public_egress=True,
                             base_url=base)
        with pytest.raises(ReaderRefused):
            build_request("anything", cfg=cfg, env=env)


def test_the_request_carries_the_key_the_version_and_a_pinned_sampler():
    cfg = ReaderSettings(enabled=True, allow_public_egress=True)
    request = build_request("read this sentence", cfg=cfg,
                            env={API_KEY_ENV: "sk-test"})
    assert request["url"] == "https://api.anthropic.com/v1/messages"
    assert request["headers"]["x-api-key"] == "sk-test"
    assert request["headers"]["anthropic-version"] == "2023-06-01"
    # Rule 5 asks two runs to agree; an unpinned sampler makes that a coin
    # toss tossed twice.
    assert request["body"]["temperature"] == 0
    assert request["body"]["messages"][0]["content"] == "read this sentence"


def test_a_real_shaped_response_goes_through_the_gate_with_no_network():
    """The seam, end to end: a transport that never opens a socket answers in
    the Messages response shape, and the same gate accepts the clause. This is
    the only part of the lane that cannot be finished without a key - what a
    live Claude actually returns for these sentences is unmeasured, and this
    asserts the wiring, not the model."""
    sent = {}

    def transport(url, *, headers, body, timeout):
        sent["url"] = url
        sent["prompt"] = body["messages"][0]["content"]
        sent["timeout"] = timeout
        return {"content": [{"type": "text",
                             "text": json.dumps({"proposals": [limit()]})}]}

    model_call = model_call_via(
        transport,
        cfg=ReaderSettings(enabled=True, allow_public_egress=True),
        env={API_KEY_ENV: "sk-test"})
    kept = only(read_sentence(CEMENT, model_call))
    assert kept["subject"] == "cement content"
    assert CEMENT.strip(".") in sent["prompt"]
    assert sent["timeout"] == 30.0


def test_a_response_with_no_text_is_malformed_not_empty():
    """An empty answer and an unparseable one are both "the model said
    nothing usable". Neither may become a proposal, and neither may be
    reported as a clause that states nothing."""
    def transport(url, *, headers, body, timeout):
        return {"content": [{"type": "thinking", "thinking": "hmm"}]}

    model_call = model_call_via(
        transport,
        cfg=ReaderSettings(enabled=True, allow_public_egress=True),
        env={API_KEY_ENV: "sk-test"})
    out = read_sentence(CEMENT, model_call)
    assert out["error"] == Reason.MODEL_MALFORMED.value


def test_the_module_imports_and_reads_with_no_api_key_present(monkeypatch):
    """No key anywhere in the code or the tests, and the module must import
    and do its whole job without one - which is what every other test in this
    file is doing.

    LOADED AS A SEPARATE MODULE OBJECT, NOT `importlib.reload`. Reloading the
    shared `app.reader_api` mints a NEW `ReaderRefused` class and leaves it in
    `sys.modules`, so every later test whose `pytest.raises(ReaderRefused)`
    was bound at import time stops catching the exception the module now
    raises. That was invisible while this was the last test in the file and
    broke the moment one was added after it. A fresh private instance proves
    the same thing and leaves nothing behind.
    """
    import importlib.util

    monkeypatch.delenv(API_KEY_ENV, raising=False)
    # The name must be package-qualified: `reader_api` uses relative imports
    # (`from .config import ...`), and those resolve through `__package__`,
    # which a bare module name leaves empty.
    spec = importlib.util.spec_from_file_location(
        "app.reader_api_isolated", Path(app_reader_api.__file__))
    isolated = importlib.util.module_from_spec(spec)
    # `@dataclass` resolves its own module through `sys.modules[__module__]`
    # while the class body executes, so the entry has to exist during the
    # load. `monkeypatch.setitem` removes it afterwards, which is the whole
    # point of doing this instead of `reload`.
    monkeypatch.setitem(sys.modules, spec.name, isolated)
    spec.loader.exec_module(isolated)

    assert isolated.ReaderSettings().enabled is False
    assert only(isolated.read_sentence(CEMENT, fake([limit()])))["value"] == "370"
    # And the shared module is untouched: same class object as at import.
    assert app_reader_api.ReaderRefused is ReaderRefused


# ================================== the key and the flags reach backend/.env

def test_the_key_is_found_in_backend_env_when_the_process_has_none(monkeypatch):
    """THE DEFECT THIS FALLBACK EXISTS FOR.

    `backend/.env` NEVER REACHES `os.environ`: pydantic-settings populates the
    `Settings` model and exports nothing. Measured on 2026-09-20 - `AUTH_MODE`
    is in that file, `settings.auth_mode` is `demo_required`, and
    `"AUTH_MODE" in os.environ` is False. So a key placed in the file rule 2
    names as its only home was invisible here and the reader refused, while
    the two flags could not be switched on from that file at all.
    """
    from app import reader_api
    from app.config import settings as live

    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.setattr(live, "anthropic_api_key", "sk-from-the-env-file")
    cfg = ReaderSettings(enabled=True, allow_public_egress=True)

    request = reader_api.build_request("anything", cfg=cfg)

    assert request["headers"]["x-api-key"] == "sk-from-the-env-file"


def test_both_flags_can_be_switched_on_from_backend_env(monkeypatch):
    from app.config import settings as live

    monkeypatch.delenv("STANDARDS_READER_ENABLED", raising=False)
    monkeypatch.delenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", raising=False)
    monkeypatch.setattr(live, "standards_reader_enabled", True)
    monkeypatch.setattr(live, "standards_reader_allow_public_egress", True)

    cfg = ReaderSettings.from_env()

    assert cfg.enabled is True and cfg.allow_public_egress is True


def test_the_process_environment_can_still_switch_the_lane_off(monkeypatch):
    """AN EXPLICIT "0" BEATS THE FILE, and that direction is the point.

    `or`-ing the two sources would make a `true` in a shared deployment file
    unkillable from the shell of the process about to start - the wrong way
    round for the flag that permits a client's clause text to leave the
    machine.
    """
    from app.config import settings as live

    monkeypatch.setattr(live, "standards_reader_enabled", True)
    monkeypatch.setattr(live, "standards_reader_allow_public_egress", True)
    monkeypatch.setenv("STANDARDS_READER_ENABLED", "0")
    monkeypatch.setenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "0")

    cfg = ReaderSettings.from_env()

    assert cfg.enabled is False and cfg.allow_public_egress is False


def test_an_injected_environment_is_obeyed_exactly_and_never_falls_back(monkeypatch):
    """THE HERMETICITY GUARANTEE, and it is what keeps this file honest.

    Every other test here passes a plain dict. If an injected environment
    fell through to `backend/.env`, this suite would pass or fail according
    to whether the developer running it happens to have a key on disk - a
    result that depends on an untracked file is not a result.
    """
    from app.config import settings as live

    monkeypatch.setattr(live, "anthropic_api_key", "sk-must-not-be-used")
    monkeypatch.setattr(live, "standards_reader_enabled", True)
    monkeypatch.setattr(live, "standards_reader_allow_public_egress", True)

    assert ReaderSettings.from_env({}).enabled is False
    cfg = ReaderSettings(enabled=True, allow_public_egress=True)
    with pytest.raises(ReaderRefused):
        build_request("anything", cfg=cfg, env={})


def test_the_refusal_names_both_places_and_never_the_key(monkeypatch):
    """A refusal that echoed what it found would log a secret the first time
    somebody sets a malformed one."""
    from app.config import settings as live

    monkeypatch.setattr(live, "anthropic_api_key", "")
    cfg = ReaderSettings(enabled=True, allow_public_egress=True)
    with pytest.raises(ReaderRefused) as raised:
        build_request("anything", cfg=cfg, env={})
    message = str(raised.value)
    assert API_KEY_ENV in message
    assert "backend/.env" in message
    assert "sk-" not in message
