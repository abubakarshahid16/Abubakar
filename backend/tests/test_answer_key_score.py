"""The answer-key scorer that matches on FIELD ROLE and PAPER PAGE (owner answer 5, 11 Nov 2026).

Invented keys and invented CRS workbooks only: no client key row, no paper text. Every rule the old word
scorer bent is held here: a word in a reasoning cell is not the problem, a wrong field on the right page is
not found, a right field on the wrong page is not found, the word match is reported but never counted, and
a key the scorer cannot read honestly is refused with its row number.
"""

from __future__ import annotations

import json

import openpyxl
import pytest
from tools import answer_key_score as aks

KEY_HEAD = [
    "Row",
    "Item No",
    "Page No./Section",
    "COMPANY Comments",
    "Standard Reference",
    "Field role",
    "Paper page",
    "Scored as",
    "Printed label",
]
CRS_HEAD = [
    "Item No",
    "Document Name",
    "Page No./Section",
    "COMPANY Comments",
    "Comment By",
    "Contractor's Response",
    "Final Resolution",
    "Standard Reference",
    "Priority",
    "Verdict",
    "AI reasoning",
]


def _key(tmp_path, rows, name="key.xlsx"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CRS rows"
    ws.append(KEY_HEAD)
    for i, r in enumerate(rows, start=1):
        ws.append(
            [
                i,
                f"K-{i}",
                r.get("section", ""),
                r.get("comment", ""),
                r.get("std", ""),
                r.get("role", ""),
                r.get("page", ""),
                r["kind"],
                r.get("label", ""),
            ]
        )
    path = tmp_path / name
    wb.save(path)
    return path


def _crs(tmp_path, lines, passes=(), name="crs.xlsx"):
    """lines / passes: (page section, comment, standard reference, verdict, reasoning)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CRS"
    ws.append(["AI review, engineer to confirm"])
    ws.append(["COMMENT RESOLUTION SHEET"])
    ws.append([])
    ws.append(CRS_HEAD)
    for i, (page, comment, std, verdict, why) in enumerate(lines, start=1):
        ws.append(
            [
                f"R-{i:03d}",
                "doc_x",
                page,
                comment,
                "AI Review",
                None,
                "Draft",
                std,
                None,
                verdict,
                why,
            ]
        )
    if passes:
        tick = wb.create_sheet("Passed - engineer to tick")
        tick.append(["run banner"])
        tick.append(CRS_HEAD)
        for i, (page, comment, std, verdict, why) in enumerate(passes, start=1):
            tick.append(
                [
                    f"P-{i:03d}",
                    "doc_x",
                    page,
                    comment,
                    "AI verdict",
                    None,
                    "Draft",
                    std,
                    None,
                    verdict,
                    why,
                ]
            )
    other = wb.create_sheet("AI met, not proven by code")
    other.append(CRS_HEAD)
    other.append(
        [
            "H-001",
            "doc_x",
            "p.2",
            "Set pressure (page 2): held",
            "AI",
            None,
            None,
            "XS-100 4.2",
            None,
            "Query",
            "",
        ]
    )
    path = tmp_path / name
    wb.save(path)
    return path


def _score(tmp_path, key_rows, lines, passes=()):
    return aks.score_files(_key(tmp_path, key_rows), _crs(tmp_path, lines, passes))


def test_field_and_page_both_decide_and_words_alone_never_count(tmp_path):
    key = [
        {
            "kind": "problem",
            "role": "set_pressure",
            "page": "2",
            "section": "p.2 - Set pressure",
            "comment": "Set pressure is left open",
        }
    ]
    # right field, wrong page / wrong field, right page and the key's words in the reasoning cell
    miss = [
        (
            "p.3 - Set pressure (TAG-1)",
            "Set pressure not stated",
            "XS-100 4.2",
            "Query",
            "",
        ),
        (
            "p.2 - Design pressure (TAG-1)",
            "see set pressure",
            "XS-100 4.2",
            "Query",
            "the set pressure on page 2 is open",
        ),
    ]
    res = _score(tmp_path, key, miss)
    assert res["problems_found"] == []
    assert res["word_only"]["problem"] == [
        2
    ]  # the old word test would have counted it: reported only
    hit = [
        *miss,
        (
            "p.2 - Set pressure (TAG-1)",
            "Set pressure not stated",
            "XS-200 7",
            "Query",
            "",
        ),
    ]
    res = _score(tmp_path, key, hit)
    assert res["problems_found"] == [2]
    assert res["word_only"]["problem"] == []
    assert res["matched_lines"][2] == ["CRS!7"]


def test_line_pages_include_the_key_page_and_absent_rows_need_the_field_only(tmp_path):
    key = [
        {"kind": "problem", "role": "set_pressure", "page": "3"},
        {"kind": "problem", "role": "cdtp", "page": "absent"},
        {
            "kind": "problem",
            "role": "cdtp",
            "page": "",
        },  # empty: not scorable, never field-only
    ]
    lines = [
        ("p.1-4 - Set pressure (TAG-1 A/B (for X))", "c", "XS-100 4.2", "Query", ""),
        (
            "page not found (not read) - Not read from the datasheet (5 pages) - Cdtp (TAG-1)",
            "c",
            "XS-100 4.3",
            "Query",
            "",
        ),
    ]
    res = _score(tmp_path, key, lines)
    assert res["problems_found"] == [2, 3]
    assert res["key_rows_without_page"]["problem"] == [4]


def test_agent_comment_lead_gives_label_and_page(tmp_path):
    assert aks.line_label("p.1", "Body (page 1): not shown") == "Body"
    assert aks.line_pages("p.1", "Body (page 1): x") == frozenset({1})
    assert aks.line_label("", "Valve type on page 4: meets the clause") == "Valve type"
    assert aks.line_pages("", "Valve type on page 4: meets") == frozenset({4})
    assert (
        aks.line_label("Overpressure: A value was read on pages 1, 2, 4, not tied", "")
        == "Overpressure"
    )
    assert aks.line_pages(
        "Overpressure: A value was read on pages 1, 2, 4, not tied", ""
    ) == frozenset({1, 2, 4})
    assert (
        aks.line_pages(
            "page not found (not read) - Not read from the datasheet (5 pages) - X", ""
        )
        == frozenset()
    )
    assert aks.parse_pages("1-2, 4") == frozenset({1, 2, 4})


def test_one_shared_word_or_a_shorter_name_inside_a_longer_one_is_not_that_field():
    _, patterns = aks._registry()
    assert "valve_type" not in aks.roles_named(
        "Valve size, rating, conn. type", patterns
    )
    assert "inlet_size" in aks.roles_named("Valve size, rating, conn. type", patterns)
    named = aks.roles_named("Viscosity at relieving temper.", patterns)
    assert "viscosity_relieving" in named and "relieving_temperature" not in named
    # the key's printed label adds a role the registry does not name
    assert "built_up_back_pressure" not in aks.roles_named(
        "Back press. Constant/Variable", patterns
    )
    assert "built_up_back_pressure" in aks.roles_named(
        "Back press. Constant/Variable",
        patterns,
        {"built_up_back_pressure": ("back press variable",)},
    )


def test_wrong_rows_need_the_same_clause_and_other_clauses_are_not_judged(tmp_path):
    key = [
        {"kind": "wrong", "role": "fluid", "page": "1", "std": "XS-100 5.5 (p.9)"},
        {
            "kind": "disputed",
            "role": "design_pressure",
            "page": "1",
            "std": "XS-100 clause 8.1",
        },
    ]
    other = [
        ("p.1 - Fluid", "c", "XS-100 5.8", "Query", ""),
        ("p.1 - Design pressure", "c", "XS-100-2023 clause 8.2", "Query", ""),
    ]
    res = _score(tmp_path, key, other)
    assert res["clear_wrong"] == [] and res["disputed_raised"] == []
    assert res["other_clause_not_judged"] == {"wrong": [2], "disputed": [3]}
    same = [
        *other,
        ("p.1 - Fluid", "c", "XS-100 clause 5.5", "Query", ""),
        ("p.1 - Design pressure", "c", "XS-100-2023 clause 8.1", "Query", ""),
    ]
    res = _score(tmp_path, key, same)
    assert res["clear_wrong"] == [2] and res["disputed_raised"] == [3]
    assert res["other_clause_not_judged"] == {"wrong": [], "disputed": []}


def test_a_wrong_row_naming_a_standard_without_a_clause_needs_that_standard(tmp_path):
    assert aks.clause_ref("XS 610 datasheet annex") == ("XS610", None)
    assert aks.clause_ref("XS-100-2023 clause 8.1") == ("XS100", "8.1")
    assert aks.clause_ref("XS-100.pdf 6.1.1") == ("XS100", "6.1.1")
    assert aks.clause_ref("XS-100 (edition not recorded) cl. 5.2") == ("XS100", "5.2")
    key = [
        {
            "kind": "wrong",
            "role": "rated_head",
            "page": "2",
            "std": "XS 610 datasheet annex",
        }
    ]
    res = _score(tmp_path, key, [("p.2 - Rated head", "c", "YS-5 6.7.4", "Query", "")])
    assert res["clear_wrong"] == [] and res["other_clause_not_judged"]["wrong"] == [2]
    res = _score(
        tmp_path,
        key,
        [("p.2 - Rated head", "c", "XS 610 datasheet annex", "Query", "")],
    )
    assert res["clear_wrong"] == [2]


def test_passes_confirm_complies_rows_and_a_pass_on_a_problem_is_a_wrong_pass(tmp_path):
    key = [
        {"kind": "complies", "role": "body_material", "page": "1"},
        {"kind": "complies", "role": "body_material", "page": "2"},
        {"kind": "problem", "role": "spring_material", "page": "1"},
        {"kind": "not scored", "role": "body_material", "page": "1"},
    ]
    passes = [
        ("p.1", "Body (page 1): meets the clause", "XS-100 6.1", "Pass", ""),
        ("p.1", "Spring (page 1): meets", "XS-100 6.2", "Pass", ""),
    ]
    # a tick-marked line on the CRS sheet is a pass line, never a comment
    lines = [("p.2 - Body", "ENGINEER TO TICK: meets", "XS-100 6.1", "", "")]
    res = _score(tmp_path, key, lines, passes)
    assert res["complies_confirmed"] == [2, 3]
    assert res["complies_raised_as_comment"] == []
    assert res["wrong_passes"] == [4]
    assert res["of"] == {
        "problem": 1,
        "complies": 2,
        "wrong": 0,
        "disputed": 0,
        "not scored": 1,
    }
    assert res["comment_lines"] == 0 and res["pass_lines"] == 3


def test_a_problem_on_the_crs_is_not_a_wrong_pass(tmp_path):
    key = [{"kind": "problem", "role": "spring_material", "page": "1"}]
    res = _score(
        tmp_path,
        key,
        [("p.1 - Spring material", "c", "XS-100 6.2", "Query", "")],
        [("p.1", "Spring (page 1): meets", "XS-100 6.2", "Pass", "")],
    )
    assert res["problems_found"] == [2] and res["wrong_passes"] == []


def test_a_key_row_with_no_field_is_counted_and_never_matched(tmp_path):
    key = [
        {
            "kind": "wrong",
            "role": "",
            "page": "",
            "section": "",
            "comment": "generic row",
        }
    ]
    res = _score(tmp_path, key, [("p.1 - Fluid", "generic row", "XS-1 1", "Query", "")])
    assert res["clear_wrong"] == []
    assert res["key_rows_without_field"]["wrong"] == [2]


@pytest.mark.parametrize(
    "row, message",
    [
        ({"kind": "maybe", "role": "fluid"}, "Scored as"),
        ({"kind": "problem", "role": "not_a_role"}, "not a role of the field registry"),
        ({"kind": "problem", "role": "fluid", "page": "first"}, "Paper page"),
    ],
)
def test_a_key_the_scorer_cannot_read_is_refused_with_its_row(tmp_path, row, message):
    with pytest.raises(aks.AnswerKeyError, match=rf"row 2: .*{message}"):
        aks.read_key(_key(tmp_path, [row]))


def test_procedure_elements_of_the_playbooks_are_registry_roles(tmp_path):
    key = aks.read_key(
        _key(tmp_path, [{"kind": "problem", "role": "sil_procedure:S08"}])
    )
    assert key[0].roles == frozenset({"sil_procedure:S08"})
    with pytest.raises(aks.AnswerKeyError):
        aks.read_key(
            _key(
                tmp_path,
                [{"kind": "problem", "role": "sil_procedure:S99"}],
                name="k2.xlsx",
            )
        )


def test_the_cli_prints_counts_and_rows_never_text(tmp_path, capsys):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "aks_cli",
        Path(__file__).resolve().parents[2] / "scripts" / "answer_key_score.py",
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    key = _key(
        tmp_path,
        [
            {
                "kind": "problem",
                "role": "set_pressure",
                "page": "2",
                "comment": "INVENTED-KEY-WORDS",
            }
        ],
    )
    crs = _crs(
        tmp_path,
        [
            (
                "p.2 - Set pressure",
                "INVENTED-CRS-WORDS",
                "XS-1 2",
                "Query",
                "INVENTED-WHY",
            )
        ],
    )
    assert cli.main(["--key", str(key), "--crs", str(crs), "--json", "--rows"]) == 0
    out = capsys.readouterr().out
    assert "INVENTED" not in out
    got = json.loads(out)
    assert got["problems_found"] == "1 of 1" and got["rows"]["problems_found"] == [2]
    bad = _key(tmp_path, [{"kind": "maybe"}], name="bad.xlsx")
    assert cli.main(["--key", str(bad), "--crs", str(crs)]) == 2


def test_one_line_never_counts_for_a_second_row_on_field_and_page_alone(tmp_path):
    key = [
        {"kind": "problem", "role": "set_pressure", "page": "2", "std": "XS-100 4.1"},
        {"kind": "problem", "role": "set_pressure", "page": "2", "std": "XS-100 4.2"},
        {"kind": "problem", "role": "set_pressure", "page": "2", "std": "XS-100 4.3"},
    ]
    # a line under an unrelated clause counts for ONE row only
    res = _score(tmp_path, key, [("p.2 - Set pressure", "c", "YS-9 1.1", "Query", "")])
    assert res["problems_found"] == [2]
    # a line citing one row's own clause counts for that row, not for the others
    res = _score(
        tmp_path, key, [("p.2 - Set pressure", "c", "XS-100 clause 4.2", "Query", "")]
    )
    assert res["problems_found"] == [3]
    # two lines with two rows' own clauses find those two rows
    res = _score(
        tmp_path,
        key,
        [
            ("p.2 - Set pressure", "c", "XS-100 4.1", "Query", ""),
            ("p.2 - Set pressure", "c", "XS-100 4.3", "Query", ""),
        ],
    )
    assert res["problems_found"] == [2, 4]


def test_a_printed_label_is_a_row_point_too(tmp_path):
    key = [
        {"kind": "problem", "role": "built_up_back_pressure", "page": "3"},
        {
            "kind": "problem",
            "role": "built_up_back_pressure",
            "page": "3",
            "label": "back press variable",
        },
    ]
    res = _score(
        tmp_path,
        key,
        [("p.3 - Back press. Constant/Variable", "c", "YS-9 1", "Query", "")],
    )
    assert res["problems_found"] == [3]


def test_a_complies_row_raised_as_a_comment_is_not_confirmed(tmp_path):
    key = [{"kind": "complies", "role": "body_material", "page": "1"}]
    res = _score(tmp_path, key, [("p.1 - Body", "c", "XS-100 6.1", "Query", "")])
    assert res["complies_confirmed"] == []
    assert res["complies_raised_as_comment"] == [2]


def test_a_one_word_printed_label_needs_the_whole_word():
    _, patterns = aks._registry()
    spell = {"bearing_type": ("bear",)}
    assert "bearing_type" not in aks.roles_named("Bearing temperature", patterns, spell)
    assert "bearing_type" in aks.roles_named("Bear", patterns, spell)
    spell = {"seal_plan": ("plant",)}
    assert "seal_plan" not in aks.roles_named("Plan view", patterns, spell)


def test_an_unknown_verdict_is_not_counted_and_is_reported(tmp_path):
    key = [
        {"kind": "problem", "role": "set_pressure", "page": "2"},
        {"kind": "complies", "role": "body_material", "page": "1"},
    ]
    lines = [
        ("p.2 - Set pressure", "c", "XS-1 1", "Maybe later", ""),
        ("p.2 - Set pressure", "c", "XS-1 1", "Passed?", ""),
        ("p.1", "Body (page 1): x", "XS-1 1", "Pass, AI verdict (model-x)", ""),
    ]
    res = _score(
        tmp_path, key, lines, [("p.1", "Body (page 1): x", "XS-1 1", "Fail", "")]
    )
    assert res["problems_found"] == [] and res["lines_unknown_verdict"] == 3
    assert res["complies_confirmed"] == [3]  # "Pass, AI verdict (...)" is a pass
    res = _score(
        tmp_path,
        key,
        [("p.2 - Set pressure", "c", "XS-1 1", "Query for the engineer", "")],
    )
    assert res["problems_found"] == [2] and res["lines_unknown_verdict"] == 0


@pytest.mark.parametrize(
    "text, ref",
    [
        ("API 610", ("API610", None)),
        ("API 2000", ("API2000", None)),
        ("API 526 2017", ("API526", None)),
        ("API 610 6.1.2", ("API610", "6.1.2")),
        ("API 2000 5.1", ("API2000", "5.1")),
        ("API 520-I \u00a75.5", ("API520I", "5.5")),
        ("API 520-I \u00a7 5.5", ("API520I", "5.5")),
        ("XS-1-2023 clause 6.1", ("XS1", "6.1")),
        ("XS-1 (edition not recorded) cl. 5", ("XS1", "5")),
        ("XS 610 datasheet annex", ("XS610", None)),
        ("ASME-Sec-VIII-Div1-2023 clause UG-99", ("ASMESECVIIIDIV1", "UG-99")),
        ("XS-1 (Table 3) 5.2", ("XS1", "5.2")),
        ("XS 526 Table 3", ("XS526", "3")),
        ("", None),
    ],
)
def test_clause_ref_reads_the_standard_and_the_clause(text, ref):
    assert aks.clause_ref(text) == ref


def test_every_output_says_it_is_a_scorer_and_wrong_passes_have_a_denominator(
    tmp_path, capsys
):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "aks_cli2",
        Path(__file__).resolve().parents[2] / "scripts" / "answer_key_score.py",
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    key = _key(tmp_path, [{"kind": "problem", "role": "spring_material", "page": "1"}])
    crs = _crs(
        tmp_path,
        [("p.1 - Body", "c", "XS-1 1", "Query", "")],
        [
            ("p.1", "Spring (page 1): meets", "XS-1 6.2", "Pass", ""),
            ("p.1", "Body (page 1): meets", "XS-1 6.1", "Pass", ""),
        ],
    )
    assert cli.main(["--key", str(key), "--crs", str(crs), "--hand-found", "2,9"]) == 0
    out = capsys.readouterr().out
    assert (
        out.splitlines()[0]
        == aks.SOURCE
        == "SCORER (field role + paper page), not a hand score"
    )
    assert "wrong passes 1 problem rows, from 1 of 2 pass lines" in out
    assert "'both': [], 'scorer_only': [], 'hand_only': [2, 9]" in out
    assert cli.main(["--key", str(key), "--crs", str(crs), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["source"] == aks.SOURCE


def test_overlap_names_rows_in_both_scorer_only_and_hand_only():
    assert aks.overlap([2, 3, 12], [2, 3, 10]) == {
        "both": [2, 3],
        "scorer_only": [12],
        "hand_only": [10],
    }


def test_a_pass_line_goes_to_the_complies_row_not_the_problem_row_on_the_same_point(
    tmp_path,
):
    key = [
        {"kind": "problem", "role": "body_material", "page": "1"},
        {"kind": "complies", "role": "body_material", "page": "1"},
    ]
    res = _score(
        tmp_path, key, [], [("p.1", "Body (page 1): meets", "XS-1 6.1", "Pass", "")]
    )
    assert res["complies_confirmed"] == [3]
    assert res["wrong_passes"] == [] and res["wrong_pass_lines"] == 0


def test_a_comment_line_goes_to_the_problem_row_not_the_complies_row(tmp_path):
    key = [
        {"kind": "complies", "role": "body_material", "page": "1"},
        {"kind": "problem", "role": "body_material", "page": "1"},
    ]
    res = _score(tmp_path, key, [("p.1 - Body", "c", "XS-1 6.1", "Query", "")])
    assert res["problems_found"] == [3]
    assert res["complies_confirmed"] == []


def test_a_one_word_printed_label_must_be_the_whole_line_label():
    _, patterns = aks._registry()
    spell = {"body_material": ("Material",)}
    assert "body_material" not in aks.roles_named("Spring material", patterns, spell)
    assert "body_material" in aks.roles_named("Material", patterns, spell)


def _ai_verdict_crs(tmp_path, rows):
    """A CRS in the NEW layout whose rows are (page, comment, status): the Status column the AI reviewer's workbook has."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CRS"
    ws.append(
        [
            "Item No",
            "Document Name",
            "Page No./Section",
            "COMPANY Comments",
            "Comment By",
            "Contractor's Response",
            "Final Resolution",
            "Standard Reference",
            "Priority",
            "Status",
        ]
    )
    for i, (page, comment, status) in enumerate(rows, start=1):
        ws.append(
            [
                i,
                "doc_x",
                page,
                comment,
                "AI reviewer",
                None,
                None,
                "XS-1 1",
                None,
                status,
            ]
        )
    path = tmp_path / "ai.xlsx"
    wb.save(path)
    return path


def test_a_two_reader_verdict_is_a_decision_of_its_own_kind_and_a_wrong_one_is_a_clear_wrong(
    tmp_path,
):
    key = [
        {"kind": "problem", "role": "set_pressure", "page": "2"},
        {"kind": "complies", "role": "body_material", "page": "1"},
        {"kind": "problem", "role": "set_pressure", "page": "3"},
    ]
    not_met = "Not met (AI, two readers agree, quotes verified): reached independently by two AI readers, engineer to confirm."
    met = "Met (AI, two readers agree, quotes verified): one AI reader's verdict, checked by a second AI reader that saw the first answer, engineer to confirm."
    crs = _ai_verdict_crs(
        tmp_path,
        [
            ("p.2 - Set pressure", not_met, "AI verdict"),
            ("p.1 - Body material", met, "AI verdict"),
            ("p.3 - Set pressure", met, "AI verdict"),
        ],
    )
    res = aks.score_files(_key(tmp_path, key), crs)
    assert res["ai_verdict_lines"] == 3 and res["lines_unknown_verdict"] == 0
    assert res["ai_verdict_found"] == [2] and res["ai_verdict_complies_confirmed"] == [
        3
    ]
    assert (
        res["ai_verdict_wrong"] == [4] and 4 in res["clear_wrong"]
    )  # a wrong "met" on a problem row is a clear wrong
    assert (
        res["problems_found"] == []
        and res["pass_lines"] == 0
        and res["complies_confirmed"] == []
    )  # never mixed into the proven counts
    assert "wrong two-reader verdicts" in aks.summary(res)["clear_wrong"]


def test_decisions_are_code_pass_fail_plus_two_reader_verdicts_right_wrong_and_not_on_the_key(
    tmp_path,
):
    key = [
        {"kind": "problem", "role": "set_pressure", "page": "2"},
        {"kind": "complies", "role": "body_material", "page": "1"},
        {"kind": "problem", "role": "design_pressure", "page": "3"},
        {"kind": "complies", "role": "operating_temperature", "page": "4"},
    ]
    met = "Met (AI, two readers agree, quotes verified): one AI reader's verdict, checked by a second AI reader that saw the first answer, engineer to confirm."
    not_met = "Not met (AI, two readers agree, quotes verified): reached independently by two AI readers, engineer to confirm."
    absent = "The AI reviewer's verdict, to be confirmed by an engineer: Two AI readers each read every page and found no value for this; the reviewer's code found none either."
    crs = _ai_verdict_crs(
        tmp_path,
        [
            ("p.2 - Set pressure", "c", "Fail"),  # a code Fail on a problem row: right
            (
                "p.1 - Body material",
                met,
                "AI verdict",
            ),  # a two-reader met on a complies row: right
            (
                "p.3 - Design pressure",
                met,
                "AI verdict",
            ),  # a two-reader met on a problem row: wrong
            ("p.9 - Tag number", not_met, "AI verdict"),  # not on the key
            (
                "p.4 - Operating temperature",
                absent,
                "AI verdict",
            ),  # not stated: not a decision
            (
                "p.4 - Operating temperature",
                "c",
                "AI opinion",
            ),  # AI thinks: not a decision
            ("p.4 - Operating temperature", "c", "Query"),  # a Query: not a decision
        ],
    )
    res = aks.score_files(_key(tmp_path, key), crs)
    assert res["decisions"] == {
        "n": 4,
        "code": 1,
        "two_reader": 3,
        "right": 2,
        "wrong": 1,
        "not_on_key": 1,
    }
    assert res["ai_verdict_wrong"] and set(res["ai_verdict_wrong"]) <= set(
        res["clear_wrong"]
    )  # a wrong two-reader verdict is a clear wrong
    assert (
        "decisions = code Pass/Fail + two-reader verdicts: right 2 of 4, wrong 1, not on the key 1"
        in aks.summary(res)["decisions"]
    )


def test_a_code_pass_on_a_complies_row_is_a_right_decision(tmp_path):
    key = [{"kind": "complies", "role": "body_material", "page": "1"}]
    crs = _crs(tmp_path, [], [("p.1", "Body (page 1): x", "XS-1 1", "Pass", "")])
    res = aks.score_files(_key(tmp_path, key), crs)
    assert res["decisions"]["right"] == 1 and res["decisions"]["n"] == 1
