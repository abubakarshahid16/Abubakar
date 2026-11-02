"""#1584: the standards compiler. Invented standard text only; the Batch API is a fake that holds what it was sent,
answers in any order and computes usage from the request body the way the real cache does. No real Claude call."""

from __future__ import annotations

import hashlib
import json
import os
import random
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import (
    claude_approved,
    claude_batch_run,
    claude_spend,
    comparison,
    compiled_rule_proof,
    converter_gates,
    db,
    numparse,
    standards,
    standards_compiler,
    standards_converter,
    submittal_review,
)
from app.config import settings
from app.reasoning_provider import ClaudeProvider, Packet, ProviderRefused
from tests.test_chat_pr1_model_lane import KEY

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import compile_standards

NOW = "2026-11-02T00:00:00Z"
DOC = "std-zz"
LABEL = "SAES-Z-900"
MODEL = "claude-sonnet-5-5"
ANSWERED = "claude-sonnet-5-5-20261001"
QUOTE = "The relief flange pressure shall not exceed 25 bar for gas service."
PAGE_1 = f"Invented standard for testing only.\n4.1 Flanges\n{QUOTE}\nThe widget shall be painted."
PAGE_2 = "4.2 Bolts\nThe invented bolt torque shall be at least 40 Nm."


@pytest.fixture(autouse=True)
def lane(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "copy.sqlite")
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "standards_compiler_enabled", True)
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", KEY)
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    for name in (
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _document(
    doc_id=DOC,
    number=LABEL,
    pages=(PAGE_1, PAGE_2),
    listed=True,
    role="COMPANY_STANDARD",
):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,?,'ready',?,?)",
            (
                doc_id,
                f"{doc_id}.pdf",
                f"sha-{doc_id}",
                f"{doc_id}.pdf",
                len(pages),
                NOW,
            ),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id,suggested_by,document_role,document_number)"
            " VALUES (?,?,?,?)",
            (doc_id, "test", role, number),
        )
        for n, text in enumerate(pages, 1):
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,batch_no) VALUES (?,?,?,?,0)",
                (doc_id, n, text, len(text)),
            )
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,text,"
            "token_count,content_hash,retrievable) VALUES (?,?,?,0,1,1,NULL,'prose','x',1,?,1)",
            (f"c-{doc_id}", doc_id, "f.pdf", f"h-{doc_id}"),
        )
    if listed:
        _list(doc_id)
    return doc_id


def _list(*doc_ids):
    path = claude_approved.list_path()
    rows = json.loads(path.read_text())["documents"] if path.exists() else []
    rows += [
        {"sha256": f"sha-{d}", "document_id": d, "status": "approved"} for d in doc_ids
    ]
    path.write_text(json.dumps({"documents": rows}))


def _rule(**over):
    rule = {
        "applies_to": "relief flanges",
        "condition": "for gas service",
        "field": "flange pressure",
        "comparator": "<=",
        "limit": "25",
        "unit": "bar",
        "clause": "4.1",
        "page": 1,
        "quote": QUOTE,
    }
    return {**rule, **over}


class FakeBatches:
    normal_output = 50
    hold_open = False  # retrieve says in_progress until cancelled
    cancel_fails = False
    cancelled = ()  # batch ids cancelled
    done_before_cancel = ()  # custom ids the batch finished before its cancel
    never_ends = False

    """The three calls of `reader_transport`, with a cache that behaves like the API's: a system block marked for
    caching is written the first time and read after; unmarked text is plain input. Tokens are characters/4."""

    def __init__(
        self,
        rules=None,
        *,
        crash_first_retrieve=False,
        kinds=None,
        stop="end_turn",
        seed=7,
    ):
        self.rules = rules if rules is not None else [_rule()]
        self.created = []
        self.retrieves = 0
        self.crash_first_retrieve = crash_first_retrieve
        self.kinds = kinds or {}
        self.stop = stop
        self.seed = seed
        self.seen_prefixes = set()
        self.normal = []
        self.missing_once = set()

    def batch_create(self, url, *, headers, requests):
        self.created.append(requests)
        return {
            "id": f"msgbatch_{len(self.created)}",
            "processing_status": "in_progress",
        }

    def batch_retrieve(self, url, batch_id, *, headers):
        self.retrieves += 1
        if self.crash_first_retrieve and self.retrieves == 1:
            raise KeyboardInterrupt("the machine went down")
        running = (self.hold_open and batch_id not in self.cancelled) or self.never_ends
        return {
            "id": batch_id,
            "processing_status": "in_progress" if running else "ended",
            "results_url": f"https://x/results/{batch_id}",
        }

    def batch_cancel(self, url, batch_id, *, headers):
        if self.cancel_fails:
            raise RuntimeError("cancel failed")
        self.cancelled = (*self.cancelled, batch_id)
        return {"id": batch_id, "processing_status": "canceling"}

    def send(self, url, *, headers, body, timeout):
        self.normal.append(body)
        return {
            "model": ANSWERED,
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": self.normal_output},
            "content": [{"type": "text", "text": self._answer_for(body)}],
        }

    def _usage(self, params):
        usage = {"input_tokens": 0, "output_tokens": 50}
        for block in params.get("system") or []:
            tokens = len(block["text"]) // 4
            if "cache_control" not in block:
                usage["input_tokens"] += tokens
            elif block["text"] in self.seen_prefixes:
                usage["cache_read_input_tokens"] = tokens
            else:
                self.seen_prefixes.add(block["text"])
                usage["cache_creation_input_tokens"] = tokens
        usage["input_tokens"] += len(json.dumps(params["messages"])) // 4
        return usage

    def _answer_for(self, params):
        text = json.dumps(params["messages"])
        rules = [r for r in self.rules if f"[page {r['page']} " in text]
        return json.dumps({"rules": rules})

    def batch_results(self, url, *, headers):
        batch_id = url.rsplit("/", 1)[-1]
        n = int(batch_id.rsplit("_", 1)[-1])
        rows = []
        for request in self.created[n - 1]:
            cid, params = request["custom_id"], request["params"]
            if cid in self.missing_once:
                continue
            kinds = self.kinds.get(cid) or self.kinds.get("*") or []
            kind = kinds.pop(0) if kinds else "succeeded"
            if batch_id in self.cancelled and cid not in self.done_before_cancel:
                kind = "canceled"
            if kind == "missing":
                continue
            result = {"type": kind}
            if kind == "succeeded":
                result["message"] = {
                    "model": ANSWERED,
                    "stop_reason": self.stop,
                    "usage": self._usage(params),
                    "content": [{"type": "text", "text": self._answer_for(params)}],
                }
            rows.append({"custom_id": cid, "result": result})
        random.Random(self.seed).shuffle(rows)
        return rows


def _compile(client, **kw):
    kw.setdefault("sleep", lambda _s: None)
    return standards_compiler.compile_standard(
        db.connect(), DOC, LABEL, client=client, **kw
    )


def _rules():
    return [
        dict(r)
        for r in db.connect().execute(
            "SELECT * FROM compiled_rules ORDER BY page, field"
        )
    ]


def _drop_reason(rule):
    _document()
    report = _compile(FakeBatches([rule]))
    assert _rules() == []
    return report["dropped"]


# ---------------------------------------------------------------------------------- quotes and values


def test_a_verified_rule_is_stored_held_as_version_2_with_its_provenance():
    _document()
    report = _compile(FakeBatches())
    assert (
        report["status"] == "all_pages_answered"
        and report["kept"] == 1
        and report["held_until_approved"] == 1
    )
    rule = _rules()[0]
    assert (rule["status"], rule["rule_version"], rule["standard"]) == (
        "held",
        2,
        LABEL,
    )
    assert (rule["limit_value"], rule["unit"], rule["unit_dimension"]) == (
        25.0,
        "bar",
        "pressure",
    )
    assert (rule["clause"], rule["page"], rule["quote"]) == ("4.1", 1, QUOTE)
    assert rule["approved_by"] is None


def test_a_rule_names_the_model_that_answered_the_prompt_version_and_the_batch():
    _document()
    _compile(FakeBatches())
    rule = _rules()[0]
    assert rule["model"] == ANSWERED  # what the API reported, never the name asked for
    assert rule["model"] != MODEL
    assert rule["prompt_version"] == standards_compiler.PROMPT_VERSION
    assert rule["batch_id"] == "msgbatch_1"


def test_a_quote_not_on_the_cited_page_is_dropped_and_counted():
    assert _drop_reason(
        _rule(quote="The relief flange pressure shall not exceed 26 bar.")
    ) == {"quote_not_on_page": 1}


def test_a_true_quote_cited_to_the_wrong_page_is_dropped():
    assert _drop_reason(_rule(page=2)) == {"quote_not_on_page": 1}


def test_a_quote_on_a_page_of_another_chunk_is_dropped():
    pages = {1: PAGE_1, 2: PAGE_2}
    chunk = standards_compiler.Chunk("c", "x", pages={2}, clauses={2: {"4.2"}})
    assert standards_compiler.verify(_rule(), chunk, pages) == (None, "page_not_sent")


def test_a_limit_outside_the_quote_is_dropped():
    assert _drop_reason(_rule(limit="26")) == {"limit_not_in_quote": 1}


def test_a_limit_inside_a_longer_number_is_not_in_the_quote():
    assert _drop_reason(_rule(limit="5")) == {"limit_not_in_quote": 1}


def test_a_unit_outside_the_quote_is_dropped():
    assert _drop_reason(_rule(unit="psi")) == {"unit_not_in_quote": 1}


def test_a_unit_left_out_of_a_quote_that_prints_one_is_dropped():
    assert _drop_reason(_rule(unit=None)) == {"unit_left_out": 1}


def test_a_comparator_the_quote_does_not_say_is_dropped():
    assert _drop_reason(_rule(comparator=">=")) == {"comparator_not_in_quote": 1}


def test_a_field_not_in_the_quote_is_dropped():
    assert _drop_reason(_rule(field="vane speed")) == {"field_not_in_quote": 1}


def test_a_clause_not_on_the_page_is_dropped():
    assert _drop_reason(_rule(clause="9.9.9")) == {"clause_not_nearest": 1}


def test_a_scope_after_the_limit_is_kept_as_the_condition():
    _document()
    _compile(FakeBatches())
    assert _rules()[0]["condition_text"] == "for gas service"


def test_a_requirement_with_no_number_is_kept_with_no_limit():
    _document()
    words = "The widget shall be painted."
    _compile(
        FakeBatches(
            [
                _rule(
                    condition=None,
                    quote=words,
                    field="widget",
                    limit=None,
                    unit=None,
                    comparator=None,
                )
            ]
        )
    )
    rule = _rules()[0]
    assert (
        rule["quote"] == words
        and rule["limit_text"] is None
        and rule["comparator"] is None
    )


def test_the_standard_is_written_by_code_not_the_answer():
    _document()
    _compile(FakeBatches([_rule(standard="SAES-A-000")]))
    assert _rules()[0]["standard"] == LABEL


def test_a_cut_answer_leaves_the_standard_partial_and_the_rerun_reads_it_again():
    _document()
    fake = FakeBatches(stop="max_tokens")
    report = _compile(fake)
    assert report["status"] == "partial" and report["kept"] == 0
    assert report["pages_not_read"] == [1, 2] and len(report["chunks_truncated"]) == 1
    assert len(fake.created) == 1  # not re-bought inside the run
    fake.stop = "end_turn"
    again = _compile(fake)
    assert (
        again["status"] == "all_pages_answered"
        and again["pages_not_read"] == []
        and len(fake.created) == 2
    )


# ----------------------------------------------------------------------------------- versions


def test_version_1_is_untouched_and_the_verdict_table_never_sees_a_compiled_rule():
    _document()
    made = standards.create_requirement(
        standard_document_id=DOC,
        chunk_id=f"c-{DOC}",
        requirement_text=QUOTE,
        source_text=QUOTE,
        clause="4.1",
        page=1,
        structured={"requirement_type": "statement"},
    )

    def v1():
        return [
            dict(r)
            for r in db.connect().execute(
                "SELECT * FROM standard_requirements ORDER BY id"
            )
        ]

    before = v1()
    _compile(FakeBatches())
    assert (
        v1() == before
        and before[0]["id"] == made["id"]
        and before[0]["superseded_at"] is None
    )
    assert len(_rules()) == 1


def test_no_module_that_decides_a_verdict_reads_the_compiled_rules():
    app = Path(comparison.__file__).parent
    readers = [
        p.name
        for p in app.rglob("*.py")
        if "compiled_rules" in p.read_text(encoding="utf-8")
    ]
    assert set(readers) == {"compiled_rule_report.py", "standards_compiler.py"}


def _review_run(run_id="run-1", outcome="{}"):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, outcome_json)"
            " VALUES (?,?,'completed',?,?,?)",
            (run_id, DOC, NOW, NOW, outcome),
        )


def test_a_run_records_the_rule_version_it_used_and_the_held_rules_it_did_not():
    _document()
    _compile(FakeBatches())
    _review_run()
    standards_compiler.record_rule_version("run-1")
    row = (
        db.connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id='run-1'")
        .fetchone()
    )
    recorded = json.loads(row["outcome_json"])["rule_version"]
    assert (
        recorded["used"] == 1
        and recorded["compiled_rules_held_not_used"] == 1
        and recorded["boundary"]
    )


def test_a_finished_run_records_its_rule_version_through_the_comparison_step():
    _document()
    _review_run()
    comparison._store_run_outcome(
        "run-1", {"code": comparison.CODE_MANUAL, "reason": "r"}, {"completeness": 0.1}
    )
    row = (
        db.connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id='run-1'")
        .fetchone()
    )
    assert json.loads(row["outcome_json"])["rule_version"]["used"] == 1


def test_switch_off_a_finished_run_has_no_rule_version_key(monkeypatch):
    _document()
    _review_run()
    monkeypatch.setattr(settings, "standards_compiler_enabled", False)
    comparison._store_run_outcome(
        "run-1", {"code": comparison.CODE_MANUAL, "reason": "r"}, {"completeness": 0.1}
    )
    row = (
        db.connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id='run-1'")
        .fetchone()
    )
    assert "rule_version" not in json.loads(row["outcome_json"])


# ------------------------------------------------------------------------------------------- once


def test_a_second_compile_is_skipped_with_a_count_and_sends_nothing():
    _document()
    fake = FakeBatches()
    _compile(fake)
    report = _compile(fake)
    assert (
        report["status"] == "skipped"
        and report["skipped"] == 1
        and len(fake.created) == 1
    )
    assert len(_rules()) == 1


def test_a_changed_text_is_compiled_again_and_the_old_rules_stay():
    _document()
    fake = FakeBatches()
    _compile(fake)
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET text = text || ' Added line.' WHERE document_id = ? AND page_no = 2",
            (DOC,),
        )
    assert _compile(fake)["status"] == "all_pages_answered"
    assert len(fake.created) == 2 and len(_rules()) == 2


# ------------------------------------------------------------------------------------------ batch


def test_results_out_of_order_land_on_their_own_chunk():
    pages = tuple(
        f"{n}.1 Part\nThe invented part{n} pressure shall not exceed {n}0 bar.\n"
        + "padding line\n" * 1200
        for n in range(1, 7)
    )
    _document(pages=pages)
    rules = [
        _rule(
            condition=None,
            page=n,
            clause=f"{n}.1",
            field=f"part{n} pressure",
            limit=f"{n}0",
            quote=f"The invented part{n} pressure shall not exceed {n}0 bar.",
        )
        for n in range(1, 7)
    ]
    report = _compile(FakeBatches(rules, seed=3))
    assert report["chunks"] > 1 and report["kept"] == 6
    assert {(r["page"], r["limit_value"]) for r in _rules()} == {
        (n, n * 10.0) for n in range(1, 7)
    }


def test_batch_results_are_charged_at_half_price():
    _document()
    _compile(FakeBatches())
    lines = [e for e in claude_spend.entries() if e.get("settles")]
    assert lines and all(e["batch"] for e in lines)
    usage = {
        k: lines[0][k]
        for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens")
    }
    assert lines[0]["cost_usd"] == pytest.approx(
        round(claude_spend.cost_usd(ANSWERED, usage, batch=True), 6)
    )


def test_a_crash_while_waiting_resumes_the_same_batch_and_pays_once():
    _document()
    fake = FakeBatches(crash_first_retrieve=True)
    with pytest.raises(KeyboardInterrupt):
        _compile(fake)
    open_lines = [e for e in claude_spend.entries() if e.get("reserved")]
    assert (
        len(open_lines) == 1
    )  # still counted at its worst case while the machine is down
    report = _compile(fake)
    assert (
        report["status"] == "all_pages_answered"
        and report["resumed_batches"] == 1
        and report["kept"] == 1
    )
    assert len(fake.created) == 1
    lines = [
        e
        for e in claude_spend.entries()
        if e.get("step") == standards_converter.step_for(LABEL)
    ]
    assert len(lines) == 1 and lines[0]["settles"] == open_lines[0]["reservation"]


def test_a_crash_inside_create_is_not_sent_again_unless_the_operator_says_so():
    _document()
    fake = FakeBatches()

    def dies(url, *, headers, requests):
        fake.created.append(requests)
        raise KeyboardInterrupt("the machine went down")

    real, fake.batch_create = fake.batch_create, dies
    with pytest.raises(KeyboardInterrupt):
        _compile(fake)
    fake.batch_create = real
    held = claude_spend.spent(standards_converter.step_for(LABEL))
    report = _compile(fake)
    assert report["status"] == "unconfirmed" and len(fake.created) == 1
    assert claude_spend.spent(standards_converter.step_for(LABEL)) == held > 0
    assert (
        _compile(fake, resend_unconfirmed=True)["status"] == "all_pages_answered"
        and len(fake.created) == 2
    )


@pytest.mark.parametrize("kind", ["errored", "expired", "canceled"])
def test_a_failed_request_is_released_and_re_queued_once_then_answered(kind):
    _document()
    fake = FakeBatches(kinds={"*": [kind]})
    report = _compile(fake)
    assert len(fake.created) == 2 and report["requeued_once"] == 1
    assert (
        report["failures_by_kind"] == {kind: 1}
        and report["gave_up"] == []
        and report["kept"] == 1
    )
    assert (
        sum(1 for e in claude_spend.entries() if e.get("settles")) == 1
    )  # the failed send cost nothing


def test_a_request_that_fails_twice_is_listed_counted_and_its_pages_named():
    _document()
    fake = FakeBatches(kinds={"*": ["expired", "errored"]})
    report = _compile(fake)
    assert (
        len(fake.created) == 2 and len(report["gave_up"]) == 1 and report["kept"] == 0
    )
    assert report["pages_not_read"] == [1, 2] and report["status"] == "partial"
    assert claude_spend.spent(standards_converter.step_for(LABEL)) == 0.0


def test_a_request_with_no_result_row_is_charged_its_worst_case_not_free():
    _document()
    fake = FakeBatches(kinds={"*": ["missing", "missing"]})
    report = _compile(fake)
    assert report["failures_by_kind"] == {claude_batch_run.NO_RESULT: 1}
    assert claude_spend.spent(standards_converter.step_for(LABEL)) > 0


def test_an_answer_in_the_response_cache_is_not_sent_again():
    _document()
    _compile(FakeBatches())
    with db.connect() as conn:
        conn.execute("DELETE FROM compiled_rules")
        conn.execute("DELETE FROM compile_runs")
        conn.execute("DELETE FROM claude_batch_requests")
        conn.execute("DELETE FROM claude_batches")
    fake = FakeBatches()
    report = _compile(fake)
    assert (
        fake.created == []
        and report["from_response_cache"] == 1
        and report["kept"] == 1
    )
    assert (
        _rules()[0]["batch_id"] == claude_batch_run.FROM_CACHE
        and _rules()[0]["model"] == ANSWERED
    )


# ------------------------------------------------------------------------------------- the cache


def _many_pages(n=4):
    return tuple(
        f"{i}.1 Part\nThe invented part{i} line.\n" + "padding line\n" * 1200
        for i in range(1, n + 1)
    )


def test_stable_text_sits_before_the_breakpoint_and_later_requests_read_it():
    _document(pages=_many_pages())
    fake = FakeBatches([])
    report = _compile(fake)
    requests = fake.created[0]
    assert len(requests) > 2
    systems = {json.dumps(r["params"]["system"]) for r in requests}
    assert len(systems) == 1  # the same bytes, or the cache never hits
    block = requests[0]["params"]["system"][0]
    assert block["cache_control"] == {"type": "ephemeral"}
    assert "padding" in block["text"] and "THE PAGES TO COMPILE" not in block["text"]
    assert all(
        "THE PAGES TO COMPILE" in json.dumps(r["params"]["messages"]) for r in requests
    )
    tokens = len(block["text"]) // 4
    assert report["cache_write_tokens"] == tokens
    assert report["cache_read_tokens"] == tokens * (len(requests) - 1)


def test_one_chunk_is_not_marked_for_the_cache_it_could_never_read():
    _document(
        pages=("4.1 Long\n" + "padding line\n" * 300,)
    )  # over the minimum, one request
    fake = FakeBatches([])
    report = _compile(fake)
    assert report["chunks"] == 1
    assert "cache_control" not in fake.created[0][0]["params"]["system"][0]
    assert report["cache_write_tokens"] == 0


def test_only_this_standards_pages_are_sent():
    _document(pages=(PAGE_1,))
    _document(
        "std-other",
        "SAES-Z-901",
        pages=("9.1 Other\nOTHERSTANDARDWORD shall not exceed 1 bar.",),
    )
    fake = FakeBatches()
    _compile(fake)
    assert "OTHERSTANDARDWORD" not in json.dumps(fake.created)


def test_every_page_with_text_is_in_exactly_one_chunk_and_keeps_clause_and_page():
    pages = {
        1: "4.1 One\nfirst words\n4.2 Two\nsecond words",
        2: "third words",
        3: "   ",
    }
    readable = {n: t for n, t in pages.items() if t.strip()}
    chunks = standards_compiler.chunks_of(readable)
    joined = "\n".join(c.text for c in chunks)
    for words in ("first words", "second words", "third words"):
        assert joined.count(words) == 1
    assert "[page 1 | clause 4.2]" in joined and "[page 2 | clause 4.2]" in joined
    assert chunks[0].clauses[2] == {"4.2"}  # the clause runs on over the page


def test_a_long_clause_is_cut_at_line_ends_and_nothing_is_lost():
    lines = [f"line number {i}" for i in range(3000)]
    chunks = standards_compiler.chunks_of({1: "\n".join(lines)})
    assert len(chunks) > 1
    joined = "\n".join(c.text for c in chunks)
    assert all(line in joined for line in lines)
    assert all(len(c.text) < standards_compiler.CHUNK_CHARS + 200 for c in chunks)


def test_custom_ids_are_stable_for_a_text_and_valid_for_the_api():
    first = standards_compiler.chunks_of({1: PAGE_1, 2: PAGE_2})
    again = standards_compiler.chunks_of({1: PAGE_1, 2: PAGE_2})
    assert [c.custom_id for c in first] == [c.custom_id for c in again]
    assert all(
        c.custom_id.replace("-", "").isalnum() and len(c.custom_id) <= 64 for c in first
    )


def test_the_request_carries_nothing_the_model_answers_400_to():
    _document()
    fake = FakeBatches()
    _compile(fake)
    params = fake.created[0][0]["params"]
    assert params["model"] == MODEL and "temperature" not in params
    assert "thinking" not in params and "stream" not in params
    assert params["max_tokens"] == standards_compiler.MAX_OUTPUT_TOKENS


# ------------------------------------------------------------------------------------------ budget


def test_the_estimate_is_shown_before_anything_is_sent():
    _document()
    order = []
    fake = FakeBatches()
    create = fake.batch_create

    def spy(url, *, headers, requests):
        order.append("sent")
        return create(url, headers=headers, requests=requests)

    fake.batch_create = spy
    _compile(
        fake,
        on_estimate=lambda e: order.append(("estimate", e["worst_usd"], e["requests"])),
    )
    assert (
        order[0][0] == "estimate"
        and order[0][1] > 0
        and order[0][2] == 1
        and order[1] == "sent"
    )


def test_estimate_only_sends_nothing_and_stores_nothing():
    _document()
    fake = FakeBatches()
    report = _compile(fake, estimate_only=True)
    assert report["status"] == "estimate" and report["estimate"]["worst_usd"] > 0
    assert fake.created == [] and _rules() == []


def test_max_usd_refuses_before_anything_is_sent_or_held():
    _document()
    fake = FakeBatches()
    with pytest.raises(standards_compiler.TooDear):
        _compile(fake, max_usd=0.0001)
    assert fake.created == [] and claude_spend.entries() == []


def test_max_usd_counts_what_was_already_spent_today():
    _document()
    worst = standards_compiler.estimate(
        MODEL,
        standards_compiler.packets_of(
            LABEL,
            {1: PAGE_1, 2: PAGE_2},
            standards_compiler.chunks_of({1: PAGE_1, 2: PAGE_2}),
        ),
    )["worst_usd"]
    claude_spend.record(
        step=standards_converter.step_for("SAES-A-1"),
        model=MODEL,
        usage=None,
        prompt_sha256="",
        wall_time_s=0.0,
        finish_reason="x",
        estimated_usd=1.0,
    )
    fake = FakeBatches()
    with pytest.raises(standards_compiler.TooDear):
        _compile(fake, max_usd=1.0 + worst / 2)
    assert fake.created == []


def test_the_daily_default_is_the_owners_100():
    assert (
        type(settings).model_fields["standards_compiler_max_usd_per_day"].default
        == 100.0
    )


def test_the_per_standard_cap_refuses_the_whole_batch(monkeypatch):
    _document()
    monkeypatch.setattr(settings, "claude_budget_usd_per_standard", 0.0001)
    fake = FakeBatches()
    with pytest.raises(claude_spend.BudgetExceeded):
        _compile(fake)
    assert fake.created == []


def test_the_total_cap_refuses(monkeypatch):
    _document()
    monkeypatch.setattr(settings, "claude_budget_usd_total", 0.0001)
    fake = FakeBatches()
    with pytest.raises(claude_spend.BudgetExceeded):
        _compile(fake)
    assert fake.created == []


def _big_pages(count, chars=8000):
    line = "invented filler words of a page line\n"
    return tuple(
        f"{n}.1 Part\n" + line * (chars // len(line)) for n in range(1, count + 1)
    )


def _worst_of(pages):
    numbered = dict(enumerate(pages, 1))
    chunks = standards_compiler.chunks_of(numbered)
    return standards_compiler.estimate(
        MODEL, standards_compiler.packets_of(LABEL, numbered, chunks)
    )["worst_usd"]


def test_the_compile_is_charged_per_standard_so_the_usd_5_step_cap_does_not_stop_it():
    pages = _big_pages(120)
    assert 5.0 < _worst_of(pages) < 25.0  # the set this test is about
    assert settings.claude_budget_usd_per_step == 5.0
    assert settings.claude_budget_usd_per_standard == 25.0
    _document(pages=pages)
    fake = FakeBatches([])
    report = _compile(fake)
    assert report["status"] == "all_pages_answered" and len(fake.created) == 1
    assert report["chunks"] == len(fake.created[0])
    steps = {e["step"] for e in claude_spend.entries()}
    assert steps == {claude_spend.STANDARD_STEP_PREFIX + LABEL}


def test_a_set_over_the_usd_25_cap_stops_at_the_cap_and_reports_partial():
    pages = _big_pages(420)
    pages = (PAGE_1, *pages)
    assert _worst_of(pages) > 25.0
    _document(pages=pages)
    fake = FakeBatches()
    report = _compile(fake)
    assert report["status"] == "partial" and report["stopped_at_cap"] is True
    sent = len(fake.created[0])
    assert (
        0 < sent < report["chunks"]
        and report["chunks_not_sent"] == report["chunks"] - sent
    )
    assert report["pages_not_read"] and report["pages_not_read"][-1] == len(pages)
    assert claude_spend.spent(claude_spend.STANDARD_STEP_PREFIX + LABEL) <= 25.0
    assert len(_rules()) == 1  # what was verified is kept, held


def test_a_partial_compile_is_not_skipped_and_the_next_run_pays_only_for_the_rest():
    pages = (PAGE_1, *_big_pages(420))
    _document(pages=pages)
    fake = FakeBatches()
    first = _compile(fake)
    assert first["status"] == "partial"
    second = _compile(fake)  # what the first send actually cost is freed, so more fits
    sent_twice = {r["custom_id"] for r in fake.created[0]} & {
        r["custom_id"] for r in fake.created[1]
    }
    assert sent_twice == set() and second.get("skipped") is None
    assert second["status"] in ("partial", "all_pages_answered")
    assert len(_rules()) == 1  # replaced, not doubled


def test_the_estimate_says_when_a_standard_is_over_its_cap():
    pages = _big_pages(420)
    _document(pages=pages)
    report = _compile(FakeBatches(), estimate_only=True)
    assert report["estimate"]["over_per_standard_cap"] is True
    assert report["estimate"]["per_standard_cap_usd"] == 25.0


def test_the_script_exit_says_a_compile_is_partial(monkeypatch):
    monkeypatch.setattr(settings, "claude_budget_usd_per_standard", 0.2)
    _document(pages=_big_pages(20))
    said = []
    code = compile_standards.run(
        _copy_db(),
        [LABEL],
        client=FakeBatches([]),
        sleep=lambda _s: None,
        emit=said.append,
        note=lambda _s: None,
    )
    assert code == compile_standards.EXIT_PARTIAL
    assert json.loads(said[0])["standards"][0]["status"] == "partial"


def test_a_requeue_is_checked_against_the_budget_again():
    _document()
    fake = FakeBatches(kinds={"*": ["expired"]})
    rooms = iter([1.0, 0.0])
    packets = {
        "a": Packet(
            prompt="invented",
            num_ctx=0,
            num_predict=10,
            step="standards_convert:SAES-Z-900",
        )
    }
    with claude_approved.carrying(()):
        out = claude_batch_run.run(
            db.connect(),
            ClaudeProvider(MODEL),
            "job",
            packets,
            client=fake,
            room=lambda _step: (next(rooms), 1e9),
            sleep=lambda _s: None,
        )
    assert len(fake.created) == 1 and out.over_budget == ["a"]


# ------------------------------------------------------------------------------------------- gates


def test_an_unlisted_standard_is_refused_even_with_enforcement_off():
    _document(listed=False)
    assert (
        settings.claude_approved_list_enforced is False
    )  # the suite's setting (env_isolation)
    fake = FakeBatches()
    with pytest.raises(claude_spend.DocumentNotApproved):
        _compile(fake)
    assert fake.created == [] and claude_spend.entries() == []


def test_the_budget_gate_asks_the_list_for_exactly_this_standard(monkeypatch):
    _document()
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    seen = []
    real = claude_approved.refusal

    def spy():
        seen.append(claude_approved.carried())
        return real()

    monkeypatch.setattr(claude_approved, "refusal", spy)
    _compile(FakeBatches())
    assert seen and all(s == frozenset({DOC}) for s in seen)


def test_a_document_that_is_not_a_standard_is_refused():
    _document(role="SUBMITTAL")
    with pytest.raises(standards_converter.NotStandardsText):
        _compile(FakeBatches())


@pytest.mark.parametrize("number", ["API 000", "ASME Z0.0"])
def test_api_and_asme_compile_by_default_on_the_owners_decision_of_1584(number):
    _document("std-held", number, pages=(PAGE_1,))
    fake = FakeBatches()
    report = standards_compiler.compile_standard(
        db.connect(), "std-held", number, client=fake, sleep=lambda _s: None
    )
    assert report["status"] == "all_pages_answered" and len(fake.created) == 1


def test_the_family_setting_can_narrow_it(monkeypatch):
    monkeypatch.setattr(settings, "standards_compiler_families", "SAES,ISO")
    _document("std-api", "API 000", pages=(PAGE_1,))
    fake = FakeBatches()
    with pytest.raises(standards_converter.FamilyNotAllowed):
        standards_compiler.compile_standard(
            db.connect(), "std-api", "API 000", client=fake
        )
    assert fake.created == []


def test_a_family_not_named_is_refused():
    _document("std-xx", "XYZ 000", pages=(PAGE_1,))
    fake = FakeBatches()
    with pytest.raises(standards_converter.FamilyNotAllowed):
        standards_compiler.compile_standard(
            db.connect(), "std-xx", "XYZ 000", client=fake
        )
    assert fake.created == []


def test_the_old_converter_keeps_its_own_family_hold():
    with pytest.raises(standards_converter.FamilyNotAllowed):
        standards_converter.require_family("API 000")


def test_egress_off_refuses(monkeypatch):
    _document()
    monkeypatch.setattr(settings, "standards_reader_enabled", False)
    fake = FakeBatches()
    with pytest.raises(ProviderRefused):
        _compile(fake)
    assert fake.created == [] and claude_spend.entries() == []


def test_a_failed_create_is_released_and_nothing_is_stored():
    import httpx

    _document()
    fake = FakeBatches()
    request = httpx.Request("POST", "https://x")

    def refuses(url, *, headers, requests):
        raise httpx.HTTPStatusError(
            "400", request=request, response=httpx.Response(400, request=request)
        )

    create, fake.batch_create = fake.batch_create, refuses
    with pytest.raises(ProviderRefused):
        _compile(fake)
    assert claude_spend.entries() == [] and "compile_runs" in _tables()
    fake.batch_create = create
    assert _compile(fake)["status"] == "all_pages_answered" and len(fake.created) == 1


def _tables():
    return {
        r["name"]
        for r in db.connect().execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


# ------------------------------------------------------------------------------------------ switch


def test_switch_off_refuses_and_creates_nothing(monkeypatch):
    _document()
    monkeypatch.setattr(settings, "standards_compiler_enabled", False)
    fake = FakeBatches()
    with pytest.raises(standards_compiler.SwitchedOff):
        _compile(fake)
    assert (
        fake.created == []
        and "compiled_rules" not in _tables()
        and "claude_batches" not in _tables()
    )


def test_switch_off_a_review_run_is_byte_identical(monkeypatch):
    _document()
    _review_run(outcome='{"kept":   "as written"}')
    monkeypatch.setattr(settings, "standards_compiler_enabled", False)
    standards_compiler.record_rule_version("run-1")
    row = (
        db.connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id='run-1'")
        .fetchone()
    )
    assert row["outcome_json"] == '{"kept":   "as written"}'


def test_the_switch_is_off_by_default():
    assert type(settings).model_fields["standards_compiler_enabled"].default is False


# ------------------------------------------------------------------------------------------ script


def _copy_db():
    db.reset_connection()
    return Path(settings.db_path)


def test_the_script_refuses_a_live_shaped_path(tmp_path):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    sqlite3.connect(live).close()
    keep = settings.db_path
    with pytest.raises(SystemExit, match="refusing"):
        compile_standards.run(live, [LABEL], emit=lambda _s: None)
    assert settings.db_path == keep


def test_the_script_with_the_switch_off_opens_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "standards_compiler_enabled", False)
    said = []
    missing = tmp_path / "no-such.sqlite"
    assert (
        compile_standards.run(missing, [LABEL], emit=said.append)
        == compile_standards.EXIT_CLOSED
    )
    assert not missing.exists() and "off" in said[0]


def test_the_script_says_the_lane_is_shut(monkeypatch):
    _document()
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    fake = FakeBatches()
    said = []
    code = compile_standards.run(_copy_db(), [LABEL], client=fake, emit=said.append)
    assert (
        code == compile_standards.EXIT_CLOSED
        and fake.created == []
        and "shut" in said[0]
    )


def test_the_script_reports_counts_only_and_prints_the_estimate_first():
    _document()
    said, notes = [], []
    code = compile_standards.run(
        _copy_db(),
        [LABEL],
        client=FakeBatches(),
        sleep=lambda _s: None,
        emit=said.append,
        note=notes.append,
    )
    assert code == 0 and notes[0].startswith("worst case before sending")
    assert len(said) == 1
    report = json.loads(said[0])["standards"][0]
    assert report["kept"] == 1 and report["models_answering"] == [ANSWERED]
    assert report["usd_on_this_standards_step"] > 0 and report["usd_boundary"]
    everything = "\n".join(said + notes)
    assert QUOTE not in everything and "invented" not in everything.lower()


def test_the_script_refuses_an_unlisted_standard_with_its_exit_code():
    _document(listed=False)
    said = []
    code = compile_standards.run(
        _copy_db(), [LABEL], client=FakeBatches(), emit=said.append
    )
    assert code == compile_standards.EXIT_REFUSED and "refused" in said[-1]


def test_the_script_exit_says_a_batch_is_still_running():
    _document()
    fake = FakeBatches()
    fake.batch_retrieve = lambda url, batch_id, *, headers: {
        "id": batch_id,
        "processing_status": "in_progress",
    }
    code = compile_standards.run(
        _copy_db(),
        [LABEL],
        client=fake,
        max_wait_s=0,
        sleep=lambda _s: None,
        emit=lambda _s: None,
    )
    assert code == compile_standards.EXIT_WAITING and _rules_table_empty()


def _rules_table_empty():
    conn = db.connect()
    return conn.execute("SELECT COUNT(*) AS n FROM compiled_rules").fetchone()["n"] == 0


# ------------------------------------------------------------------------------------- side by side


def _v1_rule(
    doc,
    *,
    text,
    source,
    page=1,
    field=None,
    operator=None,
    value=None,
    unit=None,
    version=None,
    gone=False,
):
    made = standards.create_requirement(
        standard_document_id=doc,
        chunk_id=f"c-{doc}",
        requirement_text=text,
        source_text=source or text,
        clause="4.1",
        page=1,
        structured={"requirement_type": "statement"},
    )
    with db.connect() as conn:
        conn.execute(
            "UPDATE standard_requirements SET source_text=?, page=?, field=?, operator=?, value=?, unit=?, extractor_version=?,"
            " superseded_at=? WHERE id=?",
            (
                source,
                page,
                field,
                operator,
                value,
                unit,
                version,
                NOW if gone else None,
                made["id"],
            ),
        )


def test_side_by_side_counts_both_versions_with_the_same_quote_check():
    _document()
    _v1_rule(
        DOC,
        text=QUOTE,
        source=QUOTE,
        field="p",
        operator="<=",
        value=25.0,
        unit="bar",
        version="x1",
    )
    _v1_rule(
        DOC,
        text="on the wrong page",
        source=QUOTE,
        page=2,
        field="p",
        operator="<=",
        value=25.0,
        version="x1",
    )
    _v1_rule(DOC, text="no quote at all", source=None, version=None)
    _v1_rule(
        DOC,
        text="a replaced row",
        source=QUOTE,
        field="p",
        operator="<=",
        value=1.0,
        unit="bar",
        gone=True,
    )
    _compile(FakeBatches())
    out = standards_compiler.side_by_side(db.connect(), {DOC: LABEL})
    row = out["per_standard"][0]
    v1, v2 = row["v1"], row["v2"]
    assert out["boundary"].startswith("active rows")
    assert v1["rules"] == 3  # the replaced row is not active
    assert v1["usable_numeric_limits"] == 1  # the second has no unit
    assert v1["verified_quotes"] == 1
    assert v1["extractor_versions"] == {"x1": 2, standards_compiler.NOT_RECORDED: 1}
    assert v1["models"] == {standards_compiler.NOT_RECORDED: 3}  # never a guess
    assert (v2["rules"], v2["usable_numeric_limits"], v2["verified_quotes"]) == (
        1,
        1,
        1,
    )
    assert v2["models"] == {ANSWERED: 1} and v2["batch_ids"] == ["msgbatch_1"]
    assert v2["by_status"] == {"held": 1}


def test_side_by_side_quote_check_is_run_again_on_version_2():
    _document()
    _compile(FakeBatches())
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET text = 'the page changed' WHERE document_id = ? AND page_no = 1",
            (DOC,),
        )
    row = standards_compiler.side_by_side(db.connect(), {DOC: LABEL})["per_standard"][0]
    assert row["v2"]["verified_quotes"] == 0 and row["v2"]["rules"] == 1


def test_side_by_side_totals_add_the_standards_up():
    _document()
    _document("std-yy", "SAES-Y-900", pages=(PAGE_1,))
    _v1_rule(
        DOC,
        text=QUOTE,
        source=QUOTE,
        field="p",
        operator="<=",
        value=25.0,
        unit="bar",
        version="x1",
    )
    _v1_rule(
        "std-yy",
        text=QUOTE,
        source=QUOTE,
        field="p",
        operator="<=",
        value=25.0,
        unit="bar",
        version="x2",
    )
    out = standards_compiler.side_by_side(
        db.connect(), {DOC: LABEL, "std-yy": "SAES-Y-900"}
    )
    total = out["total"]["v1"]
    assert total["rules"] == 2 and total["verified_quotes"] == 2
    assert total["extractor_versions"] == {"x1": 1, "x2": 1}
    assert (
        out["total"]["v2"]["rules"] == 0
    )  # no compile yet: zero rows, and the table need not exist


def test_the_script_prints_the_side_by_side_as_counts_only():
    _document()
    _v1_rule(
        DOC,
        text=QUOTE,
        source=QUOTE,
        field="p",
        operator="<=",
        value=25.0,
        unit="bar",
        version="x1",
    )
    said = []
    assert (
        compile_standards.run(_copy_db(), [LABEL], side_by_side=True, emit=said.append)
        == 0
    )
    out = json.loads(said[0])
    assert out["total"]["v1"]["rules"] == 1 and out["boundary"]
    assert QUOTE not in said[0]


# ------------------------------------------------------------------------------- scanned pages


def _scanned(doc_id=DOC, number=LABEL, pages=(PAGE_1, PAGE_2), conf=0.81, listed=True):
    """An invented scan: `pages.text` empty, the words in `page_ocr`, as the app stores them."""
    _document(doc_id, number, pages=("",) * len(pages), listed=listed)
    with db.connect() as conn:
        conn.execute("UPDATE pages SET needs_ocr = 1 WHERE document_id = ?", (doc_id,))
    for n, text in enumerate(pages, 1):
        _ocr(doc_id, n, text, conf)
    return doc_id


def _ocr(doc_id, page, text, conf=0.81, error=None):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO page_ocr (document_id,page_no,text,char_count,engine,model,dpi,mean_conf,min_conf,"
            "box_count,seconds,recognised_at,batch_no,error) VALUES (?,?,?,?,'e','m',200,?,?,1,0.1,?,0,?)",
            (doc_id, page, text, len(text), conf, conf, NOW, error),
        )


def test_a_scanned_standard_is_compiled_from_its_recognised_text():
    _scanned()
    fake = FakeBatches()
    report = _compile(fake)
    assert "The relief flange pressure" in json.dumps(fake.created)
    assert report["status"] == "all_pages_answered" and report["kept"] == 1
    assert (
        report["pages_total"],
        report["pages_native"],
        report["pages_from_ocr"],
    ) == (2, 0, 2)
    assert report["pages_no_text"] == []
    assert report["ocr_lowest_confidence"] == 0.81


def test_a_rule_from_a_recognised_page_says_so():
    _scanned()
    _compile(FakeBatches())
    rule = _rules()[0]
    assert (rule["page_source"], rule["page_min_conf"]) == ("recognised", 0.81)


def test_a_rule_from_a_native_page_says_so_and_claims_no_confidence():
    _document()
    report = _compile(FakeBatches())
    rule = _rules()[0]
    assert (rule["page_source"], rule["page_min_conf"]) == ("native", None)
    assert report["pages_native"] == 2 and "ocr_lowest_confidence" not in report


def test_a_quote_is_verified_against_the_recognised_text():
    _scanned(
        pages=("4.1 Flanges\nThe relief flange pressure shall not exceed 26 bar.",)
    )
    report = _compile(FakeBatches())  # the answer says 25; the recognised page says 26
    assert report["dropped"] == {"quote_not_on_page": 1} and _rules() == []


def test_recognised_text_overrides_a_stale_text_layer_as_everywhere_the_app_cites():
    _document(pages=("garbled layer words here", PAGE_2))
    _ocr(DOC, 1, PAGE_1)
    report = _compile(FakeBatches())
    assert (
        report["kept"] == 1
        and report["pages_native"] == 1
        and report["pages_from_ocr"] == 1
    )


def test_a_mixed_standard_counts_each_kind_and_lists_the_pages_with_no_text():
    _document(pages=(PAGE_1, "", "", ""))
    _ocr(DOC, 2, PAGE_2)
    _ocr(DOC, 3, "", conf=None, error="the page failed")  # page 4 was never recognised
    report = _compile(FakeBatches())
    assert (
        report["pages_total"],
        report["pages_native"],
        report["pages_from_ocr"],
    ) == (4, 1, 1)
    assert report["pages_no_text"] == [3, 4]
    assert report["status"] == "partial"
    assert (report["pages_answered"], report["pages_total"]) == (2, 4)


def test_a_standard_with_no_usable_page_is_not_compiled_and_never_reads_as_no_rules():
    _document(pages=("", "  "))
    fake = FakeBatches()
    report = _compile(fake)
    assert report["status"] == "not_compiled" and report["why"]
    assert report["pages_no_text"] == [1, 2] and "kept" not in report
    assert fake.created == [] and claude_spend.entries() == []
    assert (
        db.connect().execute("SELECT COUNT(*) AS n FROM compile_runs").fetchone()["n"]
        == 0
    )


def test_an_estimate_of_a_standard_with_no_usable_page_says_not_compiled():
    _document(pages=("",))
    report = _compile(FakeBatches(), estimate_only=True)
    assert report["status"] == "not_compiled" and "estimate" not in report


def test_a_standard_not_compiled_is_compiled_once_its_recognition_arrives():
    _document(pages=("",))
    assert _compile(FakeBatches())["status"] == "not_compiled"
    _ocr(DOC, 1, PAGE_1)
    assert _compile(FakeBatches())["status"] == "all_pages_answered"


def test_the_script_exit_says_a_standard_was_not_compiled():
    _document(pages=("",))
    said = []
    code = compile_standards.run(
        _copy_db(), [LABEL], estimate_only=True, emit=said.append, note=lambda _s: None
    )
    assert code == compile_standards.EXIT_NOT_COMPILED
    assert json.loads(said[0])["standards"][0]["status"] == "not_compiled"


def test_side_by_side_runs_the_same_quote_check_on_recognised_text():
    _scanned()
    _v1_rule(DOC, text="a sentence", source=QUOTE)
    row = standards_compiler.side_by_side(db.connect(), {DOC: LABEL})["per_standard"][0]
    assert row["v1"]["verified_quotes"] == 1
    assert (row["pages_native"], row["pages_from_ocr"], row["pages_no_text"]) == (
        0,
        2,
        [],
    )


def test_a_table_made_by_an_earlier_estimate_gets_the_new_columns():
    _document()
    conn = db.connect()
    with conn:
        conn.execute("CREATE TABLE compiled_rules (id TEXT PRIMARY KEY, run_id TEXT)")
    standards_compiler.ensure_schema(conn)
    names = {r["name"] for r in conn.execute("PRAGMA table_info(compiled_rules)")}
    assert {"page_source", "page_min_conf"} <= names


# ----------------------------------------------------------------------------------- the one line


def test_the_estimate_prints_one_clean_json_line_on_stdout_and_its_words_on_stderr(
    tmp_path,
):
    _scanned()
    path = _copy_db()
    env = {
        **os.environ,
        "STANDARDS_COMPILER_ENABLED": "true",
        "DATA_DIR": str(settings.data_dir),
        "CLAUDE_SPEND_LOG": str(tmp_path / "other.jsonl"),
    }
    done = subprocess.run(
        [
            sys.executable,
            str(Path(compile_standards.__file__)),
            "--db",
            str(path),
            "--standard",
            LABEL,
            "--estimate-only",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-400:]
    lines = done.stdout.splitlines()
    assert len(lines) == 1, done.stdout[:400]
    out = json.loads(lines[0])
    assert (
        out["standards"][0]["status"] == "estimate"
        and out["worst_usd_total"] > 0
        and out["boundary"]
    )
    assert "worst case before sending" in done.stderr


def test_a_refusal_is_also_one_json_line():
    _document(listed=False)
    said = []
    compile_standards.run(
        _copy_db(),
        [LABEL],
        client=FakeBatches(),
        emit=said.append,
        note=lambda _s: None,
    )
    assert len(said) == 1 and "refused" in json.loads(said[0])["stopped"]


# ------------------------------------------------------------------------- review of #1589: wrong rules


def _on_page(sentence, heading="4.1 Flanges"):
    return (f"{heading}\n{sentence}",)


def _outcome(sentence, **over):
    """What the proof says about one proposal on an invented page holding `sentence`."""
    pages = {1: _on_page(sentence)[0]}
    chunk = standards_compiler.chunks_of(pages)[0]
    answer = {
        "applies_to": "pumps",
        "condition": None,
        "field": "pressure",
        "comparator": "<=",
        "limit": "200",
        "unit": "psi",
        "clause": "4.1",
        "page": 1,
        "quote": sentence,
        **over,
    }
    return standards_compiler.verify(answer, chunk, pages)


NOZZLE = "The pressure of a 100 mm nozzle shall not exceed 200 psi."
PLAIN_LIMIT = "The nozzle pressure shall not exceed 200 psi."


def test_the_limit_the_sentence_binds_to_the_comparator_is_kept():
    rule, why = _outcome(PLAIN_LIMIT)
    assert why is None and (rule["limit_value"], rule["unit"]) == (200.0, "psi")


def test_a_number_of_another_thing_paired_with_the_limits_unit_is_dropped():
    assert _outcome(NOZZLE, limit="100") == (None, "number_and_unit_apart")


def test_a_number_and_unit_of_another_thing_is_not_the_limit():
    assert _outcome(NOZZLE, limit="100", unit="mm") == (None, "limit_not_bound")


def test_a_conversion_figure_with_the_first_unit_is_dropped():
    gap = "The gap pressure shall not exceed 5 mm (0.2 in)."
    assert _outcome(gap, limit="0.2", unit="mm") == (None, "number_and_unit_apart")
    assert _outcome(gap, limit="0.2", unit="in") == (None, "limit_not_bound")
    assert _outcome(gap, limit="5", unit="mm")[1] is None


@pytest.mark.parametrize("limit", ["10", "20"])
def test_a_range_is_dropped_and_counted_never_one_end(limit):
    sentence = "The pressure shall be 10 to 20 bar."
    rule, why = _outcome(sentence, limit=limit, unit="bar", comparator="=")
    assert rule is None and why in (
        "number_and_unit_apart",
        "limit_not_bound",
        "range_not_single",
    )


def test_a_range_with_the_unit_written_twice_is_named_a_range():
    sentence = "The pressure shall be 10 bar to 20 bar."
    assert _outcome(sentence, limit="10", unit="bar", comparator="=") == (
        None,
        "range_not_single",
    )


def test_a_dashed_range_is_dropped_too():
    sentence = "The pressure shall be 10-20 bar."
    assert _outcome(sentence, limit="20", unit="bar", comparator="=")[0] is None


def test_a_number_alone_is_bound_the_same_way():
    sentence = "The pressure of 3 pumps shall not exceed 2."
    assert _outcome(sentence, limit="3", unit=None)[1] == "limit_not_bound"


SOUR = "For sour service, the hardness shall not exceed 22 HRC."


def test_a_quote_cut_after_a_leading_condition_is_dropped():
    assert _outcome(
        SOUR,
        quote="the hardness shall not exceed 22 HRC",
        field="hardness",
        limit="22",
        unit="HRC",
    ) == (None, "condition_not_captured")


def test_a_whole_sentence_with_its_leading_condition_left_out_is_dropped():
    assert _outcome(SOUR, field="hardness", limit="22", unit="HRC") == (
        None,
        "condition_not_captured",
    )


def test_a_whole_sentence_with_its_leading_condition_captured_is_kept():
    rule, why = _outcome(
        SOUR, field="hardness", limit="22", unit="HRC", condition="for sour service"
    )
    assert why is None and rule["condition_text"] == "for sour service"


def test_a_list_of_subjects_is_not_a_leading_condition():
    sentence = "Flanges, bolts and nuts pressure shall not exceed 200 psi."
    assert _outcome(sentence)[1] is None


ABSENT = "In the absence of data, the pressure shall not exceed 200 psi."


def test_a_default_cut_off_from_its_words_does_not_pass_the_default_gate():
    assert _outcome(ABSENT, quote="the pressure shall not exceed 200 psi") == (
        None,
        "condition_not_captured",
    )


def test_the_default_words_gate_drops_a_whole_sentence():
    assert _outcome(ABSENT, condition="in the absence of data") == (
        None,
        "default_not_limit",
    )
    assert _outcome("The pressure shall not exceed 200 psi if not specified.") == (
        None,
        "default_not_limit",
    )


def test_a_trailing_condition_after_a_number_with_no_unit_is_not_lost():
    ratio = "The ratio shall not exceed 2 for pumps of the vertical type."
    over = {"field": "ratio", "limit": "2", "unit": None}
    assert _outcome(ratio, **over) == (None, "condition_not_captured")
    rule, why = _outcome(ratio, **over, condition="for pumps of the vertical type")
    assert why is None and rule["condition_text"] == "for pumps of the vertical type"


def test_a_reformatted_limit_does_not_lose_its_trailing_condition():
    gas = "The pressure shall not exceed 1,000 kPa for gas service."
    over = {"limit": "1000", "unit": "kPa"}
    assert _outcome(gas, **over) == (None, "condition_not_captured")
    rule, why = _outcome(gas, **over, condition="for gas service")
    assert why is None and rule["limit_value"] == 1000.0


def test_a_trailing_condition_with_the_quote_stopped_at_the_limit_is_dropped():
    cut_short = "The relief flange pressure shall not exceed 25 bar"
    assert _drop_reason(_rule(quote=cut_short)) == {"condition_not_captured": 1}


def test_a_condition_wrapped_onto_the_line_before_is_not_lost():
    pages = {
        1: "4.1 Flanges\nFor sour service in every invented process unit of the whole plant, the\nhardness shall not exceed 22 HRC."
    }
    chunk = standards_compiler.chunks_of(pages)[0]
    answer = {
        "applies_to": "pumps",
        "field": "hardness",
        "comparator": "<=",
        "limit": "22",
        "unit": "HRC",
        "clause": "4.1",
        "page": 1,
        "quote": "hardness shall not exceed 22 HRC.",
    }
    assert standards_compiler.verify(answer, chunk, pages) == (
        None,
        "condition_not_captured",
    )


def test_a_sentence_after_its_clause_number_on_the_same_line_is_whole():
    pages = {1: "4.1.2 The pressure shall not exceed 200 psi."}
    chunk = standards_compiler.chunks_of(pages)[0]
    answer = {
        "applies_to": "pumps",
        "field": "pressure",
        "comparator": "<=",
        "limit": "200",
        "unit": "psi",
        "clause": "4.1.2",
        "page": 1,
        "quote": "The pressure shall not exceed 200 psi.",
    }
    assert standards_compiler.verify(answer, chunk, pages)[1] is None


# ------------------------------------------------------------------------------ partial, not complete


def _two_chunk_pages():
    return (
        "1.1 One\nThe one widget shall be painted.\n" + "padding line\n" * 800,
        "2.1 Two\nThe two widget shall be painted.\n" + "padding line\n" * 800,
    )


def test_all_requests_expired_is_partial_with_a_non_zero_exit_and_the_rerun_is_not_skipped():
    _document()
    fake = FakeBatches(kinds={"*": ["expired", "expired"]})
    said = []
    code = compile_standards.run(
        _copy_db(),
        [LABEL],
        client=fake,
        sleep=lambda _s: None,
        emit=said.append,
        note=lambda _s: None,
    )
    report = json.loads(said[0])["standards"][0]
    assert code == compile_standards.EXIT_PARTIAL and report["status"] == "partial"
    assert report["kept"] == 0 and report["pages_not_read"] == [1, 2]
    again = _compile(fake)
    assert (
        again["status"] == "all_pages_answered"
        and again.get("skipped") is None
        and again["kept"] == 1
    )


def test_a_rerun_pays_only_for_the_pages_not_answered():
    pages = _two_chunk_pages()
    _document(pages=pages)
    numbered = dict(enumerate(pages, 1))
    first_id, second_id = (c.custom_id for c in standards_compiler.chunks_of(numbered))
    fake = FakeBatches([], kinds={second_id: ["expired", "errored"]})
    report = _compile(fake)
    assert report["status"] == "partial" and report["pages_not_read"] == [2]
    spent = claude_spend.spent(standards_converter.step_for(LABEL))
    again = _compile(fake)
    assert again["status"] == "all_pages_answered" and [
        r["custom_id"] for r in fake.created[-1]
    ] == [second_id]
    assert first_id not in {r["custom_id"] for r in fake.created[-1]}
    assert claude_spend.spent(standards_converter.step_for(LABEL)) > spent


def test_a_compiled_standard_always_reports_pages_not_read_and_only_complete_is_skipped():
    _document()
    report = _compile(FakeBatches())
    assert report["status"] == "all_pages_answered" and report["pages_not_read"] == []
    assert _compile(FakeBatches())["status"] == "skipped"


# --------------------------------------------------------------------------- clause, strength, scope


@pytest.mark.parametrize("clause", ["gas", "4.2", "service"])
def test_a_clause_must_be_the_label_nearest_before_the_quote(clause):
    _document(pages=(PAGE_1 + "\n4.2 Later\nMore words of the page.",))
    fake = FakeBatches([_rule(clause=clause)])
    assert _compile(fake)["dropped"] == {"clause_not_nearest": 1}


def test_a_clause_running_on_from_an_earlier_page_is_the_nearest():
    pages = {
        1: "4.1 Flanges\nThe first words.",
        2: "The pressure shall not exceed 200 psi.",
    }
    chunk = standards_compiler.chunks_of(pages)[0]
    answer = {
        "applies_to": "pumps",
        "field": "pressure",
        "comparator": "<=",
        "limit": "200",
        "unit": "psi",
        "page": 2,
        "quote": "The pressure shall not exceed 200 psi.",
    }
    assert (
        standards_compiler.verify({**answer, "clause": "4.1"}, chunk, pages)[1] is None
    )
    assert (
        standards_compiler.verify({**answer, "clause": "9.9"}, chunk, pages)[1]
        == "clause_not_nearest"
    )


def test_applies_to_is_marked_verified_only_when_the_page_says_it():
    _document()
    _compile(FakeBatches([_rule(applies_to="relief flanges")]))
    assert _rules()[0]["applies_to_verified"] == 1
    rule, _why = _outcome(PLAIN_LIMIT, applies_to="gearboxes")
    assert rule["applies_to_verified"] is False


@pytest.mark.parametrize(
    "verb, strength",
    [("shall", "shall"), ("must", "shall"), ("should", "should"), ("may", "may")],
)
def test_the_strength_is_kept_apart(verb, strength):
    sentence = f"The pressure {verb} not exceed 200 psi."
    rule, why = _outcome(sentence)
    assert why is None and rule["strength"] == strength


def test_need_not_exceed_is_not_a_limit():
    assert _outcome("The pressure need not exceed 200 psi.") == (
        None,
        "need_not_is_not_a_limit",
    )


def test_the_strength_and_applies_to_are_stored():
    _document()
    _compile(FakeBatches())
    assert _rules()[0]["strength"] == "shall"


def test_the_prompt_says_omit_when_unsure_and_asks_for_the_whole_sentence():
    words = standards_compiler.system_text({1: PAGE_1})
    assert "omit" in words.lower() and "whole sentence" in words.lower()


def test_the_worst_case_is_at_the_batch_price():
    packet = Packet(prompt="x" * 3000, num_ctx=0, num_predict=4096, step="s")
    assert claude_batch_run.worst_usd(MODEL, packet) == pytest.approx(
        claude_spend.worst_case_usd(MODEL, 3000, 4096) / 2
    )


def test_the_families_setting_is_documented_where_operators_look():
    root = Path(__file__).resolve().parents[2]
    assert "STANDARDS_COMPILER_FAMILIES" in (root / "backend/.env.example").read_text(
        encoding="utf-8"
    )
    assert "STANDARDS_COMPILER_FAMILIES" in (root / "docs/flags.md").read_text(
        encoding="utf-8"
    )


# ---------------------------------------------------------- ready for the versioned rulebook (plan change 6)


def _raw_rows():
    return [
        dict(r)
        for r in db.connect().execute(
            "SELECT * FROM claude_batch_answers ORDER BY received_at, custom_id"
        )
    ]


def test_every_raw_answer_is_kept_with_its_chunk_prompt_version_model_and_batch():
    _document()
    fake = FakeBatches([_rule(limit="26")])  # dropped by the proof, kept raw
    _compile(fake)
    rows = _raw_rows()
    assert len(rows) == 1 and _rules() == []
    row = rows[0]
    assert row["custom_id"] == fake.created[0][0]["custom_id"]
    assert (row["prompt_version"], row["model"], row["api_batch_id"]) == (
        standards_compiler.PROMPT_VERSION,
        ANSWERED,
        "msgbatch_1",
    )
    message = json.loads(row["raw_json"])
    assert (
        message["model"] == ANSWERED
        and "26" in message["content"][0]["text"]
        and message["usage"]
    )


def test_a_raw_answer_survives_the_rerun_that_reads_its_chunk_again():
    _document()
    fake = FakeBatches(stop="max_tokens")
    _compile(fake)
    fake.stop = "end_turn"
    _compile(fake)
    rows = _raw_rows()
    assert len(rows) == 2 and {r["custom_id"] for r in rows} == {
        fake.created[0][0]["custom_id"]
    }
    assert [json.loads(r["raw_json"])["stop_reason"] for r in rows] == [
        "max_tokens",
        "end_turn",
    ]


def test_a_raw_answer_is_kept_when_the_answer_came_from_the_response_cache():
    _document()
    _compile(FakeBatches())
    with db.connect() as conn:
        for table in (
            "compiled_rules",
            "compile_runs",
            "claude_batch_requests",
            "claude_batches",
        ):
            conn.execute(f"DELETE FROM {table}")
    _compile(FakeBatches())
    rows = _raw_rows()
    assert len(rows) == 2 and rows[1]["api_batch_id"] == claude_batch_run.FROM_CACHE


UNLESS = "The pressure shall not exceed 200 psi unless otherwise agreed."


def test_an_exception_is_kept_apart_from_the_condition():
    rule, why = _outcome(UNLESS, exceptions="unless otherwise agreed")
    assert why is None
    assert (
        rule["exception_text"] == "unless otherwise agreed"
        and rule["condition_text"] is None
    )


def test_an_exception_left_out_is_not_captured():
    assert _outcome(UNLESS) == (None, "condition_not_captured")


def test_an_exception_not_on_the_page_is_dropped():
    assert _outcome(UNLESS, exceptions="unless the moon is full") == (
        None,
        "exception_not_on_page",
    )


def test_a_quote_carries_its_hash_and_its_place_in_the_stored_page():
    pages = {1: "4.1 Flanges\nThe pressure shall\n  not exceed 200 psi."}
    chunk = standards_compiler.chunks_of(pages)[0]
    quote = "The pressure shall not exceed 200 psi."
    answer = {
        "applies_to": "pumps",
        "field": "pressure",
        "comparator": "<=",
        "limit": "200",
        "unit": "psi",
        "clause": "4.1",
        "page": 1,
        "quote": quote,
    }
    rule, why = standards_compiler.verify(answer, chunk, pages)
    assert why is None
    assert " ".join(pages[1][rule["quote_start"] : rule["quote_end"]].split()) == quote
    assert rule["quote_sha256"] == hashlib.sha256(quote.encode("utf-8")).hexdigest()


def test_a_rule_stores_the_edition_its_document_records_and_says_nothing_when_none():
    _document()
    _compile(FakeBatches())
    assert _rules()[0]["edition"] is None
    row = _rules()[0]
    assert row["quote_sha256"] and row["quote_end"] > row["quote_start"]
    with db.connect() as conn:
        conn.execute("DELETE FROM compiled_rules")
        conn.execute("DELETE FROM compile_runs")
        conn.execute(
            "UPDATE document_classification SET revision = 'Rev 7' WHERE document_id = ?",
            (DOC,),
        )
    _compile(FakeBatches())
    assert _rules()[0]["edition"] == "Rev 7"


# ------------------------------------------------------------------------------- re-review of #1589


@pytest.mark.parametrize(
    "limit, unit",
    [("100 mm", None), ("200 psi", None), ("100 mm", "mm"), ("316L", None)],
)
def test_a_limit_that_is_not_a_bare_number_is_dropped(limit, unit):
    assert _outcome(
        NOZZLE.replace("nozzle", "316L nozzle"), limit=limit, unit=unit
    ) == (
        None,
        "limit_not_a_bare_number",
    )


def _still_running(fake):
    fake.batch_retrieve = lambda url, batch_id, *, headers: {
        "id": batch_id,
        "processing_status": "in_progress",
    }


def test_budget_left_out_with_a_batch_open_reports_the_batch_not_nothing_sent(
    monkeypatch,
):
    monkeypatch.setattr(settings, "claude_budget_usd_per_standard", 0.2)
    _document(pages=_big_pages(20))
    fake = FakeBatches([])
    real = fake.batch_retrieve
    _still_running(fake)
    said = []
    code = compile_standards.run(
        _copy_db(),
        [LABEL],
        client=fake,
        max_wait_s=0,
        sleep=lambda _s: None,
        emit=said.append,
        note=lambda _s: None,
    )
    out = json.loads(said[0])
    report = out["standards"][0]
    assert code == compile_standards.EXIT_WAITING and out["stopped"] is None
    assert report["status"] == "waiting" and report["batch_ids"] == ["msgbatch_1"]
    assert report["chunks_not_sent"] > 0 and len(fake.created) == 1
    assert "nothing" not in said[0]
    fake.batch_retrieve = real
    again = _compile(fake)
    assert again["status"] == "partial" and again["resumed_batches"] == 1


def test_earlier_sends_are_never_reported_as_nothing_sent(monkeypatch):
    _document()
    fake = FakeBatches(kinds={"*": ["expired", "expired"]})
    assert _compile(fake)["status"] == "partial"
    monkeypatch.setattr(settings, "claude_budget_usd_per_standard", 0.0001)
    report = _compile(fake)
    assert report["status"] == "partial" and report["batch_ids"] == [
        "msgbatch_1",
        "msgbatch_2",
    ]
    assert report["chunks_not_sent"] == 1 and len(fake.created) == 2


def test_nothing_sent_still_refuses_when_nothing_was_sent(monkeypatch):
    _document()
    monkeypatch.setattr(settings, "claude_budget_usd_per_standard", 0.0001)
    fake = FakeBatches()
    with pytest.raises(standards_compiler.TooDear, match="nothing was sent"):
        _compile(fake)
    assert fake.created == []


def test_pages_with_no_text_keep_a_standard_partial_and_state_the_denominator():
    _document(pages=(PAGE_1, "", "", "", ""))
    said = []
    code = compile_standards.run(
        _copy_db(),
        [LABEL],
        client=FakeBatches(),
        sleep=lambda _s: None,
        emit=said.append,
        note=lambda _s: None,
    )
    report = json.loads(said[0])["standards"][0]
    assert code == compile_standards.EXIT_PARTIAL and report["status"] == "partial"
    assert (report["pages_answered"], report["pages_total"]) == (1, 5)
    assert report["pages_denominator"] and report["pages_no_text"] == [2, 3, 4, 5]


def test_a_partial_standard_with_blank_pages_costs_nothing_to_run_again():
    _document(pages=(PAGE_1, ""))
    fake = FakeBatches()
    _compile(fake)
    assert _compile(fake)["status"] == "partial" and len(fake.created) == 1
    assert len(_rules()) == 1


def test_the_finished_word_says_answered_not_extracted():
    _document()
    report = _compile(FakeBatches([]))
    assert report["status"] == "all_pages_answered" and report["kept"] == 0


def test_side_by_side_says_a_partial_version_2_is_partial_with_its_drops():
    _document()
    fake = FakeBatches([_rule(), _rule(limit="26")], kinds={})
    report = _compile(fake)
    assert report["status"] == "all_pages_answered"
    v2 = standards_compiler.side_by_side(db.connect(), {DOC: LABEL})["per_standard"][0][
        "v2"
    ]
    assert v2["run_status"] == "all_pages_answered" and v2["proposed"] == 2
    assert v2["dropped"] == {"limit_not_in_quote": 1} and v2["pages_not_read"] == 0


def test_side_by_side_marks_partial_and_not_compiled_and_adds_them_up():
    _document(pages=(PAGE_1, ""))
    _document("std-yy", "SAES-Y-900", pages=(PAGE_1,))
    _compile(FakeBatches())
    out = standards_compiler.side_by_side(
        db.connect(), {DOC: LABEL, "std-yy": "SAES-Y-900"}
    )
    statuses = {r["standard"]: r["v2"]["run_status"] for r in out["per_standard"]}
    assert statuses == {LABEL: "partial", "SAES-Y-900": "not compiled"}
    assert out["total"]["v2"]["run_statuses"] == {"partial": 1, "not compiled": 1}


def test_a_skipped_rerun_still_shows_the_drops():
    _document()
    fake = FakeBatches([_rule(), _rule(limit="26")])
    _compile(fake)
    report = _compile(fake)
    assert report["status"] == "skipped" and report["skipped"] == 1
    assert report["dropped"] == {"limit_not_in_quote": 1} and report["kept"] == 1


def test_the_conditional_gate_alone_drops_a_condition_in_the_middle():
    sentence = "The widget in gas service shall be painted."
    over = {"field": "widget", "limit": None, "unit": None, "comparator": None}
    assert _outcome(sentence, **over) == (None, "condition_not_captured")
    assert _outcome(sentence, **over, condition="in gas service")[1] is None


# ------------------------------------------------------------ table rows and scope outside the sentence

ROW = "Maximum flange pressure 25 bar"
TABLE_PAGE = f"4.1 Flanges\nRow heading words\n{ROW}\nAnother row words"


def _tabled():
    _document(pages=(TABLE_PAGE,))
    tables = json.dumps(
        {"tables": [{"rows": [["Maximum flange pressure", "25 bar"]], "lines": [2]}]}
    )
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET tables_json = ? WHERE document_id = ?", (tables, DOC)
        )


def test_a_dropped_table_row_is_counted_as_one():
    _tabled()
    report = _compile(FakeBatches([_rule(quote=ROW, condition=None, limit="26")]))
    assert report["dropped"] == {"limit_not_in_quote": 1}
    assert report["dropped_table_rows"] == {"limit_not_in_quote": 1}


def test_a_dropped_sentence_is_not_counted_as_a_table_row():
    _document()
    report = _compile(FakeBatches([_rule(limit="26")]))
    assert report["dropped_table_rows"] == {}


def test_a_rule_kept_from_a_table_row_is_flagged_and_cannot_read_as_a_plain_shall():
    _tabled()
    report = _compile(FakeBatches([_rule(quote=ROW, condition=None)]))
    rule = _rules()[0]
    assert (
        "table_row" in rule["context_flag"] and rule["strength"] == "context_dependent"
    )
    assert rule["sentence_strength"] == "stated"
    assert report["kept_with_context_flag"]["table_row"] == 1


@pytest.mark.parametrize(
    "page, flag",
    [
        ("4.1 Flanges for sour service\nSome plain words here.\n{s}", "heading_scope"),
        ("Table 3 - Limits for gas lines\n{s}", "caption_scope"),
        (
            "4.1 Flanges\nThe rules below apply only to sour service. {s}",
            "adjacent_scope",
        ),
        ("4.1 Flanges\n{s} This limit applies only to sour service.", "adjacent_scope"),
    ],
)
def test_scope_outside_the_sentence_flags_the_rule(page, flag):
    sentence = "The pressure shall not exceed 200 psi."
    pages = {1: page.format(s=sentence)}
    chunk = standards_compiler.chunks_of(pages)[0]
    clause = "4.1" if page.startswith("4.1") else "3"
    if flag == "caption_scope":
        pages = {1: "4.1 Flanges\n" + pages[1]}
        chunk = standards_compiler.chunks_of(pages)[0]
        clause = "4.1"
    answer = {
        "applies_to": "pumps",
        "field": "pressure",
        "comparator": "<=",
        "limit": "200",
        "unit": "psi",
        "clause": clause,
        "page": 1,
        "quote": sentence,
    }
    rule, why = standards_compiler.verify(answer, chunk, pages)
    assert why is None and flag in rule["context_flag"]
    assert (
        rule["strength"] == "context_dependent" and rule["sentence_strength"] == "shall"
    )


def test_a_heading_running_on_from_an_earlier_page_flags_the_rule():
    sentence = "The pressure shall not exceed 200 psi."
    pages = {1: "4.1 Flanges for sour service\nSome plain words here.", 2: sentence}
    chunk = standards_compiler.chunks_of(pages)[0]
    answer = {
        "applies_to": "pumps",
        "field": "pressure",
        "comparator": "<=",
        "limit": "200",
        "unit": "psi",
        "clause": "4.1",
        "page": 2,
        "quote": sentence,
    }
    rule, why = standards_compiler.verify(answer, chunk, pages)
    assert why is None and "heading_scope" in rule["context_flag"]


def test_a_sentence_that_refers_back_is_flagged():
    rule, why = _outcome("These pressure limits shall not exceed 200 psi.")
    assert why is None and "refers_back" in rule["context_flag"]
    assert rule["strength"] == "context_dependent"


def test_a_line_with_no_verb_is_flagged_row_like():
    rule, why = _outcome("Set pressure max 200 psi", comparator="<=")
    assert why is None and "row_like" in rule["context_flag"]


def test_a_plain_sentence_under_a_plain_heading_carries_no_flag():
    rule, why = _outcome(PLAIN_LIMIT)
    assert why is None and rule["context_flag"] is None and rule["strength"] == "shall"


def test_a_limit_of_its_own_before_it_does_not_flag_the_next_sentence():
    first = "The flange pressure shall not exceed 25 bar for gas service."
    sentence = "The pressure shall not exceed 200 psi."
    pages = {1: f"4.1 Flanges\n{first} {sentence}"}
    chunk = standards_compiler.chunks_of(pages)[0]
    answer = {
        "applies_to": "pumps",
        "field": "pressure",
        "comparator": "<=",
        "limit": "200",
        "unit": "psi",
        "clause": "4.1",
        "page": 1,
        "quote": sentence,
    }
    rule, why = standards_compiler.verify(answer, chunk, pages)
    assert why is None and rule["context_flag"] is None


def test_pages_answered_leaves_out_the_pages_whose_request_was_not_answered():
    pages = _two_chunk_pages()
    _document(pages=pages)
    second_id = standards_compiler.chunks_of(dict(enumerate(pages, 1)))[1].custom_id
    report = _compile(FakeBatches([], kinds={second_id: ["expired", "errored"]}))
    assert (report["pages_answered"], report["pages_total"]) == (1, 2)
    assert report["pages_no_text"] == [] and report["pages_not_read"] == [2]


# -------------------------------------------------------------- wrong drops the first stored answers showed


def _verify_on(pages, quote, **over):
    pages = pages if isinstance(pages, dict) else {1: pages}
    chunk = standards_compiler.chunks_of(pages)[0]
    answer = {
        "applies_to": "widgets",
        "condition": None,
        "field": "pressure",
        "comparator": "<=",
        "limit": "200",
        "unit": "psi",
        "clause": "7.3",
        "page": max(pages),
        "quote": quote,
        **over,
    }
    return standards_compiler.verify(answer, chunk, pages)


def test_a_clause_number_alone_on_its_line_is_a_heading():
    quote = "The pressure shall not exceed 200 psi."
    page = f"7.2 Older part\nSome words here.\n7.3 \nWidget Lines\n{quote}"
    assert _verify_on(page, quote)[1] is None
    assert _verify_on(page, quote, clause="7.2") == (None, "clause_not_nearest")


def test_a_lone_figure_before_a_lowercase_line_is_not_a_heading():
    quote = "The pressure shall not exceed 200 psi."
    page = f"7.3 Part\nSome words here.\n2.5\nmore words here.\n{quote}"
    assert _verify_on(page, quote)[1] is None


@pytest.mark.parametrize(
    "sentence, over",
    [
        (
            "The distance shall be at a minimum of 7 m from any fence.",
            {
                "field": "minimum distance from any fence",
                "comparator": ">=",
                "limit": "7",
                "unit": "m",
            },
        ),
        (
            "The drop shall not exceed 6% of the widest gauge reading.",
            {"field": "drop", "limit": "6", "unit": "%"},
        ),
        (
            "The drain shall hold a maximum thickness of 77 Poise is not exceeded.",
            {"field": "maximum thickness", "limit": "77", "unit": "Poise"},
        ),
        (
            "The widgets shall be of 5-inch size.",
            {"field": "widget size", "comparator": "=", "limit": "5", "unit": "inch"},
        ),
    ],
)
def test_words_that_finish_the_property_are_not_a_lost_condition(sentence, over):
    rule, why = _verify_on(f"7.3 Part\n{sentence}", sentence, **over)
    assert (
        why is None
        and rule["condition_text"] is None
        and rule["limit_value"] == float(over["limit"])
    )


@pytest.mark.parametrize(
    "tail",
    [
        "for gas service",
        "when the plant is cold",
        "unless the owner agrees",
        "in sour plants",
    ],
)
def test_a_scope_after_those_words_stays_a_condition(tail):
    sentence = f"The drop shall not exceed 6% of the widest gauge reading {tail}."
    over = {"field": "drop", "limit": "6", "unit": "%"}
    assert _verify_on(f"7.3 Part\n{sentence}", sentence, **over) == (
        None,
        "condition_not_captured",
    )


def test_a_trailing_scope_named_in_the_field_is_still_a_condition():
    sentence = "The pressure shall not exceed 200 psi for gas service."
    assert _verify_on(
        f"7.3 Part\n{sentence}", sentence, field="pressure for gas service"
    ) == (None, "condition_not_captured")


HIGH = "When the top rail is at least 9 m above the deck, the minimum side gap shall be 9 m."
HIGH_OVER = {
    "field": "minimum side gap",
    "comparator": ">=",
    "limit": "9",
    "unit": "m",
}


def test_the_comparator_is_read_outside_the_condition():
    rule, why = _verify_on(
        f"7.3 Part\n{HIGH}",
        HIGH,
        **HIGH_OVER,
        condition="When the top rail is at least 9 m above the deck",
    )
    assert (
        why is None
        and rule["condition_text"] == "when the top rail is at least 9 m above the deck"
    )


def test_that_sentence_with_its_condition_left_out_is_still_dropped():
    assert _verify_on(f"7.3 Part\n{HIGH}", HIGH, **HIGH_OVER)[0] is None


def test_a_number_inside_the_condition_is_not_the_limit():
    sentence = (
        "When the height is 9 m above the deck, the pressure shall not exceed 200 psi."
    )
    over = {
        "limit": "9",
        "unit": "m",
        "condition": "When the height is 9 m above the deck",
    }
    assert _verify_on(f"7.3 Part\n{sentence}", sentence, **over) == (
        None,
        "limit_not_in_quote",
    )


def test_a_condition_wholly_outside_the_sentence_does_not_cover_its_own_scope():
    sentence = "The pressure shall not exceed 200 psi for gas service."
    page = f"7.3 Part\nSome other words here.\n{sentence}"
    assert (
        _verify_on(page, sentence, condition="Some other words")[1]
        == "condition_not_a_clause"
    )


@pytest.mark.parametrize(
    "field, quote_word",
    [
        ("widget drain size", "widget drain"),
        ("widget location", "widget"),
        ("use of widgets", "widgets"),
        ("service", "services"),
    ],
)
def test_a_generic_property_word_or_a_plural_does_not_refuse_a_field(field, quote_word):
    sentence = f"The {quote_word} shall be painted."
    if field == "service":
        sentence = "The services shall be painted."
    rule, why = _verify_on(
        f"7.3 Part\n{sentence}",
        sentence,
        field=field,
        limit=None,
        unit=None,
        comparator=None,
    )
    assert why is None and rule["field"] == field


def test_a_field_about_something_else_is_still_refused():
    sentence = "The pressure shall not exceed 200 psi."
    assert _verify_on(f"7.3 Part\n{sentence}", sentence, field="vane speed") == (
        None,
        "field_not_in_quote",
    )
    assert _verify_on(
        f"7.3 Part\n{sentence}", sentence, field="pressure of the vane"
    ) == (None, "field_not_in_quote")


def test_a_bracketed_gloss_on_a_field_is_not_stored_as_read():
    sentence = "The drop shall not exceed 6% of the gauge."
    rule, why = _verify_on(
        f"7.3 Part\n{sentence}",
        sentence,
        field="drop (percent of gauge)",
        limit="6",
        unit="%",
    )
    assert why is None and rule["field"] == "drop"


def test_a_number_joined_to_its_unit_by_a_hyphen_stands_together():
    sentence = "The drain shall be of 2-inch diameter."
    rule, why = _verify_on(
        f"7.3 Part\n{sentence}",
        sentence,
        field="drain diameter",
        comparator="=",
        limit="2",
        unit="inch",
    )
    assert why is None and rule["limit_value"] == 2.0


@pytest.mark.parametrize(
    "written, limit, value",
    [
        ("5\u20448", "5/8", 0.625),
        ("5/8", "5\u20448", 0.625),
        ("2-3/8", "2-3/8", 2.375),
        ("2 3/8", "2 3/8", 2.375),
    ],
)
def test_a_fraction_is_a_number_through_numparse(written, limit, value):
    assert numparse.as_limit(limit) == value
    sentence = f"The widget drain shall be {written} inch."
    rule, why = _verify_on(
        f"7.3 Part\n{sentence}",
        sentence,
        field="drain",
        comparator="=",
        limit=limit,
        unit="inch",
    )
    assert why is None and rule["limit_value"] == value


@pytest.mark.parametrize(
    "text", ["3/0", "12/25/2019", "5/8/5", "a/b", "1.5/2", "5/8 inch", "size 5/8"]
)
def test_what_is_not_one_fraction_stays_no_number(text):
    assert numparse.as_limit(text) is None


def test_a_plain_number_is_unchanged_by_the_fraction_reader():
    assert numparse.as_limit("1,000") == 1000.0 and numparse.as_limit("-5") == -5.0


def test_a_fraction_of_another_size_is_not_the_limit():
    sentence = "The widget drain shall be 5/8 inch."
    assert _verify_on(
        f"7.3 Part\n{sentence}",
        sentence,
        field="drain",
        comparator="=",
        limit="1/2",
        unit="inch",
    )[1] == ("limit_not_in_quote")


def test_not_exceed_by_more_than_is_one_limit():
    sentence = "The pressure rise shall not exceed the rail pressure by more than 7%."
    rule, why = _verify_on(
        f"7.3 Part\n{sentence}", sentence, field="pressure rise", limit="7", unit="%"
    )
    assert why is None and rule["comparator"] == "<="


def test_more_than_alone_still_says_more_than():
    sentence = "The pressure rise shall be by more than 7%."
    assert _verify_on(
        f"7.3 Part\n{sentence}", sentence, field="pressure rise", limit="7", unit="%"
    ) == (None, "comparator_not_in_quote")


def test_a_plural_acronym_is_not_garbled_text():
    assert (
        converter_gates.quote_unreadable("XKVs shall have painted parts.", "x") is False
    )


def test_a_plural_acronym_does_not_excuse_real_noise():
    assert (
        converter_gates.quote_unreadable("Xkvb shall have pqrstv zxcvb mnbvc.", "x")
        is True
    )


LEAD = "7.3 Part\nWhen the widget is wet, the widget and"
FOLLOW = "drain shall hold a maximum thickness of 77 Poise."
FOLLOW_OVER = {"field": "maximum thickness", "limit": "77", "unit": "Poise"}


def test_a_sentence_crossing_a_page_keeps_its_condition_from_the_page_before_and_is_flagged():
    rule, why = _verify_on(
        {1: LEAD, 2: FOLLOW}, FOLLOW, **FOLLOW_OVER, condition="When the widget is wet"
    )
    assert why is None and rule["condition_text"] == "when the widget is wet"
    assert (
        "crosses_page" in rule["context_flag"]
        and rule["strength"] == "context_dependent"
    )


def test_a_sentence_crossing_a_page_with_its_condition_left_out_is_dropped():
    assert _verify_on({1: LEAD, 2: FOLLOW}, FOLLOW, **FOLLOW_OVER) == (
        None,
        "condition_not_captured",
    )


def test_a_condition_on_the_page_before_does_not_count_when_that_page_ended_its_sentence():
    pages = {1: "7.3 Part\nWhen the widget is wet, stop here.", 2: FOLLOW}
    assert _verify_on(
        pages, FOLLOW, **FOLLOW_OVER, condition="When the widget is wet"
    ) == (None, "condition_not_on_page")


# ------------------------------------------------------------------- re-verifying stored answers, USD 0


def test_stored_answers_are_proved_again_with_nothing_sent(monkeypatch):
    _document()
    fake = FakeBatches([_rule(), _rule(limit="26")])
    first = _compile(fake)
    assert first["kept"] == 1
    before = claude_spend.entries()
    real = standards_compiler.verify
    monkeypatch.setattr(
        standards_compiler,
        "verify",
        lambda answer, chunk, pages, tables=None: real(
            {**answer, "limit": "25"}, chunk, pages, tables
        ),
    )
    report = standards_compiler.reverify_stored(db.connect(), DOC, LABEL)
    assert report["status"] == "all_pages_answered" and report["reverified"] is True
    assert (
        report["kept"] == 1 and report["duplicates"] == 1
    )  # the second proposal now proves, as the same rule
    assert report["usd_this_step"] == 0.0 and claude_spend.entries() == before
    assert len(fake.created) == 1
    rule = _rules()[0]
    assert rule["model"] == ANSWERED and rule["batch_id"] == "msgbatch_1"


def test_a_reverify_replaces_the_rules_and_leaves_version_1_alone():
    _document()
    _compile(FakeBatches())
    standards_compiler.reverify_stored(db.connect(), DOC, LABEL)
    assert len(_rules()) == 1
    assert (
        db.connect().execute("SELECT COUNT(*) AS n FROM compile_runs").fetchone()["n"]
        == 1
    )


def test_a_reverify_with_no_stored_answers_says_so_and_stores_nothing():
    _document()
    report = standards_compiler.reverify_stored(db.connect(), DOC, LABEL)
    assert report["status"] == "nothing_stored" and report["answered"] == 0
    assert claude_spend.entries() == []


def test_a_reverify_keeps_the_pages_not_answered_as_not_read():
    _document()
    fake = FakeBatches(kinds={"*": ["expired", "expired"]})
    _compile(fake)
    report = standards_compiler.reverify_stored(db.connect(), DOC, LABEL)
    assert report["status"] == "nothing_stored" and report["pages_total"] == 2
    pages = _two_chunk_pages()
    _document("std-two", "SAES-Y-901", pages=pages)
    ids = [c.custom_id for c in standards_compiler.chunks_of(dict(enumerate(pages, 1)))]
    standards_compiler.compile_standard(
        db.connect(),
        "std-two",
        "SAES-Y-901",
        client=FakeBatches([], kinds={ids[1]: ["expired", "errored"]}),
        sleep=lambda _s: None,
    )
    again = standards_compiler.reverify_stored(db.connect(), "std-two", "SAES-Y-901")
    assert again["status"] == "partial" and again["pages_not_read"] == [2]


def test_a_reverify_refuses_with_the_switch_off(monkeypatch):
    _document()
    monkeypatch.setattr(settings, "standards_compiler_enabled", False)
    with pytest.raises(standards_compiler.SwitchedOff):
        standards_compiler.reverify_stored(db.connect(), DOC, LABEL)


def test_the_script_reverifies_without_opening_the_lane(monkeypatch):
    _document()
    _compile(FakeBatches())
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    monkeypatch.setattr(settings, "standards_reader_enabled", False)
    said = []
    code = compile_standards.run(
        _copy_db(), [LABEL], reverify=True, emit=said.append, note=lambda _s: None
    )
    report = json.loads(said[0])["standards"][0]
    assert code == 0 and report["reverified"] is True and report["kept"] == 1


def test_a_chunk_label_reads_a_clause_number_alone_on_its_line():
    page = "7.3 \nWidget Lines\nThe pressure shall not exceed 200 psi."
    chunk = standards_compiler.chunks_of({1: page})[0]
    assert "[page 1 | clause 7.3]" in chunk.text and chunk.clauses[1] == {"7.3"}


def test_a_lone_figure_before_lower_case_words_is_not_a_chunk_label():
    chunk = standards_compiler.chunks_of({1: "2.5\nmore words here."})[0]
    assert "[page 1 | clause none]" in chunk.text


def test_a_qualifier_inside_the_field_does_not_contradict_the_comparator():
    sentence = "The maximum widget load shall be less than 4% of the rail load."
    over = {
        "field": "maximum widget load",
        "comparator": "<",
        "limit": "4",
        "unit": "%",
    }
    rule, why = _verify_on(f"7.3 Part\n{sentence}", sentence, **over)
    assert why is None and rule["comparator"] == "<"


def test_two_comparators_outside_the_field_stay_refused():
    sentence = "The widget load at the minimum shall be less than 4% of the rail load."
    over = {
        "field": "widget load",
        "comparator": "<",
        "limit": "4",
        "unit": "%",
    }
    assert _verify_on(f"7.3 Part\n{sentence}", sentence, **over) == (
        None,
        "comparator_not_in_quote",
    )


def test_material_is_a_generic_field_word():
    sentence = "Widgets shall be made of steel."
    rule, why = _verify_on(
        f"7.3 Part\n{sentence}",
        sentence,
        field="widget material",
        limit=None,
        unit=None,
        comparator=None,
    )
    assert why is None and rule["field"] == "widget material"


def test_a_bracket_in_the_words_after_a_limit_is_not_read_as_a_condition():
    sentence = "The drain shall be a 2-inch low drain (sump hole) at the low end."
    over = {
        "field": "low drain end (sump hole)",
        "comparator": "=",
        "limit": "2",
        "unit": "inch",
    }
    rule, why = _verify_on(f"7.3 Part\n{sentence}", sentence, **over)
    assert why is None and rule["limit_value"] == 2.0


def test_what_is_left_after_a_captured_condition_is_not_a_range():
    sentence = "The pressure of the air is -22 C and the widgets are clean."
    over = {
        "field": "pressure",
        "comparator": "=",
        "limit": "-22",
        "unit": "C",
        "condition": "the widgets are clean",
    }
    assert (
        _verify_on(f"7.3 Part\n{sentence}", sentence, **over)[1] != "range_not_single"
    )


def test_a_negative_limit_stands_on_its_own():
    sentence = "The pressure shall be -22 C."
    rule, why = _verify_on(
        f"7.3 Part\n{sentence}", sentence, comparator="=", limit="-22", unit="C"
    )
    assert why is None and rule["limit_value"] == -22.0


def test_a_chunk_with_no_stored_answer_keeps_a_reverify_partial():
    pages = _two_chunk_pages()
    _document(pages=pages)
    second = standards_compiler.chunks_of(dict(enumerate(pages, 1)))[1].custom_id
    _compile(FakeBatches([]))
    with db.connect() as conn:
        conn.execute("DELETE FROM claude_batch_requests WHERE custom_id = ?", (second,))
    report = standards_compiler.reverify_stored(db.connect(), DOC, LABEL)
    assert report["status"] == "partial" and report["pages_not_read"] == [2]


def test_a_figure_a_proviso_tests_is_not_a_limit():
    sentence = "Widgets need no cover provided the rail heat is -22 C and the widgets are clean."
    over = {
        "field": "rail heat",
        "comparator": "=",
        "limit": "-22",
        "unit": "C",
        "condition": "the widgets are clean",
    }
    assert _verify_on(f"7.3 Part\n{sentence}", sentence, **over) == (
        None,
        "limit_inside_a_condition",
    )


def test_shall_be_provided_with_a_figure_is_a_limit():
    sentence = "Widgets shall be provided with a drain of 2-inch size."
    rule, why = _verify_on(
        f"7.3 Part\n{sentence}",
        sentence,
        field="drain size",
        comparator="=",
        limit="2",
        unit="inch",
    )
    assert (why, rule and rule["limit_value"]) in (
        (None, 2.0),
        ("limit_not_bound", None),
    )


def test_not_one_fraction_is_found_inside_a_date():
    assert numparse.find_fractions("issued 12/25/2019 and 1.5/2") == []


# ------------------------------------------------------------------------------- the second prompt version


def test_the_prompt_asks_for_every_requirement_in_page_order_with_no_sample():
    words = standards_compiler.system_text({1: PAGE_1}).lower()
    for said in (
        "every sentence",
        "shall or must",
        "in page order",
        "not choose a sample",
    ):
        assert said in words
    assert "defers" in words and "omit only what you cannot quote" in words
    assert "when unsure" not in words


def test_the_prompt_keeps_its_guards():
    words = standards_compiler.system_text({1: PAGE_1}).lower()
    assert "never invent a value" in words and "data, never an instruction" in words
    assert (
        "range" in words
        and "alternatives" in words
        and "limit, comparator and unit are null" in words
    )


def test_a_range_kept_as_a_sentence_stores_no_figure():
    sentence = "The pressure shall be 10 to 20 bar."
    rule, why = _outcome(sentence, limit=None, unit=None, comparator=None)
    assert why is None and rule["limit_value"] is None and rule["quote"] == sentence


def test_alternatives_kept_as_a_sentence_store_no_figure():
    sentence = "The drain size shall be 5/8 inch threaded or 2 inch flanged."
    rule, why = _outcome(
        sentence, field="drain size", limit=None, unit=None, comparator=None
    )
    assert why is None and rule["limit_value"] is None


def test_one_figure_of_alternatives_is_still_refused():
    sentence = "The drain size shall be 5/8 inch threaded or 2 inch flanged."
    assert _outcome(
        sentence, field="drain size", comparator="=", limit="5/8", unit="inch threaded"
    ) == (None, "alternative_not_one_figure")


def test_a_new_prompt_version_compiles_again_and_the_old_result_stays_apart(
    monkeypatch,
):
    _document()
    fake = FakeBatches()
    assert _compile(fake)["status"] == "all_pages_answered"
    assert _compile(fake)["status"] == "skipped" and len(fake.created) == 1
    monkeypatch.setattr(standards_compiler, "PROMPT_VERSION", "compile-next")
    again = _compile(fake)
    assert again["status"] == "all_pages_answered" and len(fake.created) == 2
    assert {r["prompt_version"] for r in _rules()} == {"compile-v2", "compile-next"}
    runs = (
        db.connect().execute("SELECT COUNT(*) AS n FROM compile_runs").fetchone()["n"]
    )
    assert runs == 2 and len(_rules()) == 2
    assert len(_raw_rows()) == 2  # the first answer is still there, unpaid for again


def test_side_by_side_counts_the_latest_version_only_and_names_it(monkeypatch):
    _document()
    fake = FakeBatches()
    _compile(fake)
    monkeypatch.setattr(standards_compiler, "PROMPT_VERSION", "compile-next")
    _compile(fake)
    v2 = standards_compiler.side_by_side(db.connect(), {DOC: LABEL})["per_standard"][0][
        "v2"
    ]
    assert v2["rules"] == 1 and v2["prompt_versions"] == {"compile-next": 1}


def test_a_reverify_reads_only_the_version_it_is_asked_about(monkeypatch):
    _document()
    _compile(FakeBatches())
    monkeypatch.setattr(standards_compiler, "PROMPT_VERSION", "compile-next")
    assert (
        standards_compiler.reverify_stored(db.connect(), DOC, LABEL)["status"]
        == "nothing_stored"
    )
    assert len(_rules()) == 1


def _shall_page(count, words=8):
    return "\n".join(
        f"The widget {n} {'part ' * words}shall be painted." for n in range(count)
    )


def test_a_chunk_never_asks_for_more_rules_than_its_output_room_holds():
    chunks = standards_compiler.chunks_of({1: _shall_page(70), 2: _shall_page(70)})
    assert len(chunks) >= 6
    counts = [standards_compiler.shall_count(c.text) for c in chunks]
    assert max(counts) <= standards_compiler.MAX_RULES_PER_CHUNK and sum(counts) == 140


def test_the_output_room_holds_a_full_chunk_of_rules_at_the_measured_size():
    room = standards_compiler.MAX_RULES_PER_CHUNK * standards_compiler.TOKENS_PER_RULE
    assert (
        room * 2 <= standards_compiler.MAX_OUTPUT_TOKENS
    )  # the other half is thinking and long quotes


def test_no_page_text_is_lost_by_the_rule_count():
    pages = {1: _shall_page(70)}
    joined = "\n".join(c.text for c in standards_compiler.chunks_of(pages))
    assert all(f"The widget {n} " in joined for n in range(70))


def test_the_worst_case_bounds_a_full_answer_with_every_prompt_token_a_cache_write():
    pages = {1: _shall_page(70)}
    chunks = standards_compiler.chunks_of(pages)
    packets = standards_compiler.packets_of(LABEL, pages, chunks)
    total = 0.0
    for packet in packets.values():
        tokens_in = (len(packet.system) + len(packet.prompt)) // 3
        total += claude_spend.cost_usd(
            MODEL,
            {
                "input_tokens": 0,
                "cache_creation_input_tokens": tokens_in,
                "output_tokens": standards_compiler.MAX_OUTPUT_TOKENS,
            },
            batch=True,
        )
    assert total <= standards_compiler.estimate(MODEL, packets)["worst_usd"] + 0.001


def test_a_truncated_chunk_is_named_and_its_pages_are_not_read():
    _document()
    report = _compile(FakeBatches(stop="max_tokens"))
    assert report["status"] == "partial" and report["chunks_truncated"]
    assert report["pages_not_read"] == [1, 2]


def test_a_short_answer_is_reported_against_the_sentences_on_the_page():
    pages = (_shall_page(10),)
    _document(pages=pages)
    report = _compile(FakeBatches([]))
    assert report["shall_sentences"] == 10 and report["shall_sentences_proposed"] == 0
    assert report["shall_boundary"] and len(report["chunks_short"]) == 1


def test_a_full_answer_is_not_reported_short():
    sentence = "The pressure shall not exceed 200 psi."
    _document(pages=(f"7.3 Part\n{sentence}",))
    rule = _rule(
        quote=sentence,
        clause="7.3",
        field="pressure",
        limit="200",
        unit="psi",
        condition=None,
    )
    report = _compile(FakeBatches([rule]))
    assert report["shall_sentences"] == 1 and report["shall_sentences_proposed"] == 1
    assert report["chunks_short"] == []


# ---------------------------------------------------------------- second review: wrong rules the relaxed proof kept


def _plain(sentence, **over):
    return _verify_on(f"7.3 Part\n{sentence}", sentence, **over)


PLAIN = "The pressure shall not exceed 25 bar for gas service in winter."


@pytest.mark.parametrize(
    "condition",
    [
        "2",
        "25",
        "5 bar",
        "for gas",
        "gas service",
        "The pressure shall not exceed 25 bar",
    ],
)
def test_a_condition_that_is_not_a_whole_clause_of_the_sentence_drops_the_rule(
    condition,
):
    assert _plain(PLAIN, limit="25", unit="bar", condition=condition) == (
        None,
        "condition_not_a_clause",
    )


def test_a_digit_as_condition_cannot_turn_one_figure_into_another():
    sentence = "The pressure shall not exceed 225 bar."
    assert _plain(sentence, limit="25", unit="bar", condition="2")[0] is None


def test_a_main_clause_as_condition_cannot_let_a_proviso_figure_stand():
    sentence = "The cover shall not be used provided the pressure is 5 bar."
    over = {
        "limit": "5",
        "unit": "bar",
        "comparator": "=",
        "condition": "The cover shall not be used",
    }
    assert _plain(sentence, **over)[0] is None


def test_an_exception_that_is_part_of_a_clause_drops_the_rule():
    sentence = (
        "The pressure shall not exceed 25 bar unless the owner agrees in writing."
    )
    over = {"limit": "25", "unit": "bar", "exceptions": "the owner"}
    assert _plain(sentence, **over) == (None, "condition_not_a_clause")


def test_an_exception_elsewhere_on_the_page_is_kept_apart():
    sentence = "The pressure shall not exceed 25 bar."
    page = f"7.3 Part\n{sentence}\nException:\nCold widgets are not covered."
    rule, why = _verify_on(
        page,
        sentence,
        limit="25",
        unit="bar",
        exceptions="Cold widgets are not covered",
    )
    assert why is None and rule["exception_text"]


@pytest.mark.parametrize(
    "sentence",
    [
        "The cover shall be closed while the pressure is 5 bar.",
        "The cover shall be closed until the pressure is 5 bar.",
        "The cover shall be closed once the pressure is 5 bar.",
        "The cover shall be closed as long as the pressure is 5 bar.",
        "The cover shall be closed in case the pressure is 5 bar.",
        "The cover shall be closed providing the pressure is 5 bar.",
        "The cover shall be closed given that the pressure is 5 bar.",
        "Should the pressure be 5 bar, the cover shall be closed.",
        "The pressure of the cover shall be tested at 5 bar.",
        "The pressure shall be tested for loads of 5 bar.",
        "The pressure shall be checked with 5 bar.",
        "The pressure shall be read over 5 bar.",
        "Covers having a pressure of 5 bar shall be closed.",
    ],
)
def test_a_figure_the_modal_does_not_bind_is_not_a_limit(sentence):
    rule, why = _plain(
        sentence, field="pressure", comparator="=", limit="5", unit="bar"
    )
    assert rule is None, why


@pytest.mark.parametrize(
    "sentence",
    [
        "The pressure shall not exceed 200 psi once tested.",
        "The pressure shall not exceed 200 psi until tested.",
        "Once tested, the pressure shall not exceed 200 psi.",
        "The pressure, once tested, shall not exceed 200 psi.",
        "For pumps the pressure shall not exceed 200 psi.",
        "Pumps having 5 kW rating, the pressure shall not exceed 200 psi.",
        "Pumps over 5 kW pressure shall not exceed 200 psi.",
    ],
)
def test_a_scope_around_a_bound_limit_is_not_lost(sentence):
    assert _plain(sentence)[0] is None


def test_a_field_after_the_modal_with_an_equal_figure_drops():
    assert (
        _plain(
            "The widget shall have a drain of 2 inch.",
            field="drain",
            comparator="=",
            limit="2",
            unit="inch",
        )[0]
        is None
    )


def test_a_field_named_by_the_comparator_after_the_modal_is_bound():
    rule, why = _plain("The widget shall have a maximum pressure of 200 psi.")
    assert why is None and rule["limit_value"] == 200.0


@pytest.mark.parametrize(
    "sentence, over",
    [
        ("The pressure shall be 25 bar or 30 bar.", {"condition": "or 30 bar"}),
        ("The pressure shall be 25 bar or 30 bar.", {"exceptions": "or 30 bar"}),
        (
            "The pressure shall exceed the rail load by 25 bar or 30 bar, whichever is greater.",
            {"condition": "whichever is greater"},
        ),
        (
            "The pressure shall be 25 bar, whichever is greater.",
            {"exceptions": "whichever is greater"},
        ),
        ("The pressure shall be 25 bar (or 30 bar).", {}),
        ("The pressure shall be 25 bar (30 bar in winter).", {}),
    ],
)
def test_an_alternative_never_keeps_one_figure(sentence, over):
    rule, why = _plain(sentence, comparator="=", limit="25", unit="bar", **over)
    assert rule is None and why == "alternative_not_one_figure"


def test_an_alternative_with_no_figure_stored_is_kept_as_a_sentence():
    sentence = "The pressure shall be 25 bar or 30 bar."
    rule, why = _plain(sentence, limit=None, unit=None, comparator=None)
    assert why is None and rule["limit_value"] is None


def test_a_conversion_in_brackets_is_not_an_alternative():
    _rule_kept, why = _plain(
        "The pressure shall not exceed 25 bar (360 psi).", limit="25", unit="bar"
    )
    assert why is None


def test_a_bracketed_scope_does_not_vanish():
    sentence = "The pressure shall not exceed 25 bar (for gas service)."
    assert _plain(sentence, limit="25", unit="bar") == (None, "condition_not_captured")
    assert (
        _plain(sentence, limit="25", unit="bar", condition="for gas service")[1] is None
    )


def test_a_bracketed_scope_earlier_in_the_sentence_does_not_vanish():
    sentence = "The pressure (for gas service) shall not exceed 25 bar."
    assert _plain(sentence, limit="25", unit="bar") == (None, "condition_not_captured")


@pytest.mark.parametrize(
    "sentence, comparator",
    [
        ("The maximum pressure shall be 200 psi.", "="),
        ("The minimum pressure shall be 200 psi.", "="),
        ("The maximum pressure shall exceed 200 psi.", ">"),
        ("The minimum pressure shall be less than 200 psi.", "<"),
    ],
)
def test_a_comparator_that_conflicts_with_the_sentence_is_refused(sentence, comparator):
    field = "maximum pressure" if "maximum" in sentence else "minimum pressure"
    assert _plain(sentence, field=field, comparator=comparator) == (
        None,
        "comparator_not_in_quote",
    )


def test_the_maximum_a_sentence_states_is_read_as_a_maximum():
    rule, why = _plain(
        "The maximum pressure shall be 200 psi.", field="maximum pressure"
    )
    assert why is None and rule["comparator"] == "<="


@pytest.mark.parametrize(
    "tail",
    ["to gas lines", "from gas lines", "of gas lines"],
)
def test_words_read_as_the_property_are_flagged_not_lost(tail):
    sentence = f"The pressure shall not exceed 200 psi {tail}."
    rule, why = _plain(sentence)
    assert why is None and "tail_after_limit" in rule["context_flag"]
    assert rule["strength"] == "context_dependent"


def test_words_the_field_already_names_are_not_flagged():
    sentence = "The pressure shall not exceed 6% of the gauge."
    rule, why = _plain(sentence, field="pressure of the gauge", limit="6", unit="%")
    assert why is None and rule["context_flag"] is None


def test_must_be_met_by_is_a_scope():
    sentence = "The pressure shall not exceed 200 psi must be met by pumps."
    assert _plain(sentence) == (None, "condition_not_captured")


def test_a_reverify_counts_the_rows_it_replaces():
    _document()
    _compile(FakeBatches())
    report = standards_compiler.reverify_stored(db.connect(), DOC, LABEL)
    assert report["rules_replaced"] == 1


@pytest.mark.parametrize("status", ["approved", "rejected"])
def test_a_reverify_refuses_a_rule_that_is_no_longer_held(status):
    _document()
    _compile(FakeBatches())
    with db.connect() as conn:
        conn.execute(
            "UPDATE compiled_rules SET status = ?, approved_by = 'x'", (status,)
        )
    with pytest.raises(standards_compiler.NotHeld):
        standards_compiler.reverify_stored(db.connect(), DOC, LABEL)
    assert _rules()[0]["status"] == status


def test_the_script_reports_a_refused_reverify():
    _document()
    _compile(FakeBatches())
    with db.connect() as conn:
        conn.execute("UPDATE compiled_rules SET status = 'approved'")
    said = []
    code = compile_standards.run(
        _copy_db(), [LABEL], reverify=True, emit=said.append, note=lambda _s: None
    )
    assert (
        code == compile_standards.EXIT_REFUSED
        and "held" in json.loads(said[0])["stopped"]
    )


def test_an_older_prompt_versions_answers_can_be_proved_again(monkeypatch):
    _document()
    _compile(FakeBatches())
    monkeypatch.setattr(standards_compiler, "PROMPT_VERSION", "compile-next")
    report = standards_compiler.reverify_stored(
        db.connect(), DOC, LABEL, prompt_version="compile-v2"
    )
    assert report["kept"] == 1 and report["prompt_version"] == "compile-v2"
    assert {r["prompt_version"] for r in _rules()} == {"compile-v2"}


# ------------------------------------------------------------------------------------- should-haves


def test_a_generic_word_does_not_admit_a_property_the_quote_does_not_print_for_a_figure():
    sentence = "The widget pressure shall not exceed 200 psi."
    assert _plain(sentence, field="widget size") == (None, "field_not_in_quote")


def test_a_lone_decimal_out_of_sequence_is_not_a_heading():
    quote = "The pressure shall not exceed 200 psi."
    page = f"7.3 Part\nSome words here.\n2.5\nMore words here.\n{quote}"
    assert _verify_on(page, quote)[1] is None


def test_a_lone_number_in_sequence_is_a_heading():
    quote = "The pressure shall not exceed 200 psi."
    page = f"7.3 Part\nSome words here.\n8.1\nWidget Lines\n{quote}"
    assert _verify_on(page, quote, clause="8.1")[1] is None


def test_a_negation_in_the_lead_in_drops_the_rule():
    pages = {
        1: "7.3 Part\nWhen the widget is wet, the drain shall not",
        2: "hold a maximum thickness of 77 Poise.",
    }
    over = {
        "field": "maximum thickness",
        "limit": "77",
        "unit": "Poise",
        "condition": "When the widget is wet",
    }
    assert _verify_on(pages, pages[2], **over) == (None, "lead_in_holds_the_obligation")


def test_a_rule_on_a_low_confidence_page_is_flagged_and_not_gated():
    _scanned(conf=0.4)
    report = _compile(FakeBatches())
    rule = _rules()[0]
    assert report["kept"] == 1 and "low_ocr_confidence" in rule["context_flag"]
    assert (
        report["ocr_lowest_confidence"] == 0.4
        and report["kept_with_context_flag"]["low_ocr_confidence"] == 1
    )


def test_a_rule_on_a_clear_page_is_not_flagged_for_confidence():
    _scanned(conf=0.95)
    _compile(FakeBatches())
    assert "low_ocr_confidence" not in (_rules()[0]["context_flag"] or "")


def test_a_scope_in_the_subject_is_a_clause_up_to_its_modal():
    sentence = "Covers for sour lines or wet lines shall be painted."
    over = {"field": "covers", "limit": None, "unit": None, "comparator": None}
    rule, why = _plain(sentence, **over, condition="sour lines or wet lines")
    assert why is None and rule["condition_text"] == "sour lines or wet lines"


def test_part_of_that_scope_is_still_not_a_clause():
    sentence = "Covers for sour lines or wet lines shall be painted."
    over = {"field": "covers", "limit": None, "unit": None, "comparator": None}
    assert (
        _plain(sentence, **over, condition="sour lines")[1] == "condition_not_a_clause"
    )


def test_is_not_exceeded_is_not_flagged_as_a_lost_scope():
    sentence = "The drain shall hold a maximum thickness of 77 Poise is not exceeded."
    rule, why = _plain(sentence, field="maximum thickness", limit="77", unit="Poise")
    assert why is None and rule["context_flag"] is None


@pytest.mark.parametrize(
    "sentence", ["The pressure is 5 bar.", "The pressure of the rail is 5 bar."]
)
def test_a_figure_with_no_modal_the_modal_does_not_bind(sentence):
    assert _plain(sentence, comparator="=", limit="5", unit="bar") == (
        None,
        "limit_not_bound",
    )


def test_a_cue_behind_a_scope_word_the_modal_does_not_bind():
    sentence = "The pressure shall be vented for loads of at most 200 psi."
    assert _plain(sentence) == (None, "limit_not_bound")


def test_a_digit_is_never_a_clause():
    assert (
        compiled_rule_proof._clause_span("5", "the load, 5, shall be painted") is None
    )


def test_a_modal_inside_a_condition_is_not_a_clause():
    sentence = "the load shall be low, the pressure shall be high"
    assert compiled_rule_proof._clause_span("the load shall be low", sentence) is None


def test_a_bracket_with_no_condition_word_still_holds_a_scope():
    sentence = "The pressure shall not exceed 25 bar (during frost)."
    assert _plain(sentence, limit="25", unit="bar") == (None, "condition_not_captured")
    assert _plain(sentence, limit="25", unit="bar", condition="during frost")[1] is None


def test_a_sentence_opening_on_a_scope_word_with_no_comma_holds_a_scope():
    assert _plain("During frost the pressure shall not exceed 200 psi.") == (
        None,
        "condition_not_captured",
    )


# ---------------------------------------------------------------------------------- one batch, many standards

SECOND = "SAES-Z-901"
THIRD = "SAES-Z-902"


def _three():
    _document()
    _document(
        "std-b", SECOND, pages=("5.1 Part\nOTHERWORD pressure shall not exceed 7 bar.",)
    )
    _document(
        "std-c", THIRD, pages=("6.1 Part\nTHIRDWORD pressure shall not exceed 9 bar.",)
    )
    return {DOC: LABEL, "std-b": SECOND, "std-c": THIRD}


def test_named_standards_go_in_one_batch_with_a_report_each():
    documents = _three()
    fake = FakeBatches([])
    reports = standards_compiler.compile_many(
        db.connect(), documents, client=fake, sleep=lambda _s: None
    )
    assert len(fake.created) == 1 and len(fake.created[0]) == 3
    assert [r["standard"] for r in reports] == [LABEL, SECOND, THIRD]
    assert all(r["status"] == "all_pages_answered" for r in reports)


def test_each_request_in_the_one_batch_holds_one_standard_only():
    documents = _three()
    fake = FakeBatches([])
    standards_compiler.compile_many(
        db.connect(), documents, client=fake, sleep=lambda _s: None
    )
    bodies = [json.dumps(r["params"]) for r in fake.created[0]]
    assert (
        sum("OTHERWORD" in b for b in bodies) == 1
        and sum("THIRDWORD" in b for b in bodies) == 1
    )
    assert not any("OTHERWORD" in b and "THIRDWORD" in b for b in bodies)


def test_each_standard_is_charged_on_its_own_step_inside_one_batch():
    documents = _three()
    standards_compiler.compile_many(
        db.connect(), documents, client=FakeBatches([]), sleep=lambda _s: None
    )
    steps = {e["step"] for e in claude_spend.entries()}
    assert steps == {
        claude_spend.STANDARD_STEP_PREFIX + x for x in (LABEL, SECOND, THIRD)
    }


def test_the_per_standard_cap_holds_inside_one_batch(monkeypatch):
    _document(pages=_big_pages(20))
    _document(
        "std-b", SECOND, pages=("5.1 Part\nThe pressure shall not exceed 7 bar.",)
    )
    monkeypatch.setattr(settings, "claude_budget_usd_per_standard", 0.2)
    fake = FakeBatches([])
    reports = standards_compiler.compile_many(
        db.connect(), {DOC: LABEL, "std-b": SECOND}, client=fake, sleep=lambda _s: None
    )
    by_name = {r["standard"]: r for r in reports}
    assert (
        by_name[LABEL]["status"] == "partial" and by_name[LABEL]["chunks_not_sent"] > 0
    )
    assert by_name[SECOND]["status"] == "all_pages_answered" and len(fake.created) == 1


def test_one_refused_standard_sends_nothing_for_any():
    _three()
    _document("std-x", "SAES-Z-903", pages=(PAGE_1,), listed=False)
    fake = FakeBatches([])
    with pytest.raises(claude_spend.DocumentNotApproved):
        standards_compiler.compile_many(
            db.connect(),
            {DOC: LABEL, "std-b": SECOND, "std-x": "SAES-Z-903"},
            client=fake,
        )
    assert fake.created == [] and claude_spend.entries() == []


def test_the_script_given_three_standards_makes_one_batch():
    _three()
    fake = FakeBatches([])
    said = []
    code = compile_standards.run(
        _copy_db(),
        [LABEL, SECOND, THIRD],
        client=fake,
        sleep=lambda _s: None,
        emit=said.append,
        note=lambda _s: None,
    )
    assert code == 0 and len(fake.created) == 1
    assert len(json.loads(said[0])["standards"]) == 3


def test_a_batch_splits_only_at_the_apis_request_limit(monkeypatch):
    documents = _three()
    monkeypatch.setattr(claude_batch_run, "MAX_BATCH_REQUESTS", 2)
    fake = FakeBatches([])
    reports = standards_compiler.compile_many(
        db.connect(), documents, client=fake, sleep=lambda _s: None
    )
    assert [len(c) for c in fake.created] == [2, 1]
    assert all(r["status"] == "all_pages_answered" for r in reports)


def test_a_batch_splits_only_at_the_apis_size_limit(monkeypatch):
    documents = _three()
    monkeypatch.setattr(claude_batch_run, "MAX_BATCH_BYTES", 1)
    fake = FakeBatches([])
    standards_compiler.compile_many(
        db.connect(), documents, client=fake, sleep=lambda _s: None
    )
    assert len(fake.created) == 3


def test_the_same_chunk_in_two_standards_keeps_two_answers():
    same = "5.1 Part\nThe pressure shall not exceed 7 bar."
    _document("std-b", SECOND, pages=(same,))
    _document("std-c", THIRD, pages=(same,))
    fake = FakeBatches([])
    standards_compiler.compile_many(
        db.connect(),
        {"std-b": SECOND, "std-c": THIRD},
        client=fake,
        sleep=lambda _s: None,
    )
    ids = [r["custom_id"] for r in fake.created[0]]
    assert len(set(ids)) == 2
    rows = (
        db.connect()
        .execute(
            "SELECT COUNT(*) AS n FROM claude_batch_requests WHERE state='answered'"
        )
        .fetchone()
    )
    assert rows["n"] == 2


def test_a_run_naming_only_part_of_an_open_batch_is_refused_and_sends_nothing_new():
    documents = _three()
    fake = FakeBatches([])
    fake.hold_open = True
    reports = standards_compiler.compile_many(
        db.connect(), documents, client=fake, sleep=lambda _s: None, max_wait_s=0
    )
    assert all(r["status"] == "waiting" for r in reports)
    with pytest.raises(ProviderRefused, match="name every standard"):
        standards_compiler.compile_many(
            db.connect(), {DOC: LABEL}, client=fake, sleep=lambda _s: None
        )
    assert len(fake.created) == 1


def test_a_crash_resumes_the_one_batch_for_every_standard():
    documents = _three()
    fake = FakeBatches([], crash_first_retrieve=True)
    with pytest.raises(KeyboardInterrupt):
        standards_compiler.compile_many(
            db.connect(), documents, client=fake, sleep=lambda _s: None
        )
    reports = standards_compiler.compile_many(
        db.connect(), documents, client=fake, sleep=lambda _s: None
    )
    assert len(fake.created) == 1 and all(
        r["status"] == "all_pages_answered" for r in reports
    )


# ------------------------------------------------------------------------------------- the normal-price fallback


class _Clock:
    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


HOUR = 3600.0


def _fallback(fake, documents=None, **kw):
    clock = _Clock()
    kw.setdefault("fallback_after_s", HOUR)
    return standards_compiler.compile_many(
        db.connect(),
        documents or {DOC: LABEL},
        client=fake,
        send=fake.send,
        sleep=clock.sleep,
        clock=clock,
        **kw,
    )


def test_the_fallback_is_off_by_default():
    _document()
    fake = FakeBatches()
    fake.hold_open = True
    clock = _Clock()
    report = standards_compiler.compile_standard(
        db.connect(),
        DOC,
        LABEL,
        client=fake,
        send=fake.send,
        sleep=clock.sleep,
        clock=clock,
        max_wait_s=2 * HOUR,
    )
    assert report["status"] == "waiting" and fake.cancelled == () and fake.normal == []


def test_a_batch_back_in_time_sends_nothing_at_the_normal_price():
    _document()
    fake = FakeBatches()
    report = _fallback(fake)[0]
    assert (
        report["status"] == "all_pages_answered" and report["sent_at_normal_price"] == 0
    )
    assert fake.normal == [] and fake.cancelled == ()


def test_an_overdue_batch_is_cancelled_first_then_what_it_left_is_sent_normally():
    _document()
    fake = FakeBatches()
    fake.hold_open = True
    report = _fallback(fake)[0]
    assert fake.cancelled == ("msgbatch_1",) and len(fake.normal) == 1
    assert (
        report["status"] == "all_pages_answered" and report["sent_at_normal_price"] == 1
    )
    assert report["kept"] == 1 and report["batches_cancelled"] == 1
    assert _rules()[0]["batch_id"] == claude_batch_run.NORMAL_SEND


def test_the_fallback_waits_the_time_it_was_given():
    _document()
    fake = FakeBatches()
    fake.hold_open = True
    clock = _Clock()
    start = clock.now
    standards_compiler.compile_many(
        db.connect(),
        {DOC: LABEL},
        client=fake,
        send=fake.send,
        sleep=clock.sleep,
        clock=clock,
        fallback_after_s=HOUR,
        poll_seconds=60.0,
    )
    assert HOUR <= clock.now - start < HOUR + 300


def test_a_partial_cancel_keeps_what_the_batch_finished_and_sends_only_the_rest():
    pages = _two_chunk_pages()
    _document(pages=pages)
    first, _second = (
        c.custom_id for c in standards_compiler.chunks_of(dict(enumerate(pages, 1)))
    )
    fake = FakeBatches([])
    fake.hold_open = True
    fake.done_before_cancel = (first,)
    report = _fallback(fake)[0]
    assert len(fake.normal) == 1 and report["sent_at_normal_price"] == 1
    sent = json.dumps(fake.normal[0]["messages"])
    assert "The two widget" in sent and "The one widget" not in sent
    prices = [bool(e.get("batch")) for e in claude_spend.entries() if e.get("settles")]
    assert sorted(prices) == [False, True]


def test_a_failed_cancel_sends_nothing():
    _document()
    fake = FakeBatches()
    fake.hold_open = True
    fake.cancel_fails = True
    report = _fallback(fake)[0]
    assert report["status"] == "waiting" and fake.normal == []
    assert [
        e for e in claude_spend.entries() if e.get("reserved")
    ]  # still held at its worst case


def test_a_cancel_that_does_not_finish_sends_nothing_and_the_next_run_goes_on():
    _document()
    fake = FakeBatches()
    fake.never_ends = True
    report = _fallback(fake)[0]
    assert (
        report["status"] == "waiting"
        and fake.normal == []
        and fake.cancelled == ("msgbatch_1",)
    )
    fake.never_ends = False
    again = _fallback(fake)[0]
    assert (
        again["status"] == "all_pages_answered"
        and len(fake.normal) == 1
        and len(fake.cancelled) == 1
    )


def test_a_request_is_never_answered_twice_at_two_prices():
    pages = _two_chunk_pages()
    _document(pages=pages)
    first, second = (
        c.custom_id for c in standards_compiler.chunks_of(dict(enumerate(pages, 1)))
    )
    fake = FakeBatches([])
    fake.hold_open = True
    fake.done_before_cancel = (first, second)
    report = _fallback(fake)[0]
    assert fake.normal == [] and report["sent_at_normal_price"] == 0


def test_a_batch_result_arriving_late_is_used_not_bought_again():
    _document()
    fake = FakeBatches()
    cid = standards_compiler.chunks_of({1: PAGE_1, 2: PAGE_2})[0].custom_id
    fake.hold_open = True
    fake.cancel_fails = False
    fake.done_before_cancel = (cid,)
    fake.missing_once = {cid}
    first = _fallback(fake)[
        0
    ]  # the row is missing, charged its worst case, and sent normally
    assert first["sent_at_normal_price"] == 1
    lines = len(claude_spend.entries())
    charged = claude_spend.spent(standards_converter.step_for(LABEL))
    fake.missing_once = set()
    with db.connect() as conn:
        conn.execute("UPDATE claude_batch_requests SET answer = ?", ('{"rules": []}',))
        conn.execute("DELETE FROM compiled_rules")
        conn.execute("DELETE FROM compile_runs")
    second = standards_compiler.compile_many(
        db.connect(), {DOC: LABEL}, client=fake, send=fake.send, sleep=lambda _s: None
    )[0]
    row = db.connect().execute("SELECT answer FROM claude_batch_requests").fetchone()
    assert (
        row["answer"] == '{"rules": []}'
    )  # the late one is kept raw and replaces nothing
    assert second["late_results"] == 1
    assert (
        len(claude_spend.entries()) == lines
        and claude_spend.spent(standards_converter.step_for(LABEL)) == charged
    )


def test_a_late_row_with_no_other_answer_saves_the_send():
    _document(pages=("7.3 Part\nThe pressure shall not exceed 200 psi.",))
    fake = FakeBatches([])
    cid = standards_compiler.chunks_of(
        {1: "7.3 Part\nThe pressure shall not exceed 200 psi."}
    )[0].custom_id
    fake.kinds = {cid: ["missing", "missing"]}
    report = standards_compiler.compile_standard(
        db.connect(), DOC, LABEL, client=fake, sleep=lambda _s: None
    )
    assert report["status"] == "partial"
    fake.kinds = {}
    again = standards_compiler.compile_standard(
        db.connect(), DOC, LABEL, client=fake, sleep=lambda _s: None
    )
    assert again["status"] == "all_pages_answered" and again["late_results"] >= 1
    assert len(fake.created) == 2


def test_a_late_result_on_an_answered_request_is_charged_at_the_batch_price_and_replaces_nothing():
    _document()
    fake = FakeBatches()
    fake.hold_open = True
    _fallback(fake)
    with db.connect() as conn:
        conn.execute("UPDATE claude_batches SET state = 'open'")
        conn.execute("DELETE FROM compiled_rules")
        conn.execute("DELETE FROM compile_runs")
        conn.execute(
            "UPDATE claude_batch_requests SET batch_row = (SELECT id FROM claude_batches LIMIT 1)"
        )
    fake.hold_open = False
    fake.cancelled = ()
    before = claude_spend.spent(standards_converter.step_for(LABEL))
    report = standards_compiler.compile_standard(
        db.connect(), DOC, LABEL, client=fake, sleep=lambda _s: None
    )
    assert report["late_results"] == 1 and report["status"] == "all_pages_answered"
    late = [
        e
        for e in claude_spend.entries()
        if e.get("finish_reason") == "late_batch_result"
    ]
    assert len(late) == 1 and late[0]["batch"] is True and late[0]["cost_usd"] > 0
    assert claude_spend.spent(standards_converter.step_for(LABEL)) > before
    assert _rules()[0]["batch_id"] == claude_batch_run.NORMAL_SEND


def test_the_normal_send_carries_the_same_model_and_prompt():
    _document()
    fake = FakeBatches()
    fake.hold_open = True
    _fallback(fake)
    batch_params, normal = fake.created[0][0]["params"], fake.normal[0]
    assert normal["model"] == batch_params["model"] == MODEL
    assert normal["system"][0]["text"] == batch_params["system"][0]["text"]
    assert normal["messages"] == batch_params["messages"]
    assert _rules()[0]["prompt_version"] == standards_compiler.PROMPT_VERSION
    assert _rules()[0]["model"] == ANSWERED


def test_the_normal_send_uses_the_same_answer_cache():
    _document()
    fake = FakeBatches()
    fake.hold_open = True
    _fallback(fake)
    with db.connect() as conn:
        for table in (
            "compiled_rules",
            "compile_runs",
            "claude_batch_requests",
            "claude_batches",
        ):
            conn.execute(f"DELETE FROM {table}")
    fake2 = FakeBatches()
    fake2.hold_open = True
    report = _fallback(fake2)[0]
    assert fake2.normal == [] and report["kept"] == 1


def test_a_spend_line_says_batch_or_normal_and_the_normal_costs_twice():
    usage = {"input_tokens": 1000, "output_tokens": 500}
    entry = claude_spend.record(
        step="s",
        model=MODEL,
        usage=usage,
        prompt_sha256="",
        wall_time_s=0.0,
        finish_reason="x",
    )
    batch = claude_spend.record(
        step="s",
        model=MODEL,
        usage=usage,
        prompt_sha256="",
        wall_time_s=0.0,
        finish_reason="x",
        batch=True,
    )
    assert "batch" not in entry and batch["batch"] is True
    assert entry["cost_usd"] == pytest.approx(2 * batch["cost_usd"])


def test_a_normal_send_is_settled_at_the_normal_price():
    _document()
    fake = FakeBatches()
    fake.hold_open = True
    _fallback(fake)
    line = next(e for e in claude_spend.entries() if e.get("settles"))
    assert "batch" not in line
    assert line["cost_usd"] == pytest.approx(
        claude_spend.cost_usd(ANSWERED, {"input_tokens": 100, "output_tokens": 50})
    )


def test_the_fallback_reservation_is_at_the_normal_worst_case(monkeypatch):
    _document()
    packet = next(
        iter(
            standards_compiler.packets_of(
                LABEL,
                {1: PAGE_1, 2: PAGE_2},
                standards_compiler.chunks_of({1: PAGE_1, 2: PAGE_2}),
            ).values()
        )
    )
    normal = claude_batch_run.worst_usd(MODEL, packet, batch=False)
    assert normal == pytest.approx(2 * claude_batch_run.worst_usd(MODEL, packet))
    held = []
    real = claude_spend.reserve_all

    def spy(items, **kw):
        held.append((items[0][1], kw.get("batch", False)))
        return real(items, **kw)

    monkeypatch.setattr(claude_spend, "reserve_all", spy)
    fake = FakeBatches()
    fake.hold_open = True
    _fallback(fake)
    assert held[0][1] is True and held[1][1] is False and held[1][0] > held[0][0]


@pytest.mark.parametrize(
    "setting", ["claude_budget_usd_per_standard", "claude_budget_usd_total"]
)
def test_the_fallback_stops_at_a_cap_and_reports_partial_with_what_was_not_sent(
    monkeypatch, setting
):
    pages = _big_pages(30)
    _document(pages=pages)
    per_request = 0.12
    cap = per_request * 15
    monkeypatch.setattr(settings, setting, cap)
    fake = FakeBatches([])
    fake.hold_open = True
    fake.normal_output = 12000
    report = _fallback(fake)[0]
    assert report["status"] == "partial" and report["chunks_not_sent"] > 0
    assert (
        report["sent_at_normal_price"] + report["chunks_not_sent"] == report["chunks"]
    )
    assert report["pages_not_read"]
    assert claude_spend.spent() <= cap


def test_the_fallback_stops_at_the_daily_limit():
    _document(pages=_big_pages(30))
    fake = FakeBatches([])
    fake.hold_open = True
    fake.normal_output = 12000
    report = _fallback(fake, max_usd=1.0)[0]
    assert report["status"] == "partial" and report["chunks_not_sent"] > 0
    assert claude_spend.spent() <= 1.0


def test_a_normal_price_over_the_cap_stops_there_and_names_the_rest():
    pages = tuple(
        f"{n}.1 Part\n" + "invented filler words of a page line\n" * 250
        for n in range(1, 300)
    )
    numbered = dict(enumerate(pages, 1))
    packets = standards_compiler.packets_of(
        LABEL, numbered, standards_compiler.chunks_of(numbered)
    )
    worst = standards_compiler.estimate(MODEL, packets)
    assert worst["worst_usd"] < 25.0 < worst["worst_usd_normal_price"]
    _document(pages=pages)
    fake = FakeBatches([])
    fake.hold_open = True
    fake.normal_output = 12000
    report = _fallback(fake)[0]
    assert report["status"] == "partial" and report["chunks_not_sent"] > 0
    assert claude_spend.spent(standards_converter.step_for(LABEL)) <= 25.0


def test_the_estimate_gives_both_prices_and_how_the_cap_stops_the_dearer():
    pages = tuple(
        f"{n}.1 Part\n" + "invented filler words of a page line\n" * 250
        for n in range(1, 300)
    )
    _document(pages=pages)
    report = standards_compiler.compile_standard(
        db.connect(), DOC, LABEL, client=FakeBatches(), estimate_only=True
    )
    estimate_ = report["estimate"]
    assert estimate_["worst_usd"] < 25.0 and estimate_["over_per_standard_cap"] is False
    assert estimate_["normal_price_over_per_standard_cap"] is True
    assert estimate_["normal_price_stops_at_usd"] == 25.0


def test_the_script_prints_the_batch_and_the_fallback_worst_case():
    _three()
    said = []
    assert (
        compile_standards.run(
            _copy_db(),
            [LABEL, SECOND, THIRD],
            estimate_only=True,
            emit=said.append,
            note=lambda _s: None,
        )
        == 0
    )
    out = json.loads(said[0])
    assert out["requests_total"] == 3 and out["batches_needed"] == 1
    assert out["fallback_worst_usd_normal_price_total"] == pytest.approx(
        2 * out["worst_usd_total"], rel=0.01
    )
    assert out["fallback_stops_at_usd_total"] > 0


def test_batches_needed_counts_the_apis_limits():
    assert claude_batch_run.batches_needed(0, 0) == 0
    assert claude_batch_run.batches_needed(1, 10) == 1
    assert claude_batch_run.batches_needed(100_001, 10) == 2
    assert claude_batch_run.batches_needed(5, claude_batch_run.MAX_BATCH_BYTES + 1) == 2


def test_the_script_takes_the_fallback_option_off_by_default():
    fallback = compile_standards.run.__kwdefaults__["fallback_after_s"]
    assert fallback is None


def test_batch_cancel_goes_through_the_gate_and_refuses_a_strange_id(monkeypatch):
    from app import reader_transport

    calls = []

    class Reply:
        status_code = 200

        def json(self):
            return {"id": "b", "processing_status": "canceling"}

    monkeypatch.setattr(
        reader_transport,
        "_gated",
        lambda method, url, **kw: calls.append((method, url)) or Reply(),
    )
    out = reader_transport.batch_cancel(
        "https://x/v1/messages", "msgbatch_1", headers={}
    )
    assert out["processing_status"] == "canceling"
    assert calls == [("POST", "https://x/v1/messages/batches/msgbatch_1/cancel")]
    with pytest.raises(reader_transport.TransportRefused):
        reader_transport.batch_cancel("https://x/v1/messages", "../x", headers={})


def test_batch_cancel_is_shut_with_egress_off():
    from app import reader_transport

    with_egress_off = settings.standards_reader_enabled
    settings.standards_reader_enabled = False
    try:
        with pytest.raises(reader_transport.TransportRefused):
            reader_transport.batch_cancel(
                "https://api.anthropic.com/v1/messages", "b1", headers={}
            )
    finally:
        settings.standards_reader_enabled = with_egress_off


# ------------------------------------------------------------------------------------- the cost audit (#1595)


def _other_route(usd, step="chat"):
    claude_spend.record(
        step=step,
        model=MODEL,
        usage=None,
        prompt_sha256="",
        wall_time_s=0.0,
        finish_reason="x",
        estimated_usd=usd,
    )


def test_the_day_limit_counts_every_route_not_only_this_job():
    _document()
    _other_route(1.0)
    fake = FakeBatches()
    with pytest.raises(standards_compiler.TooDear):
        _compile(fake, max_usd=1.0)
    assert fake.created == []


def test_a_day_nearly_full_sends_what_fits_and_names_the_rest():
    _document(pages=_big_pages(20))
    fake = FakeBatches([])
    report = _compile(fake, max_usd=0.5)
    assert report["status"] == "partial" and 0 < len(fake.created[0]) < report["chunks"]
    assert report["chunks_not_sent"] == report["chunks"] - len(fake.created[0])


def test_the_report_keeps_what_was_spent_apart_from_what_is_held():
    _document()
    fake = FakeBatches()
    _still_running(fake)
    report = _compile(fake, max_wait_s=0)
    assert report["status"] == "waiting"
    assert report["usd_on_this_standards_step"] == 0 and report["usd_still_held"] > 0


def _left_over_hold(step, age_s=0.0):
    held = claude_spend.reserve(step, 24.97, model=MODEL)
    return held


def test_a_hold_nothing_owns_older_than_any_batch_does_not_block_a_standard():
    _document()
    _left_over_hold(standards_converter.step_for(LABEL))
    fake = FakeBatches()
    clock = _Clock()
    clock.now += standards_compiler.STALE_HOLD_S + 60
    report = standards_compiler.compile_standard(
        db.connect(), DOC, LABEL, client=fake, sleep=clock.sleep, clock=clock
    )
    assert report["status"] == "all_pages_answered" and report["holds_released"] == 1
    assert report["holds_released_usd"] == 24.97 and report["usd_still_held"] == 0


def test_a_young_hold_nothing_owns_stays_counted_unless_the_operator_says():
    _document()
    _left_over_hold(standards_converter.step_for(LABEL))
    fake = FakeBatches()
    with pytest.raises(standards_compiler.TooDear):
        standards_compiler.compile_standard(
            db.connect(), DOC, LABEL, client=fake, sleep=lambda _s: None
        )
    report = standards_compiler.compile_standard(
        db.connect(), DOC, LABEL, client=fake, sleep=lambda _s: None, release_holds=True
    )
    assert report["status"] == "all_pages_answered" and report["holds_released"] == 1


def test_a_hold_a_running_batch_owns_is_never_released():
    _document()
    fake = FakeBatches()
    _still_running(fake)
    _compile(fake, max_wait_s=0)
    freed = standards_compiler.release_left_over_holds(
        db.connect(), {standards_converter.step_for(LABEL)}, force=True
    )
    assert freed["holds_released"] == 0
    assert [e for e in claude_spend.entries() if e.get("reserved")]


def test_a_hold_on_another_standard_is_left_alone():
    _document()
    _left_over_hold(standards_converter.step_for("SAES-A-1"))
    freed = standards_compiler.release_left_over_holds(
        db.connect(), {standards_converter.step_for(LABEL)}, force=True
    )
    assert freed["holds_released"] == 0


def test_ensure_schema_takes_no_argument_like_every_other_module():
    standards_compiler.ensure_schema()
    claude_batch_run.ensure_schema()
    names = {
        r["name"]
        for r in db.connect().execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"compiled_rules", "compile_runs", "claude_batches"} <= names


# --------------------------------------------------------------------------------------- third review


@pytest.mark.parametrize(
    "sentence, comparator",
    [
        ("The pressure shall not be above 200 psi.", ">"),
        ("The pressure shall not be over 200 psi.", ">"),
        ("The pressure shall not be below 200 psi.", "<"),
        ("The pressure shall not be under 200 psi.", "<"),
        ("No pressure shall be above 200 psi.", ">"),
        ("No widget pressure shall exceed 200 psi.", ">"),
        ("The pressure shall never be above 200 psi.", ">"),
    ],
)
def test_a_negated_comparator_never_stores_the_opposite_direction(sentence, comparator):
    assert _plain(sentence, comparator=comparator) == (None, "comparator_negated")


@pytest.mark.parametrize(
    "sentence, comparator",
    [
        ("The pressure shall not exceed 200 psi.", "<="),
        ("The pressure shall not be more than 200 psi.", "<="),
        ("The pressure shall not be less than 200 psi.", ">="),
        ("The pressure shall be no more than 200 psi.", "<="),
    ],
)
def test_a_comparator_whose_words_hold_the_negation_is_kept(sentence, comparator):
    rule, why = _plain(sentence, comparator=comparator)
    assert why is None and rule["comparator"] == comparator


@pytest.mark.parametrize(
    "rest",
    ["or 30 bar for gas.", "alternatively 30 bar.", "30 bar whichever is greater."],
)
def test_an_alternative_in_the_next_semicolon_clause_keeps_no_figure(rest):
    sentence = f"The pressure shall be 25 bar; {rest}"
    quote = "The pressure shall be 25 bar;"
    assert _verify_on(
        f"7.3 Part\n{sentence}", quote, comparator="=", limit="25", unit="bar"
    ) == (None, "alternative_not_one_figure")


def test_a_separate_rule_after_a_semicolon_is_not_an_alternative():
    sentence = "The pressure shall be 25 bar; the widget load shall be 30 bar."
    quote = "The pressure shall be 25 bar;"
    assert (
        _verify_on(
            f"7.3 Part\n{sentence}", quote, comparator="=", limit="25", unit="bar"
        )[1]
        is None
    )


@pytest.mark.parametrize(
    "opener",
    [
        "In frost",
        "On rails",
        "When wet",
        "If wet",
        "Where wet",
        "While wet",
        "Until dry",
        "Once dry",
        "Unless dry",
        "Within plants",
        "After tests",
        "Before tests",
        "Given frost",
        "Provided dry",
    ],
)
def test_an_opener_with_no_comma_holds_a_scope(opener):
    assert _plain(f"{opener} the pressure shall not exceed 200 psi.")[0] is None


@pytest.mark.parametrize(
    "sentence",
    [
        "Pumps 5 kW and larger pressure shall not exceed 200 psi.",
        "The 10 inch widget pressure shall not exceed 200 psi.",
    ],
)
def test_a_figure_in_the_subject_is_a_scope(sentence):
    assert _plain(sentence) == (None, "condition_not_captured")


def test_a_figure_in_the_second_subject_is_a_scope():
    sentence = (
        "Covers shall be painted and 10 inch widget pressure shall not exceed 200 psi."
    )
    assert _plain(sentence)[0] is None


@pytest.mark.parametrize(
    "sentence",
    [
        "The pressure (gas lines) shall not exceed 25 bar.",
        "The pressure shall not exceed 25 bar (gas lines).",
    ],
)
def test_a_bracketed_noun_is_a_scope(sentence):
    assert _plain(sentence, limit="25", unit="bar") == (None, "condition_not_captured")
    assert (
        _plain(sentence, limit="25", unit="bar", condition="gas lines")[1]
        != "condition_not_captured"
    )


def test_a_bracket_the_field_names_is_not_a_scope():
    sentence = "The drain pressure (sump hole) shall not exceed 25 bar."
    rule, why = _plain(
        sentence, field="drain pressure (sump hole)", limit="25", unit="bar"
    )
    assert why is None and rule["field"] == "drain pressure"


def test_a_pressure_reference_in_brackets_is_not_a_scope():
    _rule_kept, why = _plain(
        "The pressure shall not exceed 25 bar (gauge).", limit="25", unit="bar"
    )
    assert why is None


def test_a_bracket_after_the_modal_of_a_sentence_with_no_figure_is_not_a_scope():
    sentence = "Covers shall be made of Alloy 9 (UNS N1)."
    _rule_kept, why = _plain(
        sentence, field="covers", limit=None, unit=None, comparator=None
    )
    assert why is None


def test_a_held_condition_does_not_excuse_a_second_one_in_the_middle():
    sentence = "For frost, the widget in gas service shall be painted."
    over = {
        "field": "widget",
        "limit": None,
        "unit": None,
        "comparator": None,
        "condition": "For frost",
    }
    assert _plain(sentence, **over) == (None, "condition_not_captured")
    assert (
        _plain(sentence, **{**over, "condition": "For frost; in gas service"})[1]
        is None
    )


def test_the_limit_belongs_to_the_subject_of_its_own_modal():
    sentence = "Pumps shall be vented and the valve pressure shall not exceed 200 psi."
    assert _plain(sentence, field="pump") == (None, "limit_not_bound")
    assert _plain(sentence, field="valve pressure")[1] is None


def test_an_exception_in_the_next_sentence_is_flagged():
    sentence = "The pressure shall not exceed 200 psi."
    page = f"7.3 Part\n{sentence}\nThis does not apply to cold plants."
    rule, why = _verify_on(page, sentence)
    assert why is None and "next_sentence_exception" in rule["context_flag"]
    assert rule["strength"] == "context_dependent"


@pytest.mark.parametrize(
    "words", ["Exception:", "However, cold plants may differ.", "Except cold plants."]
)
def test_other_exception_openers_are_flagged(words):
    sentence = "The pressure shall not exceed 200 psi."
    rule, why = _verify_on(f"7.3 Part\n{sentence} {words}", sentence)
    assert why is None and "next_sentence_exception" in rule["context_flag"]


def test_unset_means_no_normal_send_even_after_a_flagged_run_left_a_batch_canceling():
    _document()
    fake = FakeBatches()
    fake.never_ends = True
    assert _fallback(fake)[0]["status"] == "waiting"
    fake.never_ends = False
    report = standards_compiler.compile_standard(
        db.connect(), DOC, LABEL, client=fake, send=fake.send, sleep=lambda _s: None
    )
    assert fake.normal == [] and report["sent_at_normal_price"] == 0
    assert report["status"] == "all_pages_answered" and len(fake.created) == 2


def test_unset_waits_on_a_canceling_batch_and_sends_nothing():
    _document()
    fake = FakeBatches()
    fake.never_ends = True
    _fallback(fake)
    clock = _Clock()
    report = standards_compiler.compile_standard(
        db.connect(),
        DOC,
        LABEL,
        client=fake,
        send=fake.send,
        sleep=clock.sleep,
        clock=clock,
        max_wait_s=120.0,
    )
    assert (
        report["status"] == "waiting" and fake.normal == [] and len(fake.created) == 1
    )


def test_shall_not_be_a_figure_is_never_an_equal_limit():
    assert _plain("The pressure shall not be 200 psi.", comparator="=")[0] is None
