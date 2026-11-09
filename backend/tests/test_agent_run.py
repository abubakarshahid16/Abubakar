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
def db_is_copy(copy_db, monkeypatch):
    """The app's configured database IS the copy (what `DB_PATH=<copy>` does in the command environment)."""
    from app.config import settings

    monkeypatch.setattr(settings, "db_path", copy_db)


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


@pytest.mark.usefixtures("db_is_copy")
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


@pytest.mark.usefixtures("db_is_copy")
def test_cli_claude_without_documents_is_refused(cli, copy_db, tmp_path):
    lines = []
    args = [*_args(copy_db, tmp_path, "--dry-run"), "--provider", "claude"]
    assert cli.main(args, env={"AGENT_REVIEW_ENABLED": "1"}, out=lines.append) == 2
    assert any("--documents" in line for line in lines)


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


def test_cli_second_opinion_local_needs_a_model_and_the_module(
    cli, copy_db, tmp_path, monkeypatch
):
    lines = []
    args = [*_args(copy_db, tmp_path), "--second-opinion", "local"]
    assert cli.main(args, env={"AGENT_REVIEW_ENABLED": "1"}, out=lines.append) == 2
    assert "--local-model" in lines[0]
    monkeypatch.setitem(sys.modules, "app.agent_local", None)  # not built yet
    with pytest.raises(SystemExit) as exc:
        cli.make_second_opinion("qwen-x")
    assert "not built yet" in str(exc.value)


def test_cli_has_no_claude_second_opinion_choice(cli):
    with pytest.raises(SystemExit):
        cli.parse(["--db-copy", "a", "--document", "d", "--skill", "s", "--provider", "fake", "--second-opinion", "claude"])  # fmt: skip


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
    class Flaky(Sender):
        def __call__(self, url, *, headers, body, timeout):
            self.raises = (
                ValueError("x") if not self.models else None
            )  # only the first call fails
            return super().__call__(url, headers=headers, body=body, timeout=timeout)

    s = claude_go(copy_db, run_dir, real(Flaky(), total_cap_usd=10.0))
    assert not s["stopped"] and [f["color"] for f in s["findings"]] == ["YELLOW"] * 3


@pytest.mark.usefixtures("db_is_copy")
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


class LocalFake(Opinion):
    unloaded = 0

    def unload(self):
        LocalFake.unloaded += 1


@pytest.mark.usefixtures("db_is_copy")
def test_local_second_opinion_never_sends_anything_to_claude(
    cli, copy_db, tmp_path, monkeypatch, claude_ledger
):
    monkeypatch.setattr(
        ar, "default_toolbox", lambda scope, readers: factory(scope, readers)
    )
    sender, local = Sender("GREEN"), LocalFake([ok(True, "qwen3.5:35b")])
    LocalFake.unloaded = 0
    monkeypatch.setattr(
        cli, "make_provider", lambda _k: real(sender, total_cap_usd=10.0)
    )
    monkeypatch.setattr(cli, "make_second_opinion", lambda _m: local)
    args = [*_args(copy_db, tmp_path, "--documents", "D1", "--limit", "1"), "--provider", "claude", "--second-opinion", "local", "--local-model", "qwen3.5:35b"]  # fmt: skip
    assert cli.main(args, env={"AGENT_REVIEW_ENABLED": "1"}, out=lambda _l: None) == 0
    assert sender.models == ["claude-sonnet-5-5"]  # Opus is never called
    assert len(local.calls) == 1 and LocalFake.unloaded == 1
    assert "agreed 1" in (tmp_path / "cli-run" / "RESULTS.md").read_text()


def test_the_lead_cannot_be_its_own_second_opinion(copy_db, run_dir):
    p = al.FakeProvider([final("GREEN")])
    with pytest.raises(ValueError):
        go(copy_db, run_dir, p, second_opinion=p)


def test_local_second_opinion_takes_the_heavy_lock_per_call(
    copy_db, tmp_path, monkeypatch
):
    lock = tmp_path / "heavy.lock"
    monkeypatch.setenv("HEAVY_JOB_LOCK", str(lock))
    seen = []

    class Peek(Opinion):
        def second_opinion(self, finding, evidence, **kw):
            seen.append(lock.exists())
            return super().second_opinion(finding, evidence)

    go(copy_db, tmp_path / "r", al.FakeProvider([final("GREEN")]), second_opinion=Peek([ok(True)]), limit=1)  # fmt: skip
    assert seen == [True] and not lock.exists()


def test_busy_heavy_lock_stops_the_run_not_a_yellow(copy_db, tmp_path, monkeypatch):
    from app import heavy_lock

    lock = tmp_path / "heavy.lock"
    monkeypatch.setenv("HEAVY_JOB_LOCK", str(lock))
    monkeypatch.setenv("HEAVY_JOB_WAIT_MINUTES", "0")
    held = heavy_lock.try_acquire("other", "someone", lock)
    try:
        s = go(copy_db, tmp_path / "r", al.FakeProvider([final("GREEN")] * 3), second_opinion=Opinion([ok(True)]), limit=1)  # fmt: skip
    finally:
        held.release()
    assert s["stopped"] == "heavy lock busy" and "heavy lock busy" in s["status_box"]
    assert not (tmp_path / "r" / "second_opinion.json").exists()


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


# ---- edition resolves from the file name OR the first 3 pages ----------------------------------------------------


@pytest.fixture
def std_db(tmp_path):
    path = tmp_path / "std.sqlite"
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT);"
        "CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);"
        "INSERT INTO documents VALUES ('A','ISO 7777.pdf'),('B','ISO 7777-2021.pdf'),"
        "('C','ISO 8888.pdf'),('D','ISO 6666.pdf');"
        "INSERT INTO pages VALUES ('A',1,'Title.\nIssue Date: 23 May 2019'),"
        "('C',1,'nothing'),('C',2,'nothing'),('C',3,'nothing'),('C',4,'Issue Date: 1 June 2018'),"
        "('D',2,'Issue   Date:  23   May   2019');"
    )
    db.commit()
    conn = ar.open_readonly(path)
    yield conn
    conn.close()


def resolve(conn, standard, edition, docs=("A", "B", "C", "D")):
    return ar.resolve_standard(conn, docs, standard, edition)


def test_edition_only_in_page_text_resolves(std_db):
    assert resolve(std_db, "ISO 7777", "23 May 2019", docs=("A",)) == "A"


def test_edition_in_the_file_name_still_resolves(std_db):
    assert resolve(std_db, "ISO 7777", "2021") == "B"


def test_edition_in_neither_is_not_held(std_db):
    assert resolve(std_db, "ISO 7777", "1 January 1999") is None


def test_wrong_standard_with_the_right_edition_is_not_held(std_db):
    assert resolve(std_db, "ISO 9999", "23 May 2019") is None
    assert resolve(std_db, "ISO 8888", "23 May 2019") is None


def test_edition_printed_only_on_page_4_does_not_resolve(std_db):
    assert resolve(std_db, "ISO 8888", "1 June 2018") is None


def test_empty_edition_is_refused(std_db):
    assert resolve(std_db, "ISO 7777", "") is None
    assert resolve(std_db, "ISO 7777", "   ") is None


def test_date_folding_matches_spacing_and_case(std_db):
    for text in ("23 May 2019", "23may2019", "23  May  2019", "23 MAY 2019"):
        assert resolve(std_db, "ISO 7777", text, docs=("A",)) == "A"
        assert resolve(std_db, "ISO 6666", text, docs=("D",)) == "D"


def test_a_toolbox_with_no_evidence_source_fails_closed_without_touching_any_database(
    monkeypatch,
):
    from app import agent_tools, db

    def boom():
        raise AssertionError("the configured database was opened")

    monkeypatch.setattr(db, "connect", boom)
    ctx = agent_tools.ToolContext(frozenset({"A"}), "A", {"ISO 7777": "23 May 2019"})
    out = agent_tools.ToolBox(ctx, standard_pages=lambda _d: [(1, "x")]).run(
        "get_clause", {"standard": "ISO 7777", "clause": "4.1"}
    )
    assert (
        out["ok"] is False
        and out["result"]["state"] == "not held: edition not confirmed"
    )


# ---- edition EVIDENCE: page quote, verbatim, or 'edition not confirmed' ------------------------------------------

LONG = "Issue Date:" + " " * 100 + "23 May 2019"


@pytest.fixture
def ev_db(tmp_path):
    path = tmp_path / "ev.sqlite"
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT);"
        "CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);"
        "INSERT INTO documents VALUES ('A','ISO 7777.pdf'),('C','ISO 8888.pdf'),('E','ISO 5555.pdf'),"
        "('L','ISO 4444.pdf'),('N','ISO 3333-2021.pdf'),('P','ISO 2222.pdf'),('Q','ISO 2222 copy.pdf');"
    )
    db.executemany(
        "INSERT INTO pages VALUES (?,?,?)",
        [
            ("A", 1, "Title line\n  Issue Date:  23 May 2019  \nother"),
            ("C", 4, "Issue Date: 1 June 2018"),
            ("E", 2, "Issue Date: 23 May\n2019"),
            ("L", 3, LONG),
            ("P", 1, "Issue Date: 5 July 2020"),
            ("Q", 1, "Issue Date: 5 July 2020"),
            ("A", 2, "Clause 4.1 The figure shall be 5."),
        ],
    )
    db.commit()
    conn = ar.open_readonly(path)
    yield conn
    conn.close()


def ev(conn, std, edition, docs=("A", "C", "E", "L", "N", "P", "Q")):
    from app import agent_edition

    return agent_edition.edition_evidence(conn, docs, std, edition)


def test_edition_on_page_1_gives_the_page_and_the_exact_printed_line(ev_db):
    got = ev(ev_db, "ISO 7777", "23 May 2019")
    assert got["status"] == "confirmed" and got["doc"] == "A" and got["page"] == 1
    assert (
        got["quote"] == "Issue Date:  23 May 2019"
    )  # verbatim: the original spacing, not the folded text
    assert got["quote"] in "Title line\n  Issue Date:  23 May 2019  \nother"


def test_edition_only_on_page_4_is_not_confirmed(ev_db):
    got = ev(ev_db, "ISO 8888", "1 June 2018")
    assert (
        got["status"] == "edition not confirmed"
        and got["doc"] is None
        and got["quote"] is None
    )


def test_empty_or_missing_edition_is_not_confirmed(ev_db):
    for edition in ("", "  ", None):
        assert ev(ev_db, "ISO 7777", edition)["status"] == "edition not confirmed"


def test_file_name_edition_carries_the_file_name_source(ev_db):
    got = ev(ev_db, "ISO 3333", "2021")
    assert (
        got["doc"] == "N"
        and got["source"] == "file name"
        and got["page"] is None
        and got["quote"] is None
    )


def test_a_line_longer_than_80_characters_is_never_quoted(ev_db):
    assert ev(ev_db, "ISO 4444", "23 May 2019")["status"] == "edition not confirmed"


def test_an_edition_split_over_two_lines_has_no_verifiable_quote_so_not_confirmed(
    ev_db,
):
    assert ev(ev_db, "ISO 5555", "23 May 2019")["status"] == "edition not confirmed"


def test_two_standards_resolve_independently(ev_db):
    a = ev(ev_db, "ISO 7777", "23 May 2019")
    n = ev(ev_db, "ISO 3333", "2021")
    assert (a["doc"], n["doc"]) == ("A", "N")
    assert ev(ev_db, "ISO 7777", "2021")["status"] == "edition not confirmed"


def test_two_matching_documents_are_not_guessed_between(ev_db):
    assert ev(ev_db, "ISO 2222", "5 July 2020")["status"] == "edition not confirmed"


def test_get_clause_with_an_unconfirmed_edition_returns_no_clause_text(ev_db):
    from app import agent_tools

    def box(editions):
        ctx = agent_tools.ToolContext(frozenset({"A", "C"}), "A", editions)
        return agent_tools.ToolBox(
            ctx, edition_evidence=ar.Readers(ev_db, {"A", "C"}).evidence,
            standard_pages=lambda _d: [(2, "1 General\nIntro words.\n4.1 Figure\nThe figure shall be 5.\n4.2 Next\nOther.")],
        )  # fmt: skip

    bad = box({"ISO 8888": "1 June 2018"}).run(
        "get_clause", {"standard": "ISO 8888", "clause": "4.1"}
    )
    assert (
        bad["ok"] is False
        and bad["result"]["state"] == "not held: edition not confirmed"
    )
    assert "text" not in bad["result"]
    good = box({"ISO 7777": "23 May 2019"}).run(
        "get_clause", {"standard": "ISO 7777", "clause": "4.1"}
    )
    assert good["ok"] is True
    assert good["result"]["edition_evidence"]["page"] == 1
    assert good["result"]["edition_evidence"]["quote"] == "Issue Date:  23 May 2019"


def test_results_lists_each_standard_with_page_quote_or_not_confirmed(
    copy_db, run_dir, tmp_path
):
    run_dir.mkdir()
    ev_conn = sqlite3.connect(copy_db)
    ev_conn.execute("INSERT INTO pages VALUES ('S1', 2, 'Issue Date: 9 March 2021')")
    ev_conn.commit()
    ev_conn.close()
    go(copy_db, run_dir, al.FakeProvider([final("YELLOW")]), limit=1,
       editions={"ISO 9999": "9 March 2021", "ISO 1111": "2000"})  # fmt: skip
    text = (run_dir / "RESULTS.md").read_text()
    assert (
        "- Edition: ISO 9999 9 March 2021 p.2 verified: Issue Date: 9 March 2021"
        in text
    )
    assert "- Edition: ISO 1111 2000: edition not confirmed" in text


# ---- the printed line must be a LABELLED edition line ---------------------------------------------------------


def one_page_db(tmp_path, text, page=2, filename="ISO 7777.pdf"):
    path = tmp_path / f"one-{abs(hash((text, filename)))}.sqlite"
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT);"
        "CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);"
    )
    db.execute("INSERT INTO documents VALUES ('A', ?)", (filename,))
    db.execute("INSERT INTO pages VALUES ('A', ?, ?)", (page, text))
    db.commit()
    db.close()
    return ar.open_readonly(path)


@pytest.mark.parametrize(
    ("text", "asked"),
    [
        ("Previous Issue: 1 January 2018", "1 January 2018"),
        ("Next Planned Update: 1 June 2024", "1 June 2024"),
        ("Copyright (c) 2020 The Body", "2020"),
        ("© Issue Date: 2020", "2020"),
        ("Doc no 12019-44", "2019"),
        ("Issue Date: 12019-44", "2019"),
        ("Issue Date: 23 May 20199", "23 May 2019"),
        ("23 May 2019", "23 May 2019"),  # a bare date, no label
        ("This edition supersedes the one of 23 May 2019", "23 May 2019"),
        ("Issue Date: 1 May 2018 (previous 23 May 2019)", "23 May 2019"),
        ("Issued with Next Planned Update: 23 May 2019", "23 May 2019"),
        ("Edition: 2019.5", "2019"),
        ("Issue Date: 2019-06-01", "2019"),
        ("Edition 3.1", "3"),
        ("Edition: 1/2019", "2019"),
        ("Edition: 2019,5", "2019"),
        ("This standard, edition 2019 is withdrawn", "2019"),
        ("The date of issue 23 May 2019 was postponed", "23 May 2019"),
        ("Issue Date: 23 May 2019 (Rev 3)", "23 May 2019"),
        ("Revision Date: 23 May 2019", "23 May 2019"),
    ],
)
def test_a_line_that_is_not_the_labelled_issue_date_never_confirms(
    tmp_path, text, asked
):
    conn = one_page_db(tmp_path, "Title\n" + text + "\nBody")
    assert ev(conn, "ISO 7777", asked, docs=("A",))["status"] == "edition not confirmed"


@pytest.mark.parametrize(
    "label",
    [
        "Issue Date:",
        "Date of Issue -",
        "Issued:",
        "Edition:",
        "1. Edition",
        "- Issue Date:",
    ],
)
def test_each_allowed_label_confirms_the_correct_line(tmp_path, label):
    conn = one_page_db(tmp_path, f"Title\n{label} 23 May 2019\nBody", page=2)
    got = ev(conn, "ISO 7777", "23 May 2019", docs=("A",))
    assert (
        got["status"] == "confirmed"
        and got["page"] == 2
        and got["quote"] == f"{label} 23 May 2019"
    )


def test_issue_date_on_page_2_confirms_with_page_2_and_the_verbatim_line(tmp_path):
    conn = one_page_db(tmp_path, "Cover\n  Issue Date: 23 May 2019   \nOther", page=2)
    got = ev(conn, "ISO 7777", "23 May 2019", docs=("A",))
    assert (got["status"], got["page"], got["quote"]) == (
        "confirmed",
        2,
        "Issue Date: 23 May 2019",
    )


def test_two_different_dates_are_not_confirmed_unless_the_asked_one_is_the_issue_date(
    tmp_path,
):
    text = "Issue Date: 23 May 2019\nRevision Date: 5 July 2020"
    conn = one_page_db(tmp_path, text)
    assert (
        ev(conn, "ISO 7777", "23 May 2019", docs=("A",))["status"] == "confirmed"
    )  # the issue date
    assert (
        ev(conn, "ISO 7777", "5 July 2020", docs=("A",))["status"]
        == "edition not confirmed"
    )  # a revision


def test_file_name_edition_needs_digit_boundaries(tmp_path):
    conn = one_page_db(tmp_path, "x", filename="ISO 7777-12019.pdf")
    assert (
        ev(conn, "ISO 7777", "2019", docs=("A",))["status"] == "edition not confirmed"
    )
    conn = one_page_db(tmp_path, "x", filename="ISO 7777-2019.pdf")
    assert ev(conn, "ISO 7777", "2019", docs=("A",))["source"] == "file name"


def test_verify_quote_refuses_a_quote_that_is_not_on_the_page_or_too_long():
    from app import agent_edition

    page = "Title\nIssue Date: 23 May 2019\n"
    assert agent_edition.verify_quote("Issue Date: 23 May 2019", page, "23 May 2019")
    assert not agent_edition.verify_quote(
        "Issue Date: 23 May 2019", "other page", "23 May 2019"
    )
    assert not agent_edition.verify_quote("Issue Date: 23 May 2019" + " " * 80, page + " " * 80, "23 May 2019")  # fmt: skip
    assert not agent_edition.verify_quote("Next Issue Date: 23 May 2019", "Next Issue Date: 23 May 2019", "23 May 2019")  # fmt: skip


@pytest.mark.usefixtures("db_is_copy")
def test_the_cli_builds_exactly_one_provider_per_run(
    cli, copy_db, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        ar, "default_toolbox", lambda scope, readers: factory(scope, readers)
    )
    built = []

    def make(_kind):
        built.append(1)
        return al.FakeProvider([final("YELLOW")] * 3)

    monkeypatch.setattr(cli, "make_provider", make)
    args = [*_args(copy_db, tmp_path), "--provider", "local"]
    assert cli.main(args, env={"AGENT_REVIEW_ENABLED": "1"}, out=lambda _l: None) == 0
    assert len(built) == 1


@pytest.mark.parametrize(
    "line", ["Edition: 2019.", "Issue Date: 2019,", "  Edition   2019  "]
)
def test_end_punctuation_and_spacing_after_the_edition_are_fine(tmp_path, line):
    conn = one_page_db(tmp_path, "Title\n" + line)
    assert ev(conn, "ISO 7777", "2019", docs=("A",))["status"] == "confirmed"


def test_two_issue_lines_with_different_dates_are_not_confirmed(tmp_path):
    conn = one_page_db(tmp_path, "Issue Date: 23 May 2019\nEdition: 2020")
    assert (
        ev(conn, "ISO 7777", "23 May 2019", docs=("A",))["status"]
        == "edition not confirmed"
    )
    assert (
        ev(conn, "ISO 7777", "2020", docs=("A",))["status"] == "edition not confirmed"
    )


def test_the_same_issue_date_repeated_as_a_running_header_is_fine(tmp_path):
    conn = one_page_db(
        tmp_path, "Issue Date: 23 May 2019\nBody\nIssue Date: 23 May 2019"
    )
    assert ev(conn, "ISO 7777", "23 May 2019", docs=("A",))["status"] == "confirmed"


def test_a_file_name_followed_by_a_longer_value_does_not_confirm(tmp_path):
    for name in ("ISO 7777-2019.5.pdf", "ISO 7777-2019-06-01.pdf"):
        conn = one_page_db(tmp_path, "x", filename=name)
        assert (
            ev(conn, "ISO 7777", "2019", docs=("A",))["status"]
            == "edition not confirmed"
        )


def test_a_closed_toolbox_never_returns_clause_text_or_opens_a_database(monkeypatch):
    from app import agent_tools, db

    opened = []
    monkeypatch.setattr(db, "connect", lambda: opened.append(1))
    ctx = agent_tools.ToolContext(frozenset({"A"}), "A", {"ISO 7777": "23 May 2019"})
    pages = [
        (1, "1 General\nIntro.\n4.1 Figure\nThe figure shall be 5.\n4.2 Next\nOther.")
    ]
    out = agent_tools.ToolBox(ctx, standard_pages=lambda _d: pages).run(
        "get_clause", {"standard": "ISO 7777", "clause": "4.1"}
    )
    assert out["ok"] is False and "text" not in out["result"] and opened == []


def test_issued_by_is_not_a_label_so_it_is_harmless(tmp_path):
    text = "Issue Date: 23 May 2019\nIssued by the standards committee for general use"
    assert (
        ev(one_page_db(tmp_path, text), "ISO 7777", "23 May 2019", docs=("A",))[
            "status"
        ]
        == "confirmed"
    )


@pytest.mark.parametrize(
    "other",
    [
        "Issue Date: 23/05/24",
        "Issue Date: 5 June 24",
        "Issue Date: \u0662\u0660\u0662\u0664",  # an Arabic-Indic digit year
        "Issue Date: 5 June",  # a date with no year
        "Issued: 5 June",
        "Issued 5 June",
        "Date of Issue - 7 May",
        "Edition: second",
    ],
)
def test_any_other_labelled_value_is_a_conflict(tmp_path, other):
    conn = one_page_db(tmp_path, "Edition: 2019\n" + other)
    assert (
        ev(conn, "ISO 7777", "2019", docs=("A",))["status"] == "edition not confirmed"
    )


def test_a_date_split_over_two_lines_never_confirms(tmp_path):
    conn = one_page_db(tmp_path, "Edition: 2019\nIssue Date: 5 June\n2024")
    assert (
        ev(conn, "ISO 7777", "2019", docs=("A",))["status"] == "edition not confirmed"
    )


def test_a_label_with_an_empty_value_is_not_a_conflict_and_does_not_confirm(tmp_path):
    conn = one_page_db(tmp_path, "Edition: 2019\nIssue Date:\n5 June 2024")
    assert ev(conn, "ISO 7777", "2019", docs=("A",))["status"] == "confirmed"
    assert ev(one_page_db(tmp_path, "Issue Date:\n2019", filename="ISO 7777.pdf"), "ISO 7777", "2019", docs=("A",))["status"] == "edition not confirmed"  # fmt: skip


@pytest.mark.parametrize(
    "quote",
    [
        "Edition: 2019.5",
        "Issue Date: 2019-06-01",
        "Edition: 2019 and more",
        "Edition 20190",
    ],
)
def test_verify_quote_needs_the_exact_value(quote):
    from app import agent_edition

    assert not agent_edition.verify_quote(quote, quote, "2019")
    assert agent_edition.verify_quote("Edition: 2019.", "x\nEdition: 2019.\n", "2019")


def test_the_real_copy_shape_prose_after_the_label_does_not_block_a_confirmation(
    tmp_path,
):
    text = "Title\nIssue Date: 23 May 2019\nedition of the references listed below, unless noted otherwise"
    got = ev(one_page_db(tmp_path, text), "ISO 7777", "23 May 2019", docs=("A",))
    assert got["status"] == "confirmed" and got["page"] == 2


@pytest.mark.parametrize(
    "other",
    [
        "Edition: Third",
        "Edition: III",
        "Edition: 3rd",
        "Edition: 24 May",
        "Edition: iv",
        "Edition: Sept",
    ],
)
def test_a_value_like_edition_line_is_a_conflict(tmp_path, other):
    conn = one_page_db(tmp_path, "Issue Date: 23 May 2019\n" + other)
    assert (
        ev(conn, "ISO 7777", "23 May 2019", docs=("A",))["status"]
        == "edition not confirmed"
    )


def _sentences(n=30):
    """Invented prose of 5 to 9 words: no digit, month, ordinal word or Roman numeral."""
    subjects = [
        "the references listed below",
        "all cited documents",
        "every supplier drawing",
        "the attached notes",
        "this clause",
    ]
    verbs = [
        "apply unless noted otherwise",
        "remain valid for reviewers",
        "are kept with the project file",
        "describe general practice only",
        "form part of the package",
    ]
    out = [f"{sub} {verb}" for sub in subjects for verb in verbs]
    prefixes = [
        "edition of",
        "edition: see that the",
        "issued: note that the",
        "date of issue is where the",
        "issue date and the",
        "edition is that the",
    ]
    return [f"{prefixes[i % len(prefixes)]} {out[i % len(out)]}" for i in range(n)]


def test_thirty_invented_prose_lines_of_five_words_or_more_are_ignored(tmp_path):
    from app import agent_edition

    lines = _sentences(30)
    assert len(set(lines)) == 30
    for line in lines:
        assert len(line.split()) >= 5 and agent_edition._is_prose(line), line
    conn = one_page_db(tmp_path, "Issue Date: 23 May 2019\n" + "\n".join(lines))
    assert ev(conn, "ISO 7777", "23 May 2019", docs=("A",))["status"] == "confirmed"


@pytest.mark.parametrize(
    "value",
    [
        "Eleventh", "Twentieth", "Twelve", "Two", "Rev. B", "A", "twenty nineteen", "Mayo", "Mai", "Dezember", "octobre",
        "Draft", "Superseded", "Previous", "Final", "Current", "Withdrawn", "latest",
    ],
)  # fmt: skip
def test_a_short_value_of_any_kind_is_a_competing_value(tmp_path, value):
    for label in ("Edition:", "Issue Date:", "Date of Issue -"):
        conn = one_page_db(tmp_path, f"Issue Date: 23 May 2019\n{label} {value}")
        assert (
            ev(conn, "ISO 7777", "23 May 2019", docs=("A",))["status"]
            == "edition not confirmed"
        )


def test_four_word_prose_is_treated_as_a_value_and_fails_safe(tmp_path):
    conn = one_page_db(
        tmp_path, "Issue Date: 23 May 2019\nEdition notes are listed below here"
    )  # 5 words: a sentence
    assert ev(conn, "ISO 7777", "23 May 2019", docs=("A",))["status"] == "confirmed"
    conn = one_page_db(
        tmp_path, "Issue Date: 23 May 2019\nEdition notes follow"
    )  # 2 words
    assert (
        ev(conn, "ISO 7777", "23 May 2019", docs=("A",))["status"]
        == "edition not confirmed"
    )
    conn = one_page_db(
        tmp_path, "Issue Date: 23 May 2019\nEdition: see the notes below"
    )  # 4 words
    assert (
        ev(conn, "ISO 7777", "23 May 2019", docs=("A",))["status"]
        == "edition not confirmed"
    )


@pytest.mark.parametrize(
    "line",
    [
        "Edition: the references listed below were reviewed in 2024",
        "Edition: see the notes dated 5 June for the details",
        "Edition: the references listed below say third edition",
        "Edition: the references listed below use part iv",
        "Edition: the references listed below use ٢٠ pages",
        "Edition: the notes written in May for the details",
    ],
)  # fmt: skip
def test_a_long_line_with_a_digit_month_ordinal_or_roman_numeral_still_conflicts(
    tmp_path, line
):
    conn = one_page_db(tmp_path, "Issue Date: 23 May 2019\n" + line)
    assert (
        ev(conn, "ISO 7777", "23 May 2019", docs=("A",))["status"]
        == "edition not confirmed"
    )


# ---- first real Claude run lessons: breaker, honest counts, db path guard, error codes, resume ----------------------


def boom(_m):
    raise RuntimeError("provider down")


class Hot(RuntimeError):
    fatal = True
    code = "budget_stop"


def test_two_provider_errors_with_no_spend_stop_the_run_and_keep_the_items_out_of_finals(
    copy_db, run_dir
):
    s = go(copy_db, run_dir, al.FakeProvider([boom, boom, boom]))
    assert s["stopped"].startswith("provider errors on 2 items in a row (RuntimeError)")
    assert s["items_done"] == 0 and "provider errors" in s["status_box"]
    assert json.loads((run_dir / "finals.json").read_text()) == {}
    assert json.loads((run_dir / "state.json").read_text())["completed"] == {}


def test_after_the_breaker_a_resume_asks_the_failed_items_again(copy_db, run_dir):
    go(copy_db, run_dir, al.FakeProvider([boom, boom]))
    p = al.FakeProvider([final("YELLOW")] * 3)
    s = go(copy_db, run_dir, p)
    assert len(p.calls) == 3 and s["items_done"] == 3 and not s["stopped"]


def test_one_provider_error_between_good_items_does_not_trip_the_breaker(
    copy_db, run_dir
):
    s = go(copy_db, run_dir, al.FakeProvider([boom, final("YELLOW"), boom]))
    assert not s["stopped"] and s["items_done"] == 3
    assert "items ended by provider error: 2" in (run_dir / "RESULTS.md").read_text()


def test_a_provider_error_with_spend_is_not_counted_by_the_breaker(copy_db, run_dir):
    def tool(_m):
        return {
            "tool": "open_page",
            "args": {"doc": "D1", "page": 1},
            "reason": "r",
            "usd": 0.1,
        }

    # item 1: a paid tool step, then the provider fails: spend > 0, so it does not count toward the breaker
    s = go(copy_db, run_dir, al.FakeProvider([tool, boom, tool, boom, final("YELLOW")]))
    assert not s["stopped"]


def test_the_exception_class_code_is_logged_never_the_message(copy_db, run_dir):
    go(copy_db, run_dir, al.FakeProvider([boom, final("YELLOW"), final("YELLOW")]))
    log = (run_dir / "live.log").read_text()
    assert "provider error RuntimeError" in log and "provider down" not in log
    traces = "".join(p.read_text() for p in run_dir.glob("*.trace.jsonl"))
    assert "provider error RuntimeError" in traces and "provider down" not in traces


def test_a_clean_run_says_problems_zero(copy_db, run_dir):
    s = go(copy_db, run_dir, al.FakeProvider([final("YELLOW")] * 3))
    text = (run_dir / "RESULTS.md").read_text()
    assert (
        "Problems: 0" in text
        and "unreliable" not in text
        and "PROBLEMS none" in s["status_box"]
    )
    assert "tool calls failed: 0 of 3 (0.0%; limit: over 30%)" in text


class FailingBox(Box):
    def run(self, name, args):
        if name == "record_finding":
            return super().run(name, args)
        return {"ok": False, "result": {"error": "bad"}, "cites": []}


def test_failing_tool_calls_make_the_run_unreliable_and_problems_nonzero(
    copy_db, run_dir
):
    def step():
        return {"tool": "open_page", "args": {"doc": "D1", "page": 1}, "reason": "r"}

    script = [step(), final("YELLOW")] * 3
    s = go(
        copy_db,
        run_dir,
        al.FakeProvider(script),
        toolbox_factory=lambda sc, rd: FailingBox(),
    )
    text = (run_dir / "RESULTS.md").read_text()
    assert (
        "run unreliable: tool failures" in text
        and "tool calls failed: 3 of 6 (50.0%; limit: over 30%)" in text
    )
    assert "Problems: 0" not in text
    assert (
        "run unreliable: tool failures" in s["status_box"]
        and "PROBLEMS none" not in s["status_box"]
    )
    assert "tool calls failed: 3 of 6 (50.0%; limit: over 30%)" in s["status_box"]


def test_an_item_ended_on_the_step_limit_is_counted(copy_db, run_dir):
    class Forever:
        def complete(self, _m, _s):
            return {
                "tool": "open_page",
                "args": {"doc": "D1", "page": 1},
                "reason": "r",
                "usd": 0,
            }

    s = go(copy_db, run_dir, Forever(), limit=1)
    text = (run_dir / "RESULTS.md").read_text()
    assert "items ended on the step limit: 1" in text and "Problems: 0" not in text
    assert s["findings"][0]["color"] == "YELLOW"


def test_a_fatal_stop_on_item_one_is_retried_on_resume_not_replayed(copy_db, run_dir):
    def fatal(_m):
        raise Hot("budget_stop")

    s = go(copy_db, run_dir, al.FakeProvider([fatal]))
    assert s["stopped"].startswith("budget stop") and s["items_done"] == 0
    p = al.FakeProvider([final("YELLOW")] * 3)
    s2 = go(copy_db, run_dir, p)
    assert (
        len(p.calls) == 3 and s2["items_done"] == 3
    )  # item 1 asked the provider again


def test_the_db_path_guard_names_the_one_line_fix(copy_db, tmp_path):
    with pytest.raises(ar.DbPathMismatch) as exc:
        ar.check_db_path(copy_db, configured=tmp_path / "other.sqlite")
    assert str(exc.value).startswith("set DB_PATH=") and str(copy_db.resolve()) in str(
        exc.value
    )
    assert str(exc.value).endswith("in the command environment")
    ar.check_db_path(copy_db, configured=copy_db)


def test_cli_refuses_before_any_model_call_when_db_path_is_not_the_copy(
    cli, copy_db, tmp_path, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "elsewhere.sqlite")
    monkeypatch.setattr(
        cli, "make_provider", lambda _k: (_ for _ in ()).throw(AssertionError("built"))
    )
    for extra in ([], ["--dry-run"]):
        lines = []
        args = [
            *_args(copy_db, tmp_path, "--documents", "D1", *extra),
            "--provider",
            "claude",
        ]
        assert cli.main(args, env={"AGENT_REVIEW_ENABLED": "1"}, out=lines.append) == 2
        assert "set DB_PATH=" in lines[0] and "in the command environment" in lines[0]
    lines = []  # a fake provider never reads the configured database: no check
    assert (
        cli.main(
            _args(copy_db, tmp_path, "--dry-run"),
            env={"AGENT_REVIEW_ENABLED": "1"},
            out=lines.append,
        )
        == 0
    )


@pytest.mark.usefixtures("db_is_copy")
def test_cli_exits_3_when_the_breaker_stops_the_run(
    cli, copy_db, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        ar, "default_toolbox", lambda scope, readers: factory(scope, readers)
    )
    monkeypatch.setattr(cli, "make_provider", lambda _k: al.FakeProvider([boom, boom]))
    lines = []
    args = [*_args(copy_db, tmp_path, "--documents", "D1"), "--provider", "local"]
    assert cli.main(args, env={"AGENT_REVIEW_ENABLED": "1"}, out=lines.append) == 3
    assert "provider errors on 2 items in a row" in "\n".join(lines)


# ---- review round: one source of truth, once per item, error code leak, unmeasured --------------------------------

SKILL4 = {
    **SKILL,
    "items": [
        {"id": f"I{n}", "order": n, "topic": f"zorblat rating {n}"}
        for n in (1, 2, 3, 4)
    ],
}


def field(text, name):
    import re as _re

    m = _re.search(rf"^- \*\*{name}\*\*: (.*)$", text, _re.M)
    return m.group(1) if m else None


def box_field(box, name):
    import re as _re

    m = _re.search(rf"^{name}\s+(.*)$", box, _re.M)
    return m.group(1) if m else None


def run_with_failing_tools(copy_db, run_dir):
    def step():
        return {"tool": "open_page", "args": {"doc": "D1", "page": 1}, "reason": "r"}

    return go(
        copy_db,
        run_dir,
        al.FakeProvider([step(), final("YELLOW")] * 3),
        toolbox_factory=lambda sc, rd: FailingBox(),
    )


@pytest.mark.parametrize("failing", [True, False])
def test_live_results_and_status_say_the_same_about_problems(copy_db, run_dir, failing):
    if failing:
        s = run_with_failing_tools(copy_db, run_dir)
    else:
        s = go(copy_db, run_dir, al.FakeProvider([final("YELLOW")] * 3))
    live = (run_dir / "LIVE.md").read_text()
    results = (run_dir / "RESULTS.md").read_text()
    assert field(live, "PROBLEMS") == box_field(s["status_box"], "PROBLEMS")
    assert (
        field(live, "RESULTS")
        == box_field(s["status_box"], "RESULTS").split(" (GREEN and RED")[0]
    )
    count = int(results.split("- Problems: ")[1].split(";")[0].split("\n")[0])
    if failing:
        for line in ("tool calls failed: 3 of 6 (50.0%; limit: over 30%)",):
            assert line in field(live, "PROBLEMS") and line in results
        assert (
            "run unreliable: tool failures" in field(live, "RESULTS")
            and "run unreliable: tool failures" in results
        )
        assert count >= 1 and "PROBLEMS" in live and field(live, "PROBLEMS") != "none"
        assert "run unreliable: tool failures" in (run_dir / "live.log").read_text()
    else:
        assert (
            field(live, "PROBLEMS") == "none"
            and count == 0
            and "unreliable" not in live + results
        )


def run4(copy_db, run_dir, provider, **kw):
    return go(copy_db, run_dir, provider, skill=SKILL4, **kw)


def test_literal_breaker_then_resume_counts_each_item_once_by_its_latest_outcome(
    copy_db, run_dir
):
    s = run4(
        copy_db,
        run_dir,
        al.FakeProvider([final("YELLOW"), final("YELLOW"), boom, boom]),
    )
    assert (
        s["stopped"].startswith("provider errors on 2 items in a row")
        and s["items_done"] == 2
    )
    assert "items ended by provider error: 2" in (run_dir / "RESULTS.md").read_text()
    p = al.FakeProvider([final("YELLOW"), final("YELLOW")])
    s2 = run4(copy_db, run_dir, p)
    text = (run_dir / "RESULTS.md").read_text()
    assert len(p.calls) == 2 and s2["items_done"] == 4 and not s2["stopped"]
    assert (
        "items ended by provider error: 0" in text and "retried after error: 2" in text
    )
    assert "Problems: 0" in text and "unreliable" not in text
    assert field((run_dir / "LIVE.md").read_text(), "PROBLEMS").startswith(
        "items ended by provider error: 0"
    )


def test_literal_kill_after_item_two_resumes_at_item_three(copy_db, run_dir):
    def die(_m):
        raise Killed

    first = al.FakeProvider([final("YELLOW"), final("YELLOW"), die])
    with pytest.raises(Killed):
        run4(copy_db, run_dir, first)
    second = al.FakeProvider([final("YELLOW"), final("YELLOW")])
    s = run4(copy_db, run_dir, second)
    assert len(second.calls) == 2 and s["items_done"] == 4
    assert "items ended by provider error: 0" in (run_dir / "RESULTS.md").read_text()


SENTINEL = (
    "SENTINEL-KEY-4711 and a long sentence that looks like a clause of a document"
)


def test_the_error_code_never_leaks_a_message_or_a_document_like_code(
    cli, copy_db, run_dir, monkeypatch, capsys
):
    class Leaky(RuntimeError):
        code = SENTINEL

    def leak(_m):
        raise Leaky(SENTINEL)

    s = go(copy_db, run_dir, al.FakeProvider([leak, final("YELLOW"), final("YELLOW")]))
    assert s["items_done"] == 3
    blob = "".join(
        p.read_text()
        for p in run_dir.rglob("*")
        if p.is_file() and p.suffix in (".log", ".jsonl", ".md", ".json")
    )
    blob += s["status_box"] + capsys.readouterr().out + capsys.readouterr().err
    for leaked in ("SENTINEL", "4711", "long sentence", "clause of a document"):
        assert leaked not in blob
    assert "provider error Leaky" in (run_dir / "live.log").read_text()


def test_the_adapter_codes_are_kept_when_short_and_ours_and_dropped_otherwise():
    from app import agent_claude, agent_loop

    assert (
        agent_loop.safe_error_code(
            agent_claude.AgentTransportError("transport_LiveWriteRefused")
        )
        == "transport_LiveWriteRefused"
    )
    assert (
        agent_loop.safe_error_code(agent_claude.AgentBadReply("x" * 41))
        == "AgentBadReply"
    )
    assert (
        agent_loop.safe_error_code(agent_claude.AgentBadReply("bad shape with spaces"))
        == "AgentBadReply"
    )
    assert agent_loop.safe_error_code(ValueError("m")) == "ValueError"


def test_the_rate_prints_with_one_decimal_and_the_threshold_is_stated():
    from app import agent_run_stats as rs

    st = rs.RunStats()
    st.items = {"a": {"outcome": "ok", "calls": 1000, "fails": 304, "retried": False}}
    assert (
        rs.percent(st.rate) == "30.4%"
        and rs.unreliable_note(st) == "run unreliable: tool failures"
    )
    assert "(30.4%; limit: over 30%)" in "\n".join(rs.stat_lines(st))
    st.items["a"]["fails"] = 300  # exactly 30% is not over the limit
    assert rs.unreliable_note(st) == ""


def test_a_run_from_before_the_counts_says_not_measured_never_zero(copy_db, run_dir):
    run_dir.mkdir()
    (run_dir / "run_meta.json").write_text(
        json.dumps({"seconds": 5.0, "lead_models": ["x"]})
    )
    go(copy_db, run_dir, al.FakeProvider([final("YELLOW")] * 3))
    text = (run_dir / "RESULTS.md").read_text()
    assert (
        "earlier items: not measured" in text
        and "items ended by provider error: 0" not in text
    )
    assert "earlier items: not measured (this run started" in field(
        (run_dir / "LIVE.md").read_text(), "PROBLEMS"
    )
    s2 = go(
        copy_db, run_dir, al.FakeProvider([final("YELLOW")] * 3)
    )  # still not measured after a resume
    assert (
        "earlier items: not measured" in (run_dir / "RESULTS.md").read_text()
        and s2["items_done"] == 3
    )


def everything_written(run_dir, status_box, capsys):
    blob = "".join(
        p.read_text()
        for p in run_dir.rglob("*")
        if p.is_file() and p.suffix in (".log", ".jsonl", ".md", ".json")
    )
    return blob + status_box + capsys.readouterr().out + capsys.readouterr().err


def test_a_fatal_exception_with_a_document_like_code_or_a_key_leaks_nowhere(
    copy_db, run_dir, capsys
):
    class FatalLeak(RuntimeError):
        fatal = True
        code = SENTINEL

    def hot(_m):
        raise FatalLeak(SENTINEL)

    s = go(copy_db, run_dir, al.FakeProvider([hot]))
    assert s["stopped"] and "fatal FatalLeak" in (run_dir / "live.log").read_text()
    blob = everything_written(run_dir, s["status_box"], capsys)
    for leaked in ("SENTINEL", "4711", "long sentence", "clause of a document"):
        assert leaked not in blob


def test_a_foreign_exception_with_a_short_code_logs_only_its_class_name(
    copy_db, run_dir
):
    class Foreign(RuntimeError):
        code = "ABC123"

    def err(_m):
        raise Foreign("m")

    go(copy_db, run_dir, al.FakeProvider([err, final("YELLOW"), final("YELLOW")]))
    log = (run_dir / "live.log").read_text()
    assert "provider error Foreign" in log and "ABC123" not in log


def test_a_run_resumed_from_before_the_counts_still_counts_its_own_provider_error(
    copy_db, run_dir
):
    run_dir.mkdir()
    (run_dir / "run_meta.json").write_text(
        json.dumps({"seconds": 5.0, "lead_models": ["x"]})
    )
    s = go(copy_db, run_dir, al.FakeProvider([boom, final("YELLOW"), final("YELLOW")]))
    text = (run_dir / "RESULTS.md").read_text()
    assert (
        "earlier items: not measured" in text
        and "items ended by provider error: 1" in text
    )
    assert "Problems: 0" not in text and "run unreliable" in text
    assert (
        "run unreliable" in s["status_box"]
        and field((run_dir / "LIVE.md").read_text(), "PROBLEMS") != "none"
    )


def test_the_unreliable_line_in_live_log_says_it_is_this_run_only(copy_db, run_dir):
    run4(copy_db, run_dir, al.FakeProvider([final("YELLOW"), boom, boom]))
    run4(copy_db, run_dir, al.FakeProvider([boom, boom]))
    lines = [
        x
        for x in (run_dir / "live.log").read_text().splitlines()
        if "run unreliable" in x and "PROBLEM" in x
    ]
    assert len(lines) == 2
    assert "this run only; not cumulative" in lines[0] and "resumed run" not in lines[0]
    assert "this run only, resumed run 2; not cumulative" in lines[1]


def test_a_foreign_fatal_code_never_chooses_the_problem_words(copy_db, run_dir):
    class Foreign(RuntimeError):
        fatal = True
        code = "document_x"

    def hot(_m):
        raise Foreign("m")

    s = go(copy_db, run_dir, al.FakeProvider([hot]))
    assert (
        s["stopped"].startswith("budget stop")
        and "documents not declared" not in s["stopped"]
    )
