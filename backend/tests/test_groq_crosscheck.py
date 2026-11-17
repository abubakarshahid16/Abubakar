"""The second AI's cross-check on Groq (owner decision 17 Nov 2026, #1584): off by default, gated, only quotes leave,
it can only make a line less confident, and it has its own money caps. Invented paper, rule book, models and key; no
network: `httpx.Client` is a fake that records what would have left, or a guard that fails the test if it is built."""

# ruff: noqa: F811
from __future__ import annotations

import hashlib
import json
import logging
import threading

import httpx
import pytest

from app import (
    agent_claude,
    agent_run_second,
    classification,
    claude_approved,
    claude_spend,
    db,
    groq_approved,
    groq_spend,
    groq_transport,
    review_engine,
    review_leaving,
    review_shown,
)
from app import agent_review_crosscheck as cc
from app import agent_review_crosscheck_run as ccrun
from app import agent_review_wording as W
from app.config import Settings, settings
from tests import agent_review_support as s
from tests.test_agent_review_guards import run_review, w  # noqa: F401
from tests.test_agent_review_job import lines_of, run_job, start

KEY = "fake-key-for-tests-0123456789"
SECRET_ECHO = "the API echoes " + KEY


def sha(doc_id: str) -> str:
    return hashlib.sha256(
        doc_id.encode()
    ).hexdigest()  # the support module's invented hash per document


def write_list(path, *shas: str) -> None:
    rows = [
        {"sha256": h, "status": "approved", "label": "invented", "approved_by": "owner"}
        for h in shas
    ]
    path.write_text(json.dumps({"documents": rows}), encoding="utf-8")


def approve(claude=(), groq=()) -> None:
    from app import claude_approved

    write_list(claude_approved.list_path(), *claude)
    write_list(groq_approved.list_path(), *groq)


def switch_on(monkeypatch) -> None:
    monkeypatch.setattr(settings, "groq_crosscheck_enabled", True)
    monkeypatch.setattr(settings, "groq_api_key", KEY)


class FakeGroq:
    """An invented Groq. Records every request (url, headers, body) and answers `agree` per colour, or `status`."""

    def __init__(
        self, agree=None, status=200, raw=None, ctype="application/json", raises=None
    ):
        self.agree = agree if agree is not None else {"GREEN": True, "RED": False}
        self.status, self.raw, self.ctype, self.raises = status, raw, ctype, raises
        self.sent: list[dict] = []
        self.built = 0

    def client(self, **kwargs):
        fake = self

        class Client:
            def __init__(self):
                fake.built += 1
                assert (
                    kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
                )

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, url, headers=None, content=None):
                fake.sent.append(
                    {"url": url, "headers": dict(headers), "body": json.loads(content)}
                )
                if fake.raises is not None:
                    raise fake.raises
                data = fake.raw
                if data is None:
                    colour = json.loads(json.loads(content)["messages"][1]["content"])[
                        "colour"
                    ]
                    text = json.dumps(
                        {"agree": fake.agree[colour], "reason": "invented reason"}
                    )
                    data = json.dumps(
                        {
                            "model": "openai/gpt-oss-120b",
                            "usage": {"prompt_tokens": 300, "completion_tokens": 80},
                            "choices": [
                                {"finish_reason": "stop", "message": {"content": text}}
                            ],
                        }
                    ).encode()
                return httpx.Response(
                    fake.status,
                    content=data,
                    headers={"content-type": fake.ctype},
                    request=httpx.Request("POST", url, headers=headers),
                )

        return Client()


@pytest.fixture
def groq(monkeypatch):
    fake = FakeGroq()
    monkeypatch.setattr(httpx, "Client", fake.client)
    return fake


@pytest.fixture
def no_client(monkeypatch):
    def explode(*a, **k):  # pragma: no cover - the point is that it is not hit
        raise AssertionError("an httpx.Client was built for a refused Groq request")

    monkeypatch.setattr(httpx, "Client", explode)


BODY = {"model": "openai/gpt-oss-120b", "messages": [{"role": "user", "content": "q"}]}


# ------------------------------------------------------------------ the world: an invented library on a temp database


NOW = "2026-11-17T00:00:00Z"


def record_start(run_id, *, second_ai=True, shown=True, docs=(s.PAPER, s.STD)):
    """What a start from the review page stores: the plan (with or without the second AI's line) and the shown list."""
    line = {"to": "Groq", "words": groq_approved.PLAN_WORDS}
    plan = {
        "choice": "claude",
        "documents": {groq_approved.PLAN_KEY: line} if second_ai else {},
    }
    with db.connect() as conn:
        review_engine.record_in(
            conn, run_id, plan, "tester", then_ai=False, bar_claude=False, now=NOW
        )
        if shown:
            review_shown.record_in(conn, run_id, list(docs), NOW)


def run_shown_review(**kw):
    """A review run started as the review page starts one (its plan and its shown list stored), then run."""
    run_id, job_id = start()
    record_start(run_id, **kw)
    run_job(job_id)
    return run_id


@pytest.fixture
def lib(tmp_path, monkeypatch):
    s.setup_world(tmp_path, monkeypatch)
    with db.connect() as conn:
        s.add_document(conn, "doc_contract", "contract.pdf", "invented")
        # the register's name, from the block's own key (never spelt out here), with a copy suffix
        register = claude_approved.REGISTER_NAME_KEY + " (1).pdf"
        s.add_document(conn, "doc_register", register, "invented")
    classification.set_role("doc_contract", "CONTRACT_DOCUMENT")
    record_start("run-shown")
    with claude_spend.for_run(
        "run-shown"
    ):  # inside a run that showed the second AI's line
        yield
    db.reset_connection()


# ------------------------------------------------------------------ 1. off by default: nothing is sent


def test_off_by_default_sends_nothing_and_no_line_changes(w, monkeypatch, no_client):
    assert Settings.model_fields["groq_crosscheck_enabled"].default is False
    approve(claude=[sha(s.PAPER), sha(s.STD)], groq=[sha(s.PAPER), sha(s.STD)])
    monkeypatch.setattr(settings, "groq_api_key", KEY)  # a key alone opens nothing
    run_id = run_review()
    rows = lines_of(run_id)
    assert rows and all(
        cc.FIELD not in json.loads(r["line_json"]) for r in rows.values()
    )
    counts = json.loads(
        db.connect()
        .execute("SELECT counts_json FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()["counts_json"]
    )
    assert "crosscheck_step" not in counts
    assert not groq_spend.ledger_path().exists()


# ------------------------------------------------------------------ 2. each gate refuses before a client is built


@pytest.mark.parametrize(
    "url",
    [
        "http://api.groq.com/openai/v1/chat/completions",  # not https
        "https://api.groq.com.evil.test/openai/v1/chat/completions",  # a name that starts like the host
        "https://evil.test?@api.groq.com/openai/v1/chat/completions",  # the string-splitting bypass
        "https://user@api.groq.com/openai/v1/chat/completions",  # user info
        "https://api.groq.com:8443/openai/v1/chat/completions",  # a port
        "https://api.groq.com/openai/v1/models",  # another path
        "https://api.groq.com/openai/v1/chat/completions?x=1",  # a query
    ],
)
def test_any_other_url_is_refused(url, monkeypatch, no_client):
    switch_on(monkeypatch)
    monkeypatch.setattr(groq_approved, "refusal", lambda ids: None)
    with pytest.raises(groq_transport.GroqRefused, match="host_refused"):
        groq_transport.send(BODY, document_ids=["doc_paper"], url=url)


def test_a_document_not_on_both_lists_is_refused_before_a_client(
    lib, monkeypatch, no_client
):
    switch_on(monkeypatch)
    approve(claude=[sha(s.PAPER)], groq=[])
    with pytest.raises(
        groq_transport.GroqRefused, match=groq_approved.NOT_ON_GROQ_LIST
    ):
        groq_transport.send(BODY, document_ids=[s.PAPER])
    with pytest.raises(groq_transport.GroqRefused, match=groq_approved.UNDECLARED):
        groq_transport.send(BODY, document_ids=[])


def test_the_approval_rule(lib):
    paper, book = sha(s.PAPER), sha(s.STD)
    assert groq_approved.refusal([]) == groq_approved.UNDECLARED
    approve(claude=[paper], groq=[])
    assert groq_approved.refusal([s.PAPER]) == groq_approved.NOT_ON_GROQ_LIST
    approve(claude=[], groq=[paper])
    assert groq_approved.refusal([s.PAPER]) == groq_approved.NOT_ON_CLAUDE_LIST
    approve(claude=[paper], groq=[paper])
    assert groq_approved.refusal([s.PAPER]) is None
    assert (
        groq_approved.refusal([s.PAPER, s.STD]) == groq_approved.NOT_ON_CLAUDE_LIST
    )  # the rule book too
    approve(claude=[paper, book], groq=[paper, book])
    assert groq_approved.refusal([s.PAPER, s.STD]) is None
    assert (
        groq_approved.refusal([s.PAPER, "doc_nowhere"])
        == groq_approved.UNKNOWN_DOCUMENT
    )
    with review_engine.barring():  # Local only: nothing leaves the machine
        assert groq_approved.refusal([s.PAPER]) == groq_approved.LOCAL_ONLY


def test_a_contract_and_the_register_are_never_sent_whatever_the_lists_say(lib):
    every = [sha(d) for d in (s.PAPER, "doc_contract", "doc_register")]
    approve(claude=every, groq=every)
    assert groq_approved.refusal(["doc_contract"]) == groq_approved.CONTRACT
    assert groq_approved.refusal(["doc_register"]) in (groq_approved.BLOCKED,)
    assert (
        groq_approved.refusal([s.PAPER]) is None
    )  # the guard on the guard: the same lists pass a plain paper


def test_a_hash_in_the_block_file_blocks_and_a_damaged_block_file_refuses(lib):
    from app import claude_approved

    approve(claude=[sha(s.PAPER)], groq=[sha(s.PAPER)])
    claude_approved.block_file_path().write_text(
        json.dumps({"blocked_sha256": [sha(s.PAPER)]}), encoding="utf-8"
    )
    assert groq_approved.refusal([s.PAPER]) == groq_approved.BLOCKED
    claude_approved.block_file_path().write_text("{not json", encoding="utf-8")
    assert groq_approved.refusal([s.PAPER]) == groq_approved.LISTS_UNREADABLE


# ------------------------------------------------------------------ 3. the transport: JSON only, our words, no key anywhere


def test_a_good_answer_is_returned_and_the_key_is_only_in_the_header(
    monkeypatch, groq, caplog
):
    switch_on(monkeypatch)
    monkeypatch.setattr(groq_approved, "refusal", lambda ids: None)
    body = {
        "model": "openai/gpt-oss-120b",
        "messages": [
            {"role": "system", "content": "s"},
            {
                "role": "user",
                "content": agent_claude.second_prompt(
                    "GREEN", "invented paper words", "invented clause"
                ),
            },
        ],
    }
    with caplog.at_level(logging.DEBUG):
        got = groq_transport.send(body, document_ids=["doc_paper"])
    assert got["choices"][0]["message"]["content"]
    assert groq.sent[0]["url"] == groq_transport.URL
    assert groq.sent[0]["headers"]["Authorization"] == "Bearer " + KEY
    assert groq.sent[0]["body"] == body  # exactly what the caller built, nothing added
    assert KEY not in caplog.text and "invented paper words" not in caplog.text
    assert "status=200" in caplog.text and "openai/gpt-oss-120b" in caplog.text


@pytest.mark.parametrize(
    "status,billed",
    [(400, False), (401, False), (429, False), (500, True), (503, True)],
)
def test_an_error_status_is_our_sentence_never_the_api_text_or_the_key(
    status, billed, monkeypatch, caplog
):
    fake = FakeGroq(
        status=status,
        raw=json.dumps({"error": {"message": SECRET_ECHO, "type": "x"}}).encode(),
    )
    monkeypatch.setattr(httpx, "Client", fake.client)
    switch_on(monkeypatch)
    monkeypatch.setattr(groq_approved, "refusal", lambda ids: None)
    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(groq_transport.GroqRejected) as caught,
    ):
        groq_transport.send(BODY, document_ids=["doc_paper"])
    for text in (str(caught.value), repr(caught.value), caplog.text):
        assert KEY not in text and "echoes" not in text
    assert str(caught.value).startswith(f"{status} from api.groq.com")
    assert groq_transport.unbilled(caught.value) is (not billed)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "raises,sent",
    [(httpx.ConnectError("refused"), False), (httpx.ReadTimeout("slow"), True)],
)
def test_a_failed_connection_carries_no_request_and_no_key(raises, sent, monkeypatch):
    fake = FakeGroq(raises=raises)
    monkeypatch.setattr(httpx, "Client", fake.client)
    switch_on(monkeypatch)
    monkeypatch.setattr(groq_approved, "refusal", lambda ids: None)
    with pytest.raises(groq_transport.GroqUnreachable) as caught:
        groq_transport.send(BODY, document_ids=["doc_paper"])
    assert caught.value.sent is sent and groq_transport.unbilled(caught.value) is (
        not sent
    )
    assert (
        caught.value.__context__ is None and caught.value.__cause__ is None
    )  # no httpx error (its request holds the key)
    assert KEY not in repr(caught.value) and KEY not in str(caught.value)


@pytest.mark.parametrize(
    "raw,ctype",
    [
        (  # valid JSON, only too big: refused by the size cap alone
            b'{"pad": "' + b"x" * groq_transport.MAX_RESPONSE_BYTES + b'"}',
            "application/json",
        ),
        (b"<html>hello</html>", "text/html"),
        (b"[1, 2]", "application/json"),
        (b'{"choices": []}', "text/html"),  # JSON words, another content type
    ],
)
def test_a_big_or_non_json_answer_is_refused_and_may_be_billed(raw, ctype, monkeypatch):
    fake = FakeGroq(raw=raw, ctype=ctype)
    monkeypatch.setattr(httpx, "Client", fake.client)
    switch_on(monkeypatch)
    monkeypatch.setattr(groq_approved, "refusal", lambda ids: None)
    with pytest.raises(groq_transport.GroqRefused) as caught:
        groq_transport.send(BODY, document_ids=["doc_paper"])
    assert caught.value.sent is True and not groq_transport.unbilled(caught.value)


# ------------------------------------------------------------------ 4. money: its own ledger and caps


def test_caps_refuse_before_anything_is_sent(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "groq_crosscheck_usd_per_run", 0.01)
    monkeypatch.setattr(settings, "groq_crosscheck_usd_per_day", 0.015)
    groq_spend.settle(groq_spend.reserve("run-1", "openai/gpt-oss-120b", 0.008), 0.008)
    with pytest.raises(groq_spend.GroqBudgetExceeded) as caught:
        groq_spend.reserve("run-1", "openai/gpt-oss-120b", 0.003)
    assert caught.value.code == groq_spend.RUN_CAP
    with pytest.raises(groq_spend.GroqBudgetExceeded) as caught:
        groq_spend.reserve("run-2", "openai/gpt-oss-120b", 0.008)
    assert caught.value.code == groq_spend.DAY_CAP
    assert groq_spend.spent() == 0.008  # the refused reservations left no line
    held = groq_spend.reserve("run-2", "openai/gpt-oss-120b", 0.005)
    assert (
        groq_spend.spent(run="run-2") == 0.005
    )  # an open reservation counts at its worst case
    groq_spend.release(held)
    assert groq_spend.spent(run="run-2") == 0.0


def test_a_torn_ledger_line_counts_at_the_day_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    groq_spend.ledger_path().write_text('{"reservation": "half', encoding="utf-8")
    with pytest.raises(groq_spend.GroqBudgetExceeded):
        groq_spend.reserve("run-1", "openai/gpt-oss-120b", 0.0001)


def test_prices_and_the_worst_case():
    assert groq_spend.worst_case_usd(
        "openai/gpt-oss-120b", 1000, 1000
    ) == pytest.approx((1200 * 0.15 + 1000 * 0.75) / 1e6)
    assert groq_spend.price_for("someone/unknown") == groq_spend.UNKNOWN_PRICE
    assert groq_spend.UNKNOWN_PRICE >= max(groq_spend.PRICES.values())
    assert groq_spend.cost_usd(
        "openai/gpt-oss-120b", {"prompt_tokens": 1000, "completion_tokens": 100}
    ) == pytest.approx((1000 * 0.15 + 100 * 0.75) / 1e6)
    assert groq_spend.cost_usd("openai/gpt-oss-120b", None) is None


# ------------------------------------------------------------------ 5. the words: only ever LESS confident


def opinion_line(ai="Pass", **extra):
    return {
        "item_id": "R-x",
        "source": "rule",
        "ai_verdict": ai,
        "verdict": "Query",
        "decided_by": "engineer",
        "why": "no second opinion",
        "reason_code": "met" if ai == "Pass" else "not_met",
        "quotes_checked": {"paper": True, "clause": True, "both": True},
        "paper_quote": "invented paper words",
        "clause_quote": "invented clause words",
        **extra,
    }


def proven_line(**extra):
    return {
        **opinion_line(),
        "verdict": "Pass",
        "decided_by": "decided by code",
        "why": None,
        "compare": {"decided": True, "verdict": "meets"},
        **extra,
    }


@pytest.mark.parametrize(
    "ai,before", [("Pass", W.THINKS_MET), ("Fail", W.THINKS_NOT_MET)]
)
def test_a_disagreement_makes_an_ai_line_a_query(ai, before):
    line = opinion_line(ai)
    assert W.classify(line)["verdict_label"] == before
    got = W.classify(
        {**line, cc.FIELD: {"asked": True, "agree": False, "model": "m", "usd": 0.0001}}
    )
    assert got == {
        "verdict_label": W.WORD_QUERY,
        "verdict_class": W.CLASS_QUERY,
        "not_proven_reason": cc.DISAGREE_WHY,
    }


def test_a_disagreement_on_a_rule_not_yet_approved_says_both():
    line = {
        **opinion_line(),
        "rule_tier": "not_approved",
        "rule_unapproved_why": "invented",
    }
    assert W.classify(line)["verdict_class"] == W.CLASS_UNAPPROVED
    got = W.classify({**line, cc.FIELD: {"asked": True, "agree": False}})
    assert got["verdict_class"] == W.CLASS_QUERY
    assert (
        got["not_proven_reason"].startswith(cc.DISAGREE_WHY)
        and "not AI approved" in got["not_proven_reason"]
    )


@pytest.mark.parametrize("line", [opinion_line("Pass"), opinion_line("Fail")])
def test_agreement_changes_nothing(line):
    agreed = {
        **line,
        cc.FIELD: {
            "asked": True,
            "agree": True,
            "model": "m",
            "usd": 0.0001,
            "reason": "fine",
        },
    }
    assert W.classify(agreed) == W.classify(line)
    assert {k: v for k, v in W.apply(agreed).items() if k != cc.FIELD} == W.apply(line)


def test_a_proven_line_is_never_touched_and_never_asked():
    line = proven_line()
    assert W.classify(line)["verdict_class"] == W.CLASS_PROVEN
    marked = {**line, cc.FIELD: {"asked": True, "agree": False}}
    assert W.classify(marked) == W.classify(line)
    assert not ccrun.candidate(line)
    code = {**opinion_line(), "source": "code", "item_id": "C-1"}
    assert not ccrun.candidate(code) and not cc.disagrees(
        {**code, cc.FIELD: {"asked": True, "agree": False}}
    )


def test_not_run_is_said_after_the_reason_and_changes_no_class():
    line = opinion_line()
    rec = {
        "asked": False,
        "agree": None,
        "code": "not_on_groq_list",
        "said": cc.NOT_APPROVED_SAID,
    }
    got = W.apply({**line, cc.FIELD: rec})
    assert got["verdict_class"] == W.apply(line)["verdict_class"]
    assert got["not_proven_reason"].endswith("; " + cc.NOT_APPROVED_SAID)
    assert W.apply(got)["not_proven_reason"] == got["not_proven_reason"]  # idempotent


def test_candidates():
    assert ccrun.candidate(opinion_line("Pass")) and ccrun.candidate(
        opinion_line("Fail")
    )
    assert not ccrun.candidate({**opinion_line(), "error": "transport_x"})
    assert not ccrun.candidate(
        {**opinion_line(), cc.FIELD: {"asked": True, "agree": True}}
    )  # answered: never again
    assert ccrun.candidate(
        {**opinion_line(), cc.FIELD: {"asked": False, "agree": None}}
    )  # not run: asked on resume
    disagreed = {
        **opinion_line(),
        "second_opinion": {"agree": False, "model": "m"},
    }  # the Claude second opinion said no: already a Query, nothing to change
    assert W.classify(disagreed)["verdict_class"] == W.CLASS_QUERY
    assert not ccrun.candidate(disagreed)


def test_the_question_is_the_claude_second_opinion_question():
    body = ccrun.body_for(opinion_line("Fail"), "openai/gpt-oss-120b")
    assert body["messages"] == [
        {"role": "system", "content": agent_claude.SECOND_SYSTEM},
        {
            "role": "user",
            "content": agent_claude.second_prompt(
                "RED", "invented paper words", "invented clause words"
            ),
        },
    ]
    assert json.loads(body["messages"][1]["content"]) == {
        "colour": "RED",
        "document_quote": "invented paper words",
        "clause_quote": "invented clause words",
        "question": agent_claude.SECOND_QUESTION,
    }
    assert set(body) == {
        "model",
        "messages",
        "temperature",
        "max_completion_tokens",
        "response_format",
        "reasoning_effort",
    }


@pytest.mark.parametrize(
    "answer,agree",
    [
        (
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"agree": false, "reason": "r"}'},
                    }
                ]
            },
            False,
        ),
        (
            {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": '{"agree": true}'},
                    }
                ]
            },
            None,
        ),
        (
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"agree": "yes"}'},
                    }
                ]
            },
            None,
        ),
        ({"choices": []}, None),
    ],
)
def test_only_a_true_or_false_answer_counts(answer, agree):
    assert ccrun.parse_reply(answer)[0] is agree


# ------------------------------------------------------------------ 6. the whole run, end to end, on the invented library


def _rows(run_id):
    return {
        iid: (r["verdict_class"], r["word"], r["reason"])
        for iid, r in lines_of(run_id).items()
    }


def _counts(run_id):
    row = (
        db.connect()
        .execute(
            "SELECT usd, counts_json FROM agent_review_run WHERE run_id = ?", (run_id,)
        )
        .fetchone()
    )
    return row["usd"], json.loads(row["counts_json"])


def test_a_run_asks_the_unproven_lines_only_and_a_disagreement_is_a_query(
    w, monkeypatch, groq
):
    off_run = run_shown_review()
    off_rows, off_usd = _rows(off_run), _counts(off_run)[0]
    switch_on(monkeypatch)
    approve(claude=[sha(s.PAPER), sha(s.STD)], groq=[sha(s.PAPER), sha(s.STD)])
    run_id = run_shown_review()
    on_rows = _rows(run_id)
    sent = [json.loads(x["body"]["messages"][1]["content"]) for x in groq.sent]
    # only the lines code did not prove: R-coat (an AI met) and R-mark (an AI not met); never R-frame (compared by code)
    assert sorted(q["colour"] for q in sent) == ["GREEN", "RED"]
    assert all(q["document_quote"] != s.ANSWERS["R-frame"]["paper_quote"] for q in sent)
    assert (
        on_rows["R-frame"] == off_rows["R-frame"]
        and off_rows["R-frame"][0] == W.CLASS_PROVEN
    )
    # Groq agrees on R-coat: nothing changes; it disagrees on R-mark: a Query with the reason
    assert on_rows["R-coat"] == off_rows["R-coat"]
    assert (
        off_rows["R-mark"][0] == W.CLASS_TWO_READERS
    )  # "AI verdict: not met": firm, but not proven by code
    assert (
        on_rows["R-mark"][:2] == (W.CLASS_QUERY, "Query")
        and cc.DISAGREE_WHY in on_rows["R-mark"][2]
    )
    # its money is its own: the Claude total is the same, the step's usd is on the run row and in the ledger
    usd, counts = _counts(run_id)
    assert usd == off_usd
    step = counts["crosscheck_step"]
    assert (step["candidates"], step["asked"], step["agreed"], step["disagreed"]) == (
        2,
        2,
        1,
        1,
    )
    assert step["usd"] > 0 and groq_spend.spent(run=run_id) == pytest.approx(
        step["usd"]
    )
    stored = json.loads(lines_of(run_id)["R-mark"]["line_json"])[cc.FIELD]
    assert (
        stored["asked"] is True
        and stored["agree"] is False
        and stored["model"] == "openai/gpt-oss-120b"
    )
    assert stored["usd"] > 0 and stored["reason"] == "invented reason"
    for iid in ("R-coat", "R-mark"):  # a line's own usd stays Claude's
        assert (
            json.loads(lines_of(run_id)[iid]["line_json"])["usd"]
            == json.loads(lines_of(off_run)[iid]["line_json"])["usd"]
        )


def test_only_the_two_quotes_leave(w, monkeypatch, groq):
    switch_on(monkeypatch)
    approve(claude=[sha(s.PAPER), sha(s.STD)], groq=[sha(s.PAPER), sha(s.STD)])
    run_shown_review()
    assert groq.sent
    for req in groq.sent:
        text = json.dumps(req["body"])
        for never in (
            "paper.pdf",
            "INV-STD-100.pdf",
            s.PAPER,
            s.STD,
            "Serial invented",
            "DATA SHEET",
            "4.5 Colour",
        ):
            assert never not in text, never
        user = json.loads(req["body"]["messages"][1]["content"])
        assert set(user) == {"colour", "document_quote", "clause_quote", "question"}
        assert (
            user["document_quote"] in s.PAPER_PAGE
            and user["clause_quote"] in s.STD_PAGE
        )


def test_not_approved_sends_nothing_and_the_line_says_so(w, monkeypatch, no_client):
    switch_on(monkeypatch)
    approve(
        claude=[sha(s.PAPER), sha(s.STD)], groq=[sha(s.PAPER)]
    )  # the rule book is not on the Groq list
    run_id = run_shown_review()
    rows = _rows(run_id)
    assert (
        cc.NOT_APPROVED_SAID in rows["R-mark"][2]
        and rows["R-mark"][0] == W.CLASS_TWO_READERS
    )
    assert (
        cc.NOT_APPROVED_SAID not in rows["R-frame"][2]
    )  # a proven line says nothing of it
    step = _counts(run_id)[1]["crosscheck_step"]
    assert (step["asked"], step["not_approved"], step["usd"]) == (0, 2, 0.0)


def test_a_4xx_costs_nothing_and_changes_no_line(w, monkeypatch):
    fake = FakeGroq(status=429, raw=b'{"error": {"message": "slow down"}}')
    monkeypatch.setattr(httpx, "Client", fake.client)
    off_rows = _rows(run_shown_review())
    switch_on(monkeypatch)
    approve(claude=[sha(s.PAPER), sha(s.STD)], groq=[sha(s.PAPER), sha(s.STD)])
    run_id = run_shown_review()
    assert len(fake.sent) == 2
    step = _counts(run_id)[1]["crosscheck_step"]
    assert (step["no_answer"], step["usd"]) == (2, 0.0) and groq_spend.spent(
        run=run_id
    ) == 0.0
    on_rows = _rows(run_id)
    assert {k: v[:2] for k, v in on_rows.items()} == {
        k: v[:2] for k, v in off_rows.items()
    }
    assert cc.NO_ANSWER_SAID in on_rows["R-mark"][2]


def test_a_5xx_is_charged_its_worst_case(w, monkeypatch):
    fake = FakeGroq(status=503, raw=b"{}")
    monkeypatch.setattr(httpx, "Client", fake.client)
    switch_on(monkeypatch)
    approve(claude=[sha(s.PAPER), sha(s.STD)], groq=[sha(s.PAPER), sha(s.STD)])
    run_id = run_shown_review()
    assert (
        groq_spend.spent(run=run_id) > 0
    )  # may have been billed: charged at the worst case


def test_the_run_cap_stops_the_step_and_the_rest_say_so(w, monkeypatch, groq):
    switch_on(monkeypatch)
    monkeypatch.setattr(settings, "groq_crosscheck_usd_per_run", 0.0)
    approve(claude=[sha(s.PAPER), sha(s.STD)], groq=[sha(s.PAPER), sha(s.STD)])
    run_id = run_shown_review()
    assert groq.sent == []
    step = _counts(run_id)[1]["crosscheck_step"]
    assert (
        step["off"] == groq_spend.RUN_CAP
        and step["asked"] == 0
        and step["not_run_cap"] == 2
    )
    assert cc.CAP_SAID in _rows(run_id)["R-mark"][2]


# ------------------------------------------------------------------ 7. review R-1854


class FakeRunner(ccrun.CrosscheckMixin):
    """The runner's parts the cross-check step reads, around stored lines."""

    def __init__(self, *lines):
        self.lines = {ln["item_id"]: dict(ln) for ln in lines}
        self.paper, self.local, self.sink = s.PAPER, None, None
        self._stop, self._lock = threading.Event(), threading.Lock()

    def exit_line(self, line):
        return W.apply(line)


def _line(item_id, **extra):
    return {
        **opinion_line(),
        "item_id": item_id,
        "standard_document_id": s.STD,
        **extra,
    }


def _ready(monkeypatch):
    switch_on(monkeypatch)
    approve(claude=[sha(s.PAPER), sha(s.STD)], groq=[sha(s.PAPER), sha(s.STD)])


@pytest.mark.parametrize(
    "checks",
    [
        {"paper": False, "clause": True},
        {"paper": True, "clause": False},
        {"paper": False, "clause": False},
        {},
    ],
)
def test_a_quote_code_did_not_verify_is_never_sent(checks, lib, monkeypatch, groq):
    _ready(monkeypatch)
    # an AI "not met" stays an opinion with an unverified quote (an unverified "met" is already a Query, N9): the gate is
    # the only thing between its quotes and the wire
    bad = {
        **_line("R-bad", quotes_checked=checks),
        "ai_verdict": "Fail",
        "reason_code": "not_met",
    }
    assert ccrun.candidate(bad)
    runner = FakeRunner(bad, _line("R-good"))
    runner.run_crosscheck()
    assert len(groq.sent) == 1  # the verified line only: the guard on the guard
    sent = json.loads(groq.sent[0]["body"]["messages"][1]["content"])
    assert sent["document_quote"] == "invented paper words"
    rec = runner.lines["R-bad"][cc.FIELD]
    assert (
        rec["asked"] is False
        and rec["code"] == "quotes_not_verified"
        and rec["said"] == cc.NOT_VERIFIED_SAID
    )
    assert runner.crosscheck_counts()["crosscheck_step"]["not_verified"] == 1


@pytest.mark.parametrize("field", ["paper_quote", "clause_quote"])
def test_a_quote_over_the_cap_keeps_the_line_at_home(field, lib, monkeypatch, groq):
    _ready(monkeypatch)
    at_cap = "w" * ccrun.MAX_QUOTE_CHARS
    runner = FakeRunner(
        _line("R-long", **{field: at_cap + "x"}), _line("R-at-cap", **{field: at_cap})
    )
    runner.run_crosscheck()
    assert len(groq.sent) == 1 and at_cap in json.dumps(
        groq.sent[0]["body"]
    )  # exactly at the cap is sent whole
    assert at_cap + "x" not in json.dumps(groq.sent)  # never cut and sent either
    rec = runner.lines["R-long"][cc.FIELD]
    assert rec["code"] == "quote_too_long" and rec["said"] == cc.TOO_LONG_SAID
    assert W.apply(runner.lines["R-long"])["not_proven_reason"].endswith(
        cc.TOO_LONG_SAID
    )


@pytest.mark.parametrize("ai", ["Pass", "Fail"])
def test_a_line_already_a_query_is_not_asked(ai, lib, monkeypatch, groq):
    """A met the guard holds and a not met the second reader said no to (#1851) are Queries: nothing to change, nothing sent."""
    _ready(monkeypatch)
    said_no = {"agree": False, "model": "m"}
    assert agent_run_second.disagreed(said_no)
    line = {**_line("R-q", second_opinion=said_no), "ai_verdict": ai}
    assert (
        W.classify(line)["verdict_class"] == W.CLASS_QUERY
    )  # main's own rule, for both words
    runner = FakeRunner(line)
    runner.run_crosscheck()
    assert groq.sent == [] and cc.FIELD not in runner.lines["R-q"]
    assert runner.crosscheck_counts()["crosscheck_step"]["candidates"] == 0


def test_a_met_the_guard_holds_is_not_asked(lib, monkeypatch, groq):
    """A Query by the met guard alone (the paper quote defers the value; no second reader said anything): not sent either."""
    _ready(monkeypatch)
    line = _line("R-tba", paper_quote="TBA")
    assert not agent_run_second.disagreed(line.get("second_opinion"))
    assert W.classify(line)["verdict_class"] == W.CLASS_QUERY
    runner = FakeRunner(line, _line("R-good"))
    runner.run_crosscheck()
    assert (
        len(groq.sent) == 1 and cc.FIELD not in runner.lines["R-tba"]
    )  # the good line only
    assert runner.crosscheck_counts()["crosscheck_step"]["candidates"] == 1


@pytest.mark.parametrize(
    "second_ai,shown", [(False, True), (True, False), (False, False)]
)
def test_a_run_whose_start_did_not_show_the_second_ai_sends_nothing(
    second_ai, shown, lib, monkeypatch, no_client
):
    _ready(monkeypatch)
    record_start("run-other", second_ai=second_ai, shown=shown)
    with claude_spend.for_run("run-other"):
        assert groq_approved.refusal([s.PAPER]) == groq_approved.NOT_SHOWN
        runner = FakeRunner(_line("R-1"))
        runner.run_crosscheck()
    rec = runner.lines["R-1"][cc.FIELD]
    assert rec["code"] == groq_approved.NOT_SHOWN and rec["said"] == cc.NOT_SHOWN_SAID
    with (
        pytest.raises(groq_transport.GroqRefused, match=groq_approved.NOT_SHOWN),
        claude_spend.for_run("run-other"),
    ):
        groq_transport.send(BODY, document_ids=[s.PAPER])


def test_no_run_at_all_sends_nothing(lib, monkeypatch, no_client):
    _ready(monkeypatch)
    with claude_spend.for_run(
        None
    ):  # a script or a retry queue: no review run, no stored list
        assert groq_approved.refusal([s.PAPER]) == groq_approved.NOT_SHOWN
    assert (
        groq_approved.refusal([s.PAPER]) is None
    )  # the guard on the guard: the shown run passes


def test_a_queued_run_with_no_stored_list_sends_nothing_and_says_so(
    w, monkeypatch, no_client
):
    switch_on(monkeypatch)
    approve(claude=[sha(s.PAPER), sha(s.STD)], groq=[sha(s.PAPER), sha(s.STD)])
    run_id = (
        run_review()
    )  # queued straight onto the job queue, as a script does: no plan, no shown list
    assert cc.NOT_SHOWN_SAID in _rows(run_id)["R-mark"][2]
    assert _counts(run_id)[1]["crosscheck_step"]["not_shown"] == 2


def test_the_plan_shows_the_second_ai_line_only_when_it_can_run(lib, monkeypatch):
    assert groq_approved.plan_line(True, True) is None  # switch off: not shown
    switch_on(monkeypatch)
    assert groq_approved.plan_line(True, True)["words"] == groq_approved.PLAN_WORDS
    assert groq_approved.plan_line(False, True) is None  # nothing leaves (Local only)
    assert (
        groq_approved.plan_line(True, False) is None
    )  # the AI review is not on Claude

    class Part:
        engine = review_engine.ON_CLAUDE

    class Plan:
        text_leaves, choice = True, "claude"

        def part(self, name):
            return Part()

    monkeypatch.setattr(
        review_leaving, "leaving_for", lambda *a, **k: {"leaving": [], "not_sent": []}
    )
    monkeypatch.setattr(review_engine, "_earlier_books", lambda *a: [])
    ctx = (db.connect(), s.PAPER, frozenset({s.PAPER}), None, None)
    docs = review_leaving.documents_block(ctx, Plan(), ())
    assert docs[groq_approved.PLAN_KEY]["words"] == groq_approved.PLAN_WORDS
    assert "Groq (another AI company)" in groq_approved.PLAN_WORDS
    monkeypatch.setattr(settings, "groq_crosscheck_enabled", False)
    assert groq_approved.PLAN_KEY not in review_leaving.documents_block(ctx, Plan(), ())


def test_a_follow_on_plan_may_not_add_the_second_ai_line():
    started = {"documents": {}}
    again = {"documents": {groq_approved.PLAN_KEY: {"words": "x"}, "leaving": []}}
    groq_approved.narrow_replan(started, again)
    assert groq_approved.PLAN_KEY not in again["documents"]
    kept = {"documents": {groq_approved.PLAN_KEY: {"words": "x"}}}
    groq_approved.narrow_replan(
        {"documents": {groq_approved.PLAN_KEY: {"words": "x"}}}, kept
    )
    assert groq_approved.PLAN_KEY in kept["documents"]


def test_the_not_run_note_is_on_the_page_too():
    line = {
        **opinion_line(),
        cc.FIELD: {
            "asked": False,
            "agree": None,
            "code": "c",
            "said": cc.NOT_APPROVED_SAID,
        },
    }
    assert W.read_time(line)["not_proven_reason"].endswith("; " + cc.NOT_APPROVED_SAID)
    assert (
        W.read_time(opinion_line())["not_proven_reason"]
        == W.classify(opinion_line())["not_proven_reason"]
    )


def test_the_reservation_is_a_strict_upper_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    line = _line("R-u", paper_quote="\u4e2d" * 100)  # 100 characters, 300 UTF-8 bytes
    body = ccrun.body_for(line, "openai/gpt-oss-120b")
    sent = json.dumps(body["messages"], ensure_ascii=False).encode("utf-8")
    worst = groq_spend.worst_case_usd(
        "openai/gpt-oss-120b", len(sent), ccrun.MAX_TOKENS
    )
    every_byte_a_token = groq_spend.cost_usd(
        "openai/gpt-oss-120b",
        {"prompt_tokens": len(sent), "completion_tokens": ccrun.MAX_TOKENS},
    )
    assert worst >= every_byte_a_token
    monkeypatch.setattr(settings, "groq_crosscheck_usd_per_run", worst * 1.5)
    res = groq_spend.reserve("run-x", "openai/gpt-oss-120b", worst)
    assert (
        groq_spend.settle(res, worst * 3) == worst
    )  # never charged above the reservation
    assert groq_spend.spent(run="run-x") == pytest.approx(worst)
    excess = [e for e in groq_spend.entries() if e.get("excess_usd")]
    assert excess and excess[0]["excess_usd"] == pytest.approx(worst * 2)


# ------------------------------------------------------------------ review R2-1854: egress, money, wording, one home


@pytest.mark.parametrize(
    "paper,book",
    [(s.PAPER, None), (s.PAPER, ""), (None, s.STD), ("", s.STD), (None, None)],
)
def test_a_quote_whose_document_is_not_known_stays_home(
    paper, book, lib, monkeypatch, groq
):
    """Every document whose words a request carries must be KNOWN (and on both lists): a clause quote with no book id, or a
    paper quote with no paper id, is never sent with a partial declaration (R2-1854: it was sent with the paper alone)."""
    _ready(monkeypatch)
    runner = FakeRunner(_line("R-nobook", standard_document_id=book))
    runner.paper = paper
    runner.run_crosscheck()
    assert groq.sent == [] and groq.built == 0
    rec = runner.lines["R-nobook"][cc.FIELD]
    assert rec["asked"] is False and rec["code"] == "source_unknown"
    assert rec["said"] == cc.SOURCE_UNKNOWN_SAID
    assert W.apply(runner.lines["R-nobook"])["not_proven_reason"].endswith(
        cc.SOURCE_UNKNOWN_SAID
    )
    assert runner.crosscheck_counts()["crosscheck_step"]["source_unknown"] == 1
    assert ccrun.carried_ids(s.PAPER, _line("R-ok")) == sorted({s.PAPER, s.STD})


def _usage_answer(usage_json: str) -> bytes:
    """A good answer whose `usage` is the raw JSON text given (it may hold Infinity, NaN or an absurd number)."""
    text = json.dumps({"agree": True, "reason": "invented reason"})
    choices = json.dumps([{"finish_reason": "stop", "message": {"content": text}}])
    return (
        '{"model": "openai/gpt-oss-120b", "usage": ' + usage_json + ', "choices": '
        + choices + "}"
    ).encode()  # fmt: skip


@pytest.mark.parametrize(
    "usage",
    [
        '{"prompt_tokens": Infinity, "completion_tokens": 10}',
        '{"prompt_tokens": 10, "completion_tokens": 1e999}',
        '{"prompt_tokens": NaN, "completion_tokens": 10}',
        '{"prompt_tokens": -Infinity, "completion_tokens": 10}',
        '{"prompt_tokens": [1, 2], "completion_tokens": 10}',
        '{"prompt_tokens": 1' + "0" * 400 + ', "completion_tokens": 10}',
        "[1, 2]",
    ],
)
def test_every_hold_is_closed_once_whatever_the_usage_says(
    usage, lib, monkeypatch, groq
):
    """R2-1854: a usage of Infinity or 1e999 raised OverflowError between the call and the settlement: holds written, none
    closed. Now every reservation is closed exactly once, at its worst case and marked estimated, and the line is answered."""
    _ready(monkeypatch)
    groq.raw = _usage_answer(usage)
    runner = FakeRunner(_line("R-a"), _line("R-b"))
    runner.run_crosscheck()
    st = runner.crosscheck_counts()["crosscheck_step"]
    assert st["off"] is None and st["asked"] == 2 and st["agreed"] == 2
    raw = groq_spend._raw_lines()
    holds = [e["reservation"] for e in raw if e.get("reservation")]
    closes = [e for e in raw if e.get("settles") or e.get("releases")]
    assert len(holds) == 2
    assert sorted(e.get("settles") for e in closes) == sorted(holds)  # once each
    worst = {e["reservation"]: e["cost_usd"] for e in raw if e.get("reservation")}
    for e in closes:
        assert e["estimated"] is True and e["cost_usd"] == worst[e["settles"]]
    assert "Infinity" not in groq_spend.ledger_path().read_text(encoding="utf-8")
    for iid in ("R-a", "R-b"):
        assert runner.lines[iid][cc.FIELD]["agree"] is True


@pytest.mark.parametrize(
    "usage",
    [
        {"prompt_tokens": float("inf"), "completion_tokens": 1},
        {"prompt_tokens": 1, "completion_tokens": float("nan")},
        {"prompt_tokens": 10**400, "completion_tokens": 1},
        {"prompt_tokens": [1], "completion_tokens": 1},
        [1, 2],
        "12",
    ],
)
def test_a_usage_that_is_no_count_costs_nothing_known(usage, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    assert groq_spend.cost_usd("openai/gpt-oss-120b", usage) is None
    res = groq_spend.reserve("run-u", "openai/gpt-oss-120b", 0.001)
    assert groq_spend.settle_usage(res, {"usage": usage}) == 0.001
    for bad in (float("inf"), float("nan")):  # a NaN on the ledger would pass every cap
        held = groq_spend.reserve("run-v", "openai/gpt-oss-120b", 0.001)
        assert groq_spend.settle(held, bad) == 0.001
    assert groq_spend.spent() == pytest.approx(0.003)
    text = groq_spend.ledger_path().read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text


def test_a_line_the_second_ai_disagreed_with_asks_the_engineer_in_the_team_file(
    w, monkeypatch, groq, tmp_path
):
    """R2-1854: the action of a line the second AI disagreed with comes from the ONE home of a disagreement ("Engineer to
    check ...: the readers disagree"), never "Contractor to confirm or justify", in the team file as built."""
    import openpyxl

    from app import crs_ai_actions, crs_ai_workbook
    from app.review_points_service import run_meta, stored_lines

    switch_on(monkeypatch)
    approve(claude=[sha(s.PAPER), sha(s.STD)], groq=[sha(s.PAPER), sha(s.STD)])
    run_id = run_shown_review()
    conn = db.connect()
    lines = stored_lines(conn, run_id)
    mark = next(ln for ln in lines if ln["item_id"] == "R-mark")
    assert cc.disagrees(mark) and crs_ai_actions.action_case(mark) == "disagree"
    meta = run_meta(conn, run_id, s.PAPER, tmp_path)
    path = crs_ai_workbook.write(lines, tmp_path / "team.xlsx", meta, "internal")
    cells = [
        str(c.value)
        for ws in openpyxl.load_workbook(path).worksheets
        for row in ws.iter_rows()
        for c in row
        if c.value is not None
    ]
    disagree = [c for c in cells if ": the readers disagree." in c]
    assert len(disagree) == 1 and "Engineer to check " in disagree[0]
    assert not any("Contractor to confirm or justify" in c for c in cells)


@pytest.mark.parametrize("ai", ["Pass", "Fail"])
@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"rule_tier": W.RULE_NOT_APPROVED},
        {"reason_code": "sheet_silent"},
        {"conditional_hold": True},
        {"quotes_checked": {"paper": True, "clause": False}},
    ],
)
def test_a_line_the_claude_second_opinion_said_no_to_is_never_a_candidate(ai, extra):
    """`candidate` has no check of its own for "the second reader said no" (R2-1854: it could never fire): the wording's ONE
    home makes every such unproven line a Query or a class that is not asked, whatever else the line holds."""
    line = {
        **_line("R-n", **extra),
        "ai_verdict": ai,
        "second_opinion": {"agree": False, "model": "m"},
    }
    assert cc.unproven_ai_line(line)
    assert W.classify(line)["verdict_class"] not in ccrun.CANDIDATE_CLASSES
    assert not ccrun.candidate(line)
