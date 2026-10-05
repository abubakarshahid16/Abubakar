"""Performance quick wins (perf audit items 1, 2, 4, 5, 7, 8, 9).

Every test here pins a BEHAVIOUR, not a timing: a wall-clock assertion on a
shared or throttled machine is a coin toss, and a coin toss is a vacuous test
that happens to pass. What is pinned instead is the mechanism the speed comes
from - statements issued, commits made, characters scanned, texts harvested,
options sent - each of which a mutation in `scripts/mutations/perf_quick_wins.py`
(M1330-M1349) breaks and the test notices.

The before/after timings are in the commit messages and the final report,
measured with the audit's own scripts.
"""

from __future__ import annotations

import logging
import random
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import pytest

from app import acronyms, comparison, datasheets, db, deliverables, review, standards
from app import submittal_review, warmup
from app.config import Settings, settings

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "perf.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    acronyms.reset_cache()
    yield
    acronyms.reset_cache()
    db.reset_connection()


class _Trace:
    """Every SQL statement this thread's connection issues, while active."""

    def __init__(self):
        self.statements: list[str] = []

    def __enter__(self):
        db.connect().set_trace_callback(self.statements.append)
        return self

    def __exit__(self, *exc):
        db.connect().set_trace_callback(None)
        return False

    def count(self, pattern: str) -> int:
        rx = re.compile(pattern, re.I)
        return sum(1 for s in self.statements if rx.match(s.strip()))


def _doc(doc_id: str, role: str = "COMPANY_STANDARD") -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',1,'2026-09-18T00:00:00Z')""",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf"))
        conn.execute("INSERT INTO document_classification (document_id, suggested_by,"
                     " document_role) VALUES (?, 'test', ?)", (doc_id, role))
    return doc_id


def _chunk(chunk_id: str, doc_id: str, text: str = "x", ordinal: int = 0) -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,?,1,1,NULL,'prose',?,1,?,1)""",
            (chunk_id, doc_id, "f.pdf", ordinal, text, f"h-{chunk_id}"))
    return chunk_id


# ====================================================== 1/9. the schema memo

def test_a_second_ensure_schema_issues_one_statement_not_a_hundred():
    """Item 9: 392 of 397 statements per request were schema checks. Once the
    schema is proven, re-proving it costs one `PRAGMA schema_version`."""
    # Settle first: a module proven BEFORE another module's DDL bumped the
    # schema version re-proves itself once (the memo is exact, not hopeful).
    # Once no module has DDL left to do, nothing re-runs.
    for _ in range(2):
        for fn in (submittal_review.ensure_schema, review.ensure_schema,
                   deliverables.ensure_schema):
            fn()
    with _Trace() as trace:
        submittal_review.ensure_schema()
        review.ensure_schema()
        deliverables.ensure_schema()
    # deliverables' owner sync is one INSERT per call by design (see below);
    # everything else must be the schema_version read alone.
    ddl = [s for s in trace.statements
           if re.match(r"\s*(PRAGMA table_info|CREATE|ALTER)", s, re.I)]
    assert ddl == [], ddl[:5]
    assert trace.count(r"PRAGMA schema_version") >= 3


def test_the_memo_is_exact_a_dropped_table_is_recreated():
    """Keyed on SQLite's own schema counter, not on "ran once": a DROP from
    anywhere changes the version and the next call rebuilds."""
    review.ensure_schema()
    with db.connect() as conn:
        conn.execute("DROP INDEX idx_review_findings_run_requirement")
    review.ensure_schema()
    names = {r[0] for r in db.connect().execute(
        "SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert "idx_review_findings_run_requirement" in names


def test_a_new_items_owner_still_becomes_a_stakeholder_on_the_next_read():
    """The owner sync in deliverables.ensure_schema LOOKS like a one-off
    migration but is what makes a new item's owner a stakeholder. It must
    survive the memo."""
    deliverables.ensure_schema()            # memo primed before the item exists
    with db.connect() as conn:
        conn.execute("INSERT INTO users (id,email,display_name,password_hash,created_at)"
                     " VALUES ('u1','u1@example.test','U1','h','2026-09-18T00:00:00Z')")
    item = deliverables.create({"wbs_code": "1.1", "title": "Pump datasheet",
                                "deliverable_type": "datasheet",
                                "owner_user_id": "u1"}, created_by=None)
    roles = {(s["user_id"], s["role"]) for s in deliverables.stakeholders(item["id"])}
    assert ("u1", "owner") in roles


# ------------------------------------------------------- synchronous pragma

def test_connections_use_synchronous_normal_by_default():
    assert Settings().sqlite_synchronous == "NORMAL"
    assert db.connect().execute("PRAGMA synchronous").fetchone()[0] == 1   # NORMAL


def test_synchronous_full_is_one_setting_away(monkeypatch):
    monkeypatch.setattr(settings, "sqlite_synchronous", "full")
    db.reset_connection()
    assert db.connect().execute("PRAGMA synchronous").fetchone()[0] == 2   # FULL


def test_an_unknown_synchronous_value_is_refused_not_interpolated(monkeypatch):
    monkeypatch.setattr(settings, "sqlite_synchronous", "OFF; DROP TABLE documents")
    db.reset_connection()
    with pytest.raises(ValueError, match="SQLITE_SYNCHRONOUS"):
        db.connect()


# ------------------------------------------------ the duplicate gate's index

def test_the_duplicate_gate_is_answered_from_its_own_index():
    plan = " ".join(r[3] for r in db.connect().execute(
        "EXPLAIN QUERY PLAN SELECT id FROM review_findings WHERE review_run_id = ?"
        " AND requirement_id = ? AND fact_id IS ? AND confirmed_by IS NULL",
        ("r", "q", None)))
    assert "idx_review_findings_run_requirement" in plan, plan


# ======================================== 1. a run's findings: one transaction

def _review_setup(n: int) -> tuple[str, str, str]:
    std = _doc("std")
    sub = _doc("sub", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std)
    fc = _chunk("fc", sub)
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_runs
            (id,submittal_document_id,status,created_at,updated_at)
            VALUES (?,?,'pending','2026-09-18T00:00:00Z','2026-09-18T00:00:00Z')""",
            (run, sub))
        conn.execute("""INSERT INTO review_applicable_standards
            (id,review_run_id,standard_document_id,selection_method,included,
             created_at) VALUES (?,?,?,'rule',1,?)""",
            (str(uuid.uuid4()), run, std, "2026-09-18T00:00:00Z"))
    for i in range(n):
        limit = 80 + i
        text = f"The noise level of unit {i} shall not exceed {limit} dB(A)."
        standards.create_requirement(
            standard_document_id=std, chunk_id=sc, clause=f"5.{i}", page=1,
            requirement_text=text, source_text=text,
            structured={"requirement_type": "numeric_limit", "operator": "<=",
                        "value": float(limit), "unit": "dB(A)",
                        "raw_value": str(limit), "raw_unit": "dB(A)",
                        "field": "noise level", "subject": "noise level"})
    datasheets.create_fact(submittal_document_id=sub, chunk_id=fc,
                           field_label="Noise level", raw_value="85 dB(A)", page=1)
    return run, std, sub


def _findings_of(run: str) -> list[str]:
    return sorted(r[0] for r in db.connect().execute(
        "SELECT id FROM review_findings WHERE review_run_id = ?", (run,)))


def test_a_run_writes_all_its_findings_in_one_commit_not_one_each():
    run, std, sub = _review_setup(12)
    scope = frozenset({std, sub})
    with _Trace() as trace:
        result = comparison.run_comparison(run, allowed_document_ids=scope)
    assert result["requirements_evaluated"] == 12
    inserted = trace.count(r"INSERT INTO review_findings")
    assert inserted >= 12
    # One commit for the findings; a few more for the ledger, the datasheet
    # checks and the stored outcome - never one per finding.
    assert trace.count(r"COMMIT") < 12, trace.count(r"COMMIT")


def test_a_rerun_that_fails_half_way_leaves_the_previous_findings_untouched(monkeypatch):
    """ATOMIC. The old code deleted the run's findings first and committed each
    new one, so a failure half way left half a run on the review screen."""
    run, std, sub = _review_setup(6)
    scope = frozenset({std, sub})
    comparison.run_comparison(run, allowed_document_ids=scope)
    before = _findings_of(run)
    assert len(before) >= 6

    real, calls = comparison.compare, []

    def failing(*args, **kwargs):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("injected failure on the third requirement")
        return real(*args, **kwargs)

    monkeypatch.setattr(comparison, "compare", failing)
    with pytest.raises(RuntimeError, match="injected"):
        comparison.run_comparison(run, allowed_document_ids=scope)
    assert _findings_of(run) == before


def test_the_duplicate_gate_also_sees_findings_not_yet_written(monkeypatch):
    """A batch is invisible to the stored-row query, so the gate checks the
    batch too - and refuses before anything is written."""
    run, std, sub = _review_setup(2)
    scope = frozenset({std, sub})
    real = standards.list_requirements

    def doubled(*args, **kwargs):
        rows = real(*args, **kwargs)
        return rows + rows[:1]          # the same requirement twice

    monkeypatch.setattr(standards, "list_requirements", doubled)
    with pytest.raises(comparison.ComparisonError, match="duplicate finding is refused"):
        comparison.run_comparison(run, allowed_document_ids=scope)
    assert _findings_of(run) == []


# ============================================================= 2. acronyms

def _fuzz_texts(seed: int, count: int):
    rng = random.Random(seed)
    alphabet = ["alpha", "Beta", "g-h", "x", " ", "\t", " \n ", "(", ")", "(NDFT)",
                "( PWHT )", "(AB-C)", "NACE", "-", "7", "A/B", "( X )", "nominal",
                "dry", "film", "thickness"]
    for _ in range(count):
        yield "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 60)))


def test_the_fast_parenthetical_finder_matches_the_regex_exactly():
    """GOLDEN DIFF: `_parentheticals` must return exactly what
    `_PARENTHETICAL.finditer` returns - spans and groups - including runs of
    more than seven words, hyphens, brackets back to back and no brackets."""
    fixed = [
        "nominal dry film thickness (NDFT) and post weld heat treatment (PWHT)",
        "one two three four five six seven eight nine (ABCD)",
        "x-ray inspection (XRI)(XRJ) a b (AB)",
        "(NDFT) at the start, and ( PWHT ) spaced",
        "no brackets at all here " * 20,
        "ab-cd ef (CE)",
    ]
    matched = 0
    for text in [*fixed, *_fuzz_texts(11, 20000)]:
        expected = [(m.span(), m.groups()) for m in acronyms._PARENTHETICAL.finditer(text)]
        got = [(m.span(), m.groups()) for m in acronyms._parentheticals(text)]
        assert got == expected, repr(text)
        matched += len(expected)
    assert matched > 1000          # the fuzz really exercised matches


def test_the_parenthetical_regex_only_ever_sees_the_words_before_a_bracket(monkeypatch):
    """Item 2's 9.2 s: the unanchored pattern was tried at every letter. Now it
    is searched only in the few words before each bracket."""
    spans: list[int] = []
    real = acronyms._PARENTHETICAL

    class Spy:
        def search(self, text, pos, endpos):
            spans.append(endpos - pos)
            return real.search(text, pos, endpos)

    monkeypatch.setattr(acronyms, "_PARENTHETICAL", Spy())
    filler = "the coating shall be applied in accordance with the procedure " * 800
    text = filler + " nominal dry film thickness (NDFT) " + filler + " heat treatment (HT)"
    found = [m.group(2) for m in acronyms._parentheticals(text)]
    assert found == ["NDFT", "HT"]
    assert len(spans) == 2
    assert sum(spans) < 400, spans          # not the ~100,000 characters of text


def test_alternating_scopes_harvest_each_document_once(monkeypatch):
    """The single-entry cache re-harvested the whole corpus whenever the scope
    changed (a library question after a one-document one, another user)."""
    a, b = _doc("docA"), _doc("docB")
    _chunk("ca", a, "The nominal dry film thickness (NDFT) is 250 um.")
    _chunk("cb", b, "The post weld heat treatment (PWHT) applies.")
    harvested: list[str] = []
    real = acronyms._harvest_text
    monkeypatch.setattr(acronyms, "_harvest_text",
                        lambda found, text: (harvested.append(text), real(found, text)))
    both = frozenset({a, b})
    for _ in range(3):
        assert set(acronyms.harvest(allowed_document_ids=both)) == {"NDFT", "PWHT"}
        assert set(acronyms.harvest(a, allowed_document_ids=both)) == {"NDFT"}
        assert set(acronyms.harvest(allowed_document_ids=frozenset({b}))) == {"PWHT"}
    assert len(harvested) == 2, harvested


def test_a_document_outside_the_scope_contributes_nothing():
    a, b = _doc("docA"), _doc("docB")
    # ZQET is invented and not in the built-in list, so its only possible
    # source is document B: a caller who may read only A must get nothing.
    _chunk("ca", a, "The nominal dry film thickness (NDFT) is 250 um.")
    _chunk("cb", b, "The zinc quench exposure test (ZQET) applies.")
    acronyms.harvest(allowed_document_ids=frozenset({a, b}))       # both cached
    assert set(acronyms.harvest(allowed_document_ids=frozenset({a}))) == {"NDFT"}
    assert acronyms.equivalents("ZQET", allowed_document_ids=frozenset({a})) == []
    assert acronyms.equivalents("ZQET", allowed_document_ids=frozenset({a, b})) != []


def test_a_built_in_expansion_does_not_depend_on_which_documents_are_in_scope():
    """The built-in list is not document data: it expands a capitalised
    abbreviation the same for every caller, so it can leak nothing."""
    a = _doc("docA")
    _chunk("ca", a, "The nominal dry film thickness (NDFT) is 250 um.")
    assert acronyms.equivalents("PWHT", allowed_document_ids=frozenset({a})) == [
        "post weld heat treatment"]
    assert acronyms.equivalents("PWHT", allowed_document_ids=frozenset()) == [
        "post weld heat treatment"]


def test_a_rechunked_document_is_reharvested_without_a_manual_reset():
    a = _doc("docA")
    _chunk("ca", a, "The nominal dry film thickness (NDFT) is 250 um.")
    scope = frozenset({a})
    assert set(acronyms.harvest(allowed_document_ids=scope)) == {"NDFT"}
    _chunk("ca2", a, "The magnetic particle testing (MPT) applies.", ordinal=1)
    assert set(acronyms.harvest(allowed_document_ids=scope)) == {"NDFT", "MPT"}
    with db.connect() as conn:
        conn.execute("UPDATE chunks SET retrievable = 0 WHERE id = 'ca'")
    assert set(acronyms.harvest(allowed_document_ids=scope)) == {"MPT"}


def test_the_per_document_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(settings, "acronym_cache_documents", 2)
    ids = [_doc(f"d{i}") for i in range(4)]
    for i, doc_id in enumerate(ids):
        _chunk(f"c{i}", doc_id, "The nominal dry film thickness (NDFT) is 250 um.")
    acronyms.harvest(allowed_document_ids=frozenset(ids))
    assert len(acronyms._doc_cache) == 2


# ============================================================ 3. warm-up

def test_the_lifespan_starts_the_warmup_and_it_really_harvests(monkeypatch):
    """The old startup call raised TypeError into `except: pass`. Now the
    lifespan starts the warm-up, and its acronym step fills the cache."""
    from fastapi.testclient import TestClient

    from app import main

    a = _doc("docA")
    _chunk("ca", a, "The nominal dry film thickness (NDFT) is 250 um.")
    monkeypatch.setattr(settings, "startup_warmup", True)
    monkeypatch.setattr(settings, "watch_folder", "")
    monkeypatch.setattr(warmup, "STEPS", (("acronyms", warmup._acronyms),))
    with TestClient(main.app):
        deadline = time.time() + 30
        while "acronyms" not in warmup.status() and time.time() < deadline:
            time.sleep(0.05)
    assert warmup.status()["acronyms"]["ok"] is True, warmup.status()
    assert any(key[1] == a for key in acronyms._doc_cache)


def test_the_warmup_never_blocks_the_server_start(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main

    release = threading.Event()
    monkeypatch.setattr(settings, "startup_warmup", True)
    monkeypatch.setattr(settings, "watch_folder", "")
    monkeypatch.setattr(warmup, "STEPS", (("slow", lambda: release.wait(10)),))
    started = time.perf_counter()
    try:
        with TestClient(main.app) as client:
            entered = time.perf_counter() - started
            assert client.get("/api/health").status_code == 200
            assert "slow" not in warmup.status()        # still running
    finally:
        release.set()
    assert entered < 8, entered


def test_a_failing_warmup_step_is_logged_and_recorded_never_swallowed(caplog, monkeypatch):
    def broken():
        raise RuntimeError("model file missing")

    ran = []
    monkeypatch.setattr(settings, "startup_warmup", True)
    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        thread = warmup.start((("broken", broken), ("next", lambda: ran.append(1))))
        thread.join(10)
    status = warmup.status()
    assert status["broken"]["ok"] is False
    assert "model file missing" in status["broken"]["error"]
    assert ran == [1] and status["next"]["ok"] is True       # later steps still run
    assert any("warm-up step 'broken' failed" in r.getMessage() for r in caplog.records)


def test_the_warmup_never_writes_the_database(monkeypatch):
    """Every statement the warm-up thread issues, on its own connection."""
    a = _doc("docA")
    _chunk("ca", a, "The nominal dry film thickness (NDFT) is 250 um.")
    statements: list[str] = []
    real_connect = sqlite3.connect

    def traced(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(db.sqlite3, "connect", traced)
    monkeypatch.setattr(settings, "startup_warmup", True)
    thread = warmup.start((("acronyms", warmup._acronyms),))
    thread.join(30)
    assert warmup.status()["acronyms"]["ok"] is True
    assert statements, "the warm-up issued no SQL at all - the trace saw nothing"
    writes = [s for s in statements if re.match(
        r"\s*(INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP)", s, re.I)]
    assert writes == [], writes[:5]


# ============================================================ 5. embedder

def test_the_embedder_config_reads_its_settings(monkeypatch):
    from app.embedder import EmbedderConfig

    monkeypatch.setattr(settings, "embed_batch_size", 5)
    monkeypatch.setattr(settings, "embed_threads", 3)
    monkeypatch.setattr(settings, "onnx_cpu_arena_embed", True)
    config = EmbedderConfig()
    assert (config.batch_size, config.intra_op_threads, config.cpu_arena) == (5, 3, True)


def test_embed_threads_zero_means_half_the_logical_cores(monkeypatch):
    import os

    monkeypatch.setattr(settings, "embed_threads", 0)
    monkeypatch.setattr(os, "cpu_count", lambda: 12)
    assert settings.embed_intra_op_threads() == 6
    monkeypatch.setattr(os, "cpu_count", lambda: 1)
    assert settings.embed_intra_op_threads() == 1


def test_the_embedders_arena_is_off_by_default_and_the_rerankers_is_not():
    fresh = Settings()
    assert fresh.onnx_cpu_arena_embed is False
    assert fresh.onnx_cpu_arena_rerank is True
    assert fresh.embed_batch_size == 16


def test_the_session_is_built_with_the_configured_threads_arena_and_batch(monkeypatch):
    from app.embedder import Embedder, EmbedderConfig

    monkeypatch.setattr(settings, "onnx_cpu_arena_embed", False)
    monkeypatch.setattr(settings, "embed_threads", 1)
    monkeypatch.setattr(settings, "embed_batch_size", 3)
    embedder = Embedder(EmbedderConfig())
    options = embedder.session.get_session_options()
    assert options.enable_cpu_mem_arena is False
    assert options.intra_op_num_threads == 1

    sizes: list[int] = []
    real = embedder._forward
    monkeypatch.setattr(embedder, "_forward", lambda texts: (sizes.append(len(texts)), real(texts))[1])
    embedder.embed_passages([f"passage number {i}" for i in range(7)])
    assert sorted(sizes, reverse=True) == [3, 3, 1]


# ============================================================ 7. Ollama

def _capture_posts(monkeypatch):
    import httpx

    seen: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "{}", "done_reason": "stop", "model": "m"}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None):
            seen.append(json)
            return FakeResponse()

    monkeypatch.setattr(settings, "ollama_url", "http://127.0.0.1:11434")
    monkeypatch.setattr(httpx, "Client", FakeClient)
    return seen


def _runner(body: dict) -> tuple:
    options = body["options"]
    return (options["num_ctx"], options["num_thread"], options["num_batch"],
            body["keep_alive"])


def test_every_ollama_caller_asks_for_the_same_runner(monkeypatch):
    """Item 7: differing runner options made Ollama reload the model between
    features. The provider path sent no keep_alive and no thread/batch."""
    from app import analysis, chat_model
    from app.reasoning_provider import OllamaProvider, Packet

    monkeypatch.setattr(settings, "ollama_keep_alive", "45m")
    seen = _capture_posts(monkeypatch)
    OllamaProvider().reason(Packet(prompt="q", num_ctx=4096, num_predict=10))
    chat_model.generate("system", "prompt", temperature=0.0, preference="ollama")
    analysis.ollama_generate("system", "prompt")
    comparison._ask_model_once(
        {"requirement_text": "noise shall not exceed 90 dB(A)", "id": "r"},
        [{"field_name": "Noise level", "id": "f"}])
    assert len(seen) == 4
    expected = (settings.num_ctx, settings.num_thread, settings.num_batch, "45m")
    assert [_runner(b) for b in seen] == [expected] * 4


def test_a_larger_context_is_kept_and_a_smaller_one_raised(monkeypatch):
    from app.reasoning_provider import OllamaProvider, Packet

    seen = _capture_posts(monkeypatch)
    OllamaProvider().reason(Packet(prompt="q", num_ctx=16384, num_predict=10))
    OllamaProvider().reason(Packet(prompt="q", num_ctx=1024, num_predict=10))
    assert [b["options"]["num_ctx"] for b in seen] == [16384, settings.num_ctx]


def test_the_streamed_path_sends_the_same_runner_options(monkeypatch):
    from app import model_transport

    captured: dict = {}

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            return iter(['{"response": "ok", "done": true}'])

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def stream(self, method, url, json=None, extensions=None):
            captured["body"] = json
            return FakeStream()

        def close(self):
            pass

    import httpx

    monkeypatch.setattr(settings, "ollama_url", "http://127.0.0.1:11434")
    monkeypatch.setattr(httpx, "Client", FakeClient)
    list(model_transport.stream_json("/api/generate",
                                     {"model": "m", "prompt": "p", "options": {"num_ctx": 2048}},
                                     timeout=5))
    assert _runner(captured["body"]) == (settings.num_ctx, settings.num_thread,
                                         settings.num_batch, settings.ollama_keep_alive)


# ======================================================== 8. test markers

def test_the_benchmark_is_deselected_locally_and_run_by_ci():
    """Not reduced silently: deselected from a plain run, run by CI."""
    ini = (REPO / "backend" / "pytest.ini").read_text(encoding="utf-8")
    assert re.search(r'addopts\s*=.*not benchmark', ini)
    workflow = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert re.search(r"run:\s*python -m pytest[^\n]*-m benchmark", workflow), \
        "CI no longer runs the benchmarks the default run deselects"
    source = (REPO / "backend" / "tests" / "test_b6_core_retrieval.py").read_text(encoding="utf-8")
    assert "@pytest.mark.benchmark\ndef test_recall_mrr_precision_and_latency_are_measured" in source
