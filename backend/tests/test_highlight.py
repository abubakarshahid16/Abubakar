"""Boxing the answer on the rendered page.

The most convincing thing this product does: an engineer sees the answer
outlined on the specification page they already know. Reading a quotation asks
them to trust the extraction; seeing it boxed asks them to trust nothing.

Which is exactly why a wrong box is unacceptable. One box around the wrong
clause and no box is ever trusted again, so every test here is about the
system declining to draw rather than drawing something plausible.
"""

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import db, highlight, keyword, pageimage
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

ZINC = [
    "8.2",
    "Coating materials",
    "The materials for metal spraying shall be in accordance with the following:",
    "Aluminium: Type Al 99.5 of DIN 8566-2 or equivalent.",
    "Zinc or alloys of zinc shall be supplied with product data sheets.",
    "Maximum operating temperature when zinc metal coating is used is 120 C.",
]


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def upload(client, blocks=(ZINC,), name="spec.pdf") -> str:
    path = settings.data_dir / name
    doc = pymupdf.open()
    for block in blocks:
        page = doc.new_page()
        for i, line in enumerate(block):
            page.insert_text((72, 100 + i * 18), line)
    doc.save(str(path))
    doc.close()
    with open(path, "rb") as fh:
        doc_id = client.post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    return doc_id


def stored_path(document_id: str) -> str:
    return db.connect().execute(
        "SELECT stored_path FROM documents WHERE id = ?", (document_id,)
    ).fetchone()["stored_path"]


# ------------------------------------------------------------- locating


def test_a_sentence_on_the_page_is_located():
    client = TestClient(app)
    doc_id = upload(client)
    rects, matched = highlight.locate(
        stored_path(doc_id),
        1,
        "Maximum operating temperature when zinc metal coating is used is 120 C.",
    )
    assert rects
    assert matched
    x0, y0, x1, y1 = rects[0]
    assert x1 > x0 and y1 > y0


def test_text_that_is_not_on_the_page_is_not_located():
    """The case the whole feature depends on getting right."""
    client = TestClient(app)
    doc_id = upload(client)
    rects, matched = highlight.locate(
        stored_path(doc_id), 1, "Inconel 625 cladding thickness shall be 3 mm."
    )
    assert rects == []
    assert matched is None


def test_a_damaged_span_falls_back_to_less_of_the_SAME_text():
    """Extraction normalises whitespace and drops symbol-font characters, so a
    verbatim search misses often. Every fallback is a SHORTER piece of the same
    text - never different text and never approximate matching, because that is
    the difference between a miss and a wrong box."""
    client = TestClient(app)
    doc_id = upload(client)
    damaged = (
        "The  materials for metal spraying shall be in accordance with the "
        "following:  �� garbage that was never on the page"
    )
    rects, matched = highlight.locate(stored_path(doc_id), 1, damaged)
    assert rects
    # what matched is a prefix of what was asked for, not a paraphrase of it
    assert matched
    assert damaged.replace("  ", " ").startswith(matched[:30])


def test_a_fragment_too_short_to_be_unique_is_never_attempted():
    assert highlight._candidates("3") == []
    assert highlight._candidates("of the") == []
    assert all(
        len(c) >= highlight.MIN_FRAGMENT_CHARS
        for c in highlight._candidates(
            "Maximum operating temperature when zinc metal coating is used is 120 C."
        )
    )


def test_a_match_covering_most_of_the_page_is_rejected():
    """That is not a highlight, it is the page. Something matched far too
    loosely and drawing it would say "the answer is everything"."""
    assert highlight.MAX_COVERAGE < 1.0
    client = TestClient(app)
    doc_id = upload(client)
    with pymupdf.open(stored_path(doc_id)) as doc:
        page_area = abs(doc.load_page(0).rect.get_area())
    rects, _ = highlight.locate(stored_path(doc_id), 1, "Zinc or alloys of zinc")
    area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in rects)
    assert area / page_area <= highlight.MAX_COVERAGE


def test_a_page_out_of_range_is_a_miss_not_a_crash():
    client = TestClient(app)
    doc_id = upload(client)
    assert highlight.locate(stored_path(doc_id), 999, "anything at all here") == ([], None)


# --------------------------------------------- only box an identified answer


def test_no_box_is_drawn_without_an_identified_answering_sentence():
    """A box means "here is the answer". With no span there is no answer to
    point at, and boxing the whole passage instead produced eleven rectangles
    covering most of the text - not a wrong box, but it reads as "the answer is
    all of this", which is its own kind of untrue."""
    client = TestClient(app)
    doc_id = upload(client)
    result = highlight.rectangles_for_answer(
        {"stored_path": stored_path(doc_id)}, 1, "some passage text here", None
    )
    assert result["located"] is False
    assert result["rects"] == []
    assert "no box is drawn" in result["note"]


def test_a_span_that_does_not_fit_the_passage_draws_nothing():
    client = TestClient(app)
    doc_id = upload(client)
    result = highlight.rectangles_for_answer(
        {"stored_path": stored_path(doc_id)}, 1, "short", [10, 900]
    )
    assert result["located"] is False
    assert result["rects"] == []


def test_for_chunk_boxes_the_sentence_that_answers_the_question():
    client = TestClient(app)
    doc_id = upload(client)
    chunk_id = db.connect().execute(
        "SELECT id FROM chunks WHERE document_id = ? AND retrievable = 1 LIMIT 1",
        (doc_id,),
    ).fetchone()["id"]

    result = highlight.for_chunk(
        doc_id, chunk_id, "what is the maximum operating temperature for zinc"
    )
    assert result["located"] is True
    assert result["rects"]
    assert "Maximum operating temperature" in result["matched_fragment"]


def test_for_chunk_on_an_unknown_chunk_is_a_miss():
    client = TestClient(app)
    doc_id = upload(client)
    result = highlight.for_chunk(doc_id, "nope", "anything")
    assert result["located"] is False
    assert result["rects"] == []


# ----------------------------------------------------------- the rendering


def test_the_boxed_render_differs_from_the_plain_one():
    client = TestClient(app)
    doc_id = upload(client)
    doc = dict(
        db.connect().execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    )
    rects, _ = highlight.locate(
        doc["stored_path"], 1, "Maximum operating temperature when zinc metal coating"
    )
    assert rects
    boxed = pageimage.render_page_with_highlight(doc, 1, rects)
    plain = pageimage.render_page(doc, 1)
    assert boxed != plain
    assert boxed.read_bytes() != plain.read_bytes()


def test_the_boxed_render_is_cached_by_what_was_drawn():
    """The cache key has to include the rectangles, or a second question would
    be served the first question's box."""
    client = TestClient(app)
    doc_id = upload(client)
    doc = dict(
        db.connect().execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    )
    first, _ = highlight.locate(doc["stored_path"], 1, "Maximum operating temperature when zinc")
    second, _ = highlight.locate(doc["stored_path"], 1, "The materials for metal spraying shall")
    assert first and second and first != second

    a = pageimage.render_page_with_highlight(doc, 1, first)
    b = pageimage.render_page_with_highlight(doc, 1, second)
    assert a != b, "two different answers on one page shared a cached render"
    assert a == pageimage.render_page_with_highlight(doc, 1, first)


def test_no_rectangles_falls_back_to_the_plain_render():
    client = TestClient(app)
    doc_id = upload(client)
    doc = dict(
        db.connect().execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    )
    assert pageimage.render_page_with_highlight(doc, 1, []) == pageimage.render_page(doc, 1)


# ------------------------------------------------------------- the endpoint


def test_the_endpoint_boxes_the_answer_and_says_it_did():
    client = TestClient(app)
    doc_id = upload(client)
    question = "what is the maximum operating temperature for zinc metal coating"
    answer = client.get(f"/api/answer?q={question}").json()
    passage = answer["answer_passages"][0]

    response = client.get(
        f"/api/documents/{doc_id}/pages/{passage['page_start']}/image",
        params={"chunk_id": passage["chunk_id"], "q": question},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["X-Answer-Located"] == "1"


def test_the_endpoint_says_so_when_it_could_not_locate_the_answer():
    """An unboxed page must not leave the reader assuming the answer is not on
    it. The header distinguishes "no box because we could not find it" from
    "no box because none was asked for"."""
    client = TestClient(app)
    doc_id = upload(client)
    chunk_id = db.connect().execute(
        "SELECT id FROM chunks WHERE document_id = ? AND retrievable = 1 LIMIT 1",
        (doc_id,),
    ).fetchone()["id"]

    response = client.get(
        f"/api/documents/{doc_id}/pages/1/image",
        params={"chunk_id": chunk_id, "q": "zzzz"},
    )
    assert response.status_code == 200
    assert response.headers["X-Answer-Located"] == "0"


def test_a_plain_request_carries_no_located_header_at_all():
    client = TestClient(app)
    doc_id = upload(client)
    response = client.get(f"/api/documents/{doc_id}/pages/1/image")
    assert response.status_code == 200
    assert "X-Answer-Located" not in response.headers


def test_the_endpoint_still_rejects_unknown_parameters():
    client = TestClient(app)
    doc_id = upload(client)
    assert client.get(f"/api/documents/{doc_id}/pages/1/image?bogus=1").status_code == 422
