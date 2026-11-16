"""Order 14 lane E: the contract checks CT-01 to CT-03 (`scripts/contract_checks.py`) and the draft checklist
(`reference/contract_checks.json`). Every paper here is invented text."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "contract_checks", REPO / "scripts" / "contract_checks.py"
)
cc = importlib.util.module_from_spec(_SPEC)
sys.modules["contract_checks"] = cc
_SPEC.loader.exec_module(cc)  # type: ignore[union-attr]


def _one(results, ct, topic=None):
    got = [r for r in results if r.ct == ct and (topic is None or r.topic == topic)]
    assert len(got) == 1, [(r.ct, r.topic, r.outcome) for r in results]
    return got[0]


# ------------------------------------------------------------------------------------------------ the draft checklist


def test_the_checklist_is_an_ai_draft_with_eight_items_and_the_owners_three_first():
    data = cc.checklist()
    assert (
        data["status"] == "AI draft, engineer to confirm"
        and data["approver"] == "the owner"
        and data["approved"] is False
    )
    items = data["items"]
    assert [i["id"] for i in items] == [f"CT-0{n}" for n in range(1, 9)]
    assert all(i["code_check"] in ("full", "partly", "not") for i in items)
    assert all(i["needs_text"].strip() for i in items)
    assert [i["code_check"] for i in items[:3]] == ["full", "full", "partly"]
    assert [i["source"] for i in items[:3]] == [
        "owner example 1",
        "owner example 2",
        "owner example 3",
    ]


# ------------------------------------------------------------------------------------------------ CT-01 stages add to 100%

STAGES_90 = [
    (
        1,
        "Article 3 Payment\n3.1 The Price is paid in three (3) instalments:\n"
        "(a) 10% advance payment on signing;\n(b) 60% payment on delivery;\n(c) 20% payment on acceptance.\n"
        "3.2 Late payment interest is 1.5% per month.\n"
        "3.3 Liquidated damages of 0.5 percent of the Price per week.",
    )
]


def test_stages_that_do_not_add_to_100_are_a_finding_with_the_sum_and_page():
    results = cc.check_stages(STAGES_90)
    sched = _one(results, "CT-01", "payment schedule p1")
    assert sched.outcome == cc.INCONSISTENT
    assert (
        sched.value == "10 + 60 + 20 = 90%"
    )  # the interest rate and the damages rate are not stages
    assert {q.page for q in sched.quotes} == {1} and all(
        q.verified for q in sched.quotes
    )
    assert (
        _one(results, "CT-01", "number of stages p1").outcome == cc.CONSISTENT
    )  # three stated, three found


def test_stages_that_add_to_100_are_consistent_and_a_wrong_stated_count_is_a_finding():
    pages = [
        (
            1,
            "Payment in four instalments.\nMilestone 1: 30% payment on order\nMilestone 2: 70% payment on delivery",
        )
    ]
    results = cc.check_stages(pages)
    assert _one(results, "CT-01", "payment schedule p1").outcome == cc.CONSISTENT
    count = _one(results, "CT-01", "number of stages p1")
    assert count.outcome == cc.INCONSISTENT and count.value == "4 stated, 2 found"


def test_a_stated_count_with_no_stage_anywhere_goes_to_the_engineer_with_the_whole_paper_read():
    pages = [
        (
            1,
            "3.1 The Owner pays the Price in three instalments as set out in Schedule B.",
        ),
        (2, "Schedule B\nB.1 Price USD 10."),
    ]
    r = _one(cc.check_stages(pages), "CT-01")
    assert (
        r.outcome == cc.ENGINEER and r.value == "3 stated, 0 found" and r.absence_proven
    )


def test_a_stage_line_with_two_percentages_is_not_added():
    pages = [
        (
            1,
            "Stage 1: 10% advance payment, of which 5% on signing\nStage 2: 90% payment on delivery",
        )
    ]
    assert _one(cc.check_stages(pages), "CT-01").outcome == cc.ENGINEER


def test_a_paper_with_no_payment_stage_gives_no_row():
    assert cc.check_stages([(1, "The Supplier warrants the goods.")]) == []


# ------------------------------------------------------------------------------------------------ CT-02 every attachment present

CONTRACT = [
    (
        1,
        "1.1 The Works are described in Schedule A.\n1.2 The codes are in Appendix F.\n"
        "List of schedules\nSchedule A Scope\nSchedule B Price\nSchedule C Addresses",
    ),
    (
        2,
        "Schedule A Scope of work\nThe Works comprise two pumps. See Appendix F.\nPayment terms are in Schedule B.",
    ),
]


def test_a_referred_appendix_that_is_not_present_is_a_finding_on_its_pages():
    results = cc.check_attachments(CONTRACT)
    f = _one(results, "CT-02", "Appendix F")
    assert (
        f.outcome == cc.INCONSISTENT
        and {q.page for q in f.quotes} == {1, 2}
        and f.absence_proven
    )
    assert (
        _one(results, "CT-02", "Schedule A").outcome == cc.CONSISTENT
    )  # its heading on page 2


def test_a_list_of_schedules_does_not_make_them_present():
    # Schedule B and C appear only in the list on page 1: a list refers to parts, it does not hold them
    b = _one(cc.check_attachments(CONTRACT), "CT-02", "Schedule B")
    assert b.outcome == cc.INCONSISTENT


def test_a_held_package_document_makes_its_part_present():
    package = {
        "doc_b": [(1, "Schedule B\nPrice and payment\nB.1 ...")],
        "doc_c": [(1, 'SCHEDULE "C"\nAddresses')],
    }
    results = cc.check_attachments(CONTRACT, package)
    assert _one(results, "CT-02", "Schedule B").value == "present (held document doc_b)"
    assert _one(results, "CT-02", "Schedule C").outcome == cc.CONSISTENT


PART_K = [
    (
        1,
        'SCHEDULE "K"\nMaterials\n1.1 Tools are listed on Attachment I to this SCHEDULE "K".\n'
        '1.2 Spares per Article 4 of Attachment III, to SCHEDULE "W".\n1.3 Payments under Schedule C.',
    )
]
PACKAGE_K = {
    "doc_att1": [(1, 'SCHEDULE "K"\nATTACHMENT I\nTOOLS')],
    "doc_att3": [(1, 'SCHEDULE "K"\nATTACHMENT III\nSPARES')],
    "doc_ex1": [(1, 'EXHIBIT I, ATTACHMENT III, SCHEDULE "K"\nSPARE PRICES')],
}


def test_a_part_of_another_schedule_is_not_matched_by_the_same_label_of_this_one():
    results = cc.check_attachments(PART_K, PACKAGE_K)
    assert (
        _one(results, "CT-02", "Attachment I of Schedule K").value
        == "present (held document doc_att1)"
    )
    q = _one(results, "CT-02", "Attachment III of Schedule W")
    assert (
        q.outcome != cc.CONSISTENT
    )  # Attachment III of Schedule K does not answer for Schedule W's


def test_a_sibling_part_outside_the_package_goes_to_the_engineer_not_a_finding():
    results = cc.check_attachments(PART_K, PACKAGE_K)
    for topic in ("Schedule C", "Schedule W", "Attachment III of Schedule W"):
        r = _one(results, "CT-02", topic)
        assert r.outcome == cc.ENGINEER and r.value == "not held"


def test_a_package_document_is_its_deepest_heading_label_under_the_next_higher_one():
    assert cc.package_part(PACKAGE_K["doc_ex1"]) == [
        (("exhibit", "I"), ("attachment", "III"))
    ]
    assert cc.package_part(PACKAGE_K["doc_att1"]) == [
        (("attachment", "I"), ("schedule", "K"))
    ]


def test_plain_capitals_are_not_labels():
    assert cc.labels("SCHEDULE OF RATES and ATTACHMENT TO THE FORM") == []
    assert [
        (w, lab)
        for w, lab, _i in cc.labels('see Appendix F, SCHEDULE "K" and Attachment VII.')
    ] == [("appendix", "F"), ("schedule", "K"), ("attachment", "VII")]


# ------------------------------------------------------------------------------------------------ CT-03 one name per guarantee

PARTIES = 'This Contract is between Alpha Owner Company (the "Owner") and Beta Supplier Limited (the "Supplier").\n'


def test_one_party_giving_the_warranty_is_consistent():
    pages = [
        (
            1,
            PARTIES
            + "Article 5 Warranty\n5.1 The Supplier warrants the Works for 12 months.\n"
            "5.2 The warranty period runs from delivery.",
        )
    ]
    r = _one(cc.check_guarantees(pages), "CT-03", "warranty")
    assert r.outcome == cc.CONSISTENT and r.value == "Supplier"


def test_two_parties_giving_one_guarantee_kind_is_a_finding_with_both_quotes():
    pages = [
        (
            1,
            PARTIES
            + "7.1 Beta Supplier Limited shall furnish a performance bond of 10% of the Price.",
        ),
        (2, "7.4 The Owner shall provide the performance bond within 30 days."),
    ]
    r = _one(cc.check_guarantees(pages), "CT-03", "performance bond")
    assert r.outcome == cc.INCONSISTENT and r.value == "Owner / Supplier"
    assert {q.page for q in r.quotes} == {1, 2} and all(q.verified for q in r.quotes)


def test_the_party_a_guarantee_benefits_or_who_obtains_it_is_not_a_giver():
    pages = [
        (
            1,
            PARTIES + "8.1 The Supplier warrants the goods.\n"
            "8.2 The Owner shall obtain from the manufacturers such warranties as they give.\n"
            "8.3 Such warranties shall run to the benefit of the Owner.",
        )
    ]
    r = _one(cc.check_guarantees(pages), "CT-03", "warranty")
    assert r.outcome == cc.CONSISTENT and r.value == "Supplier"


def test_an_abbreviation_is_not_a_party():
    names = cc.parties(
        [(1, "The Material Take Off (MTO) and the Owner Company Limited (the Owner).")]
    )
    assert "MTO" not in names and names.get("Owner") == "Owner"


def test_no_named_giver_goes_to_the_engineer():
    r = _one(
        cc.check_guarantees([(1, PARTIES + "9.1 A bank guarantee is required.")]),
        "CT-03",
        "bank guarantee",
    )
    assert r.outcome == cc.ENGINEER


# ------------------------------------------------------------------------------------------------ quotes, gates, stored lines


def test_a_finding_whose_quote_does_not_stand_on_its_page_goes_to_the_engineer():
    r = cc._finish(
        cc.Result(
            "CT-02",
            "Appendix Z",
            cc.INCONSISTENT,
            "not present",
            "m",
            [cc.Quote(1, "words not on the page", False)],
        )
    )
    assert r.outcome == cc.ENGINEER


def test_the_rows_pass_the_shared_gates_g3_g4_g5_and_g5_sees_an_unverified_value():
    results = cc.run_all(
        [
            *CONTRACT,
            (
                3,
                "Payment in two stages:\nStage 1: 50% payment on order\nStage 2: 40% payment on delivery",
            ),
        ]
    )
    judged = cc.judge_rows(results)
    assert {g: v["status"] for g, v in judged.items()} == {
        "G3": "PASS",
        "G4": "PASS",
        "G5": "PASS",
    }
    rows = cc.gate_rows(results)
    assert any(r.rank == cc.FIRM_RANK for r in rows) and all(
        r.book and r.clause.startswith("CT-") for r in rows
    )
    rows[0].value_verified, rows[0].absence_proven, rows[0].rank = (
        False,
        False,
        cc.FIRM_RANK,
    )
    assert cc._gates().g5_firm(rows).status == "FAIL"


def test_stored_lines_are_kept_and_a_contradiction_is_named():
    results = cc.check_attachments(CONTRACT)
    lines = [
        {
            "item_id": "G-1",
            "part": "paper against itself",
            "page": 1,
            "class": "AI note, no rule book",
        },
        {
            "item_id": "G-2",
            "part": "paper against itself",
            "page": 2,
            "class": "AI note, no rule book",
        },
        {
            "item_id": "G-3",
            "part": "engineering comment",
            "page": 1,
            "class": "AI note, no rule book",
        },
        {
            "item_id": "G-4",
            "part": "paper against itself",
            "page": 2,
            "class": "AI note, no rule book",
        },
        {"item_id": "G-5", "part": "checklist", "page": None, "class": "Not reviewed"},
    ]
    mapping = {
        "G-1": "CT-02|Appendix F",
        "G-2": "CT-02|Schedule A",
        "G-3": "CT-07",
        "G-4": "CT-02|unlabelled",
    }
    got = {x["item_id"]: x["code"] for x in cc.against_stored(results, lines, mapping)}
    assert len(got) == len(lines)  # no stored line is dropped
    assert got["G-1"].startswith("agrees")
    assert got["G-2"].startswith("CONTRADICTED")
    assert (
        got["G-3"].startswith("kept")
        and got["G-4"].startswith("kept")
        and got["G-5"].startswith("kept")
    )


def test_the_command_reads_read_only_and_prints_no_paper_text(tmp_path, capsys):
    db = tmp_path / "copy.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT)")
    conn.executemany("INSERT INTO pages VALUES ('doc_x', ?, ?)", CONTRACT)
    conn.commit()
    conn.close()
    before = db.stat().st_mtime_ns
    out = tmp_path / "r.json"
    assert cc.main(["--db", str(db), "--document", "doc_x", "--json", str(out)]) == 0
    printed = capsys.readouterr().out + out.read_text()
    assert (
        "Appendix F: not present" in printed
        and "two pumps" not in printed
        and "codes are in" not in printed
    )
    assert db.stat().st_mtime_ns == before
    assert (
        json.loads(out.read_text())["checklist"]["status"]
        == "AI draft, engineer to confirm"
    )
