"""P3 (15 Nov 2026): a reader's own "Query" is a view, never "no answer"; a reader that gives NO verdict is asked once more and then the
line is "Not reviewed" (counted apart, never on the contractor file). Invented papers and rules; no network."""

# ruff: noqa: F811
from __future__ import annotations

import collections
import json

import openpyxl
import pytest

from app import agent_review_local as local_mod
from app import agent_review_verdict as V
from app import agent_review_wording as W
from app import crs_ai_workbook as WB
from tests import agent_review_support as s
from tests.test_agent_review_crs import META, mk
from tests.test_agent_review_guards import run_review, w  # noqa: F401
from tests.test_agent_review_job import lines_of
from tests.test_agent_review_routes import client  # noqa: F401
from tests.test_crs_endpoint import temp_db  # noqa: F401
from tests.test_n1_local_ai_reviewer import local  # noqa: F401

OLD = "the AI did not give pass or fail"


class Seq(dict):
    """The invented reader's answers: for the ids in `drop`, the first N answers carry NO verdict key."""

    def __init__(self, base, drop):
        super().__init__(base)
        self.drop, self.n = dict(drop), collections.Counter()

    def __getitem__(self, key):
        value = dict.__getitem__(self, key)
        if self.n[key] < self.drop.get(key, 0):
            self.n[key] += 1
            return {k: v for k, v in value.items() if k != "verdict"}
        return value


# ---------------------------------------------------------------- the gate's words


def test_the_gate_says_the_reader_answered_query_or_gave_no_verdict():
    assert local_mod.no_decision_words("Query") == local_mod.AI_QUERY_WHY
    assert local_mod.no_decision_words(None) == local_mod.NO_VERDICT_WHY
    ok = V.QuoteCheck(True, True, clause_strong=True)
    got = V.textual_verdict("Query", ok, None, None)
    assert got["why"] == local_mod.AI_QUERY_WHY and got["verdict"] == "Query"
    assert V.textual_verdict(None, ok, None, None)["why"] == local_mod.NO_VERDICT_WHY


# ---------------------------------------------------------------- the reader's own Query, routed by its reason code


def _own(code, **kw):
    return mk(
        "R-8", "Query", "Query", why=local_mod.AI_QUERY_WHY, reason_code=code, **kw
    )


def test_the_readers_own_query_is_routed_by_its_reason_code_in_plain_words():
    for code, group, words in (
        ("sheet_silent", W.GROUP_SILENT, "the sheet does not state this"),
        (
            "needs_drawing_or_calc",
            W.GROUP_DRAWING,
            "needs a drawing or a calculation to judge",
        ),
        (
            "unclear_clause",
            W.GROUP_COULD_NOT,
            "the AI could not decide: the rule's clause is not clear enough to apply",
        ),
        ("other", W.GROUP_COULD_NOT, "the AI could not decide: it gave another reason"),
        ("something_new", W.GROUP_COULD_NOT, "the AI could not decide"),
    ):
        got = W.apply(_own(code))
        assert (
            W.reader_query_group(got) == group and got["verdict_class"] == W.CLASS_QUERY
        ), code
        if (
            group != W.GROUP_SILENT
        ):  # a silent sheet keeps the silence hold's own reason ("the paper is silent on this")
            assert got["not_proven_reason"].startswith(words), code
        assert "did not give pass or fail" not in got["not_proven_reason"]


def test_not_applicable_stays_the_class_does_not_apply_and_is_never_a_decision():
    got = W.apply(_own("not_applicable"))
    assert got["verdict_class"] == W.CLASS_NOT_APPLICABLE
    assert W.decisions_of([(got["verdict_class"], got["verdict_label"])])["total"] == 0


def test_earlier_runs_stored_the_old_sentence_for_the_readers_own_query_and_read_the_same_way():
    line = mk("R-8", "Query", "Query", why=OLD, reason_code="needs_drawing_or_calc")
    assert (
        W.reader_query_group(line) == W.GROUP_DRAWING
        and W.apply(line)["verdict_class"] == W.CLASS_QUERY
    )


def test_the_groups_are_counted_apart_on_the_counts_and_the_first_sheets_notes(
    tmp_path,
):
    lines = [
        _own("sheet_silent"),
        _own("needs_drawing_or_calc"),
        _own("needs_drawing_or_calc"),
        _own("unclear_clause"),
    ]
    for i, ln in enumerate(lines):
        ln["item_id"] = f"R-{i}"
    got = W.counts(lines)
    assert (
        got["query_contractor_silent"],
        got["query_engineer_drawing"],
        got["query_ai_could_not_decide"],
    ) == (1, 2, 1)
    path = WB.write(lines, tmp_path / "i.xlsx", META, "internal")
    notes = {
        r[0]: r[1]
        for r in openpyxl.load_workbook(path)["Notes"].iter_rows(
            min_row=2, values_only=True
        )
    }
    for g, n in ((W.GROUP_SILENT, 1), (W.GROUP_DRAWING, 2), (W.GROUP_COULD_NOT, 1)):
        assert notes[f"Count: {W.GROUP_LABELS[g]}"] == n


def test_a_drawing_question_is_for_the_engineer_not_the_contractor(tmp_path):
    view = WB.layout_view([_own("needs_drawing_or_calc")], META, "internal")
    cell = view["rows"][0][3]
    assert (
        "Engineer to judge this: it needs a drawing or a calculation." in cell
        and "Contractor to state" not in cell
    )
    # a silent line with no quote found on the page: the contractor states it (FTU-1: a found quote that may state it is the engineer's)
    quiet = _own("sheet_silent", quotes_checked={"paper": False, "clause": True})
    silent = WB.layout_view([quiet], META, "internal")["rows"][0][3]
    assert "Contractor to" in silent
    found = WB.layout_view([_own("sheet_silent")], META, "internal")["rows"][0][3]
    assert "Engineer to check" in found and "Contractor to state" not in found
    assert (
        WB.layout_view([_own("needs_drawing_or_calc")], META, "contractor")["rows"]
        == []
    )


# ---------------------------------------------------------------- no verdict at all


def _no_verdict_line(**kw):
    return mk("R-8", "Query", None, why=local_mod.NO_VERDICT_WHY, **kw)


def test_a_line_with_no_verdict_is_not_reviewed_and_never_a_question_met_or_not_met():
    for ln in (
        _no_verdict_line(),
        mk("R-8", "Query", None, why=OLD),
    ):  # a new line and one stored by an earlier run
        got = W.apply(ln)
        assert (got["verdict_class"], got["verdict_label"]) == (
            W.CLASS_NOT_REVIEWED,
            W.WORD_NOT_REVIEWED,
        )
        assert got["not_proven_reason"] == W.NO_VERDICT_WORDS == "the AI gave no answer"
        assert W.no_verdict(ln) is True
        assert (
            W.decisions_of([(got["verdict_class"], got["verdict_label"])])["total"] == 0
        )
    assert W.no_verdict(_own("other")) is False  # the reader's own Query is a view


def test_a_not_reviewed_line_is_on_its_own_sheet_counted_apart_and_never_on_the_contractor_file(
    tmp_path,
):
    ln = _no_verdict_line()
    assert W.counts([ln])["not_reviewed"] == 1
    internal = WB.write(
        [ln, mk("R-9", "Fail", "Fail")], tmp_path / "i.xlsx", META, "internal"
    )
    book = openpyxl.load_workbook(internal)
    other = [r for r in book["Not a comment"].iter_rows(values_only=True) if r and r[4] == "Not reviewed"]
    assert len(other) == 1  # order 14 lane B: the sheet of lines that are not comments; this one says "Not reviewed"
    contractor = WB.write(
        [ln, mk("R-9", "Fail", "Fail")], tmp_path / "c.xlsx", META, "contractor"
    )
    text = json.dumps(
        [
            list(r)
            for sh in openpyxl.load_workbook(contractor)
            for r in sh.iter_rows(values_only=True)
        ],
        default=str,
    )
    assert "the AI gave no answer" not in text and "R-8" not in text


# ---------------------------------------------------------------- the run: asked once more, same caps


def _lead_calls(fake):
    return sum(1 for k in fake.kinds if k == "lead")


def test_a_reader_that_gives_no_verdict_is_asked_once_more_and_the_second_answer_stands(
    w,
):
    fake = w["fake"]
    fake.answers = Seq(fake.answers, {"R-coat": 1})
    run_id = run_review()
    assert (
        sum("R-coat" in ids for ids in fake.lead_asked) == 2
    )  # the same item, asked again once
    line = json.loads(lines_of(run_id)["R-coat"]["line_json"])
    assert line["ai_verdict"] == "Pass" and not line.get("error")


def test_a_reader_that_still_gives_no_verdict_leaves_a_not_reviewed_line_kept_as_a_point(
    w,
):
    fake = w["fake"]
    fake.answers = Seq(fake.answers, {"R-coat": 9})
    run_id = run_review()
    assert (
        sum("R-coat" in ids for ids in fake.lead_asked) == 2
    )  # first ask and ONE more, never a third
    row = lines_of(run_id)["R-coat"]
    line = json.loads(row["line_json"])
    assert (row["verdict_class"], row["word"]) == ("Not reviewed", "Not reviewed")
    assert (
        line["error"] == local_mod.NO_VERDICT_CODE and line["item_id"] == "R-coat"
    )  # the stored line stays: the point is counted
    assert row["reason"] == "the AI gave no answer"


@pytest.mark.parametrize(("drop", "calls"), [(0, 1), (1, 2)])
def test_the_re_ask_is_one_more_lead_call_charged_to_the_run_like_any_call(
    w, drop, calls
):
    fake = w["fake"]
    fake.answers["R-colour"] = {
        **s.ANSWERS["R-mark"]
    }  # every item answered: the only extra call is the re-ask
    fake.answers = Seq(fake.answers, {"R-coat": drop})
    run_id = run_review()
    assert len(fake.lead_asked) == calls
    assert _usd(run_id) > 0
    assert (
        len(_spend_entries()) == 2 * len(fake.kinds)
    )  # EVERY call, the re-ask included, reserved and settled in the spend ledger (same caps)


def _spend_entries():
    from app.config import settings

    path = settings.claude_spend_log
    return (
        [ln for ln in path.read_text().splitlines() if ln.strip()]
        if path.exists()
        else []
    )


def _usd(run_id):
    from app import db

    return (
        db.connect()
        .execute("SELECT usd FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()["usd"]
    )


# ---------------------------------------------------------------- the page: earlier runs read the same way, never rewritten


def test_the_page_counts_the_groups_and_reads_an_earlier_no_verdict_line_as_not_reviewed(
    client,
):
    from app import db
    from tests.test_agent_review_routes import finished_run

    run_id = finished_run(client)
    conn = db.connect()
    rows = conn.execute(
        "SELECT item_id, line_json FROM agent_review_line WHERE run_id = ? ORDER BY item_id",
        (run_id,),
    ).fetchall()
    old = json.loads(rows[0]["line_json"])
    old.update(ai_verdict=None, verdict="Query", why=OLD, error=None)
    other = json.loads(rows[1]["line_json"])
    other.update(
        ai_verdict="Query",
        verdict="Query",
        why=OLD,
        reason_code="needs_drawing_or_calc",
        error=None,
    )
    for row, line in (
        (rows[0], old),
        (rows[1], other),
    ):  # what an earlier run stored: class Query, the old sentence
        conn.execute(
            "UPDATE agent_review_line SET verdict_class = 'Query for the engineer', word = 'Query', line_json = ? WHERE run_id = ? AND item_id = ?",
            (json.dumps(line), run_id, row["item_id"]),
        )
    conn.commit()
    before = conn.execute(
        "SELECT line_json FROM agent_review_line WHERE run_id = ? ORDER BY item_id",
        (run_id,),
    ).fetchall()
    summary = client.get(f"/api/reviews/runs/{run_id}/agent/summary").json()
    assert (
        summary["query_groups"]["engineer_drawing"] >= 1
        and summary["not_reviewed"] >= 1
    )
    shown = {
        ln["item_id"]: ln
        for ln in client.get(f"/api/reviews/runs/{run_id}/agent/lines").json()["lines"]
    }
    assert (
        shown[rows[0]["item_id"]]["verdict_class"],
        shown[rows[0]["item_id"]]["word"],
    ) == ("Not reviewed", "Not reviewed")
    assert shown[rows[0]["item_id"]]["reason"] == "the AI gave no answer"
    assert shown[rows[1]["item_id"]]["verdict_class"] == "Query for the engineer"
    assert (
        conn.execute(
            "SELECT line_json FROM agent_review_line WHERE run_id = ? ORDER BY item_id",
            (run_id,),
        ).fetchall()
        == before
    )


# ---------------------------------------------------------------- the local engine: the same rule, the local budget


def _asks_of(ollama, item_id):
    n = 0
    for body in ollama.bodies:
        user = body["messages"][-1]["content"]
        raw = (
            user[user.rfind('{"items":') :].split("\n\n")[0]
            if '{"items":' in user
            else ""
        )
        n += f'"item_id": "{item_id}"' in raw
    return n


@pytest.mark.parametrize(
    ("drop", "reviewed"), [(1, True), (2, True), (3, False), (9, False)]
)
def test_the_local_reader_that_gives_no_verdict_is_asked_once_more_and_then_not_reviewed(
    local, drop, reviewed
):
    """The invented paper needs two windows for R-coat: the windows are asked, then ONE more ask on the last window (the local
    budget rules: the same request, no loop). Three answers without a verdict leave the line "Not reviewed"."""
    local["ollama"].first = Seq(s.ANSWERS, {"R-coat": drop})
    got = lines_of(run_review())
    assert (
        _asks_of(local["ollama"], "R-coat") <= 3
    )  # two windows and the one more ask, never a loop
    if reviewed:
        assert got["R-coat"]["verdict_class"] != "Not reviewed"
    else:
        assert (
            got["R-coat"]["verdict_class"] == "Not reviewed"
            and got["R-coat"]["reason"] == "the AI gave no answer"
        )


def test_an_old_stored_reader_query_is_worded_truly_in_the_listing_the_points_and_a_built_crs(
    client, tmp_path
):
    """R62 F1: at read time the REASON is mapped too, everywhere a stored line is read; the false sentence appears nowhere."""
    from app import agent_review_wording, db, review_points
    from tests.test_agent_review_routes import finished_run

    run_id = finished_run(client)
    conn = db.connect()
    rows = conn.execute(
        "SELECT item_id, line_json FROM agent_review_line WHERE run_id = ? ORDER BY item_id",
        (run_id,),
    ).fetchall()
    stored = {}
    for row, code in zip(
        rows[:3],
        ("needs_drawing_or_calc", "unclear_clause", "sheet_silent"),
        strict=False,
    ):
        line = json.loads(row["line_json"])
        line.update(
            ai_verdict="Query",
            verdict="Query",
            decided_by="engineer",
            error=None,
            reason_code=code,
            why=OLD,
            not_proven_reason=OLD,
            silence_query=False,
            quotes_checked={"paper": True, "clause": True},
            textual_pass=False,
        )  # what the 12 Nov run stored
        stored[row["item_id"]] = (code, line)
        conn.execute(
            "UPDATE agent_review_line SET verdict_class = 'Query for the engineer', word = 'Query', reason = ?, line_json = ? WHERE run_id = ? AND item_id = ?",
            (OLD, json.dumps(line), run_id, row["item_id"]),
        )
    conn.commit()
    before = conn.execute(
        "SELECT item_id, line_json FROM agent_review_line WHERE run_id = ? ORDER BY item_id",
        (run_id,),
    ).fetchall()
    false_words = ("did not reach a view", "did not give pass or fail")
    # 1. the HTTP listing
    shown = {
        ln["item_id"]: ln
        for ln in client.get(f"/api/reviews/runs/{run_id}/agent/lines").json()["lines"]
    }
    for iid, (code, _line) in stored.items():
        text = shown[iid]["reason"]
        assert not any(f in text for f in false_words), (code, text)
    assert (
        "needs a drawing or a calculation to judge"
        in shown[
            next(i for i, (c, _) in stored.items() if c == "needs_drawing_or_calc")
        ]["reason"]
    )
    assert (
        "Engineer to judge this"
        in shown[
            next(i for i, (c, _) in stored.items() if c == "needs_drawing_or_calc")
        ]["reason"]
    )
    assert (
        "the AI could not decide"
        in shown[next(i for i, (c, _) in stored.items() if c == "unclear_clause")][
            "reason"
        ]
    )
    # 2. a CRS built from the stored lines of the old run
    lines = [
        json.loads(r["line_json"])
        for r in conn.execute(
            "SELECT line_json FROM agent_review_line WHERE run_id = ?", (run_id,)
        )
    ]
    path = WB.write(lines, tmp_path / "old.xlsx", META, "internal")
    cells = json.dumps(
        [
            list(r)
            for sh in openpyxl.load_workbook(path)
            for r in sh.iter_rows(values_only=True)
        ],
        default=str,
    )
    assert not any(f in cells for f in false_words)
    assert (
        "needs a drawing or a calculation to judge" in cells
        and "the AI could not decide" in cells
    )
    # 3. the points of the run (the page that signs)
    points, _held = review_points.ai_points_of_run(
        conn, run_id, "doc_paper", frozenset()
    )
    shown_points = json.dumps(
        [review_points.public(p) for p in points], default=str
    )  # what the page's route returns
    assert not any(f in shown_points for f in false_words)
    private = json.dumps(
        [p.get("_line") for p in points], default=str
    )  # the private copy the one CRS reads
    assert not any(
        f
        in json.dumps(
            [p["_line"].get("not_proven_reason") for p in points if p.get("_line")]
        )
        for f in false_words
    )
    assert private
    # nothing was rewritten
    assert (
        conn.execute(
            "SELECT item_id, line_json FROM agent_review_line WHERE run_id = ? ORDER BY item_id",
            (run_id,),
        ).fetchall()
        == before
    )
    assert agent_review_wording.read_time({"source": "general"}) == {
        "source": "general"
    }


def _old_query_lines(client, codes):
    """A finished run whose first lines are rewritten, in the table, to what the 12 Nov run stored for a reader's own Query."""
    from app import db
    from tests.test_agent_review_routes import finished_run

    run_id = finished_run(client)
    conn = db.connect()
    rows = conn.execute(
        "SELECT item_id, line_json FROM agent_review_line WHERE run_id = ? ORDER BY item_id",
        (run_id,),
    ).fetchall()
    ids = []
    for row, code in zip(rows, codes, strict=False):
        line = json.loads(row["line_json"])
        line.update(
            ai_verdict="Query", verdict="Query", decided_by="engineer", error=None, why=OLD, not_proven_reason=OLD,
            silence_query=False, quotes_checked={"paper": True, "clause": True}, textual_pass=False,
        )  # fmt: skip
        line.pop("reason_code", None) if code is None else line.update(reason_code=code)
        ids.append(row["item_id"])
        conn.execute(
            "UPDATE agent_review_line SET verdict_class = 'Query for the engineer', word = 'Query', reason = ?, line_json = ? WHERE run_id = ? AND item_id = ?",
            (OLD, json.dumps(line), run_id, row["item_id"]),
        )
    conn.commit()
    return run_id, ids, conn


def test_the_points_of_an_old_run_carry_the_true_reason_in_their_group_key(
    client, monkeypatch
):
    """R62b N1: `review_points.ai_points_of_run` reads the stored line through `read_time`; reverting that must fail this."""
    from app import review_points

    run_id, ids, conn = _old_query_lines(
        client, [None]
    )  # no reason code: the stored sentence is the reason of the group
    monkeypatch.setattr(
        review_points,
        "_book_of",
        lambda _c, _r: dict.fromkeys(ids, ("doc_std", "INV-STD")),
    )
    points, _held = review_points.ai_points_of_run(
        conn, run_id, "doc_paper", frozenset({"doc_std"})
    )
    keys = [p["group_key"] for p in points if p.get("group_key")]
    assert keys, "the invented run's point must group (a Query with a book and a field)"
    blob = " ".join(keys).lower()
    assert "the ai could not decide" in blob and "did not give pass or fail" not in blob


def test_the_evidence_trace_of_an_old_line_says_the_true_reason(client):
    """R62b N2: the gate step "decision" of the trace reads the stored line through `read_time` too."""
    run_id, ids, conn = _old_query_lines(client, ["needs_drawing_or_calc"])
    body = client.get(f"/api/reviews/runs/{run_id}/agent/lines/{ids[0]}/trace").json()
    decision = [g for g in body["gate"] if g["step"] == "decision"][0]
    assert "needs a drawing or a calculation to judge" in decision["reason"]
    assert "did not give pass or fail" not in json.dumps(body)


def test_the_complete_crs_of_the_page_built_from_an_old_run_carries_the_true_reason(
    temp_db, monkeypatch
):
    """#1819's ONE CRS (`crs_one.build_team`, drawn from the page's own points): an old run's reader Query is worded truly in the file."""
    import io

    from app import access, crs_one, db
    from app.config import settings
    from tests.test_b1_review_points import world_with_both
    from tests.test_crs_endpoint import temp_db as _temp  # noqa: F401

    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    doc, _rc, ai, _client = world_with_both()
    conn = db.connect()
    row = conn.execute(
        "SELECT line_json FROM agent_review_line WHERE run_id = ? AND item_id = 'R-8'",
        (ai,),
    ).fetchone()
    line = json.loads(row["line_json"])
    line.update(
        ai_verdict="Query",
        verdict="Query",
        decided_by="engineer",
        why=OLD,
        not_proven_reason=OLD,
        reason_code="needs_drawing_or_calc",
        error=None,
    )
    conn.execute(
        "UPDATE agent_review_line SET verdict_class = 'Query for the engineer', word = 'Query', reason = ?, line_json = ? WHERE run_id = ? AND item_id = 'R-8'",
        (OLD, json.dumps(line), ai),
    )
    conn.commit()
    scope = access.AccessScope(
        user_id=None,
        allowed_document_ids=frozenset(
            r[0] for r in conn.execute("SELECT id FROM documents")
        ),
    )
    data = crs_one.build_team(doc, scope)
    cells = json.dumps(
        [
            list(r)
            for sh in openpyxl.load_workbook(io.BytesIO(data))
            for r in sh.iter_rows(values_only=True)
        ],
        default=str,
    )
    assert (
        "did not reach a view" not in cells and "did not give pass or fail" not in cells
    )
    assert "needs a drawing or a calculation to judge" in cells
