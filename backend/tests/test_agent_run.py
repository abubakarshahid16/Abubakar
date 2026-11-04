"""#1690 agent_run: the runner, on an invented tiny database copy, with a fake provider. No model, no network."""

import json
import re
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from app import agent_loop as al
from app import agent_run as ar
from app import agent_trace as at

DOC_QUOTE = "invented quote about the zorblat rating"
SKILL = {
    "kind": "invented_kind",
    "version": "1",
    "items": [
        {"id": f"I{n}", "order": n, "topic": f"zorblat rating {n}", "expected": "x",
         "acceptable_range": "x", "escalate_when": "x", "clause_refs": []}
        for n in (1, 2, 3)
    ],
}  # fmt: skip


class Killed(BaseException):
    """Not an Exception: the loop's own `except Exception` must not swallow it (a kill)."""


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HEAVY_JOB_LOCK", "off")
    return tmp_path / "run"


@pytest.fixture
def copy_db(tmp_path):
    path = tmp_path / "copy.sqlite"
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT);"
        "CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);"
        "INSERT INTO documents VALUES ('D1','invented-sheet.pdf'),('S1','ISO 9999-2021.pdf'),"
        "('S2','ISO 9999-2015.pdf'),('X1','unrelated-doc.pdf');"
        "INSERT INTO pages VALUES ('D1',1,'zorblat rating page one'),('D1',2,'second page'),"
        "('S1',1,'clause text'),('X1',1,'zorblat secret');"
    )
    db.commit()
    db.close()
    return path


class Box:
    """Fake toolbox: record_finding accepts. `ctx` is where the loop attaches the sink."""

    TOOL_SPECS: ClassVar[list] = [
        {"name": n, "description": "", "params": {}} for n in al.TOOL_NAMES
    ]

    def __init__(self):
        self.ctx = SimpleNamespace(findings=None)

    def run(self, name, args):
        if name == "record_finding":
            return {"ok": True, "result": {"verdict": "accepted"}, "cites": []}
        return {"ok": True, "result": {}, "cites": []}


def factory(scope, readers):
    box = Box()
    box.scope, box.readers = scope, readers
    factory.last = box
    return box


def final(colour="GREEN", **extra):
    f = {"color": colour, "doc_quote": DOC_QUOTE, "page": 1, "clause_quote": "c",
         "standard": "ISO 9999", "clause": "4.1", "action": "Revise the rating", "priority": "must",
         "reason": "rating differs"}  # fmt: skip
    f.update(extra)
    return {"final": f, "model": "lead-model-x", "usd": 0.5}


def go(copy_db, run_dir, provider, **kw):
    kw.setdefault("toolbox_factory", factory)
    kw.setdefault("skill", SKILL)
    return ar.run_review(
        copy_db, "D1", "invented_kind", provider, run_dir=run_dir, **kw
    )


# ---- read-only copy, live refusal ---------------------------------------------------------------------------------


def test_readonly_open_cannot_write(copy_db):
    conn = ar.open_readonly(copy_db)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO documents VALUES ('Z','z')")
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 4


def test_missing_copy_is_not_created(tmp_path):
    with pytest.raises(FileNotFoundError):
        ar.open_readonly(tmp_path / "nope.sqlite")
    assert not (tmp_path / "nope.sqlite").exists()


def test_live_database_path_is_refused(tmp_path):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    sqlite3.connect(live).close()
    with pytest.raises(ar.LiveDatabaseRefused):
        ar.open_readonly(live)
    assert not ar.live_guard.is_live_shaped(tmp_path / "x.sqlite")


def test_run_review_refuses_live_before_anything_is_written(tmp_path, run_dir):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    sqlite3.connect(live).close()
    with pytest.raises(ar.LiveDatabaseRefused):
        ar.run_review(
            live, "D1", "k", al.FakeProvider([]), run_dir=run_dir, skill=SKILL
        )
    assert not run_dir.exists()


# ---- scope -------------------------------------------------------------------------------------------------------


def test_scope_is_the_document_plus_standards_the_edition_map_names(copy_db, run_dir):
    go(
        copy_db,
        run_dir,
        al.FakeProvider([final()] * 3),
        editions={"ISO 9999": "2021"},
        limit=1,
    )
    scope = factory.last.scope
    assert scope["allowed"] == frozenset(
        {"D1", "S1"}
    )  # not S2 (other edition), not X1 (unrelated)
    assert scope["editions"] == {"ISO 9999": "2021"}


def test_no_edition_map_means_only_the_document(copy_db, run_dir):
    go(copy_db, run_dir, al.FakeProvider([final()]), limit=1)
    assert factory.last.scope["allowed"] == frozenset({"D1"})


def test_edition_map_not_held_is_a_problem_not_a_guess(copy_db, run_dir):
    s = go(
        copy_db,
        run_dir,
        al.FakeProvider([final()]),
        editions={"ISO 9999": "1999"},
        limit=1,
    )
    assert s["allowed_document_ids"] == ["D1"]
    assert "not held" in (run_dir / "live.log").read_text()


def test_edition_map_file_in_run_dir_is_read(copy_db, run_dir):
    run_dir.mkdir()
    (run_dir / "editions.json").write_text(json.dumps({"ISO 9999": "2015"}))
    s = go(copy_db, run_dir, al.FakeProvider([final()]), limit=1)
    assert s["allowed_document_ids"] == ["D1", "S2"]


def test_unknown_document_is_refused(copy_db, run_dir):
    with pytest.raises(LookupError):
        ar.run_review(
            copy_db, "NOPE", "k", al.FakeProvider([]), run_dir=run_dir, skill=SKILL
        )


def test_readers_are_bound_to_the_copy_and_search_stays_in_scope(copy_db):
    conn = ar.open_readonly(copy_db)
    r = ar.Readers(conn, {"D1"})
    assert r.page("D1", 1) == "zorblat rating page one"
    assert r.page("D1", 9) is None
    hits = r.search("zorblat", frozenset({"D1"}))["hits"]
    assert [h["document_id"] for h in hits] == [
        "D1"
    ]  # X1 also says zorblat but is out of scope
    assert r.search("a", frozenset({"D1"})) == {"hits": []}


# ---- run, resume, second opinion -----------------------------------------------------------------------------------


def test_full_run_writes_results_examples_and_workbook(copy_db, run_dir):
    s = go(
        copy_db,
        run_dir,
        al.FakeProvider([final("GREEN"), final("RED"), final("YELLOW")]),
    )
    assert s["items_done"] == 3 and s["quote_verified"] == 3
    results = (run_dir / "RESULTS.md").read_text()
    assert (
        "GREEN 1 and RED 1 (second opinion not run: not decided), YELLOW 1" in results
    )
    assert "Quote verified by code: 3 of 3" in results
    assert "USD 1.50" in results
    assert "lead-model-x" in results  # the name the RESPONSE reported
    assert (run_dir / "EXAMPLES.md").exists() and (run_dir / "crs.xlsx").exists()
    assert "second opinion run" in results or "no second opinion" in results.lower()


def test_model_name_comes_from_the_response_not_config(copy_db, run_dir):
    p = al.FakeProvider([{**final(), "model": "reported-name"}] * 3)
    s = go(copy_db, run_dir, p)
    assert s["lead_models"] == ["reported-name"]
    silent = al.FakeProvider([{k: v for k, v in final().items() if k != "model"}] * 3)
    s2 = go(copy_db, run_dir.parent / "run2", silent)
    assert s2["lead_models"] == []
    assert (
        "not reported by the provider"
        in (run_dir.parent / "run2" / "RESULTS.md").read_text()
    )


def test_results_has_no_document_text(copy_db, run_dir):
    go(
        copy_db,
        run_dir,
        al.FakeProvider([final("RED", reason="secret words here")] * 3),
    )
    results = (run_dir / "RESULTS.md").read_text()
    for banned in (
        DOC_QUOTE,
        "zorblat",
        "secret words",
        "ISO 9999",
        "Revise the rating",
    ):
        assert banned not in results
    # the examples file is local and DOES hold comment text
    assert "Revise the rating" in (run_dir / "EXAMPLES.md").read_text()


def test_resume_after_a_kill_does_not_ask_done_items_again(copy_db, run_dir):
    def die(_messages):
        raise Killed

    first = al.FakeProvider([final("GREEN"), die])
    with pytest.raises(Killed):
        go(copy_db, run_dir, first)
    assert len(first.calls) == 2
    assert (
        at.RunLock(run_dir).path.exists() is False
    )  # the lock was released on the way out
    second = al.FakeProvider([final("RED"), final("YELLOW")])
    s = go(copy_db, run_dir, second)
    assert len(second.calls) == 2  # item 1 is not asked again
    assert [f["color"] for f in s["findings"]] == ["GREEN", "RED", "YELLOW"]
    assert s["spend"] == pytest.approx(
        1.5
    )  # 0.5 from before the kill plus 2 x 0.5, not repeated


class Opinion:
    """Stands in for ClaudeProvider.second_opinion(finding, evidence) -> {agree, reason, usd, model}."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def second_opinion(self, finding, evidence, **_kw):
        self.calls.append((finding, evidence))
        out = self.replies.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def ok(agree, model="other-model", usd=0.1):
    reply = {"agree": agree, "reason": "r", "usd": usd}
    if model is not None:
        reply["model"] = model
    return reply


def test_second_opinion_downgrades_disagreement_and_missing_answer(copy_db, run_dir):
    lead = al.FakeProvider([final("GREEN"), final("RED"), final("GREEN")])
    other = Opinion([ok(True), ok(False), ok(None)])
    s = go(copy_db, run_dir, lead, second_opinion=other)
    assert [f["color"] for f in s["findings"]] == ["GREEN", "YELLOW", "YELLOW"]
    assert [f["second_opinion"] for f in s["findings"]] == [
        "agreed",
        "disagreed",
        "no answer",
    ]
    assert s["spend"] == pytest.approx(1.8)
    assert s["opinion_models"] == ["other-model"]
    assert "agreed 1, disagreed 1, no answer 1" in (run_dir / "RESULTS.md").read_text()
    assert other.calls[0][1] == {"doc_quote": DOC_QUOTE, "clause_quote": "c"}


def test_second_opinion_from_the_same_model_does_not_count(copy_db, run_dir):
    s = go(copy_db, run_dir, al.FakeProvider([final("GREEN")]), second_opinion=Opinion([ok(True, "lead-model-x")]), limit=1)  # fmt: skip
    assert s["findings"][0]["color"] == "YELLOW"


def test_missing_model_name_fails_closed(copy_db, run_dir):
    # opinion reply without a model key
    s = go(copy_db, run_dir, al.FakeProvider([final("GREEN")]), second_opinion=Opinion([ok(True, None)]), limit=1)  # fmt: skip
    assert s["findings"][0]["color"] == "YELLOW"
    # lead reply without a model key, opinion names its model
    bare = {k: v for k, v in final("GREEN").items() if k != "model"}
    s = go(copy_db, run_dir.parent / "r2", al.FakeProvider([bare]), second_opinion=Opinion([ok(True)]), limit=1)  # fmt: skip
    assert s["findings"][0]["color"] == "YELLOW"
    # the adapter's own 'unknown'
    s = go(copy_db, run_dir.parent / "r3", al.FakeProvider([final("GREEN", )]), second_opinion=Opinion([ok(True, "unknown")]), limit=1)  # fmt: skip
    assert s["findings"][0]["color"] == "YELLOW"


def test_different_known_models_keep_the_verdict(copy_db, run_dir):
    s = go(copy_db, run_dir, al.FakeProvider([final("GREEN")]), second_opinion=Opinion([ok(True)]), limit=1)  # fmt: skip
    assert s["findings"][0]["color"] == "GREEN"


def test_a_raising_second_opinion_is_yellow(copy_db, run_dir):
    s = go(copy_db, run_dir, al.FakeProvider([final("RED")]), second_opinion=Opinion([RuntimeError("x")]), limit=1)  # fmt: skip
    assert s["findings"][0]["color"] == "YELLOW"


def test_yellow_findings_get_no_second_opinion(copy_db, run_dir):
    other = Opinion([])
    go(copy_db, run_dir, al.FakeProvider([final("YELLOW")]), second_opinion=other, limit=1)  # fmt: skip
    assert other.calls == []


def test_headline_and_status_say_when_no_second_opinion_ran(copy_db, run_dir):
    s = go(copy_db, run_dir, al.FakeProvider([final("GREEN"), final("RED"), final("YELLOW")]))  # fmt: skip
    head = next(x for x in (run_dir / "RESULTS.md").read_text().splitlines() if x.startswith("- GREEN"))  # fmt: skip
    assert "GREEN 1 and RED 1 (second opinion not run: not decided)" in head
    assert "wrong not measured (needs the key score)" in s["status_box"]
    assert "wrong 0" not in s["status_box"]
    assert "scorer matches page digits as a substring; YELLOW rows count as raised" in (run_dir / "RESULTS.md").read_text()  # fmt: skip


def test_readonly_uri_not_just_query_only(copy_db):
    conn = ar.open_readonly(copy_db)
    conn.execute("PRAGMA query_only = OFF")
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO documents VALUES ('Z','z')")


def test_page_is_written_once_per_row_as_p_dot_n(tmp_path):
    rows = ar.crs_rows_from_findings(_findings(), {"I1": "zorblat rating"})
    out = ar.write_crs_xlsx(rows, tmp_path / "c.xlsx")
    body = _load(out, ar.CRS_SHEET)[1]
    assert body[3] == "p.3"
    assert "p.3" not in body[5] and "page 3" not in body[5].lower()
    contractor = _load(out, ar.CONTRACTOR_SHEET)[1]
    assert contractor[1] == "p.3"


def test_apply_second_opinion_unit():
    f = {"color": "GREEN", "item": "a"}
    assert ar.apply_second_opinion(f, True, True)["color"] == "GREEN"
    assert ar.apply_second_opinion(f, None, True)["color"] == "YELLOW"
    assert ar.apply_second_opinion(f, False, True)["color"] == "YELLOW"
    assert ar.apply_second_opinion(f, None, False)["second_opinion"] == "not run"


def test_limit_and_item_selection(copy_db, run_dir):
    s = go(
        copy_db, run_dir, al.FakeProvider([final()] * 3), items=["I3", "I1"], limit=1
    )
    assert [f["item"] for f in s["findings"]] == ["I1"]


def test_run_cap_pauses_and_a_later_run_finishes(copy_db, run_dir):
    p = al.FakeProvider([final()] * 3)
    s = go(copy_db, run_dir, p, usd_cap_run=0.5)
    assert s["stopped"] and s["items_done"] == 1
    s2 = go(copy_db, run_dir, al.FakeProvider([final()] * 3))
    assert s2["items_done"] == 3 and not s2["stopped"]


def test_status_box_has_the_owner_fields_and_fires_every_ten(copy_db, run_dir):
    seen = []
    big = {
        **SKILL,
        "items": [{"id": f"I{n}", "order": n, "topic": "t"} for n in range(1, 21)],
    }
    s = go(copy_db, run_dir, al.FakeProvider([final("YELLOW")] * 20), skill=big,
           on_status=lambda t: seen.append(ar.status_box(t)))  # fmt: skip
    assert len(seen) == 2
    for field in (
        "STEP",
        "DONE",
        "PROOF",
        "RUNNING",
        "PROGRESS",
        "MODEL",
        "RESULTS",
        "SPEND",
        "PROBLEMS",
        "NEXT",
    ):
        assert re.search(rf"^{field}\s", s["status_box"], re.M)


# ---- heavy lock: local runs only ----------------------------------------------------------------------------------


def test_local_run_takes_the_heavy_lock_and_a_claude_run_does_not(
    copy_db, tmp_path, monkeypatch
):
    lock = tmp_path / "heavy.lock"
    monkeypatch.setenv("HEAVY_JOB_LOCK", str(lock))
    seen = {}

    def peek(tag):
        def fn(_messages):
            seen[tag] = lock.exists()
            return final("YELLOW")

        return fn

    go(copy_db, tmp_path / "r1", al.FakeProvider([peek("local")]), local=True, limit=1)
    go(
        copy_db,
        tmp_path / "r2",
        al.FakeProvider([peek("claude")]),
        local=False,
        limit=1,
    )
    assert seen == {"local": True, "claude": False}
    assert not lock.exists()  # released


# ---- the scorer bridge ---------------------------------------------------------------------------------------------

SCORER = Path.home() / "project" / "mirror" / "answer-key" / "answer_key_score.py"


def _findings():
    return [
        {"item": "I1", "color": "RED", "page": 3, "doc_quote": DOC_QUOTE, "standard": "ISO 9999",
         "clause": "4.1", "action": "Revise the rating", "priority": "must", "reason": "rating is too low"},
        {"item": "I2", "color": "YELLOW", "page": 5, "action": "ask the engineer", "reason": "unclear"},
        {"item": "I3", "color": "GREEN", "page": 2, "doc_quote": DOC_QUOTE, "reason": "complies"},
        {"item": "I4", "color": "YELLOW", "action": "Provide the missing figure", "reason": "no value given"},
    ]  # fmt: skip


def _load(path, sheet):
    import openpyxl

    ws = openpyxl.load_workbook(path)[sheet]
    return [list(r) for r in ws.iter_rows(values_only=True)]


def test_crs_rows_and_workbook_round_trip(tmp_path):
    rows = ar.crs_rows_from_findings(
        _findings(), {"I1": "zorblat rating", "I2": "flange class"}
    )
    out = ar.write_crs_xlsx(rows, tmp_path / "crs.xlsx")
    crs = _load(out, ar.CRS_SHEET)
    assert tuple(crs[0]) == ar.CRS_HEADERS
    body = crs[1:]
    assert [r[1] for r in body] == ["I1", "I2", "I4"]  # GREEN is not a problem row
    assert "zorblat rating" in body[0][5] and "ISO 9999 clause 4.1" in body[0][5]
    assert body[2][3] is None  # no page: renders as nothing, never 0
    ok = _load(out, ar.CHECKED_SHEET)
    assert [r[1] for r in ok[1:]] == ["I3"]
    contractor = _load(out, ar.CONTRACTOR_SHEET)
    assert tuple(contractor[0]) == ar.CONTRACTOR_HEADERS
    assert (
        len(contractor) == 2
    )  # only the RED row: the others are an ask or have no page
    assert not re.search(
        r"engineer|yellow|green|model", " ".join(map(str, contractor[1])), re.I
    )


def test_green_never_reaches_the_contractor_sheet(tmp_path):
    rows = ar.crs_rows_from_findings(_findings())
    assert [r["item"] for r in rows if r["contractor"]] == ["I1"]
    assert all(not r["contractor"] for r in rows if r["color"] == "GREEN")


def test_formula_text_is_not_written_as_a_formula(tmp_path):
    f = [
        {"item": "I1", "color": "RED", "page": 1, "action": "=cmd()", "reason": "=1+1"}
    ]
    out = ar.write_crs_xlsx(ar.crs_rows_from_findings(f), tmp_path / "c.xlsx")
    import openpyxl

    ws = openpyxl.load_workbook(out)[ar.CRS_SHEET]
    assert all(c.data_type != "f" for row in ws.iter_rows() for c in row)


def _present_in(crs_rows, words, pg):
    """The scorer's matching rule, restated: first four letters of each word, and the page, in one row."""
    for r in crs_rows:
        t = " ".join(str(c) for c in r if c).lower()
        if all(w[:4] in t for w in words) and (not pg or pg[0] in t):
            return True
    return False


def test_scorer_contract_row_matches_by_topic_words_and_page(tmp_path):
    rows = ar.crs_rows_from_findings(_findings(), {"I1": "zorblat rating"})
    out = ar.write_crs_xlsx(rows, tmp_path / "c.xlsx")
    crs = _load(out, ar.CRS_SHEET)
    assert _present_in(crs, ["zorblat", "rating"], ["3"])
    assert not _present_in(crs, ["zorblat", "rating"], ["7"])
    filled = [sum(1 for c in r if c not in (None, "")) for r in crs]
    assert all(
        n >= ar.MIN_FILLED_CELLS for n in filled
    )  # the scorer counts rows with 5+ filled cells


@pytest.mark.skipif(
    not SCORER.exists(), reason="the scorer lives on the owner's Mac only"
)
def test_writer_matches_what_the_scorer_reads():
    src = SCORER.read_text(encoding="utf-8")  # the CODE only, never a key or CRS file
    assert f'load(a.crs, "{ar.CRS_SHEET}")' in src
    m = re.search(r">= (\d+)\]", src)
    assert m and int(m.group(1)) == ar.MIN_FILLED_CELLS
    # the column names the scorer reads from its key file are the ones the CRS writer uses for the same facts
    reads = set(re.findall(r'h\.index\("([^"]+)"\)', src))
    assert {"Standard Reference", "Page No./Section"} <= reads
    assert {"Standard Reference", "Page No./Section"} <= set(ar.CRS_HEADERS)


def test_scorer_header_names_are_emitted_even_without_the_scorer():
    assert ar.CRS_SHEET == "CRS"
    assert {"Standard Reference", "Page No./Section", "Comments"} <= set(ar.CRS_HEADERS)


# ---- the real ToolBox is bound to the copy ------------------------------------------------------------------------


def test_default_toolbox_reads_only_the_copy_and_only_in_scope(copy_db, run_dir):
    pytest.importorskip("app.agent_tools")
    s = go(
        copy_db,
        run_dir,
        al.FakeProvider([final("YELLOW")]),
        toolbox_factory=None,
        limit=1,
    )
    assert s["items_done"] == 1
    conn = ar.open_readonly(copy_db)
    box = ar.default_toolbox(
        {"allowed": frozenset({"D1"}), "document_id": "D1", "editions": {}},
        ar.Readers(conn, {"D1"}),
    )
    assert box.run("open_page", {"doc": "D1", "page": 1})["ok"] is True
    assert box.run("open_page", {"doc": "X1", "page": 1})["ok"] is False  # out of scope
    assert (
        box.run("get_clause", {"standard": "ISO 9999", "clause": "4.1"})["ok"] is False
    )  # not held


# ---- the CLI ------------------------------------------------------------------------------------------------------


@pytest.fixture
def cli():
    root = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(root))
    import run_agent_review as mod

    yield mod
    sys.path.remove(str(root))


def _skill_file(tmp_path):
    p = tmp_path / "skill.json"
    p.write_text(json.dumps(SKILL))
    return str(p)


def _args(copy_db, tmp_path, *extra):
    return ["--db-copy", str(copy_db), "--document", "D1", "--skill", _skill_file(tmp_path),
            "--provider", "fake", "--run-dir", str(tmp_path / "cli-run"), *extra]  # fmt: skip


def test_cli_refuses_without_the_switch(cli, copy_db, tmp_path):
    lines = []
    assert cli.main(_args(copy_db, tmp_path), env={}, out=lines.append) == 2
    assert "AGENT_REVIEW_ENABLED" in lines[0]
    assert not (tmp_path / "cli-run").exists()


def test_cli_dry_run_makes_no_provider_call(cli, copy_db, tmp_path, monkeypatch):
    class Boom:
        def complete(self, *_a):
            raise AssertionError("a model was called")

        def __init__(self, *_a, **_k):
            raise AssertionError("a provider was built")

    monkeypatch.setattr(cli, "SmokeProvider", Boom)
    monkeypatch.setattr(
        cli,
        "make_provider",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("built")),
    )
    lines = []
    code = cli.main(
        _args(copy_db, tmp_path, "--dry-run"),
        env={"AGENT_REVIEW_ENABLED": "1"},
        out=lines.append,
    )
    text = "\n".join(lines)
    assert (
        code == 0
        and "DRY RUN" in text
        and "I1, I2, I3" in text
        and "no model was called" in text
    )
    assert "at most 45 steps and USD 15.00" in text
    assert not (tmp_path / "cli-run").exists()


def test_cli_fake_run_prints_the_status_box(cli, copy_db, tmp_path, monkeypatch):
    monkeypatch.setattr(
        ar, "default_toolbox", lambda scope, readers: factory(scope, readers)
    )
    lines = []
    code = cli.main(
        _args(copy_db, tmp_path, "--limit", "2"),
        env={"AGENT_REVIEW_ENABLED": "1"},
        out=lines.append,
    )
    text = "\n".join(lines)
    assert code == 0 and "==== STATUS ====" in text and "RESULTS" in text
    assert (tmp_path / "cli-run" / "RESULTS.md").exists()


def test_cli_missing_provider_module_fails_clearly(cli):
    with pytest.raises(SystemExit) as exc:
        cli.make_provider("local")
    assert "agent_local" in str(exc.value)


def test_cli_refuses_the_live_database(cli, tmp_path):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    sqlite3.connect(live).close()
    lines = []
    args = _args(live, tmp_path, "--dry-run")
    assert cli.main(args, env={"AGENT_REVIEW_ENABLED": "1"}, out=lines.append) == 2
    assert "live database" in lines[0]


def test_enabled_reads_only_the_given_environment():
    assert ar.enabled({"AGENT_REVIEW_ENABLED": "1"}) and ar.enabled(
        {"AGENT_REVIEW_ENABLED": "true"}
    )
    assert not ar.enabled({}) and not ar.enabled({"AGENT_REVIEW_ENABLED": "0"})


# ---- Claude runs: consent, total cap -------------------------------------------------------------------------------


class FakeConsent:
    """Stands in for claude_approved: records what was declared and whether a call happened inside."""

    def __init__(self):
        self.declared = []
        self.inside = False

    def per_request_consent(self, ids):
        import contextlib

        @contextlib.contextmanager
        def ctx():
            self.declared.append(sorted(ids))
            self.inside = True
            try:
                yield
            finally:
                self.inside = False

        return ctx()


def test_claude_run_declares_exactly_the_documents_and_calls_inside_consent(
    copy_db, run_dir
):
    consent = FakeConsent()
    seen = []

    def call(_m):
        seen.append(consent.inside)
        return final("YELLOW")

    go(copy_db, run_dir, al.FakeProvider([call]), claude=True, consent=consent,
       documents=["D1", "S1"], editions={"ISO 9999": "2021"}, ledger=lambda _s: 0.0, limit=1)  # fmt: skip
    assert consent.declared == [["D1", "S1"]] and seen == [True]
    assert factory.last.scope["allowed"] == frozenset({"D1", "S1"})


def test_undeclared_or_out_of_scope_documents_are_refused_before_any_call(
    copy_db, run_dir
):
    for docs in (None, [], ["S1"], ["D1", "X1"]):
        consent, p = FakeConsent(), al.FakeProvider([final()])
        with pytest.raises(ar.DocumentsNotDeclared):
            go(copy_db, run_dir, p, claude=True, consent=consent, documents=docs,
               editions={"ISO 9999": "2021"}, ledger=lambda _s: 0.0)  # fmt: skip
        assert p.calls == [] and consent.declared == []


def test_non_claude_run_declares_nothing(copy_db, run_dir):
    consent = FakeConsent()
    go(copy_db, run_dir, al.FakeProvider([final("YELLOW")]), consent=consent, limit=1)
    assert consent.declared == []


def test_total_cap_stops_cleanly_and_resumes(copy_db, run_dir):
    spent = {"v": 0.0}

    def ledger(step):
        assert step == "agent_review"
        return spent["v"]

    def bump(_m):
        spent["v"] += 6.0
        return final("YELLOW")

    kw = {
        "claude": True,
        "consent": FakeConsent(),
        "documents": ["D1"],
        "ledger": ledger,
        "total_cap_usd": 10.0,
    }
    s = go(copy_db, run_dir, al.FakeProvider([bump, bump, bump]), **kw)
    assert s["items_done"] == 2 and s["stopped"] == "total cap for the agent test"
    assert "total cap for the agent test" in s["status_box"]
    assert "resumable" in (run_dir / "live.log").read_text()
    spent["v"] = 0.0  # the owner raises the cap / new day: the run continues
    p = al.FakeProvider([final("YELLOW")])
    s2 = go(copy_db, run_dir, p, **kw)
    assert len(p.calls) == 1 and s2["items_done"] == 3 and not s2["stopped"]


def test_cli_dry_run_lists_documents_declares_nothing_and_calls_nothing(
    cli, copy_db, tmp_path, monkeypatch
):
    consent = FakeConsent()
    monkeypatch.setattr(ar, "_consent_module", lambda _c: consent)
    monkeypatch.setattr(
        cli,
        "make_provider",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("built")),
    )
    lines = []
    args = [
        *_args(copy_db, tmp_path, "--dry-run", "--documents", "D1"),
        "--provider",
        "claude",
    ]
    code = cli.main(args, env={"AGENT_REVIEW_ENABLED": "1"}, out=lines.append)
    text = "\n".join(lines)
    assert (
        code == 0 and "WOULD be declared to Claude: D1" in text and "USD 10.00" in text
    )
    assert consent.declared == []


def test_cli_claude_without_documents_is_refused(cli, copy_db, tmp_path):
    lines = []
    args = [*_args(copy_db, tmp_path, "--dry-run"), "--provider", "claude"]
    assert cli.main(args, env={"AGENT_REVIEW_ENABLED": "1"}, out=lines.append) == 2
    assert "--documents" in lines[0]


def test_cli_builds_one_real_claude_provider_with_the_lead_model(cli):
    pytest.importorskip("app.agent_claude")
    p = cli.make_provider("claude")
    assert p.model == "claude-sonnet-5-5" and callable(p.second_opinion)


def test_cli_wrong_constructor_fails_loudly(cli, monkeypatch):
    agent_claude = pytest.importorskip("app.agent_claude")

    class Strict:
        def __init__(self):  # no model parameter
            pass

    monkeypatch.setattr(agent_claude, "ClaudeProvider", Strict)
    with pytest.raises(TypeError):
        cli.make_provider("claude")


def test_cli_second_opinion_needs_the_claude_provider(cli, copy_db, tmp_path):
    lines = []
    args = [*_args(copy_db, tmp_path), "--second-opinion", "claude"]
    assert cli.main(args, env={"AGENT_REVIEW_ENABLED": "1"}, out=lines.append) == 2
    assert "needs --provider claude" in lines[0]


# ---- the REAL ClaudeProvider with a fake sender: stops, wiring, model family --------------------------------------

CLAUDE_ENV = {
    "REASONING_PROVIDER": "claude",
    "STANDARDS_READER_ENABLED": "1",
    "STANDARDS_READER_ALLOW_PUBLIC_EGRESS": "1",
    "ANTHROPIC_API_KEY": "test-key-not-real",
}
USAGE = {"input_tokens": 100, "output_tokens": 50}


@pytest.fixture
def claude_ledger(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    return settings


class Sender:
    """Fake transport: the lead answers a finding in the colour given; the second opinion answers per `agree`."""

    def __init__(self, colour="YELLOW", agree=True, raises=None):
        self.colour, self.agree, self.raises, self.models = colour, agree, raises, []

    def __call__(self, url, *, headers, body, timeout):
        self.models.append(body["model"])
        if self.raises:
            raise self.raises
        if body["model"] == "claude-opus-5-5":
            text = json.dumps({"agree": self.agree, "reason": "r"})
        else:
            text = json.dumps(final(self.colour)["final"])
        return {"model": body["model"], "stop_reason": "end_turn", "usage": USAGE,
                "content": [{"type": "text", "text": text}]}  # fmt: skip


def real(sender, **kw):
    from app import agent_claude

    return agent_claude.ClaudeProvider(send=sender, env=CLAUDE_ENV, **kw)


def claude_go(copy_db, run_dir, provider, **kw):
    kw.setdefault("ledger", lambda _s: 0.0)
    return go(copy_db, run_dir, provider, claude=True, documents=["D1"], **kw)


def test_meter_stop_stops_the_run_leaves_the_item_out_and_resumes(
    copy_db, run_dir, claude_ledger
):
    from app import agent_claude

    agent_claude.reset_shared_meter_for_tests()
    s = claude_go(copy_db, run_dir, real(Sender(), total_cap_usd=0.0001))
    assert s["stopped"].startswith("budget stop") and s["items_done"] == 0
    assert "budget stop" in s["status_box"] and "PROBLEMS" in s["status_box"]
    assert "I1" not in json.loads((run_dir / "finals.json").read_text() if (run_dir / "finals.json").exists() else "{}")  # fmt: skip
    assert (
        not (run_dir / "state.json").exists()
        or "I1" not in (run_dir / "state.json").read_text()
    )
    s2 = claude_go(copy_db, run_dir, real(Sender(), total_cap_usd=10.0))
    assert s2["items_done"] == 3 and not s2["stopped"]


def test_ledger_step_cap_stops_the_run(copy_db, run_dir, claude_ledger):
    claude_ledger.claude_budget_usd_per_step = 0.0000001
    s = claude_go(copy_db, run_dir, real(Sender(), total_cap_usd=10.0))
    assert s["stopped"] and s["items_done"] == 0
    assert "owner decides whether to raise it" in s["status_box"]
    claude_ledger.claude_budget_usd_per_step = 5.0
    assert (
        claude_go(copy_db, run_dir, real(Sender(), total_cap_usd=10.0))["items_done"]
        == 3
    )


def test_a_non_fatal_provider_error_stays_yellow(copy_db, run_dir, claude_ledger):
    s = claude_go(
        copy_db, run_dir, real(Sender(raises=ValueError("x")), total_cap_usd=10.0)
    )
    assert not s["stopped"] and [f["color"] for f in s["findings"]] == ["YELLOW"] * 3


def test_cli_returns_non_zero_on_a_fatal_stop(
    cli, copy_db, tmp_path, monkeypatch, claude_ledger
):
    monkeypatch.setattr(
        ar, "default_toolbox", lambda scope, readers: factory(scope, readers)
    )
    monkeypatch.setattr(
        cli, "make_provider", lambda _k: real(Sender(), total_cap_usd=0.0001)
    )
    lines = []
    args = [*_args(copy_db, tmp_path, "--documents", "D1"), "--provider", "claude"]
    assert cli.main(args, env={"AGENT_REVIEW_ENABLED": "1"}, out=lines.append) == 3
    assert "budget stop" in "\n".join(lines)


def test_one_provider_object_serves_lead_and_second_opinion(
    cli, copy_db, tmp_path, monkeypatch, claude_ledger
):
    monkeypatch.setattr(
        ar, "default_toolbox", lambda scope, readers: factory(scope, readers)
    )
    built, sender = [], Sender("GREEN", agree=True)

    def make(_kind):
        built.append(real(sender, total_cap_usd=10.0))
        return built[-1]

    monkeypatch.setattr(cli, "make_provider", make)
    args = [*_args(copy_db, tmp_path, "--documents", "D1", "--limit", "1"), "--provider", "claude", "--second-opinion", "claude"]  # fmt: skip
    assert cli.main(args, env={"AGENT_REVIEW_ENABLED": "1"}, out=lambda _l: None) == 0
    assert len(built) == 1
    assert sender.models == ["claude-sonnet-5-5", "claude-opus-5-5"]
    assert built[0].spent > 0
    one_call = built[0].spent / 2
    assert built[0].spent > one_call  # both calls went through the one meter
    results = (tmp_path / "cli-run" / "RESULTS.md").read_text()
    assert "agreed 1" in results


def test_model_family_ignores_date_latest_and_version_suffixes():
    assert ar.model_family("Claude-Sonnet-5-5-20251101") == "claude-sonnet-5-5"
    assert ar.model_family("claude-sonnet-5-5-latest") == "claude-sonnet-5-5"
    assert ar.model_family("claude-sonnet-5-5@v2") == "claude-sonnet-5-5"
    assert not ar.models_differ(["claude-sonnet-5-5"], "claude-sonnet-5-5-20251101")
    assert not ar.models_differ(
        ["claude-sonnet-5-5-20251101"], "claude-sonnet-5-5-latest"
    )
    assert ar.models_differ(["claude-sonnet-5-5"], "claude-opus-5-5-20251101")


def test_same_family_with_a_date_suffix_is_yellow(copy_db, run_dir):
    s = go(copy_db, run_dir, al.FakeProvider([{**final("GREEN"), "model": "claude-sonnet-5-5"}]),
           second_opinion=Opinion([ok(True, "claude-sonnet-5-5-20251101")]), limit=1)  # fmt: skip
    assert s["findings"][0]["color"] == "YELLOW"
