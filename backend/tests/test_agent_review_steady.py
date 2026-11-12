"""Point E (order 13, steady results): stored first-reader answers, stable batches, a roomy starting limit, the steadiness number.

Invented paper, rule book and model (the same world as the other AI reviewer tests)."""

# ruff: noqa: F811
from __future__ import annotations

import json
import random
import uuid

import pytest

from app import agent_review_items as items_mod
from app import agent_review_jobs, claude_spend, db
from app import agent_review_request as request_mod
from app import agent_review_reuse as reuse_mod
from app import agent_review_run as run_mod
from app import agent_review_steady as steady
from app import agent_review_two_reader_run as step_run
from app.api import agent_review_schemas as contract
from app.config import settings
from tests import agent_review_support as s
from tests.test_agent_review_cutoff_retry import use as cut_lane
from tests.test_agent_review_guards import run_review, run_row, w  # noqa: F401
from tests.test_agent_review_job import lines_of, run_job
from tests.test_agent_review_routes import client, finished_run  # noqa: F401
from tests.test_agent_two_reader import TwoLane, lane, on  # noqa: F401


@pytest.fixture
def reuse_on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_reuse_answers_enabled", True)


@pytest.fixture
def two_batches(monkeypatch):
    """Two batches of two items, so a run makes two lead calls."""
    real = request_mod.make_batches
    monkeypatch.setattr(run_mod, "make_batches", lambda items, _mb: real(items, 2))


def tables():
    return {
        r[0]
        for r in db.connect().execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def stored_rows():
    return [dict(r) for r in db.connect().execute("SELECT * FROM agent_review_answer")]


def counts_of(run_id):
    return json.loads(run_row(run_id)["counts_json"])


def trace_of(run_id):
    path = agent_review_jobs.run_dir(run_id) / "trace.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def start_run(*, fresh=False):
    run_id, job_id = agent_review_jobs.enqueue(
        s.PAPER,
        allowed_document_ids=frozenset({s.PAPER}),
        requested_by=None,
        fresh=fresh,
    )
    assert agent_review_jobs.claim_next("w-test") == job_id
    run_job(job_id)
    return run_id


def ledger_for(run_id):
    lines = settings.claude_spend_log.read_text(encoding="utf-8").splitlines()
    return [
        e
        for e in map(json.loads, lines)
        if e.get("run") == run_id and not e.get("reserved")
    ]


# ------------------------------------------------------------------------------------------- 1. reuse


def test_switch_off_every_call_is_made_as_before_and_nothing_is_stored(
    w, monkeypatch, two_batches
):
    seen = []
    real = run_mod.Runner.call

    def call(self, model, parts, max_tokens, **kw):
        seen.append(set(kw))
        return real(self, model, parts, max_tokens, **kw)

    monkeypatch.setattr(run_mod.Runner, "call", call)
    first = run_review()
    asked = len(w["fake"].lead_asked)
    second = run_review()
    assert (
        asked >= 2 and len(w["fake"].lead_asked) == 2 * asked
    )  # every batch asked again in the second run
    assert all("reuse" not in kw for kw in seen)  # the same arguments as the base code
    assert (
        "agent_review_answer" not in tables()
        and "agent_review_answer_run" not in tables()
    )
    for run_id in (first, second):
        assert "answers_reused" not in counts_of(run_id)
        assert all(
            "reused_answer" not in json.loads(v["line_json"])
            for v in lines_of(run_id).values()
        )
        assert all("reused_answer" not in json.dumps(t) for t in trace_of(run_id))


def test_switch_on_an_identical_second_run_asks_no_first_reader_and_books_nothing_for_it(
    w, reuse_on, two_batches
):
    first = run_review()
    asked, seconds = len(w["fake"].lead_asked), w["fake"].kinds.count("second")
    bought = len(
        [k for k in w["fake"].kinds if k != "lead"]
    )  # second opinions and context checks of run 1
    assert (
        asked >= 2 and len(stored_rows()) == asked
    )  # one stored answer per distinct lead request
    before = len(ledger_for(first))
    second = run_review()
    assert len(w["fake"].lead_asked) == asked  # no first-reader call at all
    assert (
        w["fake"].kinds.count("second") == 2 * seconds
    )  # the second opinions are asked again: code ran again
    assert (
        counts_of(second)["answers_reused"] == asked
        and counts_of(first)["answers_reused"] == 0
    )
    # nothing reached the spend ledger for a reused answer: only the second opinions of run 2 are booked
    assert (
        len(ledger_for(second)) == bought and before > bought
    )  # only those are booked in run 2: no first reader
    assert {
        k: (v["verdict_class"], v["word"]) for k, v in lines_of(second).items()
    } == {k: (v["verdict_class"], v["word"]) for k, v in lines_of(first).items()}
    note = json.loads(lines_of(second)["R-coat"]["line_json"])["reused_answer"]
    assert note["run_id"] == first and note["text"].startswith(
        f"reused answer from run {first} of "
    )
    batches = [t for t in trace_of(second) if t["type"] == "batch"]
    assert batches and all(f"run {first} of" in b["reused_answer"] for b in batches)
    assert not any("reused_answer" in json.dumps(t) for t in trace_of(first))


def test_a_run_that_reuses_every_answer_and_buys_no_other_call_spent_zero_not_unknown(
    w, reuse_on
):
    # every answer is a Query: no second opinion and no context check is bought, so the first reader's calls are the only spend
    quiet = {
        "verdict": "Query",
        "reason_code": "sheet_silent",
        "paper_quote": "",
        "paper_page": 1,
    }
    w["fake"].answers = {k: {**v, **quiet} for k, v in s.ANSWERS.items()}
    first = run_review()
    second = run_review()
    assert run_row(first)["usd"] > 0
    assert (
        run_row(second)["usd"] == 0.0
    )  # booked as 0 (not NULL: answers were reused), and nothing reached the ledger
    assert ledger_for(second) == [] and counts_of(second)["answers_reused"] > 0


def test_the_quote_check_runs_again_on_a_reused_answer(w, reuse_on):
    first = run_review()
    assert lines_of(first)["R-coat"]["word"] == "Pass"
    conn, asked = db.connect(), len(w["fake"].lead_asked)
    quote = s.ANSWERS["R-coat"]["paper_quote"]
    hit = [r for r in stored_rows() if quote in r["answer_json"]]
    assert len(hit) == 1
    with conn:
        conn.execute(
            "UPDATE agent_review_answer SET answer_json = ? WHERE request_key = ?",
            (
                hit[0]["answer_json"].replace(quote, "a quote the paper does not hold"),
                hit[0]["request_key"],
            ),
        )
    second = run_review()
    assert len(w["fake"].lead_asked) == asked  # it WAS reused
    line = lines_of(second)["R-coat"]
    assert (
        line["word"] != "Pass"
        and json.loads(line["line_json"])["quotes_checked"]["paper"] is False
    )


def test_a_cut_off_or_unreadable_or_halted_answer_is_never_stored(
    w, reuse_on, monkeypatch
):
    cut_lane(w, monkeypatch, {0}, ids=("R-coat", "R-frame", "R-mark", "R-colour"))
    run_review()
    answers = [json.loads(r["answer_json"]) for r in stored_rows()]
    assert answers and all(a["stop_reason"] == "end_turn" for a in answers)
    assert (
        len(answers) == len(w["fake"].lead_asked) - 1
    )  # the cut-off call is not among them
    db.connect().execute("DELETE FROM agent_review_answer")
    db.connect().commit()
    cut_lane(w, monkeypatch, set(), garbage={0, 1, 2, 3})
    run_review()
    assert stored_rows() == []  # unreadable
    cut_lane(w, monkeypatch, set())
    monkeypatch.setattr(
        run_mod, "app_cap", lambda: 0.0001
    )  # a cap that stops the run before its first call
    stopped = run_review()
    assert run_row(stopped)["stop_reason"] and stored_rows() == []  # halted


def test_a_run_halted_after_one_answer_stores_nothing(
    w, reuse_on, two_batches, monkeypatch
):
    real, seen = run_mod.AppStepGate.acquire, []

    def acquire(self, worst, stopped):
        seen.append(worst)
        if len(seen) > 1:  # the first call fits; the next is refused by the step cap
            raise request_mod.StepCapStop("invented cap")
        return real(self, worst, stopped)

    monkeypatch.setattr(run_mod.AppStepGate, "acquire", acquire)
    halted = run_review()
    row = run_row(halted)
    assert (
        row["partial"] == 1 and row["stop_reason"] and len(w["fake"].lead_asked) >= 1
    )  # one answer WAS got
    assert stored_rows() == []  # and is not kept: its run was halted


def test_the_store_refuses_a_cut_off_or_refused_reply_and_never_returns_one():
    store = reuse_mod.AnswerStore("r", "d", "v1")
    cut = {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "{"}]}
    refused = {"stop_reason": "refusal", "content": [{"type": "text", "text": "x"}]}
    ok = {"stop_reason": "end_turn", "content": [{"type": "text", "text": "{}"}]}
    for bad in (cut, refused, {"stop_reason": "end_turn", "content": []}, None, "text"):
        store.remember("k", "m", 10, bad)
    assert store._pending == {}
    store.remember("k", "m", 10, ok)
    assert list(store._pending) == ["k"]


def test_a_stored_row_that_is_cut_off_is_a_miss(w, reuse_on):
    run_review()
    conn = db.connect()
    with conn:
        conn.execute(
            "UPDATE agent_review_answer SET answer_json = REPLACE(answer_json, 'end_turn', 'max_tokens')"
        )
    asked = len(w["fake"].lead_asked)
    run_review()
    assert (
        len(w["fake"].lead_asked) == 2 * asked
    )  # no cut-off answer stood in for a reply


def test_a_closed_lane_or_an_unapproved_document_gets_nothing_from_the_store(
    w, reuse_on, monkeypatch
):
    from app import claude_approved

    run_review()
    asked = len(w["fake"].lead_asked)
    original = claude_approved.refusal
    monkeypatch.setattr(
        claude_approved, "refusal", lambda: ("document_not_approved", "invented")
    )
    refused = run_review()  # the store does not bypass the approved list: the real call is refused as it would be without it
    assert (
        len(w["fake"].lead_asked) == asked and counts_of(refused)["answers_reused"] == 0
    )
    assert run_row(refused)["partial"] == 1
    monkeypatch.setattr(claude_approved, "refusal", original)
    monkeypatch.setattr(
        agent_review_jobs,
        "lane",
        lambda: (w["fake"], {**s.ENV, "REASONING_PROVIDER": "ollama"}),
    )
    closed = run_review()
    assert (
        counts_of(closed)["answers_reused"] == 0 and run_row(closed)["partial"] == 1
    )  # a closed lane is "not run", not an old answer


def test_fresh_ignores_the_stored_answers_and_replaces_them(w, reuse_on, two_batches):
    first = run_review()
    asked = len(w["fake"].lead_asked)
    again = start_run(fresh=True)
    assert len(w["fake"].lead_asked) == 2 * asked  # asked again
    assert (
        counts_of(again)["answers_reused"] == 0
        and counts_of(again)["answers_fresh_run"] is True
    )
    assert {r["from_run_id"] for r in stored_rows()} == {again} and first != again
    assert (
        counts_of(run_review())["answers_reused"] == asked
    )  # and the next normal run uses the replacements


def test_fresh_with_the_switch_off_records_nothing(w):
    start_run(fresh=True)
    assert (
        "agent_review_answer_run" not in tables()
        and "agent_review_answer" not in tables()
    )


def test_a_changed_request_is_a_miss_and_the_key_names_every_part(
    w, reuse_on, monkeypatch
):
    run_review()
    asked = len(w["fake"].lead_asked)
    w["doc"], w["cache"] = s.item_doc(
        ("R-coat", "R-frame")
    )  # fewer rules: another request
    run_review()
    assert (
        len(w["fake"].lead_asked) == asked + 1
    )  # the new batch is asked; nothing else is
    parts = {
        "system": [{"type": "text", "text": "S"}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "M"}]}],
    }
    key = reuse_mod.request_key("m", parts, 100, "v1")
    assert key == reuse_mod.request_key("m", json.loads(json.dumps(parts)), 100, "v1")
    other = json.loads(json.dumps(parts))
    other["messages"][0]["content"][0]["text"] = "N"
    system = json.loads(json.dumps(parts))
    system["system"][0]["text"] = "T"
    keys = {
        key,
        reuse_mod.request_key("m2", parts, 100, "v1"),
        reuse_mod.request_key("m", parts, 101, "v1"),
        reuse_mod.request_key("m", parts, 100, "v2"),
        reuse_mod.request_key("m", other, 100, "v1"),
        reuse_mod.request_key("m", system, 100, "v1"),
    }
    assert len(keys) == 6


def test_the_second_reader_batch_is_reused_only_when_its_request_is_identical(
    w, on, reuse_on
):
    fake = lane(w)
    first = run_review()
    asked = len(fake.reader2)
    assert asked == 1
    second = run_review()
    assert (
        len(fake.reader2) == asked
    )  # the byte-identical second-reader request was not sent again
    assert counts_of(second)["answers_reused"] >= 2
    classes = lambda r: {k: v["verdict_class"] for k, v in lines_of(r).items()}  # noqa: E731
    assert classes(first) == classes(second)
    fake.second["R-mark"] = {
        **s.ANSWERS["R-mark"],
        "verdict": "Pass",
        "reason_code": "met",
    }  # same request: still reused
    run_review()
    assert len(fake.reader2) == asked


def test_a_stored_answer_the_run_cannot_read_is_dropped_and_asked_for_real(w, reuse_on):
    run_review()
    conn = db.connect()
    with conn:
        conn.execute(
            "UPDATE agent_review_answer SET answer_json = ?",
            (
                json.dumps(
                    {
                        "stop_reason": "end_turn",
                        "content": [{"type": "text", "text": "not json"}],
                    }
                ),
            ),
        )
    asked = len(w["fake"].lead_asked)
    second = run_review()
    assert (
        len(w["fake"].lead_asked) > asked
        and lines_of(second)["R-coat"]["word"] == "Pass"
    )


# ------------------------------------------------------------------------------------------- 2. stable batches


def fake_items(n, rng, pages=(1, 2, 3), refs=30):
    return [
        {
            "item_id": "R-" + str(uuid.UUID(int=rng.getrandbits(128))),
            "page_hint": list(pages),
            "clause_quote_ref": f"C-{rng.randrange(refs):03d}",
        }
        for _ in range(n)
    ]


def ids_of(batches):
    return {tuple(i["item_id"] for i in b) for b in batches}


@pytest.mark.parametrize("n", [30, 53, 86])
def test_adding_one_rule_changes_one_batch_and_every_other_batch_is_byte_identical(n):
    rng = random.Random(n)
    worst = 0
    for _ in range(60):
        base = fake_items(n, rng)
        extra = fake_items(1, rng)[0]
        before, after = (
            request_mod.make_batches(base, 8)[0],
            request_mod.make_batches([*base, extra], 8)[0],
        )
        assert sorted(i["item_id"] for b in after for i in b) == sorted(
            i["item_id"] for i in [*base, extra]
        )
        assert all(len(b) <= 8 for b in after)
        worst = max(worst, len(ids_of(before) - ids_of(after)))
        assert (
            len(ids_of(after) - ids_of(before)) <= 2
        )  # the new batch, or the two halves of a split one
    assert worst <= 1


def test_the_old_rule_shifted_every_later_batch():
    """The rule this replaced: cut every 8 items from the start of a group. It fails the property above."""
    rng = random.Random(1)
    base = fake_items(60, rng)
    extra = fake_items(1, rng)[0]

    def old(items):
        out = []
        for b in items_mod.batch_by_page(items):
            out.extend(b[i : i + 8] for i in range(0, len(b), 8))
        return out

    assert len(ids_of(old(base)) - ids_of(old([*base, extra]))) > 1


def test_batches_do_not_depend_on_the_order_the_items_arrive_in_and_keep_the_group_rule():
    rng = random.Random(9)
    items = (
        fake_items(50, rng)
        + fake_items(11, rng, pages=(4,))
        + fake_items(3, rng, pages=())
    )
    shuffled = items[:]
    rng.shuffle(shuffled)
    assert ids_of(request_mod.make_batches(items, 8)[0]) == ids_of(
        request_mod.make_batches(shuffled, 8)[0]
    )
    for b in request_mod.make_batches(items, 8)[0]:
        assert (
            len({tuple(sorted(i["page_hint"])) for i in b}) == 1
        )  # one page group per batch


def test_items_of_one_clause_stay_in_one_batch_when_they_fit():
    rng = random.Random(2)
    items = fake_items(40, rng, refs=60)
    for it in items[:3]:
        it["clause_quote_ref"] = "C-same"
    batches = request_mod.make_batches(items, 8)[0]
    assert (
        len([b for b in batches if any(i["clause_quote_ref"] == "C-same" for i in b)])
        == 1
    )


# ------------------------------------------------------------------------------------------- 3. starting limit


def test_the_starting_limit_clears_the_largest_complete_answer_measured_on_the_trial_papers():
    measured = {
        1: 945,
        2: 1554,
        3: 2167,
        4: 3292,
        6: 3629,
        7: 4255,
        8: 6041,
    }  # 12 Nov paid rounds, complete answers
    for n, used in measured.items():
        limit = min(
            request_mod.MAX_TOKENS_CAP,
            request_mod.TOKENS_BASE + request_mod.TOKENS_PER_ITEM * n,
        )
        assert limit >= 1.5 * used, (n, limit, used)
    assert (
        request_mod.MAX_TOKENS_CAP < request_mod.RETRY_MAX_TOKENS
    )  # a cut-off still has a larger retry


def test_the_first_call_of_a_run_carries_the_new_limit_and_its_worst_case_reservation_follows(
    w, monkeypatch
):
    lane = cut_lane(
        w, monkeypatch, set(), ids=("R-coat", "R-frame", "R-mark", "R-colour")
    )
    run_review()
    assert lane.limits[0] == request_mod.TOKENS_BASE + request_mod.TOKENS_PER_ITEM * 4
    cap = request_mod.app_cap()
    biggest = claude_spend.worst_case_usd(
        "claude-sonnet-5-5",
        150_000,
        min(
            request_mod.MAX_TOKENS_CAP,
            request_mod.TOKENS_BASE
            + request_mod.TOKENS_PER_ITEM * request_mod.MAX_BATCH,
        ),
    )
    assert (
        request_mod.CONCURRENCY * biggest < cap
    )  # three of the biggest batches in flight still fit under the step cap


# ------------------------------------------------------------------------------------------- 4. the steadiness number


def line(cls, label="", **extra):
    return {"verdict_class": cls, "verdict_label": label, **extra}


def test_the_comparison_uses_the_class_before_the_optional_steps_and_flags_decisions():
    before = {
        "a": line("Proven by code", verdict="Pass"),
        "b": line("AI opinion, engineer to confirm", "AI thinks: not met"),
        "c": line("Query for the engineer"),
        "d": line("Query for the engineer"),
        "e": line("Query for the engineer"),
        "f": line("Query for the engineer", error="boom"),
        "g": line("Query for the engineer"),
    }
    after = {
        "a": line("Query for the engineer"),  # a proven Pass disappeared
        "b": line("AI opinion, engineer to confirm", "AI thinks: not met"),  # same
        "c": line("Not applicable"),  # a change that is not a decision
        "d": line(
            "AI verdict, two readers agree",
            "AI verdict: met",
            two_reader={
                "base": {
                    "verdict_class": "Query for the engineer",
                    "verdict_label": "Query",
                }
            },
        ),
        "e": line(
            "Query for the engineer", reread={"outcome": "recovered"}
        ),  # left out: a switch changed it
        "f": line("Proven by code", verdict="Fail"),  # a failed call before: left out
        "g": line("AI opinion, engineer to confirm", "AI thinks: met"),
    }
    got = steady.compare(before, after)
    assert (got["lines_compared"], got["changed"], got["decisions"]) == (5, 3, 2)
    assert [i["item_id"] for i in got["items"]] == ["a", "c", "g"]


def test_a_changed_answer_between_two_runs_is_counted_and_listed_in_the_trace(w):
    first = run_review()
    assert "changed_since_previous" not in counts_of(first)  # no earlier run
    w["fake"].answers["R-coat"] = {
        **s.ANSWERS["R-coat"],
        "verdict": "Query",
        "reason_code": "sheet_silent",
        "paper_quote": "",
    }
    second = run_review()
    got = counts_of(second)["changed_since_previous"]
    assert (
        got["previous_run_id"] == first
        and got["changed"] >= 1
        and got["decisions"] >= 1
    )
    record = next(t for t in trace_of(second) if t["type"] == "changed_since_previous")
    assert "R-coat" in {i["item_id"] for i in record["items"]}
    third = run_review()  # nothing changed since the second run
    assert counts_of(third)["changed_since_previous"]["changed"] == 0


def test_the_summary_contract_carries_both_numbers_and_an_old_run_shows_nothing():
    got = contract.AgentRunSummary(
        paper_kind="datasheet",
        paper_kind_source="x",
        answers_reused=3,
        changed_since_previous={
            "previous_run_id": "r",
            "lines_compared": 5,
            "changed": 2,
            "decisions": 1,
        },
    )
    assert got.answers_reused == 3 and got.changed_since_previous.decisions == 1
    old = contract.AgentRunSummary(paper_kind="datasheet", paper_kind_source="x")
    assert old.answers_reused is None and old.changed_since_previous is None


def test_the_start_route_takes_fresh_and_the_summary_route_shows_both_numbers(
    client, reuse_on
):
    first = finished_run(client)
    body = client.get(f"/api/reviews/runs/{first}/agent/summary").json()
    assert (
        body["answers_reused"] == 0 and body["changed_since_previous"] is None
    )  # no earlier run to compare with
    r = client.post(
        "/api/reviews/agent-run", json={"submittal_document_id": s.PAPER, "fresh": True}
    )
    assert r.status_code == 200, r.text
    second = r.json()["run_id"] if "run_id" in r.json() else r.json()["review_run_id"]
    assert reuse_mod.is_fresh(db.connect(), second) and not reuse_mod.is_fresh(
        db.connect(), first
    )
    assert (
        agent_review_jobs.run(agent_review_jobs.claim_next("w-test"), "w-test")
        == "done"
    )
    body = client.get(f"/api/reviews/runs/{second}/agent/summary").json()
    assert body["answers_reused"] == 0  # a fresh run asked again
    assert (
        body["changed_since_previous"]["previous_run_id"] == first
        and body["changed_since_previous"]["changed"] == 0
    )
    assert (
        client.post(
            "/api/reviews/agent-run",
            json={"submittal_document_id": s.PAPER, "fresh": "maybe"},
        ).status_code
        == 422
    )


def test_the_evidence_sheet_marks_a_reused_answer_and_the_contractor_copy_never_does(
    w, reuse_on
):
    import openpyxl

    first, second = run_review(), run_review()

    def cells(run_id, name):
        wb = openpyxl.load_workbook(agent_review_jobs.run_dir(run_id) / name)
        return [
            str(c.value)
            for ws in wb
            for row in ws.iter_rows()
            for c in row
            if c.value is not None
        ]

    assert not any("reused answer" in c for c in cells(first, "crs-internal.xlsx"))
    marked = [
        c for c in cells(second, "crs-internal.xlsx") if "reused answer from run" in c
    ]
    assert marked and all(f"run {first} of" in c for c in marked)
    assert not any("reused" in c.lower() for c in cells(second, "crs-contractor.xlsx"))


def test_an_answer_with_a_quote_that_fails_the_check_is_never_frozen(w, reuse_on):
    """N1 (review R38): a stored answer whose quote the code could not verify is dropped, so the next run asks again."""
    run_review()
    quote = s.ANSWERS["R-coat"]["paper_quote"]
    hit = [r for r in stored_rows() if quote in r["answer_json"]]
    assert len(hit) == 1
    asked = len(w["fake"].lead_asked)
    conn = db.connect()
    with conn:
        conn.execute(
            "UPDATE agent_review_answer SET answer_json = ? WHERE request_key = ?",
            (
                hit[0]["answer_json"].replace(quote, "a quote the paper does not hold"),
                hit[0]["request_key"],
            ),
        )
    second = (
        run_review()
    )  # the tampered answer is used once, the check fails, and it is dropped
    assert (
        len(w["fake"].lead_asked) == asked
        and lines_of(second)["R-coat"]["word"] != "Pass"
    )
    assert hit[0]["request_key"] not in {r["request_key"] for r in stored_rows()}
    third = run_review()  # so this run asks again, gets the good answer, and a fully verified answer is kept
    assert (
        len(w["fake"].lead_asked) == asked + 1
        and lines_of(third)["R-coat"]["word"] == "Pass"
    )
    assert hit[0]["request_key"] in {r["request_key"] for r in stored_rows()}
    assert (
        run_review() and len(w["fake"].lead_asked) == asked + 1
    )  # the verified one is reused


def test_a_new_answer_whose_quote_fails_is_not_stored_at_all(w, reuse_on):
    w["fake"].answers["R-coat"] = {
        **s.ANSWERS["R-coat"],
        "paper_quote": "a quote the paper does not hold",
    }
    first = run_review()
    assert lines_of(first)["R-coat"]["word"] != "Pass"
    quote_batches = [
        r
        for r in stored_rows()
        if "a quote the paper does not hold" in r["answer_json"]
    ]
    assert quote_batches == []
    asked = len(w["fake"].lead_asked)
    run_review()
    assert len(w["fake"].lead_asked) > asked  # asked again, not frozen


def test_an_absence_answer_with_no_quote_is_not_a_failed_quote(w, reuse_on):
    w["fake"].answers["R-mark"] = {
        **s.ANSWERS["R-mark"],
        "reason_code": "absent",
        "paper_quote": "",
        "pages_searched": [1],
    }
    run_review()
    asked = len(w["fake"].lead_asked)
    run_review()
    assert (
        len(w["fake"].lead_asked) == asked
    )  # nothing was claimed, so nothing failed: it is reused


def test_a_second_reader_answer_with_a_failed_quote_is_not_frozen_either(
    w, on, reuse_on
):
    fake = lane(
        w,
        second={
            **s.ANSWERS,
            "R-coat": {
                **s.ANSWERS["R-coat"],
                "paper_quote": "a quote the paper does not hold",
            },
        },
    )
    run_review()
    asked = len(fake.reader2)
    run_review()
    assert len(fake.reader2) == asked + 1  # asked again
    fake.second = dict(s.ANSWERS)
    run_review()
    run_review()
    assert len(fake.reader2) == asked + 2  # once verified, it is kept and reused


def test_reuse_freezes_the_first_answer_until_a_fresh_run_the_stated_trade_off(
    w, reuse_on
):
    """What reuse hides (the PR text): the first run's answer, right or wrong, is copied until a fresh run replaces it."""
    first = run_review()
    assert lines_of(first)["R-coat"]["word"] == "Pass"
    asked = len(w["fake"].lead_asked)
    w["fake"].answers["R-coat"] = {
        **s.ANSWERS["R-coat"],
        "verdict": "Query",
        "reason_code": "sheet_silent",
        "paper_quote": "",
    }
    second = (
        run_review()
    )  # the reader would now say something else, but the stored answer stands
    assert (
        len(w["fake"].lead_asked) == asked
        and lines_of(second)["R-coat"]["word"] == "Pass"
    )
    assert (
        counts_of(second).get("changed_since_previous", {}).get("changed") == 0
    )  # and the steadiness number is 0
    fresh = start_run(
        fresh=True
    )  # an engineer asks for a fresh run: the new answer shows, and replaces the stored one
    assert lines_of(fresh)["R-coat"]["word"] != "Pass"
    assert counts_of(fresh)["changed_since_previous"]["changed"] >= 1
    assert lines_of(run_review())["R-coat"]["word"] != "Pass"


def test_a_reused_lead_answer_charges_zero_and_a_failed_second_reader_call_still_charges_the_lines(
    w, reuse_on, monkeypatch
):
    """Main's `call_for_batch` / `_charge_batch` with reuse and with stable batches: the run's charge lands on the batch's lines."""
    from tests.test_agent_two_reader_charge import Breaker, _totals

    def batch_call(body):  # the reader's batch request, not the per-item second opinion
        return request_mod.SYSTEM[:60] in json.dumps(body["system"])

    monkeypatch.setattr(step_run.TwoReaderMixin, "strict_charge", True)
    w["fake"] = TwoLane()
    run_review()  # the first reader's answers are stored (the second reader is off)
    monkeypatch.setattr(settings, "agent_review_two_reader_verdict_enabled", True)
    w["fake"] = Breaker(w["fake"], "transport", batch_call)
    asked = len(w["fake"].lead_asked)
    run_id = run_review()
    assert (
        w["fake"].hit == 1 and len(w["fake"].lead_asked) == asked
    )  # the lead was reused, the second reader failed
    run_usd, line_usd = _totals(run_id)
    assert run_usd > 0 and line_usd == pytest.approx(
        run_usd, abs=1e-9
    )  # the failed call's charge is on the lines
    assert not any(
        "reused_answer" in json.dumps(t) and t.get("usd")
        for t in trace_of(run_id)
        if t["type"] == "batch"
    )
