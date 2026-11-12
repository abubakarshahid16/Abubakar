"""Two-reader verdicts count as decisions; the owner's words on the sheet; the contractor copy per kind behind a flag (owner, 12 Nov 2026).

Invented data; no model, no network."""

# ruff: noqa: F811
from __future__ import annotations

import itertools

import openpyxl
import pytest

from app import agent_review_two_reader as two
from app import agent_review_wording as W
from app import crs_ai_words as words
from app import crs_ai_workbook as WB
from app import kind_review_table, rule_labels
from app.api import agent_review_schemas as contract
from tests.test_agent_review_crs import META, mk, rows_of
from tests.test_agent_review_routes import client, finished_run  # noqa: F401

CLASS = two.CLASS_TWO_READERS


def verdict_line(word="AI verdict: met", **kw):
    """A textual line the always-on route made an "AI verdict" (old second opinion agreed, guards ok), for the CRS."""
    ai = "Pass" if word == two.WORD_MET else "Fail"
    base = {
        "verdict": "Pass" if ai == "Pass" else "Fail", "decided_by": "AI verdict", "ai_verdict": ai, "reason_code": "met" if ai == "Pass" else "not_met",
        "model": "m1", "second_opinion": {"agree": True, "model": "m2"}, "pass_guard": {"ok": True} if ai == "Pass" else None,
        "quotes_checked": {"paper": True, "clause": True, "clause_strong": True}, "field_roles": ["x"],
    }  # fmt: skip
    base.update(kw)
    return mk("R-9", base.pop("verdict"), base.pop("ai_verdict"), **base)


# ---------------------------------------------------------------- the owner's words, one home


def test_the_sentence_opens_with_the_owners_words_then_the_true_route_then_the_engineer():
    for met in (True, False):
        head = (
            "Met (AI, two readers agree, quotes verified)"
            if met
            else "Not met (AI, two readers agree, quotes verified)"
        )
        always_on = words.verdict_prefix(False, met)
        independent = words.verdict_prefix(True, met)
        assert (
            always_on.startswith(head + ": ")
            and "saw the first answer" in always_on
            and always_on.endswith("engineer to confirm.")
        )
        assert (
            independent.startswith(head + ": ")
            and "reached independently by two AI readers" in independent
            and "saw the first" not in independent
        )
        assert "independent" not in always_on.lower()


def test_the_crs_cell_carries_the_owners_words_for_met_and_not_met_by_route():
    met, not_met = verdict_line("AI verdict: met"), verdict_line("AI verdict: not met")
    for ln, head in (
        (met, "Met (AI, two readers agree, quotes verified)"),
        (not_met, "Not met (AI, two readers agree, quotes verified)"),
    ):
        assert (ln["verdict_class"], ln["verdict_label"]) == (
            CLASS,
            "AI verdict: met" if "Not" not in head else "AI verdict: not met",
        ), ln
        text = WB.layout_comment(ln, *WB.status_of(ln))
        assert (
            f"\n{head}: one AI reader's verdict, checked by a second AI reader that saw the first answer, engineer to confirm."
            in text
        )


def test_the_stored_class_and_words_are_unchanged():
    assert contract.LINE_TABLE[CLASS][0][:2] == (
        "AI verdict: met",
        "AI verdict: not met",
    )


# ---------------------------------------------------------------- the one count of decisions


@pytest.mark.parametrize(
    "cls,word",
    list(
        itertools.product(
            W.CLASSES,
            (
                "Pass",
                "Fail",
                "AI verdict: met",
                "AI verdict: not met",
                "AI verdict: not stated",
                "AI thinks: met",
                "AI thinks: not met",
                "Query",
                "x",
            ),
        )
    ),
)
def test_a_decision_is_code_pass_fail_or_a_two_reader_met_or_not_met_nothing_else(
    cls, word
):
    want = cls == W.CLASS_PROVEN or (
        cls == CLASS and word in ("AI verdict: met", "AI verdict: not met")
    )
    assert (W.decisions_of([(cls, word)])["total"] == 1) is want


def test_decisions_split_into_code_and_two_reader():
    pairs = [
        (W.CLASS_PROVEN, "Pass"),
        (W.CLASS_PROVEN, "Fail"),
        (CLASS, "AI verdict: met"),
        (CLASS, "AI verdict: not met"),
        (CLASS, "AI verdict: not stated"),
        (W.CLASS_OPINION, "AI thinks: met"),
    ]
    assert W.decisions_of(pairs) == {"code": 2, "two_reader": 2, "total": 4}


def test_counts_carry_the_decisions_the_notes_say_them_and_the_summary_route_returns_them(
    tmp_path, client
):
    lines = [
        mk("R-1", "Fail", "Fail"),
        mk("R-2", "Pass", "Pass"),
        verdict_line("AI verdict: met"),
        mk("R-3", "Query", "Fail", why="w"),
    ]
    got = W.counts(lines)
    assert (got["decisions"], got["decisions_code"], got["decisions_two_reader"]) == (
        3,
        2,
        1,
    )
    path = WB.write(lines, tmp_path / "i.xlsx", META, "internal")
    notes = {
        r[0]: r[1]
        for r in openpyxl.load_workbook(path)["Notes"].iter_rows(
            min_row=2, values_only=True
        )
    }
    assert (
        notes["Decisions"] == "Decisions: 3 = code Pass/Fail 2 + two-reader verdicts 1"
    )
    run_id = finished_run(client)
    body = client.get(f"/api/reviews/runs/{run_id}/agent/summary").json()
    classes = body["counts_by_class"]
    assert (
        body["decisions"]["total"]
        == body["decisions"]["code"] + body["decisions"]["two_reader"]
    )
    assert body["decisions"]["code"] == classes.get(
        W.CLASS_PROVEN, 0
    )  # the proven class holds only Pass and Fail
    assert body["decisions"]["two_reader"] <= classes.get(CLASS, 0)


# ---------------------------------------------------------------- the contractor flag


def test_the_contractor_flag_is_false_for_every_paper_kind_and_names_every_kind():
    table = kind_review_table.table()["kinds"]
    assert set(rule_labels.PAPER_KINDS) <= set(table)
    assert all(row["contractor_copy_ai_verdict"] is False for row in table.values())
    assert not any(
        kind_review_table.contractor_copy_ai_verdict(k) for k in (*table, "no-such-kind", None)
    )


def _all_shapes():
    out = [
        mk("R-1", "Fail", "Fail"),
        mk("R-2", "Pass", "Pass"),
        mk("R-3", "Query", "Fail", why="w"),
        mk("R-4", "Query", "Pass", why="w"),
        mk("R-5", "Query", None, why="w"),
    ]
    out += [verdict_line("AI verdict: met"), verdict_line("AI verdict: not met")]
    out += [
        verdict_line(
            "AI verdict: not met",
            quotes_checked={"paper": True, "clause": False, "clause_strong": False},
            item_id="R-10",
        )
    ]
    return out


def _contractor(tmp_path, lines, kind="datasheet"):
    path = WB.write(
        lines, tmp_path / "c.xlsx", {**META, "paper_kind": kind}, "contractor"
    )
    return rows_of(path), "\n".join(
        str(c)
        for row in openpyxl.load_workbook(path).active.iter_rows(values_only=True)
        for c in row
        if c is not None
    )


def test_no_ai_verdict_reaches_the_contractor_copy_while_the_flag_is_false(tmp_path):
    lines = _all_shapes()
    for kind in (*rule_labels.PAPER_KINDS, None, "unknown"):
        rows, text = _contractor(tmp_path, lines, kind)
        assert len(rows) == 1, (
            kind
        )  # the one proven Fail (the contractor copy has no Status column)
        for banned in (
            "AI verdict",
            "AI reader",
            "Met (AI",
            "Not met (AI",
            "AI opinion",
        ):
            assert banned not in text


@pytest.fixture
def flagged(monkeypatch):
    monkeypatch.setattr(
        kind_review_table, "contractor_copy_ai_verdict", lambda kind: kind == "datasheet"
    )


def test_a_flagged_kind_adds_only_guarded_not_met_rows_worded_for_the_contractor(
    tmp_path, flagged
):
    lines = _all_shapes()
    rows, text = _contractor(tmp_path, lines, "datasheet")
    assert (
        len(rows) == 2
    )  # the proven Fail, then the guarded not met; never met, never one with an unverified quote
    assert words.has_banned(text) is False
    for banned in (
        "AI verdict",
        "AI reader",
        "AI opinion",
        "two readers",
        "Met (AI",
        "AI ",
    ):
        assert banned not in text, banned
    other_kind_rows, _ = _contractor(tmp_path, lines, "procedure")
    assert len(other_kind_rows) == 1  # only the flagged kind moved


def test_a_flagged_kind_never_adds_met_not_stated_opinions_or_a_recommendation(
    tmp_path, flagged
):
    shapes = [
        verdict_line("AI verdict: met"),
        verdict_line("AI verdict: not met", rule_kind="advice", item_id="R-11"),
        mk("R-12", "Query", "Fail", why="w"),
    ]
    rows, _ = _contractor(tmp_path, shapes, "datasheet")
    assert rows == []


def test_the_flag_is_read_only_by_the_contractor_item_filter():
    import inspect
    import pathlib

    root = pathlib.Path(WB.__file__).parent
    users = [
        p.name
        for p in root.glob("*.py")
        if "contractor_copy_ai_verdict(" in p.read_text(encoding="utf-8")
    ]
    assert sorted(users) == ["crs_ai_workbook.py", "kind_review_table.py"]
    src = inspect.getsource(WB)
    assert (
        src.count("kind_review_table.contractor_copy_ai_verdict(") == 1
        and "def _contractor_items" in src
    )
