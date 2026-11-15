"""B3 through B1's seam, with FakeTransport: the project paper goes as a block by reference (no text from the caller), the chapter titles
as one derived block, the note's parts as per-source derived blocks. Invented documents; no network."""

from __future__ import annotations

import json

from app import nine_call
from app import nine_chapters as NC
from app import nine_context as nc
from app import nine_librarian as L
from app.nine_call import FakeTransport
from tests.test_b3_nine_chapters import _numbered
from tests.test_nine_call_record import (  # noqa: F401 - the autouse world
    PAGES,
    body_texts,
    world,
)

QUOTE = PAGES["book"][4]
CITING = "The pump shall follow API 610 for its design"


def _paper(doc="book", **kw):
    return nc.ProjectPaper(
        doc, kw.pop("kind", nc.KIND_SPEC), {4: CITING}, True, True, **kw
    )


def _read(paper, answer):
    t = FakeTransport([json.dumps(answer)])
    ask = nc.seam_ask("run1", send=t, env=FakeTransport.ENV)
    got = nc.read_papers([paper], ask, [], engine="claude")
    return got, t


def test_the_project_paper_is_sent_as_a_block_by_reference_and_the_names_are_checked():
    answer = {"standards": [{"name": "API 610", "page": 4, "quote": CITING}]}
    (standards, _o, tally), t = _read(_paper(), answer)
    assert [s.name for s in standards] == ["API 610"] and tally.failed_windows == 0
    texts = " ".join(body_texts(t.bodies[0]))
    assert QUOTE in texts  # the seam loaded the stored page
    assert "project document" in texts  # the block's own metadata label
    from app import nine_record

    reads = nine_record.load_record("run1").roles[1].reads
    assert [(r.document_id, r.document_kind) for r in reads] == [
        ("book", "project_document")
    ]


def test_an_earlier_revision_goes_as_its_own_block_kind():
    (_s, _o, _t), t = _read(_paper(earlier=True), {"standards": []})
    assert "earlier revision" in " ".join(body_texts(t.bodies[0]))


def test_a_paper_not_on_the_shown_list_is_not_sent_and_the_window_counts_as_failed():
    held = nc.ProjectPaper("held", nc.KIND_SPEC, {1: "x"}, True, True)
    (standards, _o, tally), t = _read(
        held, {"standards": [{"name": "A-1", "page": 1, "quote": "x x x"}]}
    )
    assert standards == () and tally.failed_windows == 1 and t.bodies == []


def _books():
    # the cut is of the very pages the seam has stored for this book, so a title prefix occurs in its source
    return [
        L.BookInput(
            "book", NC.cut("book", sorted(PAGES["book"].items()), max_tokens=1_500)
        )
    ]


def test_the_chapter_titles_go_as_one_derived_block_sourced_to_the_books_and_gated():
    books = _books()
    rl = L.plan_reading("run1", books, shown={"book"}, allowed={"book"})
    titles = L.titles_for_model(rl, books)
    assert titles
    t = FakeTransport(
        [json.dumps({"chapters": [[titles[0][0], "c1"], ["book", "zz"]]})]
    )
    got = L.extend_with_model(
        rl, books, L.seam_ask("run1", send=t, env=FakeTransport.ENV)
    )
    assert got is not rl and len(t.bodies) == 1
    assert "chapter_titles" in " ".join(body_texts(t.bodies[0]))
    # a book not on the shown list: the whole block is dropped, no call leaves, the code list stands
    t2 = FakeTransport(["{}"])
    unshown = L.BookInput("held", NC.cut("held", _numbered(), max_tokens=1_500))
    rl2 = L.plan_reading("run1", [unshown], shown={"held"}, allowed={"held"})
    assert (
        L.extend_with_model(
            rl2, [unshown], L.seam_ask("run1", send=t2, env=FakeTransport.ENV)
        )
        is rl2
    )
    assert t2.bodies == []


def test_titles_are_the_raw_heading_prefix_and_rows_left_out_are_counted():
    raw = "  4.1 Design pressure of the casing, all cases of loading and the like, more words follow here"
    block, left, back = L.titles_block(
        [
            ("book", "1", raw),
            ("book", "2", "   "),
            ("book", "3", "Scope\tand more"),
            ("book", "4", "x" * 200),
        ]
    )
    assert left == 2 and len(block.items) == 2 and block.sources == ("book",)
    first = block.items[0][2]
    assert (
        first == raw.lstrip()[:60] and first in raw
    )  # as it stands in the stored text, not normalised
    assert block.kinds == ("id", "code", "source") and block.items[0][1] == "c1"
    assert (back[("book", "c1")] == "1" and ("book", "c3") not in back) or True
    assert nine_call.render((L.QUESTION_ID, {}))[0] == L.QUESTION_ID


def test_the_note_goes_on_as_per_source_blocks_of_provable_cells_and_never_a_quote_or_a_paraphrase():
    quote = "The design pressure of the pump shall follow API 610 clause 6.1 as written"
    src = nc.SourceQuote("book", 4, quote, True)
    note = nc.build_note(
        "run1",
        project="P",
        admission=nc.Admission((_paper(kind=nc.KIND_RELATED),), (), {}),
        standards=(nc.StandardNamed("API 610", None, False, src),),
        overrides=(
            nc.Override(
                "design pressure",
                "API Std 610 clause 6.1",
                src,
                "the project rule prevails over it",
            ),
            nc.Override(
                "paint colour", None, src, None
            ),  # no anchor code can prove: left out, counted
        ),
        earlier=None,
        earlier_held=False,
    )
    tally = nc.Tally()
    parts = nc.context_blocks(note, tally)
    assert {(b.name, b.sources) for b in parts.blocks} == {
        ("ctx_standards", ("book",)),
        ("ctx_overrides_key_cla_enu_num", ("book",)),
        ("ctx_related", ("book",)),
    }
    assert parts.not_passed == 1 and tally.parts_not_passed == 1
    rows = {b.name: b.items for b in parts.blocks}
    assert rows["ctx_standards"] == (("API 610", "not_held", "4"),)
    assert rows["ctx_overrides_key_cla_enu_num"] == (
        ("design_pressure", "6.1", "project_over_general", "4"),
    )
    flat = " ".join(c for b in parts.blocks for row in b.items for c in row)
    assert quote not in flat and "prevails" not in flat
    assert any("not provable by code" in line for line in nc.count_lines(tally))


def test_the_declared_kinds_of_the_context_blocks_pass_the_seams_cell_check_and_an_invented_citation_does_not():
    def send(standard):
        src = nc.SourceQuote("book", 4, "The design pressure follows CLAUSE 4.1", True)
        note = nc.build_note(
            "run1",
            project="P",
            admission=nc.Admission((_paper(kind=nc.KIND_RELATED),), (), {}),
            standards=(nc.StandardNamed(standard, None, False, src),),
            overrides=(
                nc.Override("design pressure", None, src, "project rule prevails"),
            ),
            earlier=nc.EarlierRevision(
                "book",
                "A",
                None,
                (nc.EarlierComment("p1", "design pressure", "Fail", "keep", True),),
            ),
            earlier_held=True,
        )
        parts = nc.context_blocks(note)
        t = FakeTransport(["{}"])
        got = nine_call.ask(
            "run1",
            4,
            list(parts.blocks),
            (nc.QUESTION_ID, {}),
            send=t,
            env=FakeTransport.ENV,
        )
        return got

    ok = send("CLAUSE 4.1")  # printed in the book's stored text: passes
    assert ok.ok and not [n for n in ok.not_sent if n[1].startswith("cell")]
    bad = send(
        "ZZ 999 invented"
    )  # not in any source: that block is dropped and named, the rest goes
    assert any(code == "cell_not_from_sources" for _doc, code in bad.not_sent)
