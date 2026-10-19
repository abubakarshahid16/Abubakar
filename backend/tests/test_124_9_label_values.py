"""Order 124 item 9 (engine side): a form label is not a value.

"Internal design pressure" was stored with the value "and External design
pressure" - the next field's label. `row_noise.is_label_as_value` is ONE
general rule (CLAUDE.md rule 13: true for any form, no sheet's wording),
applied through `row_noise.noise_reason`, the one check every reader's rows
pass (rule reader, grid, geometry, vision and the AI gate).

All data here is synthetic.
"""

from __future__ import annotations

import pytest

from app import datasheets, db, row_noise, submittal_review
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "ds.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _one_page_sheet(tmp_path, *rows: tuple[str, str], doc_id: str = "doc_lv") -> str:
    """A ruled one-page form of (label, value) rows, stored as a document."""
    import pymupdf

    path = tmp_path / f"{doc_id}.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=500)
    y = 60
    for index, (label, value) in enumerate(rows, start=1):
        page.draw_rect(pymupdf.Rect(40, y - 14, 300, y + 6), color=(0, 0, 0), width=0.7)
        page.draw_rect(
            pymupdf.Rect(300, y - 14, 560, y + 6), color=(0, 0, 0), width=0.7
        )
        page.insert_text((44, y), f"{index}", fontsize=9)
        page.insert_text((64, y), label, fontsize=9)
        page.insert_text((304, y), value, fontsize=9)
        y += 26
    pdf.save(str(path))
    pdf.close()
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',1,?)""",
            (
                doc_id,
                "SYNTH-DS.pdf",
                f"sha-{doc_id}",
                str(path),
                "2026-10-19T00:00:00Z",
            ),
        )
        text = pymupdf.open(str(path))[0].get_text()
        conn.execute(
            """INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,1,1,1,NULL,'prose',?,1,?,1)""",
            (f"{doc_id}-c1", doc_id, "SYNTH-DS.pdf", text, f"h{doc_id}"),
        )
    return doc_id


def _facts(doc_id: str) -> dict[str, str | None]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT field_label, raw_value FROM submittal_facts"
            " WHERE submittal_document_id = ? AND superseded_at IS NULL",
            (doc_id,),
        ).fetchall()
    return {r["field_label"].strip().lower(): r["raw_value"] for r in rows}


@pytest.mark.parametrize(
    "value",
    [
        "and External design pressure",
        "or Operating temperature",
        "Max. operating temperature",
        "Design pressure",
        "Body material:",
    ],
)
def test_a_label_standing_as_the_value_is_noise(value):
    assert (
        row_noise.noise_reason("Internal design pressure", value)
        == row_noise.LABEL_AS_VALUE
    )


@pytest.mark.parametrize(
    "value",
    [
        "Two coat epoxy",
        "Carbon steel",
        "Liquid",
        "Spring loaded",
        "Balanced bellows",
        "Differential pressure",  # a measured variable named as an answer
        "Pressure",
        "25 barg",
        "Max 150 C",
        "Yes",
    ],
)
def test_a_real_answer_is_not_a_label(value):
    assert not row_noise.is_label_as_value(value)
    assert row_noise.noise_reason("Coating", value) is None


def test_the_ai_gate_drops_a_label_as_value_and_keeps_free_text():
    """The AI path skips the value gate on purpose (free text is proved by
    its quote), so this rule is the only thing between it and a label."""
    gate = datasheets._ai_gate
    assert gate({"field": "Coating", "value": "Two coat epoxy"}, set()) is None
    assert gate(
        {"field": "Spring material", "value": "and Bellows material"}, set()
    ) == (row_noise.LABEL_AS_VALUE)


def test_the_rule_reader_does_not_store_a_label_as_a_value(tmp_path):
    """Through the pipeline: a named text field whose 'value' is another
    field's label is not stored; real free-text answers beside it are."""
    doc = _one_page_sheet(
        tmp_path,
        ("Valve type", "Spring loaded"),
        ("Body material", "Carbon steel"),
        ("Fluid phase", "Liquid"),
        ("Fluid", "or Operating temperature"),
        ("Spring material", "Max. operating temperature"),
    )
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    facts = _facts(doc)
    # POSITIVE FIRST: the real answers were read.
    assert {"valve type", "body material", "fluid phase"} <= set(facts), facts
    assert "fluid" not in facts, facts
    assert "spring material" not in facts, facts


def test_a_page_of_only_labels_stores_a_plain_reason_with_the_detail_apart(tmp_path):
    """End to end (order 124 item 9, job C): the page's only pair is a
    label-as-value, so the page has no fact. Its stored reason is plain
    words, and the unparsed entry keeps the counts as "detail"."""
    doc = _one_page_sheet(tmp_path, ("Valve type", "and Body material"))
    out = datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    entry = out["unparsed"][0]
    assert entry["reason"].startswith(
        "Read, but nothing on this page is a datasheet value"
    )
    assert "form labels with no answer beside them" in entry["reason"]
    assert "noise:" not in entry["reason"] and "label-value" not in entry["reason"]
    assert row_noise.LABEL_AS_VALUE in entry["detail"]
