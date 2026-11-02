"""#1584: the standards compiler. Invented standard text only; the Batch API is a fake that holds what it was sent,
answers in any order and computes usage from the request body the way the real cache does. No real Claude call."""

from __future__ import annotations

import json
import random
import sqlite3
import sys
from pathlib import Path

import pytest

from app import (
    claude_approved,
    claude_batch_run,
    claude_spend,
    comparison,
    db,
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
        "condition": None,
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
        return {
            "id": batch_id,
            "processing_status": "ended",
            "results_url": "https://x/results",
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
        rows = []
        for request in self.created[-1]:
            cid, params = request["custom_id"], request["params"]
            kinds = self.kinds.get(cid) or self.kinds.get("*") or []
            kind = kinds.pop(0) if kinds else "succeeded"
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
        report["status"] == "complete"
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
    assert _drop_reason(_rule(clause="9.9.9")) == {"clause_not_on_page": 1}


def test_a_scope_after_the_limit_becomes_the_condition_even_when_the_quote_stops_at_the_limit():
    _document()
    cut = "The relief flange pressure shall not exceed 25 bar"
    _compile(FakeBatches([_rule(quote=cut)]))
    assert _rules()[0]["condition_text"] == "for gas service"


def test_a_requirement_with_no_number_is_kept_with_no_limit():
    _document()
    words = "The widget shall be painted."
    _compile(
        FakeBatches(
            [_rule(quote=words, field="widget", limit=None, unit=None, comparator=None)]
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


def test_a_cut_answer_is_counted_and_its_pages_are_named_not_re_bought():
    _document()
    fake = FakeBatches(stop="max_tokens")
    report = _compile(fake)
    assert report["kept"] == 0 and report["pages_not_read"] == [1, 2]
    assert len(report["chunks_truncated"]) == 1 and len(fake.created) == 1


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
    assert readers == ["standards_compiler.py"]


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
    assert _compile(fake)["status"] == "complete"
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
        report["status"] == "complete"
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
        _compile(fake, resend_unconfirmed=True)["status"] == "complete"
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
    assert report["pages_not_read"] == [1, 2]
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


def test_one_request_over_the_per_step_cap_refuses(monkeypatch):
    _document()
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 0.0001)
    fake = FakeBatches()
    with pytest.raises(standards_compiler.TooDear):
        _compile(fake)
    assert fake.created == []


def test_a_requeue_is_checked_against_the_budget_again():
    _document()
    fake = FakeBatches(kinds={"*": ["expired"]})
    calls = []

    def gate(worst):
        calls.append(worst)
        if len(calls) == 2:
            raise standards_compiler.TooDear("no")

    packets = {
        "a": Packet(
            prompt="invented",
            num_ctx=0,
            num_predict=10,
            step="standards_convert:SAES-Z-900",
        )
    }
    with claude_approved.carrying(()):
        with pytest.raises(standards_compiler.TooDear):
            claude_batch_run.run(
                db.connect(),
                ClaudeProvider(MODEL),
                "job",
                packets,
                client=fake,
                may_send=gate,
                sleep=lambda _s: None,
            )
    assert len(fake.created) == 1 and len(calls) == 2


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


def test_a_family_on_hold_is_refused():
    _document("std-api", "API 000", pages=(PAGE_1,))
    fake = FakeBatches()
    with pytest.raises(standards_converter.FamilyNotAllowed):
        standards_compiler.compile_standard(
            db.connect(), "std-api", "API 000", client=fake
        )
    assert fake.created == []


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
    assert _compile(fake)["status"] == "complete" and len(fake.created) == 1


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
    said = []
    code = compile_standards.run(
        _copy_db(),
        [LABEL],
        client=FakeBatches(),
        sleep=lambda _s: None,
        emit=said.append,
    )
    assert code == 0 and said[0].startswith("worst case before sending")
    report = json.loads(said[1])
    assert report["kept"] == 1 and report["models_answering"] == [ANSWERED]
    assert report["usd_on_this_standards_step"] > 0 and report["usd_boundary"]
    assert QUOTE not in "\n".join(said) and "invented" not in "\n".join(said).lower()


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
