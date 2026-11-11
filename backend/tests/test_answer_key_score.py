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
        {"kind": "problem", "role": "cdtp", "page": ""},
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
