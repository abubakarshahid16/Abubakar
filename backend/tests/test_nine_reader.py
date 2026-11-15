"""Role 1, the Reader and its fact sheet (`nine_reader`, `nine_facts`). Invented pages and answers only; a fake seam and a fake local model: no model is
loaded, nothing leaves. What each test guards (each fails without the code it names):

  * a value whose quote is not on the page is dropped and counted by reason, never a fact;
  * a stored value and a read value that differ are `conflict` and are not used (nor in the digest's usable part);
  * a page with no text on the local model is "not read" with the reason, never "read", and no model is asked;
  * a picture is counted by the image rule, not as text; Claude gets the picture as its own block; Local gets none;
  * a stale stored value (its page text changed) is not used and is counted;
  * the sheet is stored per run, replaced on a rerun, and read back; a run without one gives None.
"""

from __future__ import annotations

import json
import re
import sqlite3
import struct
import zlib

import pytest

from app import (
    agent_claude,
    claude_spend,
    db,
    nine_facts,
    nine_reader,
    nine_record,
    review_shown,
    submittal_review,
)
from app import agent_review_calculator_reader as reader_mod
from app.config import settings
from app.nine_call import FakeTransport, RoleGate

NOW = "2026-11-16T00:00:00Z"
PAGE1 = "Design pressure: 12 barg\nDesign temperature: 150 C\n"
PAGE2 = "Notes\nDesign pressure: 14 barg\n"


@pytest.fixture(autouse=True)
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "nine.sqlite")
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    agent_claude.reset_shared_meter_for_tests()
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    with db.connect() as conn:
        for doc in ("paper", "other"):
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
                (doc, f"{doc}.pdf", doc * 8, f"{doc}.pdf", NOW),
            )
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at) VALUES ('run1','paper','running',?,?)",
            (NOW, NOW),
        )
        review_shown.record_in(conn, "run1", ["paper"], NOW)
    nine_record.start_run("run1")
    yield
    db.reset_connection()


def answer(*rows) -> str:
    return json.dumps(
        {
            "fields": [
                dict(zip(("field_key", "value", "unit", "quote", "status"), r))
                for r in rows
            ]
        }
    )


GOOD = ("design_pressure", "12", "barg", "Design pressure: 12 barg", "found")
TEMP = ("design_temperature", "150", "C", "Design temperature: 150 C", "found")


def _page_of(content) -> int:
    return int(re.search(r"PAGE (\d+):", content[-1]["text"]).group(1))


class Tx(FakeTransport):
    """Answers per page: `text_of(page)`; keeps the bodies."""

    def __init__(self, text_of=None):
        super().__init__(["{}"])
        self.text_of = text_of or (lambda page: answer(GOOD, TEMP))

    def __call__(self, url, *, headers, body, timeout):
        self.answers = [self.text_of(_page_of(body["messages"][0]["content"]))]
        return super().__call__(url, headers=headers, body=body, timeout=timeout)


class Local:
    def __init__(self, text_of=None):
        self.parts: list[dict] = []
        self.text_of = text_of or (lambda page: answer(GOOD, TEMP))

    def __call__(self, parts):
        self.parts.append(parts)
        return {
            "text": self.text_of(_page_of(parts["messages"][0]["content"])),
            "model": "local-x",
        }


def read(pages, tx=None, stored=(), engine="claude", local=None, **kw):
    extra = (
        {"local_send": local}
        if engine == "local"
        else {"send": tx or Tx(), "env": FakeTransport.ENV}
    )
    return nine_reader.read_paper(
        run_id="run1",
        paper_id="paper",
        pages=pages,
        stored_facts=list(stored),
        engine=engine,
        **extra,
        **kw,
    )


def png(w, h) -> bytes:
    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
        + chunk(b"IEND", b"")
    )


def stored(label, value, unit, page=1, quote=None, sha=None, **kw):
    return {
        "id": f"s-{label}-{page}",
        "page": page,
        "field_label": label,
        "field_name": label.lower(),
        "raw_value": value,
        "raw_unit": unit,
        "source_text": quote or f"{label}: {value} {unit}",
        "equipment_tag": None,
        "is_blank": 0,
        "page_text_sha": sha,
        "normalized_value": None,
        "normalized_unit": None,
        "field_value": f"{value} {unit}",
        **kw,
    }


def test_a_value_whose_quote_is_not_on_the_page_is_dropped_and_counted():
    bad = ("design_pressure", "12", "barg", "Design pressure is twelve barg", "found")
    res = read({1: PAGE1}, Tx(lambda p: answer(bad, TEMP)))
    assert [f.field_label for f in res.sheet.facts] == ["Design temperature"]
    assert res.produced["dropped"] == 1
    assert res.produced["dropped_by_reason"] == {"quote_not_on_page": 1}


def test_a_stored_and_a_read_value_that_differ_are_conflict_and_not_used():
    res = read(
        {1: PAGE1},
        stored=[
            stored("Design pressure", "10", "barg", quote="Design pressure: 12 barg")
        ],
    )
    states = {f.field_label: f.state for f in res.sheet.facts}
    assert states["Design pressure"] == "conflict"
    pressure = [f for f in res.sheet.facts if f.field_label == "Design pressure"]
    assert len(pressure) == 2 and {f.source for f in pressure} == {"stored", "ai_text"}
    assert all(f.field_label != "Design pressure" for f in nine_facts.usable(res.sheet))
    assert res.sheet.conflicts == 2
    text = nine_facts.digest(res.sheet)
    assert "READ TWO WAYS, NOT USED (2)" in text
    assert text.split("READ TWO WAYS")[0].count("Design pressure") == 0


def test_an_agreeing_stored_and_read_value_is_one_agreed_fact():
    res = read({1: PAGE1}, stored=[stored("Design pressure", "12", "barg")])
    pressure = [f for f in res.sheet.facts if f.field_label == "Design pressure"]
    assert [f.state for f in pressure] == ["agreed"]


def test_a_stale_stored_value_is_not_used_and_is_counted():
    old = stored(
        "Design pressure",
        "99",
        "barg",
        quote="Design pressure: 99 barg",
        sha=reader_mod.page_sha("an earlier text"),
    )
    res = read({1: PAGE1}, Tx(lambda p: answer(TEMP)), stored=[old])
    assert res.produced["stale_stored_values"] == 1
    assert len([f for f in res.sheet.facts if f.state == "stale"]) == 1
    assert all(f.value != "99" for f in nine_facts.usable(res.sheet))


def test_a_page_with_no_text_on_local_is_not_read_with_the_reason_and_no_model_is_asked():
    local = Local()
    res = read({1: PAGE1, 2: ""}, engine="local", local=local)
    p2 = res.sheet.pages[1]
    assert (p2.page, p2.text_read, p2.picture_read) == (2, False, False)
    assert p2.not_read_why == nine_reader.NO_TEXT_LOCAL
    assert res.state == "ran_partly" and nine_reader.NO_TEXT_LOCAL in res.why
    assert all("PAGE 2" not in json.dumps(p) for p in local.parts)
    assert res.sheet.pages[0].text_read is True


def test_local_reads_text_only_says_so_and_never_sends_a_picture():
    local = Local()
    called = []
    res = read(
        {1: PAGE1},
        engine="local",
        local=local,
        picture_of=lambda n: called.append(n) or png(100, 100),
    )
    assert called == [] and res.produced["pictures"] == nine_reader.PICTURES_LOCAL
    assert res.produced["pages_with_picture"] == 0
    assert "image" not in json.dumps(local.parts)
    assert all(not f.source.endswith("picture") for f in res.sheet.facts)


def test_picture_tokens_are_counted_by_the_image_rule_not_as_text():
    from app.claude_image_tokens import image_tokens

    pic = png(1000, 1000)
    est = nine_reader.estimate({1: PAGE1}, {1: pic})
    assert est["picture_tokens"] == image_tokens(1000, 1000) == 1334
    assert est["text_tokens"] == len(PAGE1) // 3
    assert est["picture_tokens"] != len(pic) // 3


def test_claude_gets_the_picture_in_the_same_block_as_the_text_and_the_fact_says_so():
    tx = Tx()
    res = read({1: PAGE1}, tx, picture_of=lambda n: png(100, 100))
    content = tx.bodies[0]["messages"][0]["content"]
    kinds = [c["type"] for c in content]
    assert kinds.count("image") == 1 and PAGE1 in [c.get("text") for c in content]
    assert (
        PAGE1.strip() not in content[-1]["text"]
    )  # the page text is a block, not part of the question
    assert res.produced["pages_with_picture"] == 1
    assert {f.source for f in res.sheet.facts} == {"ai_picture"}
    reads = nine_record.load_record("run1").roles[0].reads
    assert [(r.document_id, r.pages, r.pictures) for r in reads] == [("paper", (1,), 1)]


def test_a_missing_picture_is_text_only_not_a_failure():
    def none(n):
        raise RuntimeError("no image")

    res = read({1: PAGE1}, picture_of=none)
    assert res.state == "ran" and res.produced["pages_with_picture"] == 0


def test_the_same_field_with_two_values_on_two_pages_is_conflict():
    tx = Tx(
        lambda p: answer(
            (
                "design_pressure",
                "12" if p == 1 else "14",
                "barg",
                f"Design pressure: {'12' if p == 1 else '14'} barg",
                "found",
            )
        )
    )
    res = read({1: PAGE1, 2: PAGE2}, tx)
    assert [f.state for f in res.sheet.facts] == ["conflict", "conflict"]
    assert nine_facts.usable(res.sheet) == ()


def test_a_failed_call_is_a_page_not_read_and_the_role_ran_partly():
    res = read(
        {1: PAGE1}, FakeTransport(raises=RuntimeError("boom")) if False else _failing()
    )
    assert res.state == "ran_partly" and res.sheet.pages[0].text_read is False
    assert "no usable answer" in res.sheet.pages[0].not_read_why


def _failing():
    class Bad(Tx):
        def __call__(self, url, *, headers, body, timeout):
            raise RuntimeError("boom")

    return Bad()


def test_a_block_the_gate_held_is_not_read_never_read():
    with (
        db.connect() as conn
    ):  # the paper is not on the list shown: the seam drops its block
        conn.execute("DELETE FROM review_shown_lists")
        review_shown.record_in(conn, "run1", ["other"], NOW)
    tx = Tx()
    res = read({1: PAGE1}, tx)
    assert tx.bodies == []
    assert res.sheet.pages[0].text_read is False and res.sheet.pages[
        0
    ].not_read_why.startswith(nine_reader.NOT_SENT)
    assert res.state == "ran_partly"


def test_the_role_budget_ends_the_reader_ran_partly_and_names_the_pages():
    res = read({1: PAGE1, 2: PAGE2, 3: PAGE1}, gate=RoleGate.for_role(1, 0.0))
    assert [p.text_read for p in res.sheet.pages] == [False, False, False]
    assert all(p.not_read_why == nine_reader.BUDGET for p in res.sheet.pages)
    assert res.state == "ran_partly" and res.produced["pages_read"] == 0


def test_the_page_without_stored_text_is_never_read_on_claude_either():
    tx = Tx()
    res = read({1: PAGE1, 2: ""}, tx, picture_of=lambda n: png(10, 10))
    assert len(tx.bodies) == 1
    assert res.sheet.pages[1].not_read_why == nine_reader.NO_TEXT_CLAUDE


def test_the_sheet_is_stored_per_run_replaced_on_rerun_and_read_back():
    conn = sqlite3.connect(":memory:")
    assert nine_facts.load(conn, "run1") is None
    res = read({1: PAGE1})
    nine_facts.store(conn, res.sheet, res.produced)
    nine_facts.store(conn, res.sheet, res.produced)
    assert nine_facts.load(conn, "run1") == res.sheet
    assert conn.execute("SELECT COUNT(*) FROM agent_review_fact").fetchone()[0] == len(
        res.sheet.facts
    )
    assert nine_facts.load(conn, "other") is None


def test_the_digest_lists_usable_values_with_ids_and_names_pages_not_read():
    res = read({1: PAGE1, 2: ""}, engine="local", local=Local())
    text = nine_facts.digest(res.sheet)
    assert "f:1:1 p1 Design pressure: 12 barg" in text
    assert "PAGES NOT READ:" in text and "p2:" in text


def test_the_digest_cuts_on_a_line_end_and_says_how_many_it_left_out():
    res = read({1: PAGE1})
    assert "more values not shown" in nine_facts.digest(res.sheet, max_chars=60)
    assert nine_facts.digest(res.sheet, max_chars=8000).count("\n") >= 2


def test_nothing_is_written_to_the_facts_table(monkeypatch):
    from app import datasheets

    called = []
    monkeypatch.setattr(datasheets, "create_fact", lambda *a, **k: called.append(1))
    read({1: PAGE1})
    assert called == []


def test_the_reader_first_helpers_of_1824_cannot_be_switched_on_here():
    """`enabled()` reads a setting that exists only on #1824: guarded, so it is off and `read_missing` returns no value and no error."""
    assert not hasattr(settings, "ai_review_reader_first_enabled")
    assert reader_mod.enabled() is False
    facts, note = reader_mod.read_missing("paper", {1: PAGE1}, [])
    assert facts == [] and note["ran"] is False


def test_the_calls_of_the_reader_are_in_the_ledger_under_its_own_step():
    read({1: PAGE1})
    assert {
        e.get("step") for e in claude_spend.entries() if e.get("run") == "run1"
    } == {nine_reader.STEP}


@pytest.mark.parametrize("name", ["nine_reader", "nine_facts"])
def test_no_module_of_the_reader_names_a_verdict_class(name):
    import pathlib

    text = (
        pathlib.Path(__file__).resolve().parents[1] / "app" / f"{name}.py"
    ).read_text(encoding="utf-8")
    for word in (
        "verdict_class",
        "agent_review_wording",
        "agent_review_schema",
        "decided_by",
    ):
        assert word not in text


def _merge(stored_facts, read_facts, pages):
    return nine_facts.merge(stored_facts, read_facts, pages)[0]


def _states(facts):
    return [(f.page, f.tag, f.state) for f in facts]


@pytest.mark.parametrize(
    ("tag1", "tag2", "conflict"),
    [
        ("T1", None, True),  # a continuation page with no tag
        ("T1, T2", "T1", True),  # a tag list that overlaps
        ("T1", "T1A", True),  # one tag starts like the other
        (None, None, True),
        (
            "T1",
            "T2",
            False,
        ),  # both tagged, different identifiers: two things, each usable
    ],
)
def test_one_field_with_two_values_is_conflict_unless_both_tagged_with_other_tags(
    tag1, tag2, conflict
):
    pages = {1: "Design pressure: 12 barg\n", 2: "Design pressure: 14 barg\n"}
    a = stored("Design pressure", "12", "barg", page=1, equipment_tag=tag1)
    b = stored("Design pressure", "14", "barg", page=2, equipment_tag=tag2)
    facts = _merge([a, b], [], pages)
    assert all(f.state == "conflict" for f in facts) is conflict
    sheet = nine_facts.sheet_of("run1", "paper", 2, [], facts, "claude", [])
    assert (nine_facts.usable(sheet) == ()) is conflict


def test_merge_rechecks_the_quote_of_a_read_value_and_drops_an_unverified_one():
    bad = {
        "field": "Design pressure",
        "value": "99",
        "unit": "barg",
        "quote": "Design pressure: 99 barg",
        "page": 1,
    }
    ok = {
        "field": "Design temperature",
        "value": "150",
        "unit": "C",
        "quote": "Design temperature: 150 C",
        "page": 1,
    }
    facts, counts = nine_facts.merge([], [bad, ok], {1: PAGE1})
    assert [f.value for f in facts] == ["150"] and counts["unverified_dropped"] == 1


def test_a_page_with_text_and_no_field_label_is_read_by_code_not_by_the_model():
    tx = Tx()
    res = read({1: "Cover sheet. Revision history.", 2: PAGE1}, tx)
    p1 = res.sheet.pages[0]
    assert (p1.text_read, p1.not_read_why) == (False, nine_reader.CODE_ONLY)
    assert (
        len(tx.bodies) == 1
        and res.produced["pages_read"] == 1
        and res.produced["pages_read_by_code_only"] == 1
    )
    assert res.state == "ran"  # nothing was left unread that a model should have read


def test_the_source_of_a_value_is_per_page_picture_only_where_one_was_sent():
    tx = Tx(
        lambda p: (
            answer(
                ("design_pressure", "12", "barg", "Design pressure: 12 barg", "found")
            )
            if p == 1
            else answer(
                ("design_temperature", "150", "C", "Design temperature: 150 C", "found")
            )
        )
    )
    res = read(
        {1: PAGE1, 2: PAGE1},
        tx,
        picture_of=lambda n: (
            png(50, 50) if n == 1 else (_ for _ in ()).throw(RuntimeError("x"))
        ),
    )
    assert {(f.page, f.source) for f in res.sheet.facts} == {
        (1, "ai_picture"),
        (2, "ai_text"),
    }


def test_a_page_stopped_after_some_groups_answered_is_read_partly_and_keeps_its_verified_values(
    monkeypatch,
):
    monkeypatch.setattr(
        nine_reader, "batches", lambda fs: [[f] for f in fs]
    )  # one field per group: two groups on the page

    class Second(Tx):
        n = 0

        def __call__(self, url, *, headers, body, timeout):
            self.n += 1
            if self.n == 2:
                raise RuntimeError("boom")
            return super().__call__(url, headers=headers, body=body, timeout=timeout)

    res = read({1: PAGE1}, Second(lambda p: answer(GOOD)))
    p = res.sheet.pages[0]
    assert p.text_read is False and p.not_read_why.startswith(
        "read partly: 1 of 2 field groups"
    )
    assert [f.field_label for f in res.sheet.facts] == [
        "Design pressure"
    ] and res.state == "ran_partly"
    assert res.produced["pages_read"] == 0


def test_a_stopped_page_by_the_budget_or_the_gate_is_partly_read_in_words():
    r = nine_reader._Page(asked=3, answered=1, budget=True)
    assert (
        nine_reader._page_read(4, r).not_read_why
        == "read partly: 1 of 3 field groups (the Reader's budget was reached (role_budget))"
    )
    r = nine_reader._Page(asked=3, answered=1, not_sent="document_not_listed")
    assert (
        "read partly: 1 of 3 field groups (not sent (document_not_listed))"
        == nine_reader._page_read(4, r).not_read_why
    )


def test_a_stored_value_whose_quote_is_not_on_the_page_is_not_usable():
    text = "Design pressure: 12 barg\n"
    s = stored(
        "Design pressure",
        "12",
        "barg",
        quote="a quote that left the page",
        sha=reader_mod.page_sha(text),
    )
    facts = _merge([s], [], {1: text})
    assert [(f.state, f.quote_verified) for f in facts] == [("stored_only", False)]
    assert (
        nine_facts.usable(nine_facts.sheet_of("r", "p", 1, [], facts, "claude", []))
        == ()
    )
