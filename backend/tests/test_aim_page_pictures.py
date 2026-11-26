"""Page pictures in a review (owner, 26 Nov 2026, #1584 7188761254; `aim_review.pictures`, job J3). Invented paper; no model, no
network: a stand-in provider answers each page picture."""

from __future__ import annotations

import pytest

from app import picture_stage
from app.aim_review import budget, pictures
from app.aim_review.engine import Meter
from app.config import settings
from app.reasoning_provider import Response
from tests.test_aim_method_helpers import PAPER, open_aim_db

PICTURE_PAGE = 3


@pytest.fixture()
def aim_db(tmp_path, monkeypatch):
    gen = open_aim_db(tmp_path, monkeypatch)
    conn = next(gen)
    with conn:  # one page of the invented paper holds no text (a sketch); its recognition had its turn and found none
        conn.execute("INSERT INTO pages (document_id, page_no, text, char_count, batch_no, needs_ocr) VALUES (?, ?, '', 0, 0, 0)",
                     (PAPER, PICTURE_PAGE))  # fmt: skip
    yield conn
    next(gen, None)


class _Provider:
    """Stands in for Claude: reads every page picture as one invented line, at an invented cost."""

    def __init__(self):
        self.packets = []

    def reason(self, packet):
        self.packets.append(packet)
        return Response(text="SKETCH: nozzle N1 4 in, overall length 1250 mm (invented)", provider="claude",
                        model_tag="claude-invented", digest="d", finish_reason="end_turn", prompt_sha256="p",
                        tokens_in=1000, tokens_out=40, cost_usd=0.02)  # fmt: skip


@pytest.fixture()
def wired(monkeypatch):
    provider = _Provider()
    monkeypatch.setattr(pictures, "_provider", lambda: (provider, None))
    monkeypatch.setattr(
        "app.agent_review_pages.pdf_path", lambda *_a, **_k: "/invented/paper.pdf"
    )

    def transcribe(
        path, page_no, prov
    ):  # the stage's own reading, with the page image left out (no PDF here)
        from app.reasoning_provider import Packet

        return prov.reason(
            Packet(
                prompt=f"Page {page_no}. Transcribe it.",
                num_ctx=1,
                num_predict=1,
                step="vision",
            )
        ).text

    monkeypatch.setattr(picture_stage, "_transcribe", transcribe)
    return provider


def test_switch_off_reads_no_picture_and_the_plan_names_none(aim_db, wired):
    assert settings.aim_page_pictures_enabled is False  # off by default
    meter = Meter(cap=5.0)
    assert (
        pictures.read(aim_db, PAPER, meter) is None
        and pictures.plan_block(aim_db, PAPER) is None
    )
    assert wired.packets == [] and meter.calls == []


def test_switch_on_reads_the_papers_no_text_pages_inside_the_run_and_charges_the_runs_meter(
    aim_db, wired, monkeypatch
):
    monkeypatch.setattr(settings, "aim_page_pictures_enabled", True)
    plan = pictures.plan_block(aim_db, PAPER)
    assert (
        plan["pages"] == [PICTURE_PAGE]
        and "page 3 of the paper under review" in plan["sentence"]
    )
    meter = Meter(cap=5.0)
    counts = pictures.read(aim_db, PAPER, meter)
    assert counts[picture_stage.READ] == 1 and len(wired.packets) == 1
    assert [(c.step, c.usd) for c in meter.calls] == [
        (pictures.STEP, 0.02)
    ] and meter.spent == pytest.approx(0.02)
    stored = aim_db.execute(
        "SELECT engine, char_count FROM page_ocr WHERE document_id = ? AND page_no = ?",
        (PAPER, PICTURE_PAGE),
    ).fetchone()
    assert (
        stored["engine"] == picture_stage.ENGINE and stored["char_count"] > 20
    )  # the review then reads it as recognised text
    from app.aim_review.paper import load_paper

    read = load_paper(aim_db, PAPER)
    assert "nozzle N1" in read.pages.get(PICTURE_PAGE, "")  # read as text
    assert (
        pictures.read(aim_db, PAPER, Meter(cap=5.0)) is None
    )  # read once: a later review does not send it again


def test_a_page_that_would_pass_the_runs_cap_is_refused_and_named_and_a_later_review_may_read_it(
    aim_db, wired, monkeypatch
):
    monkeypatch.setattr(settings, "aim_page_pictures_enabled", True)
    meter = Meter(cap=0.0001)
    counts = pictures.read(aim_db, PAPER, meter)
    assert (
        counts[picture_stage.REFUSED] == 1 and wired.packets == [] and meter.calls == []
    )
    assert picture_stage.recorded(aim_db, PAPER) == {
        PICTURE_PAGE: picture_stage.REFUSED
    }
    assert pictures.todo(aim_db, PAPER) == [
        PICTURE_PAGE
    ]  # refused by THAT run's cap: the next review may read it
    assert pictures.read(aim_db, PAPER, Meter(cap=5.0))[picture_stage.READ] == 1


def test_local_only_and_claude_not_available_send_no_picture(
    aim_db, wired, monkeypatch
):
    monkeypatch.setattr(settings, "aim_page_pictures_enabled", True)
    with budget.using(budget.LOCAL):
        assert pictures.read(aim_db, PAPER, Meter(cap=5.0)) is None
    monkeypatch.setattr(
        pictures,
        "_provider",
        lambda: (None, "the AI reviewer's engine line is not claude"),
    )
    assert pictures.read(aim_db, PAPER, Meter(cap=5.0)) is None
    assert wired.packets == []
