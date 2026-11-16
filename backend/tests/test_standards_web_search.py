"""Online search for rule books we do not hold (owner, 17 Nov 2026, #1584; review R-1853). Fake senders only: no network, no real
key."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import httpx
import pytest
from openpyxl import load_workbook

from app import (
    agent_claude,
    agent_review_jobs,
    claude_approved,
    claude_spend,
    crs_one,
    db,
    review_engine,
    review_leaving,
    review_points_service,
)
from app import standards_web_search as sws
from app.config import settings
from tests.test_b1_review_points import world_with_both
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_k4_one_crs import scope_all

KEY = "sk-test-NOT-A-REAL-KEY-0123456789"
ENV = {
    "REASONING_PROVIDER": "claude",
    "STANDARDS_READER_ENABLED": "1",
    "STANDARDS_READER_ALLOW_PUBLIC_EGRESS": "1",
    "ANTHROPIC_API_KEY": KEY,
}
USAGE = {
    "input_tokens": 20_000,
    "output_tokens": 150,
    "server_tool_use": {"web_search_requests": 2},
}
FOUND = {
    "title": "Pressure-relieving and Depressuring Systems",
    "latest_edition": "Seventh Edition",
    "year": 2020,
    "publisher": "American Petroleum Institute",
    "url": "https://www.api.org/products-and-services/standards",
}
EXPORTED = "2026-11-17 10:00 UTC"


@pytest.fixture(autouse=True)
def _on(monkeypatch, tmp_path, temp_db):  # noqa: F811
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(settings, "review_code_resubmit_at_kept_mandatory_not_met", 0)
    monkeypatch.setattr(settings, "standards_web_search_enabled", True)
    monkeypatch.setattr(settings, "standards_web_search_usd_per_run", 0.50)
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)


class Sender:
    def __init__(
        self, reply=None, raises=None, usage=USAGE, stop="end_turn", content=None
    ):
        text = (
            reply
            if isinstance(reply, str)
            else json.dumps(FOUND if reply is None else reply)
        )
        self.answer = {
            "model": sws.MODEL,
            "stop_reason": stop,
            "content": content
            if content is not None
            else [
                {
                    "type": "server_tool_use",
                    "id": "s1",
                    "name": "web_search",
                    "input": {"query": "q"},
                },
                {"type": "web_search_tool_result", "tool_use_id": "s1", "content": []},
                {"type": "text", "text": text},
            ],
            "usage": usage,
        }
        self.raises, self.bodies, self.headers, self.timeouts = raises, [], [], []

    def __call__(self, url, *, headers, body, timeout):
        self.bodies.append(json.loads(json.dumps(body)))
        self.headers.append(dict(headers))
        self.timeouts.append(timeout)
        if self.raises is not None:
            raise self.raises
        return self.answer


def answered(run_id: str, finish: str = "end_turn") -> None:
    """A ledger line of the run's AI reviewer: one Claude call answered (the paper went to Claude)."""
    with claude_spend.for_run(run_id):
        claude_spend.record(step=agent_claude.STEP, model="claude-sonnet-5-5", usage={"input_tokens": 10, "output_tokens": 5},
                            prompt_sha256="x", wall_time_s=0.0, finish_reason=finish)  # fmt: skip


def missing(run_id: str, *names: str, sent: bool = True) -> None:
    with db.connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO agent_review_missing_book (run_id, name, why) VALUES (?,?,?)",
            [(run_id, n, "cited") for n in names],
        )
    if sent:
        answered(run_id)


def rows(run_id: str) -> dict[str, dict]:
    conn = db.connect()
    return {
        r["name"]: dict(r)
        for r in conn.execute(
            "SELECT * FROM standards_web_search WHERE run_id = ?", (run_id,)
        )
    }


def has_table() -> bool:
    found = (
        db.connect()
        .execute("SELECT 1 FROM sqlite_master WHERE name = 'standards_web_search'")
        .fetchone()
    )
    return found is not None


def cells(data: bytes) -> dict[str, list]:
    wb = load_workbook(io.BytesIO(data))
    return {
        ws.title: [list(r) for r in ws.iter_rows(values_only=True)]
        for ws in wb.worksheets
    }


def open_reservations() -> list[dict]:
    return [e for e in claude_spend.entries() if e.get("reserved")]


# ------------------------------------------------------------------------------------------------ off


def test_off_nothing_is_asked_nothing_is_created_and_the_page_and_file_are_unchanged(
    monkeypatch,
):
    doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521")
    monkeypatch.setattr(settings, "standards_web_search_enabled", False)
    before_page = review_points_service.assemble(doc, scope_all())
    before = cells(crs_one.build_team(doc, scope_all(), exported=EXPORTED))
    send = Sender()
    assert sws.search_run(ai, send=send, env=ENV) == {"ran": False}
    sws.after_run(ai)
    assert send.bodies == [] and not has_table()
    assert "found_online" not in before_page["counts"]["not_held"]
    # a stored search (made while it was on) changes nothing once it is off
    monkeypatch.setattr(settings, "standards_web_search_enabled", True)
    sws.search_run(ai, send=Sender(), env=ENV)
    assert has_table()
    monkeypatch.setattr(settings, "standards_web_search_enabled", False)
    assert review_points_service.assemble(doc, scope_all()) == before_page
    assert cells(crs_one.build_team(doc, scope_all(), exported=EXPORTED)) == before
    assert before[crs_one.HELD_SHEET][2] == ["Rule book", "What it means"]
    assert sws.plan_note(True) is None


# ------------------------------------------------------------------------------------------------ what leaves


def test_only_the_cleaned_public_name_leaves_never_the_paper_or_its_words():
    doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521", "Datasheet 1 page 4 note on drum.pdf", "SAES-L-108")
    send = Sender()
    got = sws.search_run(ai, send=send, env=ENV)
    assert got["asked"] == 1 and len(send.bodies) == 1
    body = send.bodies[0]
    assert body["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "Standard: API 521"}]}
    ]
    assert body["system"] == [{"type": "text", "text": sws.SYSTEM}]
    assert (
        body["tools"] == [sws.tool()]
        and body["tools"][0]["type"] == "web_search_20250305"
    )
    assert (
        body["tools"][0]["allowed_domains"] == list(sws.PUBLISHER_DOMAINS)
        and body["tools"][0]["max_uses"] == 2
    )
    assert body["model"] == sws.MODEL
    # nothing else carries text: every other key is a fixed request setting
    assert set(body) - {"messages", "system", "tools", "model", "max_tokens"} <= {
        "temperature",
        "thinking",
        "output_config",
    }
    sent = json.dumps(body)
    for leak in ("drum.pdf", "Datasheet", "page 4", "SAES", doc):
        assert leak not in sent
    assert send.timeouts[0] <= sws.REQUEST_TIMEOUT_SECONDS
    stored = rows(ai)
    assert stored["Datasheet 1 page 4 note on drum.pdf"]["outcome"] == sws.NOT_SEARCHED
    assert stored["Datasheet 1 page 4 note on drum.pdf"]["searched_name"] is None
    assert stored["SAES-L-108"]["why"] == sws.NOT_PUBLIC
    assert stored["API 521"]["searched_name"] == "API 521"


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        ("API 521", "API 521"),
        ("NACE MR0175/ISO 15156-3", "NACE MR0175 ISO 15156-3"),
        ("asme bpvc section viii div. 1", "ASME BPVC SECTION VIII DIV 1"),
        ("ISO 15156" + chr(0x2011) + "3", "ISO 15156-3"),  # a non-breaking hyphen
        ("ASME B16.5" + chr(0x2013) + "2017", "ASME B16.5-2017"),  # an en dash
        ("ASME B31.3", "ASME B31.3"),
        ("API 520 Part I", "API 520 PART I"),
        ("API 520-I", "API 520-I"),
        ("NACE TM0177", "NACE TM0177"),
        ("API 650 13th Edition", "API 650 13TH EDITION"),
        ("ISO 9001:2015", "ISO 9001 2015"),
        ("API 610 as per the datasheet", None),
        ("API 610; see page 3", None),
        ("SAES-L-108", None),
        # tags and document numbers (review R-1853, finding 7)
        ("API 610 ZQ4821-ABC-I-07", None),
        ("ASTM QXV4821", None),
        ("IEC ZQ4821", None),
        ("AWS ZQ4821.07", None),
        (chr(0x391) + "PI 521", None),  # a Greek capital alpha that looks like an A
        ("ISO " + chr(0xFF19) + "001", None),  # a full-width digit nine
        ("API", None),
        ("ISO " + "1" * 70, None),
        ("", None),
    ],
)
def test_a_name_is_rebuilt_from_closed_word_shapes_or_refused(raw, cleaned):
    assert sws.clean_name(raw) == cleaned


# ------------------------------------------------------------------------------------------------ the names come from the paper


def test_a_run_that_sent_nothing_to_claude_sends_no_name():
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521", "ISO 9001", sent=False)
    answered(ai, finish="refused:not_approved")  # refusals and failures only
    answered(ai, finish="failed:HTTPStatusError:http_400")
    send = Sender()
    sws.search_run(ai, send=send, env=ENV)
    assert send.bodies == []
    assert {r["why"] for r in rows(ai).values()} == {sws.NOT_SENT_WORDS}


def test_a_blocked_paper_sends_no_name_even_after_its_review_sent_it():
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521")
    with (
        db.connect() as conn
    ):  # a file the owner marked in the block file (invented name)
        conn.execute(
            "UPDATE documents SET filename = 'pumpsheet.pdf' WHERE id = 'doc_sub'"
        )
    claude_approved.block_file_path().write_text(
        json.dumps({"blocked_names": ["pumpsheet.pdf"]}), encoding="utf-8"
    )
    send = Sender()
    sws.search_run(ai, send=send, env=ENV)
    assert send.bodies == []
    assert rows(ai)["API 521"]["why"].startswith(
        "the paper is not cleared for Claude now"
    )


def test_with_the_list_enforced_an_unapproved_paper_sends_nothing_and_an_approved_one_is_declared(
    monkeypatch,
):
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521")
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    send = Sender()
    sws.search_run(ai, send=send, env=ENV)
    assert send.bodies == [] and rows(ai)["API 521"]["why"].startswith(
        "the paper is not cleared for Claude now (not_approved)"
    )
    with db.connect() as conn:
        conn.execute("DELETE FROM standards_web_search")
    claude_approved.list_path().write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "sha256": "sha-doc_sub",
                        "document_id": "doc_sub",
                        "status": "approved",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    seen = []
    real = claude_approved.refusal
    monkeypatch.setattr(
        claude_approved,
        "refusal",
        lambda: seen.append(claude_approved.carried()) or real(),
    )
    sws.search_run(ai, send=send, env=ENV)
    assert len(send.bodies) == 1
    assert seen and all(
        "doc_sub" in (c or ()) for c in seen
    )  # every check was asked about THE PAPER


def test_a_run_kept_on_this_computer_sends_nothing():
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521", "ISO 9001")
    send = Sender()
    with review_engine.barring():
        sws.search_run(ai, send=send, env=ENV)
    assert send.bodies == []
    assert {r["outcome"] for r in rows(ai).values()} == {sws.NOT_SEARCHED}


def test_the_plan_before_the_start_says_what_the_search_may_send(monkeypatch):
    monkeypatch.setattr(
        review_leaving,
        "leaving_for",
        lambda *a, **k: {"leaving": [], "not_sent": [], "not_readable": 0},
    )
    monkeypatch.setattr(review_engine, "_earlier_books", lambda conn, doc: [])

    def plan(ai_engine: str, leaves: bool = True):
        part = SimpleNamespace(engine=ai_engine)
        return SimpleNamespace(
            text_leaves=leaves, choice="claude", part=lambda name: part
        )

    ctx = (db.connect(), "doc_sub", frozenset(), None, None)
    docs = review_leaving.documents_block(ctx, plan("claude"), ())
    assert docs["web_search"] == sws.plan_note(True)
    assert (
        "public names of rule books" in docs["web_search"]
        and "never document text" in docs["web_search"]
    )
    assert "web_search" not in review_leaving.documents_block(ctx, plan("local"), ())
    assert "web_search" not in review_leaving.documents_block(
        ctx, plan("claude", leaves=False), ()
    )
    monkeypatch.setattr(settings, "standards_web_search_enabled", False)
    assert "web_search" not in review_leaving.documents_block(ctx, plan("claude"), ())


# ------------------------------------------------------------------------------------------------ money


def test_the_search_fee_is_reserved_before_and_charged_after():
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521")
    sws.search_run(ai, send=Sender(), env=ENV)
    lines = [e for e in claude_spend._raw_lines() if e.get("step") == sws.STEP]
    held = [e for e in lines if e.get("reserved")]
    assert (
        len(held) == 2
    )  # the request's own worst case and the search part metered does not see
    extra = sws.extra_worst_usd(sws.body_parts("API 521"))
    assert any(abs(e["cost_usd"] - round(extra, 6)) < 1e-6 for e in held)
    assert any(
        e.get("finish_reason") == "web_search_fee" and abs(e["cost_usd"] - 0.02) < 1e-9
        for e in lines
    )
    tokens = claude_spend.cost_usd(sws.MODEL, USAGE)
    assert rows(ai)["API 521"]["usd"] == pytest.approx(tokens + 0.02)
    assert claude_spend.spent(sws.STEP) == pytest.approx(tokens + 0.02)
    assert open_reservations() == []


def test_the_worst_case_covers_three_samplings_of_every_result_at_the_long_context_rate():
    parts = sws.body_parts("API 521")
    samplings, prompt = sws.MAX_USES + 1, sws._prompt_tokens(parts)
    worst_call = {
        "input_tokens": samplings
        * (sws.MAX_USES * sws.SEARCH_RESULT_TOKENS_WORST + prompt + 100),
        "output_tokens": claude_spend.output_cap(sws.MODEL, sws.MAX_TOKENS),
    }
    assert (
        worst_call["input_tokens"] > claude_spend.LONG_PROMPT_TOKENS
    )  # billed at the long-context card
    billed = (
        claude_spend.cost_usd(sws.MODEL, worst_call)
        + sws.MAX_USES * sws.USD_PER_SEARCH_WORST
    )
    assert billed <= sws.main_worst_usd(parts) + sws.extra_worst_usd(parts)


def test_at_most_twelve_books_are_searched_in_one_run():
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, *[f"ISO {9000 + i}" for i in range(14)])
    send = Sender(usage={"input_tokens": 100, "output_tokens": 10})
    got = sws.search_run(ai, send=send, env=ENV)
    assert got["asked"] == sws.MAX_PER_RUN == len(send.bodies) == 12
    assert sum(r["why"] == sws.COUNT_WORDS for r in rows(ai).values()) == 2


def test_the_usd_limit_per_run_refuses_before_anything_is_sent(monkeypatch):
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521", "ISO 9001")
    monkeypatch.setattr(settings, "standards_web_search_usd_per_run", 0.05)
    send = Sender()
    sws.search_run(ai, send=send, env=ENV)
    assert send.bodies == []
    assert {r["why"] for r in rows(ai).values()} == {sws.CAP_WORDS}


def test_the_time_limit_stops_the_search_and_says_so(monkeypatch):
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521", "ISO 9001")
    monkeypatch.setattr(sws, "TIME_LIMIT_SECONDS", 0.0)
    send = Sender()
    sws.search_run(ai, send=send, env=ENV)
    assert send.bodies == []
    assert {r["why"] for r in rows(ai).values()} == {sws.TIME_WORDS}
    assert sws.TIME_WORDS.startswith("search stopped: time limit")


def test_a_claude_spend_cap_stops_the_run_and_nothing_is_sent(monkeypatch):
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521", "ISO 9001")
    monkeypatch.setattr(
        settings, "claude_budget_usd_per_step", 0.05
    )  # below the search's worst case
    send = Sender()
    sws.search_run(ai, send=send, env=ENV)
    assert send.bodies == []
    assert all(r["why"].startswith("a limit stopped it") for r in rows(ai).values())
    assert claude_spend.spent(sws.STEP) == 0


def test_a_4xx_costs_nothing():
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521")
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    rejected = httpx.HTTPStatusError(
        "400", request=request, response=httpx.Response(400, request=request)
    )
    send = Sender(raises=rejected)
    sws.search_run(ai, send=send, env=ENV)
    assert len(send.bodies) == 1
    row = rows(ai)["API 521"]
    assert row["outcome"] == sws.FAILED and row["usd"] == 0
    assert claude_spend.spent(sws.STEP) == 0 and open_reservations() == []


# ------------------------------------------------------------------------------------------------ the failure tuple, by index


def test_a_longer_failure_tuple_is_read_by_index_and_the_reservation_is_closed(
    monkeypatch,
):
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521", "ISO 9001")
    monkeypatch.setattr(agent_claude, "_send_once", lambda raw, request, body, step: (None, ("transport", "transport_ReadTimeout", True, True)))  # fmt: skip
    sws.search_run(ai, send=Sender(), env=ENV)
    got = rows(ai)
    assert {r["outcome"] for r in got.values()} == {sws.FAILED}
    assert all(
        r["usd"] > 0 for r in got.values()
    )  # may have been billed: charged at the worst case
    assert open_reservations() == []


def test_an_account_stop_stops_the_loop_and_releases_the_reservation(monkeypatch):
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521", "ISO 9001")
    calls = []

    def stop(raw, request, body, step):
        calls.append(step)
        return None, ("stop", "account_no_credit", False, False)

    monkeypatch.setattr(agent_claude, "_send_once", stop)
    sws.search_run(ai, send=Sender(), env=ENV)
    assert len(calls) == 1  # the second book is not asked
    assert {r["why"] for r in rows(ai).values()} == {
        "a limit stopped it (account_no_credit)"
    }
    assert open_reservations() == [] and claude_spend.spent(sws.STEP) == 0


def test_an_error_after_the_send_never_leaves_the_reservation_open(monkeypatch):
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521")

    def boom(raw, request, body, step):
        raise RuntimeError("x")

    monkeypatch.setattr(agent_claude, "_send_once", boom)
    with pytest.raises(RuntimeError):
        sws.search_run(ai, send=Sender(), env=ENV)
    assert open_reservations() == []


# ------------------------------------------------------------------------------------------------ what comes back


@pytest.mark.parametrize(
    ("url", "kept"),
    [
        ("https://www.api.org/standards/521", True),
        ("https://api.org/", True),
        ("https://www.iso.org/standard/1.html", True),
        ("https://evil.example.com/api.org", False),
        ("https://api.org.evil.example.com/", False),
        ("http://www.api.org/", False),
        ("https://user@www.api.org/", False),
        ("https://www.api.org:8443/", False),
        ("javascript:alert(1)", False),
    ],
)
def test_a_url_off_the_publishers_sites_is_dropped(url, kept):
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521")
    sws.search_run(ai, send=Sender({**FOUND, "url": url}), env=ENV)
    row = rows(ai)["API 521"]
    assert row["url"] == (url if kept else None)
    assert row["title"] == FOUND["title"]


def test_nothing_found_is_said_only_for_a_readable_answer_that_says_so():
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521")
    sws.search_run(ai, send=Sender({"title": None, "year": None, "url": None}), env=ENV)
    row = rows(ai)["API 521"]
    assert row["outcome"] == sws.NOTHING and row["year"] is None
    assert sws.words(row) == "searched online, nothing found on the publisher's site"
    # review R2-1856: a value that was reported but dropped (a year "soon") is never "nothing found"
    assert (
        sws.read_answer(
            {
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": '{"year": "soon"}'}],
            }
        )[1]
        is False
    )


@pytest.mark.parametrize(
    "sender",
    [
        Sender(stop="pause_turn"),
        Sender(stop="max_tokens"),
        Sender(stop="refusal"),
        Sender("I could not find this standard on the publisher's site."),
        Sender({"answer": "none"}),
        Sender(
            content=[
                {
                    "type": "server_tool_use",
                    "id": "s1",
                    "name": "web_search",
                    "input": {"query": "q"},
                },
                {
                    "type": "web_search_tool_result",
                    "tool_use_id": "s1",
                    "content": {
                        "type": "web_search_tool_result_error",
                        "error_code": "unavailable",
                    },
                },
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "title": None,
                            "latest_edition": None,
                            "year": None,
                            "publisher": None,
                            "url": None,
                        }
                    ),
                },
            ]
        ),
    ],
    ids=["pause_turn", "max_tokens", "refusal", "prose", "other_json", "search_error"],
)
def test_an_unreadable_answer_is_search_incomplete_never_nothing_found(sender):
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521")
    sws.search_run(ai, send=sender, env=ENV)
    row = rows(ai)["API 521"]
    assert row["outcome"] == sws.INCOMPLETE and row["title"] is None
    assert sws.words(row) == "search incomplete: the answer could not be read"


def test_what_is_found_is_only_on_the_sheet_of_books_not_held_never_a_rule_quote_clause_or_point(
    monkeypatch,
):
    doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521", "SAES-L-108")
    monkeypatch.setattr(settings, "standards_web_search_enabled", False)
    off_page = review_points_service.assemble(doc, scope_all())
    off = cells(crs_one.build_team(doc, scope_all(), exported=EXPORTED))
    monkeypatch.setattr(settings, "standards_web_search_enabled", True)
    sws.search_run(ai, send=Sender(), env=ENV)
    on_page = review_points_service.assemble(doc, scope_all())
    on = cells(crs_one.build_team(doc, scope_all(), exported=EXPORTED))
    # the points, their quotes, clauses and words are the same: the search is no verdict input
    assert (
        on_page["points"] == off_page["points"]
        and on_page["comments"] == off_page["comments"]
    )
    assert {k: v for k, v in on_page["counts"].items() if k != "not_held"} == {
        k: v for k, v in off_page["counts"].items() if k != "not_held"
    }
    found = on_page["counts"]["not_held"]["found_online"]
    assert [f["name"] for f in found] == ["API 521", "SAES-L-108"]
    assert sws.NOT_VERIFIED in found[0]["words"] and found[1]["words"].startswith(
        "not searched"
    )
    # every other sheet is the same cell for cell; the found title is only in the new column
    for title in off:
        if title not in (crs_one.HELD_SHEET, crs_one.HOW_SHEET):
            assert on[title] == off[title], title
    held = on[crs_one.HELD_SHEET]
    assert held[2] == ["Rule book", "What it means", sws.COLUMN]
    assert (
        held[3][0] == "API 521"
        and FOUND["title"] in held[3][2]
        and "not verified" in held[3][2]
    )
    assert held[3][1] == off[crs_one.HELD_SHEET][3][1]
    assert (
        sum(FOUND["title"] in str(c) for sheet in on.values() for r in sheet for c in r)
        == 1
    )
    # "How it was reviewed" says the search's own cost, apart from the AI review's (review R-1853, finding 6)
    added = [r for r in on[crs_one.HOW_SHEET] if r not in off[crs_one.HOW_SHEET]]
    assert added == [
        [sws.COST_ROW, pytest.approx(rows(ai)["API 521"]["usd"])]
        + [None] * (len(added[0]) - 2)
    ]


def test_the_key_is_used_in_the_header_and_appears_nowhere_else(caplog):
    caplog.set_level("DEBUG")
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521")
    send = Sender()
    sws.search_run(ai, send=send, env=ENV)
    assert send.headers[0]["x-api-key"] == KEY
    assert KEY not in json.dumps(send.bodies)
    assert KEY not in json.dumps(rows(ai), default=str)
    assert KEY not in caplog.text
    assert KEY not in settings.claude_spend_log.read_text(encoding="utf-8")


def test_the_ai_review_job_runs_the_search_when_it_finishes(monkeypatch):
    _doc, _rc, ai, _client = world_with_both()
    called = []
    monkeypatch.setattr(sws, "search_run", lambda run_id, **kw: called.append(run_id))
    monkeypatch.setattr(
        agent_review_jobs.crs_completeness, "record_after_run", lambda run_id: None
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, review_run_id, document_id, state, started_at, updated_at) VALUES (?,?,?,?,?,?)",
            ("job_t1", ai, "doc_sub", "running", "2026-11-17", "2026-11-17"),
        )
    result = {"partial": False, "stop_reason": None, "counts": {"lines": 3}}
    assert agent_review_jobs._done(db.connect(), "job_t1", ai, result) == "done"
    assert called == [ai]


def test_the_send_path_is_agent_claudes_own_under_its_own_step(monkeypatch):
    seen = []
    real = agent_claude._metered
    monkeypatch.setattr(
        agent_claude,
        "_metered",
        lambda send, step=agent_claude.STEP: seen.append(step) or real(send, step),
    )
    _doc, _rc, ai, _client = world_with_both()
    missing(ai, "API 521")
    sws.search_run(ai, send=Sender(), env=ENV)
    assert seen == [sws.STEP]


# --- review R2-1856 (invented values only)


@pytest.mark.parametrize(
    "raw",
    ["API 610 P101A", "ASME B16.5 V2301", "API 610 E 101", "API 610 123456 0012 07"],
)
def test_a_short_tag_or_number_after_a_designation_is_refused(raw):
    assert sws.clean_name(raw) is None


@pytest.mark.parametrize(
    "raw",
    [
        "API RP 520 Part I",
        "ASME VIII Div 1",
        "ISO 15156-3 2020",
        "API 610 11th Edition",
        "ASTM A105",
    ],
)
def test_real_designation_shapes_still_pass(raw):
    assert sws.clean_name(raw)


def test_a_reply_with_only_dropped_fields_is_incomplete_never_nothing_found():
    answer = {
        "stop_reason": "end_turn",
        "content": [
            {
                "type": "text",
                "text": '{"year": "2019", "url": "https://example.invalid/x"}',
            }
        ],
    }
    _fields, readable = sws.read_answer(answer)
    assert readable is False


def test_the_search_books_its_spend_to_the_run_by_itself(monkeypatch):
    from app import claude_spend

    seen = []
    monkeypatch.setattr(sws, "enabled", lambda: True)
    monkeypatch.setattr(
        sws,
        "_search_run",
        lambda run_id, **kw: seen.append(claude_spend.current_run()) or {"ran": True},
    )
    sws.search_run("run-invented-1")
    assert seen == ["run-invented-1"]
