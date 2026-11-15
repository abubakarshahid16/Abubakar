"""A derived cell copied from a SCANNED document is found in that document's recognised text (the first real valve run: the librarian's chapter
titles of a scanned rule book were refused as "not from the sources", because the check read only the stored page text, which a scanned book
does not have). The cell must still be refused when it is in no declared source."""

from __future__ import annotations

import json

from app import db, nine_call, nine_facts, review_shown
from app.nine_call import FakeTransport
from tests.test_nine_b4_seam import (  # noqa: F401  (the invented seam world, autouse)
    NOW,
    reply,
    world,
)

TITLE = "Scope of this standard"
Q = nine_call.template("nine_b4_scanned_q", "List the chapters.")


def _scan():
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at) VALUES ('scan','scan.pdf','s',1,'scan.pdf','ready',1,?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES ('scan', 1, '', 0, 0)"
        )
        cols = [
            (r[1], r[2])
            for r in conn.execute("PRAGMA table_info(page_ocr)")
            if r[3] and r[4] is None
        ]
        vals = {
            "document_id": "scan",
            "page_no": 1,
            "text": f"1 {TITLE}\nbody",
            "char_count": 12,
        }
        row = {
            c: vals.get(c, "x" if "CHAR" in t.upper() or "TEXT" in t.upper() else 1)
            for c, t in cols
        }
        conn.execute(
            f"INSERT INTO page_ocr ({','.join(row)}) VALUES ({','.join('?' * len(row))})",
            list(row.values()),
        )
        review_shown.record_in(conn, "run1", ["paper", "book", "scan"], NOW)


def _block(cell):
    return nine_call.Block(
        "review_record",
        name="chapter_titles",
        sources=("scan",),
        kinds=("id", "number", "source"),
        items=(("scan", "1", cell),),
    )


def _ask(cell):
    t = FakeTransport([reply()])
    ans = nine_call.ask(
        "run1", 3, [_block(cell)], (Q, {}), send=t, env=FakeTransport.ENV
    )
    return ans, t


def test_a_title_copied_from_a_scanned_source_is_accepted():
    _scan()
    ans, t = _ask(TITLE)
    assert ans.ok and len(t.bodies) == 1 and TITLE in json.dumps(t.bodies[0])


def test_a_title_that_is_in_no_declared_source_is_still_refused():
    _scan()
    ans, t = _ask("A heading that no page holds at all")
    assert not ans.ok and ans.error_code == "no_block_left" and t.bodies == []
    assert ans.not_sent == (("derived:chapter_titles", "cell_not_from_sources"),)


# ---------------------------------------------------------------- what a failed role leaves in the record


def test_a_failed_role_keeps_a_closed_list_reason_the_template_and_the_cell_kind_never_a_value():
    import pytest

    from app import nine_job

    big = tuple(
        (str(i), "x" * 150) for i in range(400)
    )  # 400 rows of 150 characters: more than one derived block may hold
    with pytest.raises(nine_call.TemplateError) as ex:
        nine_call.Block(
            "review_record", name="fact_sheet", sources=("paper",), items=big
        )
    got = nine_job.failure_detail(ex.value)
    assert got == {
        "failure_error": "TemplateError",
        "failure_reason": "derived_block_too_large",
        "failure_template": "fact_sheet",
    }
    assert got["failure_reason"] in nine_call.FAILURE_REASONS
    with pytest.raises(nine_call.TemplateError) as ex2:
        nine_call.render_full(
            (Q, {"x": "1"})
        )  # a parameter the template does not declare
    d2 = nine_job.failure_detail(ex2.value)
    assert (
        d2["failure_reason"] == "template_parameters_differ"
        and d2["failure_template"] == Q
    )
    assert nine_job.failure_detail(RuntimeError("secret words 123")) == {
        "failure_error": "RuntimeError",
        "failure_reason": "other",
    }


def test_the_librarians_refused_title_step_is_named_by_codes_not_ran_silently():
    from app import nine_librarian

    _scan()
    ask = nine_librarian.seam_ask(
        "run1", send=FakeTransport([reply()]), env=FakeTransport.ENV
    )
    assert nine_librarian.model_step_refusal(ask) is None
    assert ask([("scan", "1", "A heading that no page holds at all")]) is None
    assert (
        nine_librarian.model_step_refusal(ask) == "no_block_left: cell_not_from_sources"
    )  # codes only: no title in it


# ---------------------------------------------------------------- the facts the reviewer stands on: current rows only


def _facts_world(live=400, superseded=2000):
    """The invented paper of the lead's measure: 400 live facts plus 2,000 superseded ones (rows of earlier runs)."""
    with db.connect() as conn:
        cols = [
            (r[1], r[2], r[3], r[4])
            for r in conn.execute("PRAGMA table_info(submittal_facts)")
        ]
        need = [c for c in cols if c[2] and c[3] is None and c[0] not in ("id",)]
        for n in range(live + superseded):
            row = {
                c: ("x" if "CHAR" in t.upper() or "TEXT" in t.upper() else 0)
                for c, t, _nn, _d in need
            }
            row.update(submittal_document_id="paper", field_name=f"field_{n}", field_label=f"Label {n}", field_value=f"{n}.5", page=1, source_text="q",
                       extraction_method="x", created_at=NOW, updated_at=NOW, superseded_at=None if n < live else NOW)  # fmt: skip
            use = {k: v for k, v in row.items() if k in {c[0] for c in cols}}
            conn.execute(
                f"INSERT INTO submittal_facts ({','.join(use)}) VALUES ({','.join('?' * len(use))})",
                list(use.values()),
            )


def test_the_reader_is_given_only_the_current_facts_never_the_superseded_ones(
    monkeypatch,
):
    from app import nine_job

    _facts_world()
    seen = {}

    def spy(**kw):
        seen["n"] = len(kw["stored_facts"])
        raise RuntimeError("stop here: only the selection is under test")

    monkeypatch.setattr(nine_job.nine_reader, "read_paper", spy)
    monkeypatch.setattr(nine_job, "_engine", lambda _c: "local")
    ctx = nine_job.RoleContext("run1", "paper", None, {}, {}, lambda *a: None)
    ctx.store["pages"] = {1: "x"}
    import pytest

    with pytest.raises(RuntimeError):
        nine_job.reader_role(ctx)
    assert seen["n"] == 400  # not 2400


def _sheet(n, pages_n=8):
    from app import nine_contract as nc

    facts, text = [], {p: [] for p in range(1, pages_n + 1)}
    for i in range(n):
        page, val = 1 + i % pages_n, f"{100 + i}.5"
        role = ("set_pressure", "mawp", "trim_material")[i % 3]
        text[page].append(f"T-{i % 40} {val} barg")
        facts.append(
            nc.Fact(
                f"f:{page}:{i}",
                page,
                "L",
                role,
                val,
                "barg",
                f"{val} barg",
                True,
                f"T-{i % 40}",
                None,
                "ai_only",
                "stored_only",
                None,
                "m",
            )
        )
    sheet = nc.FactSheet(
        "run1",
        "paper",
        pages_n,
        tuple(nc.PageRead(p, True, False, None) for p in text),
        tuple(facts),
        0,
        "claude",
        ("m",),
    )
    return sheet, {p: "\n".join(t) for p, t in text.items()}


def _ctx(sheet, roles):
    from app import nine_job

    ctx = nine_job.RoleContext(
        "run1",
        "paper",
        None,
        {
            "items": [
                {
                    "item_id": "R-1",
                    "standard_document_id": "book",
                    "field_roles": list(roles),
                }
            ]
        },
        {},
        lambda *a: None,
    )
    ctx.store["fact_sheet"] = sheet
    return ctx


def _group():
    from app import nine_reviewer as rev

    return [[rev.ChapterText("book", "4", 1, 1, (4,), 100)]]


def _digest_rows_of(plan):
    return [
        row
        for b in plan
        if b.document_kind == "review_record" and b.name.startswith("fact_sheet")
        for row in b.items
    ]


def test_a_digest_that_fits_one_block_is_shared_by_every_request():
    from app import nine_support

    sheet, pages = _sheet(60)
    prefix, groups, none_ctx = nine_support._prefix(
        _ctx(sheet, ["set_pressure"]), pages, _group()
    )
    assert isinstance(prefix, list) and len(groups) == 1 and none_ctx
    assert len(_digest_rows_of(prefix)) == 60  # all rows, one shared list


def test_a_digest_over_one_block_carries_only_the_facts_of_the_chapters_fields_each_block_under_the_cap_and_counts_the_rest():
    from app import nine_support

    sheet, pages = _sheet(900)  # 900 live rows: about 100,000 characters
    ctx = _ctx(sheet, ["set_pressure"])
    prefix, groups, _n = nine_support._prefix(ctx, pages, _group())
    assert callable(prefix)
    sent = set()
    for i, _g in enumerate(groups):
        for b in prefix(i, _g):
            if b.document_kind == "review_record":
                assert (
                    sum(len(c) + 3 for r in b.items for c in r)
                    <= nine_call.MAX_DERIVED_CHARS
                )
        rows = _digest_rows_of(prefix(i, _g))
        assert all(
            r[1] == nine_facts.ROLE_CODES["set_pressure"] for r in rows
        )  # only the fields this chapter's book is asked about
        sent |= {r[0] for r in rows}
    c = ctx.store["digest_counts"]
    assert (
        c["rows"] == 900
        and len(sent) + c["never_sent"] == 900
        and c["never_sent"] == 600
    )
    assert c["left_out_reasons"]["field not asked from any chapter's book"] == 600


def test_when_even_the_narrowed_facts_do_not_fit_the_chapter_is_sent_once_per_part_and_the_record_says_so():
    from app import nine_support

    sheet, pages = _sheet(1800)  # 600 rows of the one field: more than one block
    ctx = _ctx(sheet, ["set_pressure"])
    prefix, groups, _n = nine_support._prefix(ctx, pages, _group())
    assert len(groups) >= 2 and ctx.store["digest_counts"]["parts"] == len(groups)
    pages_per_part = [
        {r[3] for r in _digest_rows_of(prefix(i, g))} for i, g in enumerate(groups)
    ]
    assert all(pages_per_part) and not set.intersection(
        *pages_per_part
    )  # whole pages per part: no page split between two requests
    sent = {r[0] for i, g in enumerate(groups) for r in _digest_rows_of(prefix(i, g))}
    assert (
        len(sent) == 600 and ctx.store["digest_counts"]["never_sent"] == 1200
    )  # the other fields, counted with their reason


def test_the_reviewer_record_names_what_the_gate_held_not_a_chapter_group_that_was_read():
    """Run 2 of the valve: 3 of 3 groups answered, 24 of 24 chapters read, and the record said "some chapter groups were not read". What had been held was
    the fact-sheet block (text_from_held_document). The words say which block and which code, and a fully read run does not claim unread groups."""
    from app import nine_reviewer as rev

    run = rev.ReviewerRun(
        groups=3,
        answered=3,
        no_context_available=True,
        not_sent=[("derived:fact_sheet", "text_from_held_document")] * 3,
    )
    state, why = run.state()
    assert (
        state == "ran_partly"
        and why
        == "not sent, held by the gate: derived:fact_sheet (text_from_held_document)"
    )
    assert "chapter group" not in why
    p = run.produced()
    assert (
        p["blocks_not_sent"] == 3
        and p["not_sent"] == "derived:fact_sheet (text_from_held_document)"
    )
    assert rev.ReviewerRun(groups=3, answered=3, no_context_available=True).state() == (
        "ran",
        None,
    )


# ---------------------------------------------------------------- field codes: no ordinary phrase goes to the held-text guard (run 2: 51 of 94 rows tripped it)


def test_every_field_code_is_short_stable_unique_and_in_the_legend():
    import re

    codes = nine_facts.ROLE_CODES
    assert codes and len(set(codes.values())) == len(codes)
    assert all(
        re.fullmatch(r"[a-z0-9]+", c) and len(c) < 12 for c in codes.values()
    )  # under the guard's 12 characters
    assert codes["set_pressure"] == nine_facts.role_code(
        "set_pressure"
    )  # stable: derived from the name alone
    legend = nine_facts.legend().splitlines()
    assert (
        len(legend) == len(codes)
        and f"{codes['set_pressure']} = set pressure" in legend
    )
    assert nine_facts.codes_of(["set_pressure", "no_such_role"]) == {
        codes["set_pressure"]
    }


def test_a_digest_row_with_a_field_code_passes_the_held_text_guard_and_a_held_phrase_still_trips_it():
    from app import nine_support  # noqa: F401

    sheet, pages = _sheet(6, pages_n=1)
    blocks, _c = nine_facts.digest_blocks(sheet, pages)
    with db.connect() as conn:
        conn.execute("DELETE FROM pages WHERE document_id = 'paper'")
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES ('paper', 1, ?, ?, 0)",
            (pages[1], len(pages[1])),
        )
        nine_facts.store(conn, sheet)
    ok, _t = _ask_blocks(blocks)
    assert (
        ok.ok
        and ok.not_sent == ()
        and any(r.document_kind == "review_record" for r in ok.reads)
    )
    from tests.test_nine_b4_seam import HELD_RULE

    bad = nine_call.Block(
        "review_record",
        name="fact_sheet",
        sources=("paper",),
        kinds=("source",),
        items=((HELD_RULE,),),
    )
    held, _t2 = _ask_blocks([nine_call.Block("paper", "paper", (1,)), bad])
    assert held.not_sent == (
        ("derived:fact_sheet", "text_from_held_document"),
    )  # the guard is NOT exempted: a held-document phrase still drops the block


def _ask_blocks(blocks):
    t = FakeTransport([reply()])
    first = (
        [nine_call.Block("paper", "paper", (1,))]
        if not any(b.document_kind == "paper" for b in blocks)
        else []
    )
    ans = nine_call.ask(
        "run1", 4, [*first, *blocks], (Q, {}), send=t, env=FakeTransport.ENV
    )
    return ans, t


# ---------------------------------------------------------------- the blank fields: "printed, blank" (rows 52 and 53 of the valve: spring and bellows material)


def _sheet_with_blanks():
    from app import nine_contract as nc

    facts = []
    for i, (role, value) in enumerate(
        [
            ("set_pressure", "150.5"),
            ("spring_material", None),
            ("spring_material", None),
            ("bellows_material", None),
            (None, None),
        ]
    ):
        facts.append(
            nc.Fact(
                f"f:1:{i}",
                1,
                "L",
                role,
                value,
                None,
                "L",
                True,
                None,
                None,
                "stored",
                "stored_only",
                None,
                "m",
            )
        )
    sheet = nc.FactSheet(
        "run1",
        "paper",
        1,
        (nc.PageRead(1, True, False, None),),
        tuple(facts),
        0,
        "claude",
        ("m",),
    )
    return sheet, {1: "L 150.5 barg\nL\n"}


def test_blank_fields_go_to_the_reviewer_as_one_line_list_of_codes_and_pages_without_a_value():
    sheet, pages = _sheet_with_blanks()
    rows, left = nine_facts.blank_rows(sheet)
    codes = nine_facts.ROLE_CODES
    assert [(r[1], r[2]) for r in rows] == [
        (codes["spring_material"], "1"),
        (codes["bellows_material"], "1"),
    ]  # one row per field and page, no value
    assert dict(left) == {"blank of a field the registry does not name": 1}
    block = nine_facts.blank_block("paper", rows)
    assert block.name == "fact_sheet_blank" and all(len(r) == 3 for r in block.items)
    with db.connect() as conn:
        conn.execute("DELETE FROM pages WHERE document_id = 'paper'")
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES ('paper', 1, ?, ?, 0)",
            (pages[1], len(pages[1])),
        )
        nine_facts.store(conn, sheet)
    ans, _t = _ask_blocks([block])
    assert (
        ans.ok
        and ans.not_sent == ()
        and any(
            r.chapter_id == "fact_sheet_blank"
            for r in ans.reads
            if r.document_kind == "review_record"
        )
    )


def test_the_prefix_carries_the_blank_block_and_narrows_it_to_the_chapters_fields_when_the_digest_is_split():
    from app import nine_support

    sheet, pages = _sheet_with_blanks()
    ctx = _ctx(sheet, ["spring_material"])
    prefix, groups, _n = nine_support._prefix(ctx, pages, _group())
    names = [b.name for b in prefix if b.document_kind == "review_record"]
    assert "fact_sheet_blank" in names and ctx.store["digest_counts"]["rows_blank"] == 2


# ---------------------------------------------------------------- the per-request ceiling (provisional, from three groups of run 2)


def test_a_request_over_the_ceiling_is_refused_before_anything_is_sent():
    with db.connect() as conn:
        conn.execute("DELETE FROM pages WHERE document_id = 'paper'")
        big = "word " * (nine_call.MAX_REQUEST_CHARS // 5 + 1000)
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES ('paper', 1, ?, ?, 0)",
            (big, len(big)),
        )
    ans, t = _ask_blocks([])
    assert (
        not ans.ok and ans.error_code == nine_call.REQUEST_TOO_LARGE and t.bodies == []
    )


def test_pieces_of_whole_pages_never_pass_the_limit_and_cover_the_range_in_order():
    from app import nine_support

    pages = dict.fromkeys(range(1, 9), "x" * 100)  # 8 pages of 100 characters, joined by a line break: 807 characters
    cuts = nine_support._page_cuts(tuple(range(1, 9)), pages, 0, 807, 250)
    assert [c[0] for c in cuts] == [(1, 2), (3, 4), (5, 6), (7, 8)]
    assert (
        all(hi - lo <= 250 for _p, lo, hi in cuts)
        and cuts[0][1] == 0
        and cuts[-1][1:] == (0, 201)
    )  # offsets are relative to each piece's first page
    one = nine_support._page_cuts((1, 2), {1: "a" * 500, 2: "b" * 10}, 0, 511, 250)
    assert [c[0] for c in one] == [
        (1,),
        (2,),
    ]  # a page alone over the limit is a piece of its own


def test_chapters_are_packed_by_characters_up_to_the_budget_and_an_oversize_part_goes_alone():
    from app import nine_reviewer as rev

    parts = [
        rev.ChapterText("b", str(i), 1, 1, (i,), n)
        for i, n in enumerate([30_000, 30_000, 30_000, 90_000, 10_000], 1)
    ]
    groups = rev.group_chapters(parts, limit_chars=60_000)
    assert [[c.chars for c in g] for g in groups] == [
        [30_000, 30_000],
        [30_000],
        [90_000],
        [10_000],
    ]


def test_the_chapter_budget_is_the_ceiling_less_what_every_request_already_carries():
    from app import nine_support

    sheet, pages = _sheet(60)
    ctx = _ctx(sheet, ["set_pressure"])
    budget = nine_support.chapter_budget(ctx, pages)
    shared = sum(len(t) for t in pages.values())
    assert (
        nine_call.MAX_REQUEST_CHARS
        - shared
        - 30_000
        - nine_support.REQUEST_OVERHEAD_CHARS
        <= budget
        < nine_call.MAX_REQUEST_CHARS - shared
    )


def test_a_cut_piece_slices_its_own_pages_so_what_is_sent_is_exactly_the_range():
    from app import nine_support

    pages = {1: "a" * 100, 2: "b" * 100, 3: "c" * 100}
    joined = "\n".join(pages[n] for n in (1, 2, 3))
    cuts = nine_support._page_cuts((1, 2, 3), pages, 50, 250, 120)
    got = "".join(("\n".join(pages[n] for n in pg))[lo:hi] for pg, lo, hi in cuts)
    assert got == joined[50:250].replace(
        "\n", ""
    )  # the pieces together are the range, each cut from its own pages
    assert all(hi - lo <= 120 for _p, lo, hi in cuts)


# ---------------------------------------------------------------- the title list: a heading that is also in a held document is left out, the rest goes


def test_a_title_that_also_occurs_in_a_held_document_is_left_out_and_counted_and_the_rest_of_the_list_goes():
    from app import nine_librarian
    from tests.test_nine_b4_seam import HELD_RULE

    _scan()
    ask = nine_librarian.seam_ask(
        "run1", send=FakeTransport([reply()]), env=FakeTransport.ENV
    )
    got = ask(
        [("scan", "1", TITLE), ("scan", "2", HELD_RULE[:40])]
    )  # the second heading is words of the held document ("held")
    assert (
        ask.left_out == 1 and nine_librarian.model_step_refusal(ask) is None
    )  # one row left out, the call ran with the other
    assert got == []  # the stub answered with no chapters


def test_screen_titles_leaves_out_only_rows_that_hit_a_held_document():
    from app import nine_librarian
    from tests.test_nine_b4_seam import HELD_RULE

    _scan()
    keep, left = nine_librarian.screen_titles(
        "run1",
        [("scan", "1", TITLE), ("scan", "2", HELD_RULE[:40]), ("scan", "3", "short")],
    )
    assert [t[1] for t in keep] == [
        "1",
        "3",
    ] and left == 1  # a heading under 12 characters is not text for the guard


# ---------------------------------------------------------------- the held-text guard reads a scanned held document through its recognised text


def test_the_held_text_guard_sees_the_recognised_text_of_a_scanned_held_document():
    from app import nine_record

    _scan()  # the scan has no stored text; its words are in page_ocr only. "scan" is NOT on the run's list in this check: hold it back
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_shown_lists SET documents_json = ? WHERE run_id = 'run1'",
            (json.dumps(["paper", "book"]),),
        )
        assert nine_record.held_text_hits(conn, "run1", [TITLE]) == {TITLE}
        assert (
            nine_record.held_text_hits(
                conn, "run1", ["words that no document holds anywhere at all"]
            )
            == set()
        )


def test_a_chapter_part_over_the_budget_is_cut_into_numbered_pieces_of_whole_pages():
    from types import SimpleNamespace as NS

    from app import nine_support

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at) VALUES ('bk','bk.pdf','b',1,'bk.pdf','ready',4,?)",
            (NOW,),
        )
        for n in range(1, 5):
            conn.execute(
                "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES ('bk', ?, ?, 100, 0)",
                (n, chr(96 + n) * 100),
            )
    joined = "\n".join(chr(96 + n) * 100 for n in range(1, 5))
    part = NS(page_from=1, page_to=4, part_no=1, part_of=1)
    chosen = [("bk", NS(chapter_id="7", parts=[part]))]
    cuts = {"bk": NS(text=lambda _c, _p: joined)}
    whole = nine_support._chapter_texts(chosen, cuts)
    assert len(whole) == 1 and whole[0].chars == len(joined)
    cut = nine_support._chapter_texts(chosen, cuts, max_chars=250)
    assert [(c.part_no, c.part_of, c.pages) for c in cut] == [
        (1, 2, (1, 2)),
        (2, 2, (3, 4)),
    ]
    assert (
        all(c.chars <= 250 for c in cut) and cut[1].char_from == 0
    )  # a piece's range is relative to its own first page
