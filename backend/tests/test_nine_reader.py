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
import sqlite3
import struct
import zlib
from dataclasses import dataclass

import pytest

from app import agent_review_calculator_reader as reader_mod
from app import nine_facts, nine_reader
from app.claude_spend import BudgetExceeded

PAGE1 = "Design pressure: 12 barg\nDesign temperature: 150 C\n"
PAGE2 = "Notes\nDesign pressure: 14 barg\n"


@dataclass
class Ans:
    text: str | None
    state: str = "answered"
    error_code: str | None = None


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


class Seam:
    def __init__(self, text_of=None):
        self.calls: list[tuple[int, list[dict], str]] = []
        self.text_of = text_of or (lambda page: answer(GOOD, TEMP))

    def __call__(self, role, blocks, question):
        self.calls.append((role, blocks, question))
        return Ans(self.text_of(blocks[0]["pages"][0]))


def read(pages, seam=None, stored=(), engine="claude", **kw):
    return nine_reader.read_paper(
        run_id="r1",
        paper_id="d1",
        pages=pages,
        stored_facts=list(stored),
        engine=engine,
        seam=seam,
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
    res = read({1: PAGE1}, Seam(lambda p: answer(bad, TEMP)))
    labels = [f.field_label for f in res.sheet.facts]
    assert labels == ["Design temperature"]
    assert res.produced["dropped"] == 1
    assert res.produced["dropped_by_reason"] == {"quote_not_on_page": 1}


def test_a_stored_and_a_read_value_that_differ_are_conflict_and_not_used():
    res = read(
        {1: PAGE1},
        Seam(),
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
    res = read({1: PAGE1}, Seam(), stored=[stored("Design pressure", "12", "barg")])
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
    res = read({1: PAGE1}, Seam(lambda p: answer(TEMP)), stored=[old])
    assert res.produced["stale_stored_values"] == 1
    stale = [f for f in res.sheet.facts if f.state == "stale"]
    assert len(stale) == 1
    assert all(f.value != "99" for f in nine_facts.usable(res.sheet))


def test_a_page_with_no_text_on_local_is_not_read_with_the_reason_and_no_model_is_asked():
    asked: list[str] = []

    def local(prompt):
        asked.append(prompt)
        return answer(GOOD, TEMP)

    res = read({1: PAGE1, 2: ""}, engine="local", local_call=local)
    p2 = res.sheet.pages[1]
    assert (p2.page, p2.text_read, p2.picture_read) == (2, False, False)
    assert p2.not_read_why == nine_reader.NO_TEXT_LOCAL
    assert res.state == "ran_partly" and nine_reader.NO_TEXT_LOCAL in res.why
    assert all("PAGE 2" not in p for p in asked)
    assert res.sheet.pages[0].text_read is True


def test_local_reads_text_only_and_never_a_picture():
    seen = []
    res = read(
        {1: PAGE1},
        engine="local",
        local_call=lambda p: seen.append(p) or answer(GOOD, TEMP),
        picture_of=lambda n: png(100, 100),
    )
    assert res.produced["pages_with_picture"] == 0 and seen
    assert all(not f.source.endswith("picture") for f in res.sheet.facts)


def test_picture_tokens_are_counted_by_the_image_rule_not_as_text():
    pic = png(1000, 1000)
    est = nine_reader.estimate({1: PAGE1}, {1: pic})
    from app.claude_image_tokens import image_tokens

    assert est["picture_tokens"] == image_tokens(1000, 1000) == 1334
    assert est["text_tokens"] == len(PAGE1) // 3
    assert est["picture_tokens"] != len(pic) // 3


def test_claude_gets_the_picture_as_its_own_block_and_the_fact_says_so():
    seam = Seam()
    res = read({1: PAGE1}, seam, picture_of=lambda n: png(100, 100))
    role, blocks, question = seam.calls[0]
    assert role == 1 and [("text" in b, "picture" in b) for b in blocks] == [
        (True, False),
        (False, True),
    ]
    assert (
        blocks[0]["text"] == PAGE1
        and blocks[0]["document_kind"] == "paper"
        and blocks[0]["pages"] == [1]
    )
    assert (
        PAGE1.strip() not in question
    )  # the page text is a block, not part of the question
    assert res.produced["pages_with_picture"] == 1
    assert {f.source for f in res.sheet.facts} == {"ai_picture"}


def test_a_missing_picture_is_text_only_not_a_failure():
    def none(n):
        raise RuntimeError("no image")

    res = read({1: PAGE1}, Seam(), picture_of=none)
    assert res.state == "ran" and res.produced["pages_with_picture"] == 0


def test_the_same_field_with_two_values_on_two_pages_is_conflict():
    seam = Seam(
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
    res = read({1: PAGE1, 2: PAGE2}, seam)
    assert [f.state for f in res.sheet.facts] == ["conflict", "conflict"]
    assert nine_facts.usable(res.sheet) == ()


def test_a_failed_call_is_a_page_not_read_and_the_role_ran_partly():
    class Bad:
        def __call__(self, role, blocks, question):
            return Ans(None, "failed", "http_500")

    res = read({1: PAGE1}, Bad())
    assert res.state == "ran_partly"
    assert (
        res.sheet.pages[0].text_read is False
        and "http_500" in res.sheet.pages[0].not_read_why
    )


def test_a_limit_stops_the_later_pages_and_says_so():
    class Stop:
        n = 0

        def __call__(self, role, blocks, question):
            self.n += 1
            if self.n == 2:
                raise BudgetExceeded()
            return Ans(answer(GOOD, TEMP))

    res = read({1: PAGE1, 2: PAGE2, 3: PAGE1}, Stop())
    assert [p.text_read for p in res.sheet.pages] == [True, False, False]
    assert "usd_cap_reached" in res.sheet.pages[2].not_read_why
    assert res.state == "ran_partly"


def test_claude_without_a_seam_is_not_run_with_a_reason():
    res = read({1: PAGE1}, None)
    assert res.state == "not_run" and "seam" in res.why and res.sheet.facts == ()


def test_the_page_without_stored_text_is_never_read_on_claude_either():
    seam = Seam()
    res = read({1: PAGE1, 2: ""}, seam, picture_of=lambda n: png(10, 10))
    assert len(seam.calls) == 1
    assert res.sheet.pages[1].not_read_why == nine_reader.NO_TEXT_CLAUDE


def test_the_sheet_is_stored_per_run_replaced_on_rerun_and_read_back():
    conn = sqlite3.connect(":memory:")
    assert nine_facts.load(conn, "r1") is None
    res = read({1: PAGE1}, Seam())
    nine_facts.store(conn, res.sheet, res.produced)
    nine_facts.store(conn, res.sheet, res.produced)
    back = nine_facts.load(conn, "r1")
    assert back == res.sheet
    assert conn.execute("SELECT COUNT(*) FROM agent_review_fact").fetchone()[0] == len(
        res.sheet.facts
    )
    assert nine_facts.load(conn, "other") is None


def test_the_digest_lists_usable_values_with_ids_and_names_pages_not_read():
    res = read(
        {1: PAGE1, 2: ""}, engine="local", local_call=lambda p: answer(GOOD, TEMP)
    )
    text = nine_facts.digest(res.sheet)
    assert "f:1:1 p1 Design pressure: 12 barg" in text
    assert "PAGES NOT READ:" in text and "p2:" in text


def test_the_digest_cuts_on_a_line_end_and_says_how_many_it_left_out():
    res = read({1: PAGE1}, Seam())
    text = nine_facts.digest(res.sheet, max_chars=60)
    assert "more values not shown" in text
    assert nine_facts.digest(res.sheet, max_chars=8000).count("\n") >= 2


def test_nothing_is_written_to_the_facts_table(monkeypatch):
    called = []
    from app import datasheets

    monkeypatch.setattr(datasheets, "create_fact", lambda *a, **k: called.append(1))
    read({1: PAGE1}, Seam())
    assert called == []


@pytest.mark.parametrize("name", ["nine_reader", "nine_facts"])
def test_no_module_of_the_reader_names_a_verdict_class(name):
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "app" / f"{name}.py"
    text = src.read_text(encoding="utf-8")
    for word in (
        "verdict_class",
        "agent_review_wording",
        "agent_review_schema",
        "decided_by",
    ):
        assert word not in text
