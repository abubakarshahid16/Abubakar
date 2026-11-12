"""N9: an "AI thinks: met" the code cannot stand behind is a Query. Invented data only; no model, no network."""

from __future__ import annotations

import itertools

import pytest

from app import agent_review_verdict as V
from app import agent_review_wording as W

CHECKLIST = {"item_id": "S-1", "source": "skill", "rule_version_id": None}
RULE_OK = {"item_id": "R-1", "source": "rule", "rule_label": {"tier": "AI approved"}}
OK = {"paper": True, "clause": True, "both": True}


def met(**kw):
    base = {
        "item_id": "S-1",
        "verdict": "Query",
        "decided_by": "engineer",
        "ai_verdict": "Pass",
        "why": "second opinion disagreed",
        "paper_quote": "Body material: carbon steel",
        "quotes_checked": dict(OK),
    }
    return {**base, **kw}


def exit_of(line, item=CHECKLIST):
    return W.final_cap(line, item, None, {"S-1"}, "datasheet")


@pytest.mark.parametrize("item", [CHECKLIST, RULE_OK])
@pytest.mark.parametrize(
    "quote",
    [
        "340 psig (By Contractor, as per Code)",
        "Set pressure: to be confirmed",
        "Capacity TBA",
        "Orifice: vendor to advise",
        "Seat tightness | later",
        "Lift | hold",
        "Tag\t-",
    ],
)
def test_met_with_a_deferring_paper_quote_is_a_query(item, quote):
    out = exit_of(met(item_id=item["item_id"], paper_quote=quote), item)
    assert out["verdict_label"] == W.WORD_QUERY
    assert out["verdict_class"] == W.CLASS_QUERY
    assert out["not_proven_reason"].startswith(V.DEFERRED_WHY)
    assert quote not in out["not_proven_reason"]


@pytest.mark.parametrize(
    ("checks", "why"),
    [
        ({"paper": True, "clause": False}, V.UNVERIFIED_CLAUSE_WHY),
        ({"paper": False, "clause": True}, V.UNVERIFIED_PAPER_WHY),
        (None, V.UNVERIFIED_PAPER_WHY),
    ],
)
def test_met_with_an_unverified_quote_is_a_query(checks, why):
    out = exit_of(met(quotes_checked=checks))
    assert (out["verdict_label"], out["verdict_class"]) == (W.WORD_QUERY, W.CLASS_QUERY)
    assert out["not_proven_reason"].startswith(why)


def test_met_with_verified_plain_quotes_stays_met():
    out = exit_of(met())
    assert out["verdict_label"] == W.THINKS_MET
    assert out["verdict_class"] == W.CLASS_OPINION


def test_a_proven_pass_is_not_touched_even_with_odd_quote_fields():
    out = exit_of(
        met(
            verdict="Pass",
            decided_by="decided by code",
            compare={"decided": True, "verdict": "meets"},
            paper_quote="By Contractor",
            quotes_checked={},
        )
    )
    assert (out["verdict_label"], out["verdict_class"]) == ("Pass", W.CLASS_PROVEN)


def test_not_met_is_not_touched():
    out = exit_of(
        met(
            ai_verdict="Fail",
            paper_quote="By Contractor",
            quotes_checked={"paper": False},
        )
    )
    assert out["verdict_label"] == W.THINKS_NOT_MET


def test_the_guard_never_makes_a_line_more_confident():
    for ai in ("Pass", "Fail", "Query", None):
        for verdict in ("Pass", "Fail", "Query"):
            for quote in ("340 psig By Contractor", "carbon steel body"):
                for checks in (dict(OK), {"paper": False}, None):
                    line = met(
                        ai_verdict=ai,
                        verdict=verdict,
                        paper_quote=quote,
                        quotes_checked=checks,
                    )
                    before = W.classify(
                        {**line, "quotes_checked": dict(OK), "paper_quote": "x" * 30}
                    )
                    after = W.classify(line)
                    rank = {
                        "Query for the engineer": 0,
                        W.THINKS_NOT_MET: 1,
                        W.THINKS_MET: 1,
                        "Fail": 2,
                        "Pass": 2,
                    }
                    assert (
                        rank[after["verdict_label"]] <= rank[before["verdict_label"]]
                        or ai != "Pass"
                    )


def test_the_deferral_word_list_is_the_one_in_blank_markers():
    """The guard has no word list of its own; these phrases are what it reacts to today (a change here is a reviewed change)."""
    deferring = [
        "by contractor",
        "by vendor",
        "by supplier",
        "by manufacturer",
        "by bidder",
        "to be advised",
        "to be confirmed",
        "to be determined",
        "to be specified",
        "to be provided",
        "vendor to advise",
        "contractor to confirm",
        "supplier to provide",
        "tba",
        "tbc",
        "tbd",
        "later",
        "hold",
        "-",
        "*",
    ]
    for word in deferring:
        assert V.quote_defers(f"Value | {word}") or V.quote_defers(f"10 bar {word}"), (
            word
        )
    for plain in ("carbon steel", "N/A", "not required", "Required", "340 psig", ""):
        assert not V.quote_defers(plain), plain


@pytest.mark.parametrize("item", [CHECKLIST, RULE_OK])
def test_met_with_a_disagreeing_second_opinion_is_a_query(item):
    out = exit_of(
        met(item_id=item["item_id"], second_opinion={"agree": False, "model": "m"}),
        item,
    )
    assert (out["verdict_label"], out["verdict_class"]) == (W.WORD_QUERY, W.CLASS_QUERY)
    assert out["not_proven_reason"].startswith(V.DISAGREE_WHY)


def test_met_with_an_agreeing_second_opinion_stays_met():
    out = exit_of(met(second_opinion={"agree": True, "model": "m"}))
    assert out["verdict_label"] == W.THINKS_MET


def test_met_with_no_second_opinion_asked_stays_met_but_other_clauses_apply():
    assert exit_of(met(second_opinion=None))["verdict_label"] == W.THINKS_MET
    out = exit_of(
        met(second_opinion=None, quotes_checked={"paper": True, "clause": False})
    )
    assert out["not_proven_reason"].startswith(V.UNVERIFIED_CLAUSE_WHY)


def test_met_with_a_failed_second_opinion_is_neither_agreement_nor_disagreement():
    failed = {"agree": None, "model": "unknown"}
    assert exit_of(met(second_opinion=failed))["verdict_label"] == W.THINKS_MET
    out = exit_of(met(second_opinion=failed, paper_quote="Value TBA"))
    assert out["not_proven_reason"].startswith(V.DEFERRED_WHY)


def test_a_disagreeing_second_opinion_does_not_move_a_proven_pass_or_not_met():
    d = {"agree": False, "model": "m"}
    assert (
        exit_of(
            met(
                verdict="Pass",
                decided_by="decided by code",
                compare={"decided": True, "verdict": "meets"},
                second_opinion=d,
            )
        )["verdict_label"]
        == "Pass"
    )
    assert (
        exit_of(met(ai_verdict="Fail", second_opinion=d))["verdict_label"]
        == W.THINKS_NOT_MET
    )


def test_line_wraps_and_note_references_are_not_deferrals():
    for text in (
        "Set pressure 10 barg is determined\nby calculation per API 520\nand shown on the drawing",
        "By design the body is cast steel",
        "Set pressure 10 bar\nNote 3",
    ):
        assert not V.quote_defers(text), text
        assert exit_of(met(paper_quote=text))["verdict_label"] == W.THINKS_MET
    assert (
        exit_of(met(paper_quote="Set pressure 340 psig (By Contractor)"))[
            "verdict_label"
        ]
        == W.WORD_QUERY
    )


def test_a_met_with_no_clause_quote_recorded_is_a_query_by_design():
    out = exit_of(
        met(
            clause_quote=None,
            quotes_checked={
                "paper": True,
                "clause": False,
                "clause_why": "no clause quote",
            },
        )
    )
    assert out["verdict_label"] == W.WORD_QUERY and out["not_proven_reason"].startswith(
        V.UNVERIFIED_CLAUSE_WHY
    )


@pytest.mark.parametrize("quote", ["340 psig (By Contractor)", "plain steel value"])
@pytest.mark.parametrize("checks", [None, {"paper": False, "clause": False}, dict(OK)])
def test_a_proven_fail_with_ai_met_is_never_touched(quote, checks):
    out = exit_of(
        met(
            verdict="Fail",
            decided_by="decided by code",
            paper_quote=quote,
            quotes_checked=checks,
            second_opinion={"agree": False},
        )
    )
    assert (out["verdict_label"], out["verdict_class"]) == ("Fail", W.CLASS_PROVEN)


def test_the_only_change_the_guard_can_make_is_met_to_query():
    """Every verdict x ai_verdict x (deferring quote, quote check, second opinion): compare the exit with the same line
    given plain verified quotes and no disagreement. The guard may only turn 'AI thinks: met' into Query."""
    for verdict in ("Pass", "Fail", "Query"):
        for ai in ("Pass", "Fail", "Query", None):
            for quote in ("Value TBA", "carbon steel"):
                for checks in (
                    None,
                    {"paper": False, "clause": True},
                    {"paper": True, "clause": False},
                    dict(OK),
                ):
                    for second, nm in itertools.product(
                        (None, {"agree": False}, {"agree": None}, {"agree": True}),
                        (False, True),
                    ):
                        line = met(
                            not_mentioned_hold=nm,
                            verdict=verdict,
                            ai_verdict=ai,
                            paper_quote=quote,
                            quotes_checked=checks,
                            second_opinion=second,
                        )
                        base = {
                            **line,
                            "paper_quote": "carbon steel",
                            "quotes_checked": dict(OK),
                            "second_opinion": None,
                            "not_mentioned_hold": False,
                        }
                        got, ref = W.classify(line), W.classify(base)
                        if got["verdict_label"] != ref["verdict_label"]:
                            assert (ref["verdict_label"], got["verdict_label"]) == (
                                W.THINKS_MET,
                                W.WORD_QUERY,
                            ), (verdict, ai, quote, checks, second)


def test_a_guarded_line_is_on_the_query_side_of_the_workbook_with_its_new_reason(
    tmp_path,
):
    import openpyxl

    from app import agent_review_crs as C

    ok = {"source": "rule", "rule_label": {"tier": "AI approved"}}

    def mk(iid, **kw):
        base = {
            "item_id": iid,
            "source": "rule",
            "standard": "STD-1",
            "clause": "4.1",
            "verdict": "Query",
            "decided_by": "engineer",
            "ai_verdict": "Pass",
            "why": "no second opinion",
            "paper_page": 2,
            "paper_quote": "Nameplate: steel",
            "clause_quote": "Nameplates shall be steel and fixed",
            "quotes_checked": dict(OK),
            "model": "m",
            "field_roles": ["nameplate_material"],
        }
        return W.final_cap({**base, **kw}, ok)

    held, moved = mk("R-4"), mk("R-9", paper_quote="Value TBA")
    assert (
        held["verdict_label"] == W.THINKS_MET and moved["verdict_label"] == W.WORD_QUERY
    )
    meta = {
        "paper": "P",
        "run_id": "r",
        "date": "2026-11-12",
        "lead_models": [],
        "second_models": [],
    }
    path = C.write_internal([held, moved], tmp_path / "i.xlsx", meta)
    wb = openpyxl.load_workbook(path)
    evidence = list(wb["Evidence"].iter_rows(min_row=2, values_only=True))
    status_of = {r[13]: r[1] for r in evidence}  # internal item id -> Status
    assert status_of == {
        "R-4": "AI opinion",
        "R-9": "Query",
    }  # the moved line is on the Query side
    text = "\n".join(
        str(c) for r in wb["CRS"].iter_rows(values_only=True) for c in r if c
    )
    assert (
        "the paper leaves the value open" in text
    )  # the guard's reason, in plain words
    assert V.DEFERRED_WHY not in text  # never the stored words
    counts = C.run_counts([held, moved])
    assert counts["held_ai_pass"] == 1 and counts["query"] == 2


@pytest.mark.parametrize(
    "marker",
    [
        "*",
        "-",
        "?",
        "_____",
        "to follow",
        "TBN",
        "VTA",
        "as per vendor",
        "later",
        "hold",
    ],
)
def test_a_lone_marker_on_its_own_line_or_cell_defers_the_value(marker):
    for quote in (
        f"Seat tightness\n{marker}",
        f"Seat tightness | {marker}",
        f"Seat tightness\t{marker}",
    ):
        assert V.quote_defers(quote), quote
        assert exit_of(met(paper_quote=quote))["not_proven_reason"].startswith(
            V.DEFERRED_WHY
        )


def test_a_marker_inside_a_longer_line_is_not_a_lone_marker():
    for text in (
        "10 - 20 bar",
        "hold-down bolts",
        "later revision applies",
        "Set pressure 10 bar\nNote 3",
    ):
        assert not V.quote_defers(text), text


def test_every_line_is_on_one_sheet_and_every_count_matches_its_sheet(tmp_path):
    import openpyxl

    from app import agent_review_crs as C
    from app import crs_ai_workbook as WB

    ok = {"source": "rule", "rule_label": {"tier": "AI approved"}}
    no = {
        "source": "rule",
        "rule_tier": V.RULE_NOT_APPROVED,
        "rule_unapproved_why": "values",
    }

    def mk(iid, item=ok, **kw):
        base = {
            "item_id": iid,
            "source": "rule",
            "standard": "STD-1",
            "clause": "4.1",
            "verdict": "Query",
            "decided_by": "engineer",
            "ai_verdict": "Pass",
            "why": "no second opinion",
            "paper_page": 2,
            "paper_quote": "Nameplate: steel",
            "clause_quote": "Nameplates shall be steel and fixed",
            "quotes_checked": dict(OK),
            "model": "m",
            "field_roles": ["nameplate_material"],
        }
        return W.final_cap({**base, **kw}, item)

    lines = [
        mk(
            "L-pass",
            verdict="Pass",
            decided_by="decided by code",
            compare={"decided": True, "verdict": "meets"},
        ),
        mk("L-fail", verdict="Fail", decided_by="decided by code", ai_verdict="Fail"),
        mk("L-met"),
        mk("L-notmet", ai_verdict="Fail"),
        mk("L-defer", paper_quote="Value TBA"),
        mk("L-unver", quotes_checked={"paper": True, "clause": False}),
        mk("L-disagree", second_opinion={"agree": False}),
        mk("L-na", ai_verdict="Query", reason_code="not_applicable"),
        mk("L-na-moved", reason_code="not_applicable", paper_quote="Value TBA"),
        mk("L-error", error="timeout", ai_verdict=None),
        mk("L-unapproved", item=no),
    ]
    meta = {
        "paper": "P",
        "run_id": "r",
        "date": "2026-11-12",
        "lead_models": [],
        "second_models": [],
    }
    path = C.write_internal(lines, tmp_path / "i.xlsx", meta)
    wb = openpyxl.load_workbook(path)
    ids = {ln["item_id"] for ln in lines}
    place = {}  # item id -> the sheet it is a row of (Evidence has one row per item, same Item No)
    on_main = {
        r[0]
        for r in wb["CRS"].iter_rows(min_row=1, values_only=True)
        if isinstance(r[0], int)
    }
    on_other = {
        r[0]
        for r in wb["Not reviewed or not applicable"].iter_rows(
            min_row=2, values_only=True
        )
    }
    evidence = list(wb["Evidence"].iter_rows(min_row=2, values_only=True))
    assert sorted(r[13] for r in evidence) == sorted(ids)  # every line once
    for r in evidence:
        place[r[13]] = (
            "CRS" if r[0] in on_main else "other" if r[0] in on_other else None
        )
    assert None not in place.values() and not on_main & on_other
    by_line = {ln["item_id"]: ln for ln in lines}
    assert {i: p == "CRS" for i, p in place.items()} == {
        i: WB.status_of(by_line[i]) is not None for i in ids
    }  # the one decision (`sheet_of`, read by `status_of`) is where each line stands
    seen = {i: [C.sheet_of(by_line[i])] for i in ids}
    rows = C.sheet_rows(lines)
    for title, n in rows.items():
        assert n == sum(1 for v in seen.values() if v[0] == title), title
    assert sum(rows.values()) == len(lines)
    counts = C.run_counts(lines)
    assert counts["sheet_rows"] == rows
    assert counts["held_ai_pass"] == rows[C.HELD_PASS_SHEET] == 1  # only L-met
    assert (
        counts["query_not_applicable"]
        == rows[C.NOT_APPLICABLE_SHEET]
        == counts["not_applicable"]
        == 1
    )
    by_class = W.counts(lines)
    classes = (
        "proven_pass proven_fail ai_thinks_met ai_thinks_not_met unapproved_ai_thinks_met "
        "unapproved_ai_thinks_not_met query_for_the_engineer not_applicable not_reviewed"
    ).split()
    assert sum(by_class[k] for k in classes) == len(lines)
    notes = {r[0]: r[1] for r in wb["Notes"].iter_rows(min_row=2, values_only=True)}
    assert int(notes["Count: rows on the CRS sheet"]) == len(on_main)
    assert int(
        notes["Count: rows on the sheet 'Not reviewed or not applicable'"]
    ) == len(on_other)
    assert len(on_main) + len(on_other) == len(lines)


def test_a_moved_line_leads_with_the_guard_reason_and_marks_the_first_readers_view(
    tmp_path,
):
    import openpyxl

    from app import agent_review_crs as C
    from app import crs_ai_workbook as WB

    view = "The sheet states the requirement is met."
    ok = {"source": "rule", "rule_label": {"tier": "AI approved"}}
    base = {
        "item_id": "R-1",
        "source": "rule",
        "standard": "STD-1",
        "clause": "4.1",
        "verdict": "Query",
        "decided_by": "engineer",
        "ai_verdict": "Pass",
        "why": "second opinion disagreed",
        "paper_page": 2,
        "paper_quote": "Nameplate: steel",
        "clause_quote": "Nameplates shall be steel and fixed",
        "quotes_checked": dict(OK),
        "model": "m",
        "field_roles": ["nameplate_material"],
        "reasoning": view,
    }
    moved = W.final_cap({**base, "second_opinion": {"agree": False}}, ok)
    unmoved = W.final_cap({**base, "item_id": "R-2"}, ok)
    text = moved["not_proven_reason"]
    assert text.startswith(V.DISAGREE_WHY)
    assert (
        text.index(W.SECOND_DISAGREED.strip())
        < text.index(W.ONE_READER)
        < text.index(view)
    )
    assert (
        unmoved["verdict_label"] == W.THINKS_MET
        and unmoved["not_proven_reason"] == "second opinion disagreed"
    )
    assert W.ONE_READER not in unmoved["not_proven_reason"]
    # the workbook comment and verdict cells, and the stored `reason`, all lead with the same text
    comment = C.company_comment(moved)
    assert comment.split(": ", 1)[1] == text
    _one, two, three = WB.layout_comment(moved, *WB.status_of(moved)).split("\n")
    assert (
        "Not confirmed: the two AI readers disagreed." in two
    )  # the guard's reason leads, in plain words
    assert (
        two.index("Not confirmed") < two.index(W.ONE_READER) < two.index(view)
    )  # then the view, marked
    assert "met" not in three  # the first reader's conclusion is not the action
    meta = {
        "paper": "P",
        "run_id": "r",
        "date": "2026-11-12",
        "lead_models": [],
        "second_models": [],
    }
    wb = openpyxl.load_workbook(C.write_internal([moved], tmp_path / "i.xlsx", meta))
    cells = [str(c) for r in wb["CRS"].iter_rows(values_only=True) for c in r if c]
    assert any(W.ONE_READER + view in c for c in cells)
    # a moved line with no first-reader text says only the guard reason
    bare = W.final_cap(
        {**base, "reasoning": None, "second_opinion": {"agree": False}}, ok
    )
    assert W.ONE_READER not in bare["not_proven_reason"]


def test_the_contractor_visible_copy_carries_none_of_the_guard_words(tmp_path):
    import openpyxl

    from app import agent_review_crs as C

    ok = {"source": "rule", "rule_label": {"tier": "AI approved"}}
    base = {
        "item_id": "R-1",
        "source": "rule",
        "standard": "STD-1",
        "clause": "4.1",
        "verdict": "Query",
        "decided_by": "engineer",
        "ai_verdict": "Pass",
        "why": "second opinion disagreed",
        "paper_page": 2,
        "paper_quote": "Nameplate: steel",
        "clause_quote": "Nameplates shall be steel and fixed",
        "quotes_checked": dict(OK),
        "model": "m",
        "field_roles": ["nameplate_material"],
        "reasoning": "The sheet states the requirement is met.",
        "second_opinion": {"agree": False},
    }
    moved = W.final_cap(base, ok)
    assert moved["not_proven_reason"].startswith(V.DISAGREE_WHY)
    meta = {
        "paper": "P",
        "run_id": "r",
        "date": "2026-11-12",
        "lead_models": [],
        "second_models": [],
    }
    internal = openpyxl.load_workbook(
        C.write_internal([moved], tmp_path / "i.xlsx", meta)
    )
    internal_text = " ".join(
        str(c)
        for ws in internal
        for r in ws.iter_rows(values_only=True)
        for c in r
        if c
    )
    assert W.ONE_READER in internal_text
    for name, path in (
        ("comment-only", C.write_comment_only([moved], tmp_path / "o.xlsx", meta)),
        ("contractor", C.write_contractor([moved], tmp_path / "c.xlsx", meta)),
    ):
        for ws in openpyxl.load_workbook(path):
            for row in ws.iter_rows(values_only=True):
                for cell in row:
                    for word in ("AI reader", "not confirmed", "AI thinks", "disagree"):
                        assert word not in str(cell or ""), (name, word)
    assert "AI reader" not in C.company_comment(moved, contractor=True)


@pytest.mark.parametrize("item", [CHECKLIST, RULE_OK])
def test_met_on_a_label_with_no_value_is_a_query(item):
    for quote in ("Lifting lever", "Lifting lever:", "LIFTING LEVER"):
        out = exit_of(
            met(
                item_id=item["item_id"],
                paper_quote=quote,
                field_label_ai="Lifting lever",
            ),
            item,
        )
        assert (out["verdict_label"], out["verdict_class"]) == (
            W.WORD_QUERY,
            W.CLASS_QUERY,
        )
        assert out["not_proven_reason"].startswith(V.NO_VALUE_WHY)
    roles = exit_of(met(paper_quote="Test gag", field_roles=["test_gag"]))
    assert roles["not_proven_reason"].startswith(V.NO_VALUE_WHY)


def test_met_with_a_value_beside_the_label_stays_met():
    for quote in (
        "Lifting lever Required",
        "Lifting lever: Yes",
        "Lifting lever 2",
        "Lifting lever, packed type",
    ):
        out = exit_of(met(paper_quote=quote, field_label_ai="Lifting lever"))
        assert out["verdict_label"] == W.THINKS_MET, quote
    assert (
        exit_of(met(paper_quote="Lifting lever"))["verdict_label"] == W.THINKS_MET
    )  # no label known: unchanged


def test_met_with_the_gates_not_mentioned_code_is_a_query():
    for item in (CHECKLIST, RULE_OK):
        out = exit_of(
            met(
                item_id=item["item_id"],
                not_mentioned_hold=True,
                reasoning="Sheet 3 is blank.",
            ),
            item,
        )
        assert (out["verdict_label"], out["verdict_class"]) == (
            W.WORD_QUERY,
            W.CLASS_QUERY,
        )
        assert out["not_proven_reason"].startswith(V.NOT_STATED_WHY)
        assert W.ONE_READER in out["not_proven_reason"]
    assert exit_of(met(not_mentioned_hold=False))["verdict_label"] == W.THINKS_MET
    assert exit_of(met())["verdict_label"] == W.THINKS_MET


def test_the_code_is_matched_not_the_sentence():
    # the English sentence alone, without the code, is not a trigger
    assert (
        exit_of(met(why="not mentioned is never a pass"))["verdict_label"]
        == W.THINKS_MET
    )


def test_the_gate_sets_the_code_and_never_returns_a_pass_when_not_mentioned():
    checks = V.QuoteCheck(True, True, None, None, True)
    for ai in ("Pass", "Fail"):
        out = V.textual_verdict(
            ai, checks, {"agree": True, "model": "other"}, "lead", absent=True
        )
        assert (out["verdict"] == V.QUERY) == (ai == "Pass")
    out = V.textual_verdict(
        "Pass", checks, {"agree": True, "model": "other"}, "lead", absent=True
    )
    assert out["verdict"] != V.PASS and out["not_mentioned"] is True
    ok = V.textual_verdict(
        "Pass", checks, {"agree": True, "model": "other"}, "lead", absent=False
    )
    assert "not_mentioned" not in ok


GUARD_REASONS = {
    "DEFERRED_WHY": "the quoted paper text defers or leaves open this value",
    "UNVERIFIED_PAPER_WHY": "the quoted paper text could not be verified by code",
    "UNVERIFIED_CLAUSE_WHY": "the quoted clause text could not be verified by code",
    "NOT_STATED_WHY": "the reviewer's code found words, in the AI reader's answer or in the text it quoted, that say this is not stated; its view is not confirmed",
    "NO_VALUE_WHY": "the AI reader quoted only the field's name, with no value; check the paper",
    "DISAGREE_WHY": "two AI readers disagree on this line",
}


BANNED = (
    "the paper gives",
    "the paper does not",
    "the paper says",
    "the paper is",
    "the paper has",
)
#: The owner's own wording for a silent paper (a rule of 16.3, not a guard reason); every other `*_WHY` is checked.
EXEMPT = {"SILENCE_WHY"}


def test_the_guard_reasons_are_exactly_these():
    for name, text in GUARD_REASONS.items():
        assert getattr(V, name) == text, name


def test_no_reason_constant_of_the_module_asserts_a_fact_about_the_paper():
    """Every `*_WHY` string of the verdict module is collected by its name, so a new reason cannot escape the check."""
    found = {
        n: getattr(V, n)
        for n in dir(V)
        if n.endswith("_WHY") and isinstance(getattr(V, n), str)
    }
    assert set(GUARD_REASONS) <= set(found)
    for name, text in found.items():
        if name not in EXEMPT:
            assert not any(b in text.lower() for b in BANNED), (name, text)
    for text in (W.SECOND_DISAGREED, W.ONE_READER):
        assert not any(b in text.lower() for b in BANNED), text


def test_not_stated_is_true_for_both_sources_the_code_reads():
    from_answer = {"reasoning": "the coating layers are not mentioned on the sheet"}
    from_quote = {"paper_quote": "Coating layers: not specified"}
    for line in (from_answer, from_quote):
        assert V.says_absent(line)
    assert not V.says_absent(
        {"reasoning": "two layers are stated", "paper_quote": "Coating layers two"}
    )
    assert "answer" in V.NOT_STATED_WHY and "text it quoted" in V.NOT_STATED_WHY


def test_a_deferral_is_stated_only_for_a_quote_code_verified():
    unverified = exit_of(
        met(paper_quote="Value TBA", quotes_checked={"paper": False, "clause": True})
    )
    assert unverified["not_proven_reason"].startswith(V.UNVERIFIED_PAPER_WHY)
    verified = exit_of(met(paper_quote="Value TBA"))
    assert verified["not_proven_reason"].startswith(V.DEFERRED_WHY)


def test_every_clause_returns_its_own_constant():
    cases = [
        (met(quotes_checked={"paper": False, "clause": True}), V.UNVERIFIED_PAPER_WHY),
        (met(paper_quote="Value TBA"), V.DEFERRED_WHY),
        (met(quotes_checked={"paper": True, "clause": False}), V.UNVERIFIED_CLAUSE_WHY),
        (met(not_mentioned_hold=True), V.NOT_STATED_WHY),
        (
            met(paper_quote="Lifting lever", field_label_ai="Lifting lever"),
            V.NO_VALUE_WHY,
        ),
        (met(second_opinion={"agree": False}), V.DISAGREE_WHY),
    ]
    for line, why in cases:
        assert V.met_unsafe_why(line) == why
