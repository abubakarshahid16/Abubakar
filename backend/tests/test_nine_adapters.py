# ruff: noqa: RUF059
"""B5: the adapters that wire roles 1 to 4 into the job. No model, no network: the role modules are replaced by fakes where a call would
be made, and every model call is shown to go through `nine_call.ask`."""

from __future__ import annotations

import json

import pytest

from app import crs_one, db, nine_call, nine_context, nine_facts, nine_job, nine_reader
from app.config import settings
from tests.test_b1_review_points import world_with_both
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", True)


def store_claude(run_id, docs, bar=False):
    """What the tightened seam needs for Claude: the run's stored engine choice (text leaves) and its stored shown list."""
    from app import review_engine, review_shown

    with db.connect() as conn:
        review_shown.ensure_schema(conn)
        review_shown.record_in(conn, run_id, list(docs), "2026-11-16T00:00:00Z")
        review_engine.record_in(
            conn,
            run_id,
            {"choice": "claude", "text_leaves": True, "parts": []},
            "starter1",
            then_ai=False,
            bar_claude=bar,
            now="2026-11-16T00:00:00Z",
        )


def ctx_for(doc, ai, items=()):
    return nine_job.RoleContext(
        ai,
        doc,
        type("K", (), {"equipment_type": "relief valve", "kind": "datasheet"})(),
        {"items": list(items)},
        {},
        lambda *a: None,
    )


def no_calls(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a model call was made")

    monkeypatch.setattr(nine_call, "ask", boom)


def test_the_reader_adapter_hands_pages_stored_facts_and_the_engine_to_the_reader_and_stores_the_sheet(
    monkeypatch,
):
    doc, rc, ai, client = world_with_both()
    store_claude(ai, [doc])
    seen = {}

    def fake(**kw):
        seen.update(kw)
        sheet = nine_facts.sheet_of(
            kw["run_id"], kw["paper_id"], 4, [], [], kw["engine"], ["m1"]
        )
        return nine_reader.ReadResult(
            sheet, {"facts": 0}, "ran_partly", "one page not read"
        )

    monkeypatch.setattr(nine_reader, "read_paper", fake)
    ctx = ctx_for(doc, ai)
    got = nine_job.reader_role(ctx)
    assert (
        seen["engine"] == "claude"
        and seen["paper_id"] == doc
        and seen["equipment_type"] == "relief valve"
        and seen["pictures"] is True
    )
    assert (
        got.state == "ran_partly"
        and got.why == "one page not read"
        and ctx.store["fact_sheet"].paper_id == doc
    )
    assert nine_facts.load(db.connect(), ai) is not None


def test_the_reader_has_no_picture_function_on_the_local_model(monkeypatch):
    doc, rc, ai, client = world_with_both()
    store_claude(ai, [doc])
    seen = {}
    monkeypatch.setattr(nine_job, "_engine", lambda ctx: "local")
    monkeypatch.setattr(
        nine_reader,
        "read_paper",
        lambda **kw: (
            seen.update(kw)
            or nine_reader.ReadResult(
                nine_facts.sheet_of(
                    kw["run_id"], kw["paper_id"], 0, [], [], "local", []
                ),
                {},
                "ran",
            )
        ),
    )
    nine_job.reader_role(ctx_for(doc, ai))
    assert seen["engine"] == "local" and seen["pictures"] is False


def test_the_context_role_with_nothing_held_makes_no_call_and_says_the_five_things_are_not_available(
    monkeypatch,
):
    doc, rc, ai, client = world_with_both()
    store_claude(ai, [doc])
    no_calls(monkeypatch)
    ctx = ctx_for(doc, ai)
    got = nine_job.context_role(ctx)
    note = ctx.store["context_note"]
    assert got.state == "ran" and [n.what for n in note.not_available] == list(
        nine_context.WHATS
    )
    assert got.produced["context_parts"] == 0  # nothing held: no part to pass


def test_the_librarian_with_no_chosen_rules_reads_nothing_and_says_so(monkeypatch):
    doc, rc, ai, client = world_with_both()
    store_claude(ai, [doc])
    no_calls(monkeypatch)
    ctx = ctx_for(doc, ai)
    got = nine_job.librarian_role(ctx)
    assert (
        got.state == "ran"
        and got.produced["books"] == 0
        and got.produced["chapters_chosen"] == 0
    )


def test_the_reviewer_with_no_reading_list_does_not_run_and_the_checklist_then_asks_everything(
    monkeypatch,
):
    doc, rc, ai, client = world_with_both()
    ctx = ctx_for(doc, ai, [{"item_id": "R-1"}, {"item_id": "S-2"}])
    got = nine_job.reviewer_role(ctx)
    assert (
        got.state == "not_run"
        and "no chapter was chosen" in got.why
        and ctx.flags["reviewer_failed"]
    )
    asked = []
    ctx.ask = lambda *a: asked.append([i["item_id"] for i in a[3]["items"]])
    nine_job.checklist_role(ctx)
    assert asked == [["R-1", "S-2"]]


def test_a_nine_role_run_whose_roles_read_nothing_asks_exactly_what_todays_review_asks(
    monkeypatch,
):
    """Roles 2 to 4 with nothing to read, role 1 unable to read: the lines come from the same ask over the same items as today's review."""
    doc, rc, ai, client = world_with_both()
    items = [{"item_id": "R-1"}, {"item_id": "R-2"}, {"item_id": "S-3"}]
    today, nine = [], []
    from app import agent_review_dispatch

    monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", False)
    agent_review_dispatch.run(
        ai,
        doc,
        "k",
        {"items": list(items)},
        {},
        lambda *a: today.append([i["item_id"] for i in a[3]["items"]]),
    )
    monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", True)
    monkeypatch.setattr(
        nine_reader,
        "read_paper",
        lambda **kw: nine_reader.ReadResult(
            nine_facts.sheet_of(
                kw["run_id"], kw["paper_id"], 0, [], [], kw["engine"], []
            ),
            {},
            "not_run",
            "no page could be read",
        ),
    )
    no_calls(monkeypatch)
    ctx = type("K", (), {"equipment_type": None, "kind": "datasheet"})()
    agent_review_dispatch.run(
        ai,
        doc,
        ctx,
        {"items": list(items)},
        {},
        lambda *a: nine.append([i["item_id"] for i in a[3]["items"]]),
    )
    assert nine == today == [["R-1", "R-2", "S-3"]]
    rows = {
        r["role_no"]: r
        for r in db.connect().execute(
            "SELECT * FROM agent_review_role WHERE run_id = ?", (ai,)
        )
    }
    assert (
        len(rows) == 9
        and rows[4]["state"] == "not_run"
        and rows[1]["state"] == "not_run"
    )


def test_the_dry_run_prints_sizes_and_usd_per_role_sends_nothing_and_applies_the_stop_line(
    tmp_path, monkeypatch, capsys
):
    import importlib.util
    import shutil
    from pathlib import Path

    doc, rc, ai, client = world_with_both()
    db.connect().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy(settings.db_path, tmp_path / "rag_intelligence.sqlite")
    spec = importlib.util.spec_from_file_location(
        "nine_dry_run",
        Path(__file__).resolve().parents[2] / "scripts" / "nine_dry_run.py",
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(
        nine_job._jobs(),
        "lane",
        lambda: (_ for _ in ()).throw(AssertionError("a dry run sends nothing")),
    )
    assert script.main(["--copy", str(tmp_path), "--paper", doc, "--run", ai]) == 0
    out = capsys.readouterr().out
    assert "1 Reader" in out and "TOTAL" in out and "within the stop line" in out
    monkeypatch.setattr(script, "STOP_EXPECTED", -1.0)
    assert (
        script.main(["--copy", str(tmp_path), "--paper", doc, "--run", ai]) == 1
    )  # over the line: the exit says STOP


# ------------------------------------------------------------------------------------------------ role 9: the writer


class _Said:
    def __init__(self, data):
        self.ok, self.data, self.error_code = True, data, None


def _writer_world(monkeypatch, wording):
    """An invented review whose first comment has a code text with a number; the writer's call is faked to answer `wording`."""
    from app import nine_record

    doc, rc, ai, client = world_with_both()
    nine_record.start_run(ai)
    store_claude(ai, [doc])
    monkeypatch.setattr(settings, "agent_review_nine_writer_enabled", True)
    seen = {}

    def fake_ask(run_id, role_no, blocks, question, **kw):
        seen["blocks"], seen["question"], seen["role"] = blocks, question, role_no
        return _Said(wording({"1": crs_one_text_of(doc, 1)}))

    monkeypatch.setattr(nine_call, "ask", fake_ask)
    return doc, ai, seen


def crs_one_text_of(doc, number):
    from app import access, crs_comments, crs_one
    from app import review_points_service as svc

    scope = access.AccessScope(
        user_id=None,
        allowed_document_ids=frozenset(
            r[0] for r in db.connect().execute("SELECT id FROM documents")
        ),
    )
    _l, raw, _f = svc.export_listing(doc, scope)
    return crs_one.comment_full_texts(crs_comments.group(raw)[number - 1])["action"]


def _scope(doc):
    from app import access

    return access.AccessScope(
        user_id=None,
        allowed_document_ids=frozenset(
            r[0] for r in db.connect().execute("SELECT id FROM documents")
        ),
    )


def _cells(data):
    import io

    from openpyxl import load_workbook

    return [
        [None if c is None else str(c) for c in r]
        for r in load_workbook(io.BytesIO(data))["CRS"].iter_rows(values_only=True)
    ]


def _comment_rows(data):
    rows = _cells(data)
    start = next(i for i, r in enumerate(rows) if r[0] == "Comment")
    return rows[start], [r for r in rows[start + 1 :] if r[0] and r[0].isdigit()]


def _record_writer(ai, got):
    from app import nine_record

    nine_record.role_end(
        ai,
        9,
        "ran",
        produced={k: v for k, v in got.produced.items() if isinstance(v, (int, str))},
        engine="claude",
    )


def test_with_the_writer_setting_off_there_is_no_call_and_the_record_says_the_sheet_was_written_by_code(
    monkeypatch,
):
    doc, rc, ai, client = world_with_both()
    store_claude(ai, [doc])

    def boom(*a, **k):
        raise AssertionError("a paid call was made")

    monkeypatch.setattr(nine_call, "ask", boom)
    got = nine_job.writer_role(ctx_for(doc, ai))
    assert got.state == "ran" and got.why is None
    assert (
        got.produced["sheet_by"] == "code"
        and got.produced["ai_wording"] == "not_used_in_this_version"
    )
    head, _rows = _comment_rows(crs_one.build_team(doc, _scope(doc)))
    assert (
        crs_one.SUGGESTED not in head
    )  # no suggestion column while the setting is off


def test_the_writer_asks_through_the_seam_with_a_template_and_one_derived_block_whose_sources_are_documents(
    monkeypatch,
):
    doc, ai, seen = _writer_world(monkeypatch, lambda code: {"1": code["1"]})
    nine_job.writer_role(ctx_for(doc, ai))
    block = seen["blocks"][0]
    assert (
        seen["role"] == 9
        and seen["question"][0] == nine_job.WRITER_QUESTION
        and len(seen["blocks"]) == 1
    )
    assert (
        block.document_kind == "review_record" and doc in block.sources and block.items
    )
    assert all(len(t) <= 60 and "\n" not in t for row in block.items for t in row)


def test_a_wording_that_passes_the_lock_is_shown_only_in_its_own_column_and_never_replaces_the_code_words(
    monkeypatch,
):
    from app import crs_completeness

    code_rows = (
        _comment_rows(crs_one.build_team(world_with_both()[0], _scope(None)))[1]
        if False
        else None
    )
    doc, ai, seen = _writer_world(
        monkeypatch, lambda code: {"1": code["1"].rstrip(".") + "."}
    )
    before_head, before = _comment_rows(crs_one.build_team(doc, _scope(doc)))
    got = nine_job.writer_role(ctx_for(doc, ai))
    assert (
        got.produced["suggestions_shown"] == 1
        and got.produced["suggestions_refused"] == 0
    )
    _record_writer(ai, got)
    head, rows = _comment_rows(crs_one.build_team(doc, _scope(doc)))
    action, suggested = (
        head.index("What the contractor must do"),
        head.index(crs_one.SUGGESTED),
    )
    assert rows[0][suggested]  # the suggestion is shown in its own column
    assert [r[action] for r in rows] == [
        r[action] for r in before
    ]  # the comment cell is the code's words, every comment, every time
    assert all(
        r["ok"] for _d, r in crs_completeness.checked_files(doc, _scope(doc)).values()
    )
    assert before_head


def test_a_wording_that_changes_a_fact_is_refused_the_column_stays_empty_and_the_first_sheet_counts_it(
    monkeypatch,
):
    doc, ai, seen = _writer_world(
        monkeypatch,
        lambda code: {"1": code["1"].replace("1", "7").replace("2", "8") + " 99 bar"},
    )
    got = nine_job.writer_role(ctx_for(doc, ai))
    assert (
        got.produced["suggestions_shown"] == 0
        and got.produced["suggestions_refused"] == 1
    )
    assert (
        db.connect()
        .execute("SELECT COUNT(*) FROM agent_review_comment_wording")
        .fetchone()[0]
        == 0
    )
    _record_writer(ai, got)
    data = crs_one.build_team(doc, _scope(doc))
    text = "\n".join(str(c) for r in _cells(data) for c in r if c)
    assert "0 suggested wordings shown, 1 refused" in text and "99 bar" not in text


def test_the_contractor_file_is_never_reworded(monkeypatch):
    doc, ai, seen = _writer_world(
        monkeypatch, lambda code: {"1": code["1"].rstrip(".") + "."}
    )
    before = crs_one.build_contractor(doc, _scope(doc), exported="x")
    nine_job.writer_role(ctx_for(doc, ai))
    assert crs_one.build_contractor(doc, _scope(doc), exported="x") == before


def test_on_the_local_model_the_writer_makes_no_call_even_with_the_setting_on(
    monkeypatch,
):
    doc, ai, seen = _writer_world(monkeypatch, lambda code: {"1": "x"})
    monkeypatch.setattr(nine_call, "engine_of_run", lambda run_id, conn=None: "local")
    got = nine_job.writer_role(ctx_for(doc, ai))
    assert (
        "blocks" not in seen
        and got.state == "ran_partly"
        and "worded by code" in got.why
        and got.engine == "code"
    )


def test_the_writers_templates_render_with_their_parameters():
    q = nine_call.render((nine_job.WRITER_QUESTION, {"count": 3}))
    assert "3 rows" in q[1] and '{"1": "comment", ...}' in q[1]
    assert nine_call.render((nine_job.WRITER_SYSTEM, {}))[1]


def test_earlier_points_come_from_the_earlier_papers_own_list_and_only_when_the_starter_may_read_it():
    doc, rc, ai, client = world_with_both()
    ids = frozenset(r[0] for r in db.connect().execute("SELECT id FROM documents"))
    got = nine_job._earlier_points(ids)(doc)
    assert (
        got
        and {"point_id", "field", "value", "status_word", "engineer_decision"}
        <= set(got[0])
        and all(p["value"] is None for p in got)
    )
    assert nine_job._earlier_points(frozenset())(doc) == ()


# ------------------------------------------------------------------------------------------------ R71: the documents a run may use


BOOK_TEXT = (
    "4.1 Frame\nThe coating thickness shall be at least 0.2 mm on every outside surface.\n"
    * 40
)


def _book_world(engine_decision: dict | None, listed: list[str] | None):
    """A paper, a rule book with a numbered chapter, and (optionally) a stored engine decision and a stored shown list."""
    doc, rc, ai, client = world_with_both()
    with db.connect() as conn:
        for n in (1, 2):
            conn.execute(
                "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?,?,?,?,0)",
                ("doc_std", n, BOOK_TEXT, len(BOOK_TEXT)),
            )
        if engine_decision is not None:
            from app import review_engine

            review_engine.record_in(
                conn,
                ai,
                engine_decision,
                "starter1",
                then_ai=False,
                bar_claude=engine_decision.get("choice") == "local",
                now="2026-11-16T00:00:00Z",
            )
        if listed is not None:
            from app import review_shown

            review_shown.ensure_schema(conn)
            review_shown.record_in(conn, ai, listed, "2026-11-16T00:00:00Z")
    items = [
        {
            "item_id": "R-1",
            "standard_document_id": "doc_std",
            "clause": "4.1",
            "clause_page": 1,
        }
    ]
    return (
        doc,
        ai,
        nine_job.RoleContext(
            ai,
            doc,
            type("K", (), {"equipment_type": None, "kind": "datasheet"})(),
            {"items": items},
            {},
            lambda *a: None,
        ),
    )


@pytest.fixture
def local_lane(monkeypatch):
    """Every local model call of the nine roles answers `{}`-like text from a fake (no Ollama is ever reached)."""
    monkeypatch.setattr(
        nine_job,
        "_seam_kwargs",
        lambda ctx=None: {
            "local_send": lambda parts: {"text": '{"chapters": []}', "model": "m"}
        },
    )


def test_a_local_run_with_no_stored_list_may_use_everything_the_starter_may_read_and_the_librarian_chooses_chapters(
    local_lane,
):
    """A start that sends nothing stores NO list (#1827): on Local the usable documents are the starter's access, so the chapters are CHOSEN (not
    "not on the list shown") and the reason words never say a list."""
    doc, ai, ctx = _book_world(
        {"choice": "local", "text_leaves": False, "parts": []}, None
    )
    got = nine_job.librarian_role(ctx)
    assert got.produced["chapters_chosen"] >= 1, got
    assert "list" not in (
        got.why or ""
    ) and "not on the list shown before the start" not in json.dumps(got.produced)


def test_a_claude_run_with_a_stored_list_that_omits_the_book_reads_nothing_of_it(
    local_lane,
):
    doc, ai, ctx = _book_world(
        {"choice": "claude", "text_leaves": True, "parts": []}, ["doc_sub"]
    )
    assert (
        nine_job.librarian_role(ctx).produced["chapters_chosen"] == 0
    )  # the book is not on the list shown: not read


def test_a_claude_run_whose_list_names_the_book_reads_it(local_lane):
    doc, ai, ctx = _book_world(
        {"choice": "claude", "text_leaves": True, "parts": []}, ["doc_sub", "doc_std"]
    )
    assert nine_job.librarian_role(ctx).produced["chapters_chosen"] >= 1


def test_a_claude_run_with_no_stored_list_uses_no_document(local_lane):
    doc, ai, ctx = _book_world(
        {"choice": "claude", "text_leaves": True, "parts": []}, None
    )
    assert nine_job._usable_documents(ctx, "claude") == frozenset()


def test_usable_documents_is_the_starters_access_on_local_and_narrowed_by_a_stored_list():
    doc, ai, ctx = _book_world(
        {"choice": "local", "text_leaves": False, "parts": []}, None
    )
    assert {"doc_sub", "doc_std"} <= nine_job._usable_documents(ctx, "local")


def test_usable_documents_with_a_stored_list_on_local_is_the_list_within_the_access():
    doc, ai, ctx = _book_world(
        {"choice": "local", "text_leaves": False, "parts": []}, ["doc_std"]
    )
    assert nine_job._usable_documents(ctx, "local") == frozenset({"doc_std"})
