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
