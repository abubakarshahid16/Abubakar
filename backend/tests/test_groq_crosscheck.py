"""The second AI's cross-check on Groq (owner decision 17 Nov 2026, #1584): off by default, gated, only quotes leave,
it can only make a line less confident, and it has its own money caps. Invented paper, rule book, models and key; no
network: `httpx.Client` is a fake that records what would have left, or a guard that fails the test if it is built."""

# ruff: noqa: F811
from __future__ import annotations

import hashlib
import json
import logging

import httpx
import pytest

from app import (
    agent_claude,
    classification,
    claude_approved,
    db,
    groq_approved,
    groq_spend,
    groq_transport,
    review_engine,
)
from app import agent_review_crosscheck as cc
from app import agent_review_crosscheck_run as ccrun
from app import agent_review_wording as W
from app.config import Settings, settings
from tests import agent_review_support as s
from tests.test_agent_review_guards import run_review, w  # noqa: F401
from tests.test_agent_review_job import lines_of

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


@pytest.fixture
def lib(tmp_path, monkeypatch):
    s.setup_world(tmp_path, monkeypatch)
    with db.connect() as conn:
        s.add_document(conn, "doc_contract", "contract.pdf", "invented")
        # the register's name, from the block's own key (never spelt out here), with a copy suffix
        register = claude_approved.REGISTER_NAME_KEY + " (1).pdf"
        s.add_document(conn, "doc_register", register, "invented")
    classification.set_role("doc_contract", "CONTRACT_DOCUMENT")
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
        (b"x" * (groq_transport.MAX_RESPONSE_BYTES + 1), "application/json"),
        (b"<html>hello</html>", "text/html"),
        (b"[1, 2]", "application/json"),
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
    ) == pytest.approx((700 * 0.15 + 1000 * 0.75) / 1e6)
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
    }  # two Claude readers disagreed
    assert W.classify(disagreed)["verdict_class"] == W.CLASS_QUERY and ccrun.candidate(
        disagreed
    )


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
    off_run = run_review()
    off_rows, off_usd = _rows(off_run), _counts(off_run)[0]
    switch_on(monkeypatch)
    approve(claude=[sha(s.PAPER), sha(s.STD)], groq=[sha(s.PAPER), sha(s.STD)])
    run_id = run_review()
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
    run_review()
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
    run_id = run_review()
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
    off_rows = _rows(run_review())
    switch_on(monkeypatch)
    approve(claude=[sha(s.PAPER), sha(s.STD)], groq=[sha(s.PAPER), sha(s.STD)])
    run_id = run_review()
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
    run_id = run_review()
    assert (
        groq_spend.spent(run=run_id) > 0
    )  # may have been billed: charged at the worst case


def test_the_run_cap_stops_the_step_and_the_rest_say_so(w, monkeypatch, groq):
    switch_on(monkeypatch)
    monkeypatch.setattr(settings, "groq_crosscheck_usd_per_run", 0.0)
    approve(claude=[sha(s.PAPER), sha(s.STD)], groq=[sha(s.PAPER), sha(s.STD)])
    run_id = run_review()
    assert groq.sent == []
    step = _counts(run_id)[1]["crosscheck_step"]
    assert (
        step["off"] == groq_spend.RUN_CAP
        and step["asked"] == 0
        and step["not_run_cap"] == 2
    )
    assert cc.CAP_SAID in _rows(run_id)["R-mark"][2]
