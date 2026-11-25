"""#1911 same paper, same comments: the consistency check of two runs, on INVENTED runs. No model, no answer key."""

from __future__ import annotations

import openpyxl

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import aim_consistency as C  # noqa: E402


def pt(
    n,
    rule_std,
    clause,
    field,
    page,
    label,
    comment="the comment",
    topic="topic one",
    item="C001",
):
    return C._point(n, item, field, page, label, comment, rule_std, clause, topic)


def run_a():
    return [
        pt(
            1,
            "STD-X",
            "4.1",
            "Set pressure",
            3,
            "Not met",
            "Set pressure is above the limit stated in the clause.",
        ),
        pt(
            2,
            "STD-X",
            "4.2",
            "Back pressure",
            3,
            "Question",
            "State the back pressure for the invented valve.",
        ),
        pt(
            3,
            "STD-X",
            "4.3",
            "Orifice size",
            4,
            "Met",
            "The orifice size matches the invented table.",
        ),
        pt(
            4,
            "",
            "",
            "Team members",
            5,
            "AI opinion",
            "Add the operations lead to the invented team.",
            topic="Team composition",
        ),
    ]


def test_two_identical_runs_match_every_point_with_no_flip_and_no_leftover():
    res = C.compare(run_a(), run_a())
    c = C.counts(res)
    assert (
        c["matched"],
        c["only_a"],
        c["only_b"],
        c["flips"],
        c["other_label_changes"],
    ) == (4, 0, 0, 0, 0)
    assert c["by_tier"]["rule+field+page"] == 4
    assert C.pct(c["matched"], c["union"]) == 100.0


def test_matching_is_by_rule_field_page_and_the_wording_may_change_freely():
    b = run_a()
    b[
        0
    ].comment = (
        "Entirely different words, same point of the same rule on the same page."
    )
    res = C.compare(run_a(), b)
    assert C.counts(res)["matched"] == 4 and res.pairs[0].tier == "rule+field+page"


def test_the_same_point_on_another_page_is_matched_by_rule_and_field():
    b = run_a()
    b[1].page = 9
    res = C.compare(run_a(), b)
    pair = next(p for p in res.pairs if p.a.n == 2)
    assert pair.tier == "rule+field" and (pair.a.page, pair.b.page) == (3, 9)


def test_wording_is_only_the_last_tie_break_inside_one_rule_and_never_across_rules():
    a = [
        pt(
            1,
            "STD-X",
            "4.1",
            "Set pressure",
            3,
            "Not met",
            "The set pressure is above the stated limit of the clause.",
        )
    ]
    renamed = [
        pt(
            1,
            "STD-X",
            "4.1",
            "Relief set point",
            8,
            "Not met",
            "The set pressure is above the stated limit of the clause.",
        )
    ]
    assert (
        C.compare(a, renamed).pairs[0].tier == "rule+wording"
    )  # same rule, a renamed field, the same words: tie-break
    other_rule = [
        pt(
            1,
            "STD-Y",
            "9.9",
            "Set pressure",
            3,
            "Not met",
            "The set pressure is above the stated limit of the clause.",
        )
    ]
    res = C.compare(a, other_rule)
    assert (
        res.pairs == [] and len(res.only_a) == 1 and len(res.only_b) == 1
    )  # identical words, another rule: never matched
    unlike = [
        pt(
            1,
            "STD-X",
            "4.1",
            "Something else",
            8,
            "Not met",
            "Completely unrelated sentence about painting the pipe supports.",
        )
    ]
    assert (
        C.compare(a, unlike).pairs == []
    )  # same rule but nothing alike: not forced together


def test_a_point_is_matched_once_and_two_points_of_one_key_pair_by_wording():
    a = [
        pt(1, "STD-X", "4.1", "Set pressure", 3, "Not met", "above the limit alpha"),
        pt(2, "STD-X", "4.1", "Set pressure", 3, "Question", "state the value beta"),
    ]
    b = [
        pt(1, "STD-X", "4.1", "Set pressure", 3, "Question", "state the value beta"),
        pt(2, "STD-X", "4.1", "Set pressure", 3, "Not met", "above the limit alpha"),
    ]
    res = C.compare(a, b)
    assert len(res.pairs) == 2 and all(
        not p.flip for p in res.pairs
    )  # the wording pairs the two of one key: no false flip


def test_verdict_flips_are_counted_by_type_and_other_label_changes_apart():
    b = run_a()
    b[0].label, b[0].kind = "Question", C.QUESTION  # Not met -> Question
    b[2].label, b[2].kind = "Not met", C.NOT_MET  # Met -> Not met
    b[3].label, b[3].kind = (
        "Question",
        C.QUESTION,
    )  # AI opinion -> Question: not a verdict flip
    c = C.counts(C.compare(run_a(), b))
    assert (
        c["flips"] == 2
        and c["other_label_changes"] == 1
        and c["flip_types"] == {"Met <-> Not met": 1, "Not met <-> Question": 1}
    )


def test_points_in_only_one_run_are_reported_with_their_side():
    b = [
        *run_a()[:3],
        pt(
            9,
            "STD-Z",
            "1.1",
            "A new field",
            7,
            "Question",
            "A point only the second run made.",
        ),
    ]
    res = C.compare(run_a(), b)
    assert [p.field for p in res.only_a] == ["Team members"] and [
        p.field for p in res.only_b
    ] == ["A new field"]
    c = C.counts(res)
    assert (c["matched"], c["only_a"], c["only_b"], c["union"]) == (3, 1, 1, 5)


def test_every_percent_states_its_denominator_and_nothing_is_a_percent_of_zero():
    assert (
        C.pct_words(3, 4) == "3 of 4 (75%)"
        and C.pct_words(0, 0) == "0 of 0"
        and C.pct(0, 0) is None
    )
    res = C.compare([], [])
    kinds = C.counts(res)["per_kind"]
    assert all(C.pct(k["a_matched"], k["a_total"]) is None for k in kinds.values())
    text = " ".join(
        v for _k, v in C.summary_lines(C.compare(run_a(), run_a()), "A", "B", True)
    )
    assert "4 of 4 (100%)" in text


def test_the_per_kind_table_gives_each_kind_its_own_denominator():
    b = run_a()[:2]  # only the Not met and the Question are repeated
    k = C.counts(C.compare(run_a(), b))["per_kind"]
    assert (k[C.NOT_MET]["a_total"], k[C.NOT_MET]["a_matched"]) == (1, 1) and (
        k[C.MET]["a_total"],
        k[C.MET]["a_matched"],
    ) == (1, 0)
    assert (k[C.OPINION]["a_total"], k[C.OPINION]["a_matched"]) == (1, 0)


def test_the_file_says_whether_it_is_a_consistency_measure():
    same = C.summary_lines(C.compare(run_a(), run_a()), "A", "B", True)[0][1]
    diff = C.summary_lines(C.compare(run_a(), run_a()), "A", "B", False)[0][1]
    assert same == C.SAME_VERSION_LINE and diff.startswith(
        "DIFFERENT VERSIONS, NOT A CONSISTENCY MEASURE"
    )


def test_the_workbook_has_its_sheets_and_reads_back(tmp_path):
    b = run_a()
    b[0].label, b[0].kind = "Question", C.QUESTION
    path = C.write_xlsx(
        C.compare(run_a(), b),
        tmp_path / "out" / "consistency.xlsx",
        "run-a",
        "run-b",
        True,
    )
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == [
        "Summary",
        "By kind",
        "Matched",
        "Flips",
        "Only in A",
        "Only in B",
    ]
    assert wb["Summary"]["A1"].value == "AI, to be checked" and wb["Flips"].max_row == 2
    assert [c.value for c in wb["Matched"][2]][2] == "rule+field+page"


def test_the_team_file_and_the_page_json_both_load(tmp_path):
    sheet = tmp_path / "s.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "Summary"
    ws = wb.create_sheet("All points")
    ws.append(["AI, to be checked"])
    ws.append(["All points: 2"])
    ws.append([])
    ws.append(
        [
            "No.",
            "Item",
            "Field",
            "Page",
            "Shown label",
            "Topic",
            "Comment",
            "Standard",
            "Clause",
        ]
    )
    ws.append(
        [
            1,
            "C001",
            "Set pressure",
            3,
            "Not met",
            "Relief",
            "above the limit",
            "STD-X",
            "4.1",
        ]
    )
    ws.append(
        [
            2,
            "C002",
            "Team",
            5,
            "AI opinion",
            "Team composition",
            "add the lead",
            None,
            None,
        ]
    )
    wb.save(sheet)
    points = C.load(sheet)
    assert [(p.n, p.rule, p.kind, p.page) for p in points] == [
        (1, "STD-X §4.1", C.NOT_MET, 3),
        (2, "topic: team composition", C.OPINION, 5),
    ]
    page = C.load_page_json({"points": [{"n": 1, "item_id": "C001", "field": "Set pressure", "page": 3, "shown_label": "Fail, compared by code",
                                         "comment": "x", "standard": "STD-X", "clause": "4.1", "topic": "Relief"}]})  # fmt: skip
    assert page[0].kind == C.NOT_MET and page[0].rule == "STD-X §4.1"


def test_label_kinds():
    for label, kind in (("Not met", C.NOT_MET), ("Fail, compared by code", C.NOT_MET), ("Met", C.MET), ("Pass, compared by code", C.MET),
                        ("Question", C.QUESTION), ("AI opinion", C.OPINION), ("AI opinion: does not apply", C.OPINION), ("", C.OTHER)):  # fmt: skip
        assert C.kind_of(label) == kind, label
