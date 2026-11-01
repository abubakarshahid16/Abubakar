"""The MERGE path of a figure page (#1540 follow-up): recognised text is added to the
text layer, never replaces it. The recogniser is a fake; the text is invented.

`test_figure_page_ocr.py` covers routing only. A routed figure page keeps its
running header in the text layer and recognition reads the drawing's labels, so
`ocr.recognise_batch` must hand both to `ocr.merge_page_text`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import ocr, pageimage

HEADER = (
    "Specification for Invented Vessels Page 47 of 82 Doc ZZ-100 J.2 Vortex breaker"
)
FOOTER = "Issued April 2022 Rev 3"
NATIVE = [(40.0, 100.0, HEADER), (1500.0, 100.0, FOOTER)]


def _box(y, x=100.0):
    return [[x, y], [x + 300, y], [x + 300, y + 20], [x, y + 20]]


def _run(monkeypatch, native, recognised):
    """recognise_batch on one page with a fake engine; recognised = [(y, text)]."""
    res = SimpleNamespace(
        txts=[t for _, t in recognised],
        scores=[0.95] * len(recognised),
        boxes=[_box(y) for y, _ in recognised],
    )
    monkeypatch.setattr(ocr, "_build_engine", lambda: lambda _img: res)
    monkeypatch.setattr(ocr, "_native_lines", lambda *_a, **_k: native)
    monkeypatch.setattr(pageimage, "render_page", lambda *_a, **_k: "fake.png")
    row = ocr.recognise_batch("stored.pdf", "sha", [1])[0]
    assert row[9] is None, row[9]
    return row[1]


def test_recognised_labels_are_added_and_the_header_stays_whole(monkeypatch):
    text = _run(
        monkeypatch,
        NATIVE,
        [(400.0, "Nozzle N1 flange 150 RF"), (800.0, "Vortex breaker detail A")],
    )
    lines = text.splitlines()
    assert HEADER in lines and FOOTER in lines  # the native lines are whole
    assert "Nozzle N1 flange 150 RF" in lines and "Vortex breaker detail A" in lines
    assert lines[0] == HEADER and lines[-1] == FOOTER  # reading order kept


def test_a_recognised_line_the_text_layer_already_says_is_not_added(monkeypatch):
    text = _run(
        monkeypatch,
        NATIVE,
        [
            (40.0, "Specification for Invented Vessels"),
            (400.0, "Nozzle N1 flange 150 RF"),
        ],
    )
    assert text.splitlines().count(HEADER) == 1
    assert "Specification for Invented Vessels" not in text.splitlines()
    assert "Nozzle N1 flange 150 RF" in text


def test_a_misread_copy_of_a_native_line_is_not_added(monkeypatch):
    misread = HEADER.replace("Vessels", "Vessels.").replace("Doc", "Dcc")
    text = _run(
        monkeypatch, NATIVE, [(42.0, misread), (400.0, "Nozzle N1 flange 150 RF")]
    )
    assert misread not in text.splitlines()
    assert text.splitlines().count(HEADER) == 1


def test_nothing_recognised_leaves_the_page_text_unchanged(monkeypatch):
    # empty stored text: the page keeps its text layer and is not claimed as recognised
    assert _run(monkeypatch, NATIVE, []) == ""
    assert ocr.merge_page_text(NATIVE, []) == ("\n".join([HEADER, FOOTER]), 0)


def test_only_duplicates_recognised_adds_nothing(monkeypatch):
    assert _run(monkeypatch, NATIVE, [(40.0, HEADER)]) == ""
    merged, added = ocr.merge_page_text(NATIVE, [(40.0, 100.0, HEADER)])
    assert (merged, added) == ("\n".join([HEADER, FOOTER]), 0)


def test_merge_never_drops_a_native_line():
    rec = [(400.0, 100.0, "Nozzle N1 flange 150 RF")]
    merged, added = ocr.merge_page_text(NATIVE, rec)
    assert added == 1
    assert merged.splitlines() == [HEADER, "Nozzle N1 flange 150 RF", FOOTER]


@pytest.mark.parametrize("n", [0, 3])
def test_added_count_matches_new_lines(n):
    rec = [
        (300.0 + 100 * i, 100.0, f"Label number {i} on the drawing") for i in range(n)
    ]
    assert ocr.merge_page_text(NATIVE, rec)[1] == n
