# ruff: noqa: F811
"""The GENERAL review (a procedure or a contract: the paper against itself, the checklist, comments) on the LOCAL model.

Invented papers and models; a fake Ollama answers `LocalEngine`'s transport. The Claude lane is never given."""

from __future__ import annotations

import json

import pytest

from app import agent_general_parts, db
from app import agent_general_review as core
from app import agent_review_local as local_mod
from app import agent_review_request as request_mod
from app import agent_review_run as runner_mod
from tests import test_agent_general_review as g1
from tests.test_agent_general_review import (  # noqa: F401 - fixtures and invented papers
    ITEMS,
    PAGES,
    PAPER,
    PROJ,
    by_part,
    full_fake,
    good_p3,
    world,
)

A, B = "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_XL", "glm-4.7-flash"
SHOWS = {
    A: {"details": {"family": "qwen35moe"}},
    B: {"details": {"family": "glm4moe"}},
    "qwen3:8b": {"details": {"family": "qwen3"}},
}


class GLocal:
    """The local engine for the general review: the invented Claude's handlers, answered by model name; every request recorded."""

    def __init__(self, fake=None, cut_when=None, **kw):
        self.fake = fake or full_fake(**kw)
        self.cut_when = cut_when  # a text whose presence in a request makes the engine report a cut prompt
        self.log: list[tuple[str, str]] = []

    def __call__(self, path, body, *, timeout):
        system, user = body["messages"][0]["content"], body["messages"][-1]["content"]
        claude_body = {
            "system": [{"type": "text", "text": system}],
            "messages": [{"content": [{"text": user.split("\n\n")[-1]}]}],
        }
        fake_reply = self.fake(None, headers={}, body={**claude_body, "model": body["model"]}, timeout=1)  # fmt: skip
        text = fake_reply["content"][0]["text"]
        self.log.append((body["model"], system[:30]))
        tokens = (sum(len(m["content"]) for m in body["messages"]) // 3) + 1
        if self.cut_when and self.cut_when in user:
            tokens = body["options"][
                "num_ctx"
            ]  # the engine cut the prompt at the window
        return {
            "model": body["model"],
            "message": {"content": text},
            "done_reason": "stop",
            "prompt_eval_count": tokens,
        }


def build_local(
    world, post, *, b=B, window=None, windows_tokens=None, project=(PROJ,), name="rl"
):
    eng = local_mod.LocalEngine(A, b, post=post, unload=lambda m: None, show=SHOWS.get, window=window, output_cap=local_mod.GENERAL_OUTPUT_CAP)  # fmt: skip
    conn = db.connect()
    runner = runner_mod.Runner(paper=PAPER, items=[], pages=request_mod.DbPages(conn, PAPER), clauses=request_mod.ClauseCache({}),
                               model="x", retry_base=0.0, local=eng)  # fmt: skip
    docs = core.load_documents(conn, PAPER, list(project), [PAPER, *project])
    folder = world / name
    folder.mkdir(exist_ok=True)
    g = agent_general_parts.GeneralRun(paper=PAPER, docs=docs, kind="procedure", books={"not_held": []}, items=list(ITEMS),
                                       items_info={"kind": "procedure"}, project=list(project), run_dir=folder, runner=runner, local=eng)  # fmt: skip
    return g, eng


def shown(g):
    return [
        ln
        for ln in g.lines
        if ln["part"] == 3 and ln["verdict_class"] == core.CLASS_NOTE
    ]


def test_the_general_review_runs_on_the_local_model_in_two_stages_and_shows_verified_findings(
    world,
):
    post = GLocal()
    g, eng = build_local(world, post)
    g.run_all()
    models = [m for m, _s in post.log]
    first_b = models.index(B)
    assert set(models[:first_b]) == {A} and set(models[first_b:]) == {
        B
    }  # every first-reader call, then the second reader
    p3 = shown(g)
    assert {ln["subkind"] for ln in p3} >= {core.SUB_SELF}
    assert all(ln["quotes_verified_by_code"] for ln in p3)
    assert g.runner.run_usd == 0.0 and eng.stats()["local_requests_second"] > 0
    for ln in g.lines:
        assert ln["verdict_class"] not in (
            "Proven by code",
            "Pass",
            "Fail",
        )  # no verdict word in this mode


def test_a_finding_whose_quote_is_not_on_its_page_is_never_shown_and_is_said(world):
    g, _eng = build_local(world, GLocal())
    g.run_all()
    texts = " ".join(ln["text"] for ln in g.lines)
    assert (
        "bad quote" not in texts and "unverified" not in texts
    )  # the invented quotes of the fake never become findings
    said = [ln for ln in g.lines if ln["text"].startswith("AI could not show where")]
    assert said and all(ln["verdict_class"] == core.CLASS_NOT_CHECKED for ln in said)
    assert {ln["part"] for ln in said} >= {3, 5}


def test_without_a_second_reader_of_another_family_no_finding_is_shown(world):
    post = GLocal()
    g, _eng = build_local(
        world, post, b="qwen3:8b"
    )  # the same family as the first reader
    g.run_all()
    assert B not in [m for m, _s in post.log] and "qwen3:8b" not in [
        m for m, _s in post.log
    ]
    assert not shown(g)
    assert any("one AI reader alone is never enough" in ln["text"] for ln in g.lines)


def test_a_paper_in_windows_says_which_pages_were_and_were_not_read(world, monkeypatch):
    monkeypatch.setattr(local_mod, "GENERAL_WINDOW_TOKENS", 40)  # one page a window
    post = GLocal(
        cut_when="Appendix Z"
    )  # the engine cuts every request that holds page 3
    g, _eng = build_local(world, post)
    g.run_all()
    counts = g.part_counts[3]
    assert 3 in counts["pages_not_read"] and 1 in counts["pages_read"]
    line = next(
        ln
        for ln in g.lines
        if ln["part"] == 3 and ln["text"].startswith("pages not read by the AI")
    )
    assert "3" in line["text"] and "pages read: 1" in line["text"]
    assert shown(
        g
    )  # what the other windows found is still shown (its quotes are on their pages)


def test_hand_revert_target_the_quote_check_decides_what_is_shown(world, monkeypatch):
    g, _eng = build_local(world, GLocal())
    monkeypatch.setattr(
        agent_general_parts.GeneralRun, "check", lambda self, quote, page, doc: True
    )  # the check reverted
    g.run_all()
    assert any(
        "bad quote" in ln["text"] for ln in g.lines
    )  # without the check an invented quote becomes a finding: the test above fails


def test_a_request_the_engine_cut_is_never_an_answer(world):
    post = GLocal(cut_when="Section")  # every paper request is cut
    g, eng = build_local(world, post)
    g.run_all()
    assert not shown(g) and eng.stats()["local_answers_discarded"] > 0
    assert any(
        ln["text"].startswith("not reviewed") and local_mod.LOCAL_TOO_LONG in ln["text"]
        for ln in g.lines
    )


def test_part_five_comments_are_internal_notes_with_verified_quotes(world):
    g, _eng = build_local(world, GLocal())
    g.run_all()
    p5 = [
        ln
        for ln in g.lines
        if ln["part"] == 5 and ln["verdict_class"] == core.CLASS_NOTE
    ]
    assert p5 and all(
        ln["quote_a"]["text"] in PAGES[ln["quote_a"]["page"]] for ln in p5
    )


def test_the_page_list_words():
    assert (
        core.page_list([1, 2, 3, 5]) == "1-3, 5"
        and core.page_list([]) == ""
        and core.page_list([4]) == "4"
    )


@pytest.mark.parametrize("name", ["done"])
def test_the_local_general_review_keeps_the_claude_path_untouched(world, name):
    fake = full_fake()
    g, runner = g1.build(world, fake)  # the older path: no local engine
    assert (
        g.local is None
        and g.p2_batch == agent_general_parts.MAX_BATCH_P2
        and runner.local is None
    )
    assert json.dumps(g.windows()) == json.dumps(
        core.window_pages(g.pages, g.window_tokens, g.overlap_pages)
    )


def test_the_job_runs_the_general_review_on_the_local_model_and_never_touches_claude(
    world, monkeypatch
):
    from app import (
        access,
        agent_review_jobs,
        claude_spend,
        model_memory,
        model_transport,
    )
    from app.config import settings
    from tests import agent_review_support as s

    def boom(url, *, headers, body, timeout):
        raise AssertionError("a local run reached the Claude lane")

    post = GLocal()
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "agent_review_local_engine_enabled", True)
    monkeypatch.setattr(settings, "agent_review_local_model_a", A)
    monkeypatch.setattr(settings, "agent_review_local_model_b", B)
    monkeypatch.setattr(local_mod, "local_run", lambda _r: True)
    monkeypatch.setattr(local_mod, "_show", SHOWS.get)
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (boom, s.ENV))
    monkeypatch.setattr(model_transport, "post_json_retrying", post)
    monkeypatch.setattr(model_memory, "unload", lambda m: True)
    run_id, job_id = g1.start()
    assert agent_review_jobs.run(job_id, "w") == "done"
    rows = g1.lines_of(run_id)
    assert rows and any(r["verdict_class"] == core.CLASS_NOTE for r in rows.values())
    run = dict(
        db.connect()
        .execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    assert run["usd"] == 0.0 and claude_spend.entries() == []
    assert json.loads(run["counts_json"])["local_requests_first"] > 0


def test_the_plan_of_a_contract_or_procedure_runs_the_whole_ai_review_on_the_local_model_now():
    from tests.test_n1_local_ai_reviewer import E, open_facts

    assert local_mod.GENERAL_ON_LOCAL is True
    for kind in ("contract", "procedure"):
        plan = E.decide(
            "local",
            open_facts(
                kind=kind,
                is_contract=kind == "contract",
                local_ai=True,
                rules_for_kind=False,
            ),
        )
        ai = plan.part(E.AI_REVIEW)
        assert (
            ai.engine == E.ON_LOCAL
            and ai.why == E.AI_ON_LOCAL
            and plan.text_leaves is False
        )


def test_a_computer_held_by_another_heavy_job_stops_the_general_review_in_plain_words(
    world, monkeypatch
):
    import contextlib

    @contextlib.contextmanager
    def busy(*_a, **_k):
        raise local_mod.heavy_lock.HeavyJobBusy({"kind": "p1"}, 1800.0)
        yield

    from app import agent_general_job

    monkeypatch.setattr(local_mod.heavy_lock, "held", busy)
    post = GLocal()
    g, eng = build_local(world, post)
    agent_general_job._run_parts(g, g.runner, [PAPER], eng, "r", None)
    assert (
        g.stopped
        == "another heavy job held the computer for 30 minutes; start again later"
        and post.log == []
    )


def test_the_general_review_progress_label_counts_requests_and_names_the_reader(
    world, monkeypatch
):
    from app import worker_review

    beats, labels = [], []
    monkeypatch.setattr(worker_review, "beat_now", lambda: beats.append(1) or 0.0)
    g, eng = build_local(world, GLocal())
    eng.progress_cb = labels.append
    g.run_all()
    assert (
        beats
        and any("reader 1 of 2" in x and "request" in x for x in labels)
        and any("reader 2 of 2" in x for x in labels)
    )
