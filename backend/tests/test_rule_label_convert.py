"""Converting the lab labeller's table (11 Nov 2026): every row decided again by the product; nothing promoted."""

from __future__ import annotations

import json
import sqlite3

import pytest

from app import (
    compiled_rule_report,
)
from app import (
    rule_label_convert as conv,
)
from app import (
    rule_label_import as imp,
)
from app import (
    rule_labels as rl,
)
from tests import r2_security_support as support
from tests import rule_label_support as s

temp_storage = support.temp_storage

LAB_COLS = (
    "source, rule_ref, state, a_model, b_model, a_prompt_version, b_prompt_version, prompt_version, quote_found,"
    " quote_page, quote_recovery, labelled_at, "
    + ", ".join(
        f"{p}_{c}"
        for p in "ab"
        for c in (
            "paper_kind",
            "field",
            "comparator",
            "values",
            "unit",
            "strength",
            "subject",
        )
    )
)


@pytest.fixture(autouse=True)
def _w(monkeypatch):
    s.switch(monkeypatch)
    s.patch_pages(monkeypatch)


def lab_row(
    ref,
    state="ai_approved",
    a_model=s.MODEL_A,
    b_model=s.MODEL_B,
    prompt="rule-label-v2",
    recovery=None,
    page=1,
    cmp_="le",
    values="[10.0]",
    unit="bar",
    kind="datasheet",
    field=s.FIELD(),
    b_kind=None,
    b_field="same",
):
    def ans(k, f=None):
        return (
            k,
            (f or field) if k == "datasheet" else None,
            cmp_,
            values,
            unit,
            "shall",
            "the item",
        )

    head = (
        "requirement",
        ref,
        state,
        a_model,
        b_model,
        prompt,
        prompt,
        prompt,
        1,
        page,
        recovery,
        "2026-11-11T00:00:00Z",
    )
    return (
        *head,
        *ans(kind),
        *ans(b_kind or kind, field if b_field == "same" else b_field),
    )


_N = [0]


def lab_db(tmp_path, rows):
    _N[0] += 1
    path = s.make_db(tmp_path / f"lab{_N[0]}.sqlite")
    conn = sqlite3.connect(str(path))
    cols = LAB_COLS
    conn.execute(f"CREATE TABLE rule_label ({cols})")
    for r in rows:
        conn.execute(
            f"INSERT INTO rule_label ({cols}) VALUES ({','.join('?' * len(r))})", r
        )
    conn.commit()
    conn.row_factory = sqlite3.Row
    return conn


def run(conn):
    return conv.convert(
        conn,
        lambda sdid: compiled_rule_report.pages_of(conn, sdid),
        lambda sdid: compiled_rule_report.page_origin(conn, sdid),
    )


def test_the_lab_approval_is_decided_again_and_marked_lab(tmp_path):
    rows, counts = run(lab_db(tmp_path, [lab_row("r1")]))
    assert (
        rows[0]["state"] == "ai_approved"
        and rows[0]["origin"] == "lab-order12"
        and rows[0]["a_prompt"] == "rule-label-v2"
    )
    assert counts["lab_ai_approved"] == counts[
        "product_ai_approved"
    ] == 1 and s.QUOTE_NUM not in json.dumps(rows)


@pytest.mark.parametrize(
    "kw,cause",
    [
        ({"b_model": s.MODEL_A}, "same_model"),
        ({"b_field": s.FIELD2()}, "field"),
        ({"values": "[99.0]"}, "invalid_reading"),
        ({"b_kind": "procedure"}, "kind"),
        ({"prompt": "rule-label-v9"}, "prompt_version"),
    ],
)
def test_a_lab_approval_the_product_cannot_prove_is_needs_human_with_the_reason(
    tmp_path, kw, cause
):
    rows, counts = run(lab_db(tmp_path, [lab_row("r1", **kw)]))
    assert rows[0]["state"] == "needs_human" and cause in rows[0]["disagreement"]
    assert counts["lab_approved_lost"] == 1 and cause in counts["lost_reasons"]


def test_nothing_is_promoted_over_the_labs_own_no(tmp_path):
    rows, _c = run(lab_db(tmp_path, [lab_row("r1", state="needs_human")]))
    assert (
        rows[0]["state"] == "needs_human"
        and rows[0]["disagreement"] == "lab_not_approved"
    )


def test_a_quote_not_on_the_page_and_other_recoveries_are_quote_not_found(
    tmp_path, monkeypatch
):
    rows, _c = run(
        lab_db(
            tmp_path, [lab_row("r1", recovery="chars"), lab_row("r2", recovery="join")]
        )
    )
    assert {r["state"] for r in rows} == {"quote_not_found"}
    s.patch_pages(
        monkeypatch, pages={1: "nothing here", 2: f"{s.QUOTE_NUM} {s.QUOTE_TXT}"}
    )
    rows, _c = run(lab_db(tmp_path, [lab_row("r1")]))
    assert rows[0]["state"] == "quote_not_found"


def test_page_recovery_is_re_proved_on_the_recovered_page(tmp_path, monkeypatch):
    s.patch_pages(
        monkeypatch,
        pages={
            1: "an unrelated first page of the invented book",
            2: f"{s.QUOTE_NUM} {s.QUOTE_TXT}",
        },
    )
    rows, _c = run(lab_db(tmp_path, [lab_row("r1", recovery="page", page=2)]))
    assert (rows[0]["state"], rows[0]["quote_page"], rows[0]["quote_recovery"]) == (
        "ai_approved",
        2,
        "page",
    )
    rows, _c = run(
        lab_db(
            tmp_path,
            [lab_row("r1", recovery="page", page=1)],
        )
    )
    assert rows[0]["state"] == "quote_not_found"


def test_a_low_confidence_ocr_page_is_never_approved(tmp_path, monkeypatch):
    s.patch_pages(
        monkeypatch, origin={1: {"page_source": "recognised", "page_min_conf": 0.1}}
    )
    rows, counts = run(lab_db(tmp_path, [lab_row("r1")]))
    assert rows[0]["state"] == "needs_human" and counts["lost_reasons"] == {
        "ocr_low_confidence": 1
    }


@pytest.fixture
def server(tmp_path):
    conn = sqlite3.connect(str(s.make_db(tmp_path / "server.sqlite")))
    conn.row_factory = sqlite3.Row
    return conn


def test_the_import_takes_a_lab_row_only_with_its_origin_and_the_tier_reads_it(
    tmp_path, server, monkeypatch
):
    s.patch_pages(
        monkeypatch,
        pages={1: "an unrelated first page", 2: f"{s.QUOTE_NUM} {s.QUOTE_TXT}"},
    )
    rows, _c = run(lab_db(tmp_path, [lab_row("r1", recovery="page", page=2)]))
    plain = [{k: v for k, v in r.items() if k != "origin"} for r in rows]
    assert (
        imp.import_labels(server, plain)["refused"] == 1
    )  # no origin: v2 and a recovery are both refused
    assert server.execute("SELECT COUNT(*) FROM rule_label").fetchone()[0] == 0
    assert imp.import_labels(server, rows)["stored"] == 1
    assert rl.usable_tier(server, requirement_id="r1").tier == "AI approved"
    bad = [dict(rows[0], quote_page=1)]  # the quote is not on the page the row names
    assert (
        imp.import_labels(server, bad)["refused"] == 1
        or server.execute("SELECT quote_page FROM rule_label").fetchone()[0] == 2
    )


def test_a_lab_field_not_on_the_list_is_needs_human_in_the_converter(tmp_path):
    rows, _c = run(lab_db(tmp_path, [lab_row("r1", field="zzz_not_listed")]))
    assert (
        rows[0]["state"] == "needs_human"
        and rows[0]["disagreement"] == "field_not_listed"
    )


def _lab(state, disagreement):
    import sqlite3

    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    return c.execute(
        "SELECT ? AS state, ? AS disagreement", (state, disagreement)
    ).fetchone()


def test_only_a_row_the_lab_held_for_the_quantity_guard_alone_may_be_promoted():
    from app.rule_label_convert import _held_only_for_the_quantity_guard as held

    assert held(_lab("needs_human", "no_number_reading"))
    assert not held(_lab("needs_human", "no_number_reading,kind"))
    assert not held(_lab("needs_human", "kind"))
    assert not held(_lab("needs_human", None))
    assert not held(_lab("needs_human", "lab_not_approved"))
    assert not held(_lab("quote_not_found", "no_number_reading"))
