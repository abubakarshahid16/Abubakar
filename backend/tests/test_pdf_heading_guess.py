"""#1522, review of #1571: a section heading known only from its font is a guess
(CLAUDE.md rule 4), so it never prints as "section found", and one false label
does not turn "could not be checked" into "Section not found".

Every PDF is built here with invented words. No model.
"""

from __future__ import annotations

import pymupdf
import pytest

from app import chunker, db, pdf_headings, playbooks, submittal_review
from app.config import settings
from tests.test_w5b_679_playbooks import hold

NOW = "2026-11-02T00:00:00Z"
BODY = 10
#: an element of the HAZOP playbook whose only cue is "node(s)"
ELEMENT = "Division of the plant into nodes"
LINE = "The panel will check every item of the batch during the working sessions."
CUE = "The nodes are listed for the panel so that each one holds a single line."
PLANT = [(LINE, "helv", BODY)] * 3


def _store(tmp_path, doc_id: str, pages: list[list[tuple]]) -> None:
    """A real PDF, stored and chunked as the upload path leaves it (status ready)."""
    pdf = pymupdf.open()
    for items in pages:
        page = pdf.new_page(width=600, height=800)
        for k, (text, font, size) in enumerate(items):
            page.insert_text((40, 130 + 20 * k), text, fontname=font, fontsize=size)
    (tmp_path / "uploads").mkdir(exist_ok=True)
    pdf.save(str(tmp_path / "uploads" / f"{doc_id}.pdf"))
    texts = [p.get_text() for p in pdf]
    pdf.close()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,?,'chunking',?,?)",
            (
                doc_id,
                f"{doc_id}.pdf",
                f"sha-{doc_id}",
                f"uploads/{doc_id}.pdf",
                len(texts),
                NOW,
            ),
        )
        for n, text in enumerate(texts, start=1):
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                " VALUES (?,?,?,?,0,0)",
                (doc_id, n, text, len(text)),
            )
    chunker.chunk_document(doc_id, force=True)
    with db.connect() as conn:
        conn.execute("UPDATE documents SET status='ready' WHERE id=?", (doc_id,))


@pytest.fixture(autouse=True)
def switches(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "guess.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    monkeypatch.setattr(settings, "pdf_heading_detection_enabled", True)
    monkeypatch.setattr(settings, "playbook_section_presence_enabled", True)
    monkeypatch.setattr(settings, "playbook_presence_without_standard_enabled", True)
    yield
    db.reset_connection()


def _entry(doc_id: str) -> dict:
    found, _ = playbooks.available()
    allowed = frozenset(
        r[0] for r in db.connect().execute("SELECT id FROM documents").fetchall()
    )
    report = playbooks.review(
        doc_id, found["hazop_procedure"], allowed_document_ids=allowed
    )
    return next(e for e in report["elements"] if e["title"] == ELEMENT)


def _font_only_section(tmp_path, doc_id="f1"):
    """A bold line holding the cue, the other cue further down under the inherited section."""
    _store(
        tmp_path,
        doc_id,
        [
            [
                ("Other Matters", "hebo", BODY),
                *PLANT,
                ("Plant Nodes", "hebo", BODY),
                *PLANT * 4,
                (CUE, "helv", BODY),
                *PLANT,
            ],
            [
                ("Further Matters", "hebo", BODY),
                *PLANT,
                ("Closing Matters", "hebo", BODY),
                *PLANT,
            ],
        ],
    )
    assert "Plant Nodes" in pdf_headings.font_only_headings(doc_id)


def test_a_font_only_heading_is_never_section_found_without_the_standard(tmp_path):
    _font_only_section(tmp_path)
    entry = _entry("f1")
    assert entry["section_state"] == playbooks.UNCLEAR
    assert entry["state"] == playbooks.STANDARD_NOT_HELD
    assert "section found" not in entry["reason"]
    assert "guess" in entry["reason"]


def test_a_font_only_heading_is_never_present_with_the_standard_held(tmp_path):
    hold("IEC 61882")
    _font_only_section(tmp_path)
    entry = _entry("f1")
    assert entry["state"] == playbooks.UNCLEAR
    assert "guess" in entry["reason"]


def test_a_heading_the_text_rules_read_is_still_found(tmp_path):
    pages = [[("4.1 Plant nodes", "helv", BODY), (CUE, "helv", BODY), *PLANT]]
    _store(tmp_path, "t1", pages)
    assert pdf_headings.font_only_headings("t1") == frozenset()
    with db.connect() as conn:
        assert conn.execute(
            "SELECT section FROM chunks WHERE document_id='t1'"
        ).fetchone()[0]
    # nearest heading confirmed by the text rule: not a guess, in both branches
    hold("IEC 61882")
    assert _entry("t1")["state"] == playbooks.PRESENT


def test_a_text_rule_heading_without_the_standard_is_still_found(tmp_path):
    pages = [
        [
            ("4.1 Plant nodes", "helv", BODY),
            (CUE, "helv", BODY),
            *PLANT,
            ("4.2 Other matters", "helv", BODY),
            *PLANT,
            ("4.3 Later matters", "helv", BODY),
            *PLANT,
        ]
    ]
    _store(tmp_path, "t2", pages)
    entry = _entry("t2")
    assert entry["section_state"] == playbooks.PRESENT
    assert "section found" in entry["reason"]


def test_one_false_label_does_not_end_could_not_be_checked(tmp_path):
    """Nothing about the element in the text, and only one label read from the font."""
    _store(tmp_path, "o1", [[("A Lone Label", "hebo", BODY), *PLANT * 3]])
    entry = _entry("o1")
    assert entry["section_state"] == playbooks.COULD_NOT_BE_CHECKED
    assert "Section not found" not in entry["reason"]


def test_not_found_on_font_headings_alone_is_marked_as_a_guess(tmp_path):
    pages = [
        [
            ("First Matters", "hebo", BODY),
            *PLANT,
            ("Second Matters", "hebo", BODY),
            *PLANT,
        ],
        [
            ("Third Matters", "hebo", BODY),
            *PLANT,
            ("Fourth Matters", "hebo", BODY),
            *PLANT,
        ],
    ]
    _store(tmp_path, "m1", pages)
    entry = _entry("m1")
    assert entry["section_state"] == playbooks.MISSING
    assert entry["reason"].startswith(f"Section not found: {ELEMENT}.")
    assert "guess" in entry["reason"]


def test_not_found_on_text_rule_headings_carries_no_guess_mark(tmp_path):
    pages = [
        [
            ("4.1 First matters", "helv", BODY),
            *PLANT,
            ("4.2 Second matters", "helv", BODY),
            *PLANT,
            ("4.3 Third matters", "helv", BODY),
            *PLANT,
        ]
    ]
    _store(tmp_path, "m2", pages)
    entry = _entry("m2")
    assert entry["section_state"] == playbooks.MISSING
    assert "guess" not in entry["reason"]


def test_with_the_detection_switch_off_nothing_is_marked(tmp_path, monkeypatch):
    pages = [[("4.1 Plant nodes", "helv", BODY), (CUE, "helv", BODY), *PLANT]]
    _store(tmp_path, "t3", pages)
    monkeypatch.setattr(settings, "pdf_heading_detection_enabled", False)
    assert pdf_headings.font_only_headings("t3") is None
    # one heading is enough, as before the detection existed
    assert _entry("t3")["section_state"] == playbooks.PRESENT


def test_a_word_document_has_no_font_only_headings(tmp_path):
    _store(tmp_path, "w1", [[("Plant Nodes", "hebo", BODY), *PLANT]])
    with db.connect() as conn:
        conn.execute("UPDATE documents SET pagination='flow' WHERE id='w1'")
    assert pdf_headings.font_only_headings("w1") is None
