"""A derived cell copied from a SCANNED document is found in that document's recognised text (the first real valve run: the librarian's chapter
titles of a scanned rule book were refused as "not from the sources", because the check read only the stored page text, which a scanned book
does not have). The cell must still be refused when it is in no declared source."""

from __future__ import annotations

import json

from app import db, nine_call, review_shown
from app.nine_call import FakeTransport
from tests.test_nine_b4_seam import NOW, reply, world  # noqa: F401  (the invented seam world, autouse)

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
            r[1] == "set_pressure" for r in rows
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
