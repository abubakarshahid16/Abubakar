"""Order 14, 16 Nov 2026 night: the valve proof runs met an empty Claude account. Every request was refused (400, "no credit"), each
was charged at its worst case and retried, and the run ended "stopped by the cap" with the true cause hidden. Now: an account-level
refusal stops the run at the first request with its own reason, and a 4xx refusal (never billed) counts USD 0 and is not retried.
Invented data; no network."""

from __future__ import annotations

import threading

import httpx
import pytest

from app import agent_claude as ac
from app import agent_review_request as req
from app import agent_review_run as arr
from app import reader_transport
from tests.test_agent_claude import (  # noqa: F401 - the module's fixtures: declared document, temp ledger
    ENV,
    MSGS,
    Sender,
    _declared,
    _ledger,
)


def _refused(sentence: str, status: int = 400) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.HTTPStatusError(
        f"{status} from api.anthropic.com (invalid_request_error: {sentence})",
        request=request,
        response=httpx.Response(status, request=request),
    )


def test_the_account_sentences_are_the_transports_own_fixed_sentences():
    ours = [sentence for _types, _pattern, sentence in reader_transport._SAFE]
    for words_, _code in ac.ACCOUNT_STOPS:
        assert any(
            s.startswith(words_) for s in ours
        )  # a reworded sentence there breaks this match here


@pytest.mark.parametrize(
    ("sentence", "code"),
    [
        ("The Claude account has no credit (the owner tops it up in the Anthropic console).", "account_no_credit"),
        ("The Claude account's usage limit is reached; access returns on 2026-12-01.", "account_usage_limit"),
    ],
)  # fmt: skip
def test_an_account_refusal_stops_the_run_with_its_own_reason(sentence, code):
    s = Sender([], raises=_refused(sentence))
    with pytest.raises(ac.AgentBudgetStop) as e:
        ac._call(ac.LEAD_MODEL, {"messages": MSGS}, 100, s, ENV)
    assert e.value.code == code
    assert req.stop_reason(e.value)[1].startswith("the Claude account")
    assert len(s.bodies) == 1


def test_another_4xx_is_a_transport_error_marked_unbilled_and_a_5xx_billed():
    with pytest.raises(ac.AgentTransportError) as e:
        ac._call(
            ac.LEAD_MODEL,
            {"messages": MSGS},
            100,
            Sender([], raises=_refused("bad", 400)),
            ENV,
        )
    assert e.value.billed is False
    with pytest.raises(ac.AgentTransportError) as e:
        ac._call(
            ac.LEAD_MODEL,
            {"messages": MSGS},
            100,
            Sender([], raises=_refused("down", 503)),
            ENV,
        )
    assert e.value.billed is True


def _bare_runner() -> arr.Runner:
    r = object.__new__(arr.Runner)
    r.local, r.gate, r.run_usd, r.send, r.env, r.stopped = (
        None,
        None,
        0.0,
        None,
        ENV,
        None,
    )
    r._stop, r._lock, r._optional = (
        threading.Event(),
        threading.Lock(),
        threading.local(),
    )
    r.calls, r.retry_base = {"retries": 0}, 0.0
    return r


@pytest.mark.parametrize("billed", [False, True])
def test_an_unbilled_refusal_costs_nothing_and_is_not_retried(monkeypatch, billed):
    tried = []

    def refuse(*_a, **_k):
        tried.append(1)
        err = ac.AgentTransportError("transport_HTTPStatusError")
        err.billed = err.retry = billed  # a plain 4xx refusal: unbilled AND not retried
        raise err

    monkeypatch.setattr(ac, "_call", refuse)
    r = _bare_runner()
    with pytest.raises(ac.AgentTransportError):
        r._metered_call(ac.LEAD_MODEL, {"messages": MSGS}, 100)
    if billed:  # may have been billed: charged at the worst case and retried, as before
        assert len(tried) == arr.MAX_RETRIES + 1 and r.run_usd > 0
    else:
        assert len(tried) == 1 and r.run_usd == 0.0 and r.calls["retries"] == 0


# --- review R-1852 (fresh full review): rate limits and lost connections are still retried; one charge rule in every home


@pytest.mark.parametrize(
    ("exc", "billed", "retry"),
    [
        (_refused("bad", 400), False, False),
        (_refused("slow down", 429), False, True),
        (_refused("timeout", 408), False, True),
        (httpx.ConnectError("no route"), False, True),
        (_refused("down", 503), True, True),
    ],
)
def test_which_failures_are_billed_and_which_are_retried(exc, billed, retry):
    with pytest.raises(ac.AgentTransportError) as e:
        ac._call(ac.LEAD_MODEL, {"messages": MSGS}, 100, Sender([], raises=exc), ENV)
    assert (e.value.billed, e.value.retry) == (billed, retry)
    assert (
        e.value.usd > 0
    ) is billed  # what it counts travels with it (the second opinion reports it)


def test_a_rate_limited_call_is_retried_and_costs_nothing(monkeypatch):
    tried = []

    def limited(*_a, **_k):
        tried.append(1)
        err = ac.AgentTransportError("transport_HTTPStatusError")
        err.billed, err.retry = False, True
        raise err

    monkeypatch.setattr(ac, "_call", limited)
    r = _bare_runner()
    with pytest.raises(ac.AgentTransportError):
        r._metered_call(ac.LEAD_MODEL, {"messages": MSGS}, 100)
    assert len(tried) == arr.MAX_RETRIES + 1 and r.run_usd == 0.0


def test_the_step_gate_settles_a_refusal_at_zero(monkeypatch):
    def refuse(*_a, **_k):
        err = ac.AgentTransportError("transport_HTTPStatusError")
        err.billed = err.retry = False
        raise err

    monkeypatch.setattr(ac, "_call", refuse)
    r = _bare_runner()
    r.gate = req.AppStepGate(10.0)
    with pytest.raises(ac.AgentTransportError):
        r._metered_call(ac.LEAD_MODEL, {"messages": MSGS}, 100)
    assert r.gate.settled == 0.0 and r.gate.inflight == 0.0


def test_a_5xx_carrying_the_sentence_is_not_an_account_stop():
    assert ac.account_stop(_refused("The Claude account has no credit", 503)) is None


def test_charge_of_is_the_one_rule():
    refused = ac.AgentTransportError("x")
    refused.billed = False
    assert ac.charge_of(refused, 1.5) == 0.0
    assert (
        ac.charge_of(ac.AgentTransportError("y"), 1.5) == 1.5
    )  # billed by default: the safe side
    assert ac.charge_of(ac.AgentBadReply("z"), 1.5) == 1.5


def test_the_reread_and_the_script_say_the_account_not_a_cap():
    from app import agent_review_reread as rr
    from app import agent_run_second as second

    stop = ac.AgentBudgetStop("account_no_credit")
    assert rr.stop_word(stop) == "the Claude account has no credit"
    assert second.fatal_problem(stop).startswith("the Claude account has no credit")
    assert (
        rr.stop_word(ac.AgentBudgetStop("budget_stop"))
        == "a spending cap refused a call"
    )
