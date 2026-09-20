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

import pytest

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

def test_a_fresh_install_calls_nothing(monkeypatch):
    """OFF BY DEFAULT, and the default is what a client machine runs. Both
    flags absent means the request is never even built."""
    monkeypatch.delenv("STANDARDS_READER_ENABLED", raising=False)
    monkeypatch.delenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", raising=False)
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
    file is doing."""
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    import importlib

    from app import reader_api
    importlib.reload(reader_api)
    assert reader_api.ReaderSettings().enabled is False
    assert only(reader_api.read_sentence(CEMENT, fake([limit()])))["value"] == "370"
