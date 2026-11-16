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
    results = cc.check_attachments(
        CONTRACT, complete=True
    )  # the caller holds the whole contract
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
    b = _one(cc.check_attachments(CONTRACT, complete=True), "CT-02", "Schedule B")
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
    # Attachment III of Schedule K does not answer for Schedule W's: no result says it is present
    assert not [
        r for r in results if r.outcome == cc.CONSISTENT and "Schedule W" in r.topic
    ]
    assert "Attachment III of Schedule W" in _one(results, "CT-02", "Schedule W").value


def test_a_sibling_part_outside_the_package_goes_to_the_engineer_not_a_finding():
    results = cc.check_attachments(PART_K, PACKAGE_K)
    for topic in ("Schedule C", "Schedule W"):
        r = _one(results, "CT-02", topic)
        assert r.outcome == cc.ENGINEER and r.value.startswith("not held")


def test_a_missing_sub_part_of_a_missing_part_is_said_in_one_comment():
    results = cc.check_attachments(PART_K, PACKAGE_K)
    w = _one(results, "CT-02", "Schedule W")
    assert (
        w.value == "not held; also Attachment III of Schedule W"
        and "Attachment III of Schedule W" in w.message
    )
    assert not [r for r in results if r.topic == "Attachment III of Schedule W"]
    assert cc.judge_rows(results)["G4"]["status"] == "PASS"


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


def test_a_missing_part_without_every_page_read_fails_g5():
    pages = [
        (1, "1.1 The codes are in Appendix F."),
        (3, "Schedule A Scope"),
    ]  # page 2 has no stored text
    results = cc.check_attachments(pages, complete=True)
    f = _one(results, "CT-02", "Appendix F")
    assert f.outcome == cc.INCONSISTENT and not f.absence_proven
    assert cc.judge_rows(results)["G5"]["status"] == "FAIL"


def test_stored_lines_are_kept_and_a_contradiction_is_named():
    results = cc.check_attachments(CONTRACT, complete=True)
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
        "Appendix F: not in the papers given" in printed
        and "two pumps" not in printed
        and "codes are in" not in printed
    )
    assert db.stat().st_mtime_ns == before
    assert (
        json.loads(out.read_text())["checklist"]["status"]
        == "AI draft, engineer to confirm"
    )


def test_the_checks_live_in_the_app_and_run_all_is_lane_bs_entry():
    from app import contract_checks as core

    assert (
        cc.run_all is core.run_all and cc.Result is core.Result
    )  # the command re-uses the app's checks, not a copy
    results = core.run_all(CONTRACT, {"doc_b": [(1, "Schedule B\nPrice")]})
    shown = [r.to_json() for r in results]
    assert {r["ct"] for r in shown} <= set(core.CODES)
    assert all(r["internal_only"] and r["rule"] == core.RULE_STATE for r in shown)
    source = Path(core.__file__).read_text(encoding="utf-8")
    assert (
        "sqlite3" not in source and "connect(" not in source
    )  # pure: pages in, results out


def test_a_higher_part_on_the_next_line_is_read():
    pages = [
        (
            1,
            'SCHEDULE "K"\nScope\n2.1 Material as listed in Appendix I of\nSchedule W.\n2.2 Items in Attachment III.',
        )
    ]
    results = cc.check_attachments(pages)
    w = _one(
        results, "CT-02", "Schedule W"
    )  # a missing appendix of a missing schedule: one comment
    assert w.value == "not held; also Appendix I of Schedule W"
    assert not [
        r for r in results if r.outcome == cc.CONSISTENT and "Schedule W" in r.topic
    ]


def test_in_a_part_of_a_contract_a_sub_part_with_no_named_higher_part_goes_to_the_engineer():
    pages = [
        (
            1,
            'SCHEDULE "K"\nScope\n2.1 Thereof, Appendix "C" - instructions.\n2.2 Spares per Appendix D to this Schedule K.'
            "\nAppendix E\nThe spare parts are listed here with their prices and their delivery dates.",
        )
    ]
    results = cc.check_attachments(pages, complete=True)
    c = _one(results, "CT-02", "Appendix C")
    assert c.outcome == cc.ENGINEER and c.value.startswith("not held")
    # named as this paper's own, and the papers are the whole contract: a missing one is a finding
    d = _one(results, "CT-02", "Appendix D of Schedule K")
    assert d.outcome == cc.INCONSISTENT


def test_a_part_missing_from_a_paper_that_holds_none_of_its_kind_is_not_a_finding():
    pages = [(1, "1.1 The Works are in Schedule A.\n1.2 Codes in Appendix F.")]
    f = _one(cc.check_attachments(pages), "CT-02", "Appendix F")
    assert f.outcome == cc.ENGINEER and f.value == "not in the papers given"
    assert (
        _one(cc.check_attachments(pages, complete=True), "CT-02", "Appendix F").outcome
        == cc.INCONSISTENT
    )


def test_a_list_of_schedules_with_titles_between_does_not_make_them_present():
    pages = [
        (
            1,
            'FORM OF AGREEMENT\nThe following form part of this Contract:\nSCHEDULE "A"\nGeneral Terms\nSCHEDULE "B"\n'
            'Scope of Work\nSCHEDULE "C"\nPrices\nOrder of precedence:\n1.\nSchedule "B"\n2.\nSchedule "A"\n3.',
        )
    ]
    results = cc.check_attachments(pages, complete=True)
    assert {r.topic: r.outcome for r in results} == {
        "Schedule A": cc.INCONSISTENT,
        "Schedule B": cc.INCONSISTENT,
        "Schedule C": cc.INCONSISTENT,
    }  # none is present: the list names them, it does not hold them
    assert {r.outcome for r in cc.check_attachments(pages)} == {
        cc.ENGINEER
    }  # the package may hold them
    held = cc.check_attachments(
        pages,
        {
            "doc_a": [
                (1, 'SCHEDULE "A"\nGeneral Terms and Conditions of the contract text')
            ]
        },
    )
    assert _one(held, "CT-02", "Schedule A").value == "present (held document doc_a)"


def test_a_heading_inside_the_paper_counts_only_for_the_whole_contract():
    # Schedule A has a heading with a body on page 2; in papers that may not be the whole contract a heading line is no
    # proof (a list of schedules or a reference at the start of a line looks the same)
    a = _one(cc.check_attachments(CONTRACT), "CT-02", "Schedule A")
    assert a.outcome == cc.ENGINEER and a.value == "not in the papers given"
    assert (
        _one(
            cc.check_attachments(CONTRACT, complete=True), "CT-02", "Schedule A"
        ).outcome
        == cc.CONSISTENT
    )


def test_a_giving_verb_far_from_the_guarantee_word_does_not_name_a_giver():
    pages = [(1, PARTIES + "6.1 The Supplier shall provide the installation, testing and commissioning of every pump and skid"
                           " on site to maintain the vendor warranty.")]  # fmt: skip
    assert _one(cc.check_guarantees(pages), "CT-03", "warranty").outcome == cc.ENGINEER


def test_sibling_numbered_clauses_of_one_percentage_each_are_a_payment_schedule():
    pages = [(1, "7.2 Material price\n7.2.1.1 Twenty percent (20%) of the price on order.\n7.2.1.2 Seventy percent (70%) of"
                 " the price on delivery.\n7.2.1.3 Ten percent (10%) of the price on acceptance.\n"
                 "7.3.1 Thirty percent (30%) of the price on order.\n7.3.2 The rest is paid as agreed.")]  # fmt: skip
    results = cc.check_stages(pages)
    assert [(r.value, r.outcome) for r in results] == [
        ("20 + 70 + 10 = 100%", cc.CONSISTENT)
    ]  # 7.3.x: a sibling has none
    pages[0] = (1, pages[0][1].replace("Ten percent (10%)", "Five percent (5%)"))
    assert [r.outcome for r in cc.check_stages(pages)] == [cc.INCONSISTENT]


def test_a_wrapped_cross_reference_does_not_break_a_numbered_schedule_and_an_unverified_quote_decides_nothing():
    pages = [(1, "7.2.2.1 Thirty percent (30%) of the price on order.\n7.2.2.2 Sixty-five percent (65%) of the price on"
                 " delivery.\n7.2.2.3 Remaining five percent (5%) of the price.\nThe rest is paid under Sub-Article\n"
                 "7.2.2.2 and upon acceptance.")]  # fmt: skip
    assert [(r.value, r.outcome) for r in cc.check_stages(pages)] == [
        ("30 + 65 + 5 = 100%", cc.CONSISTENT)
    ]
    r = cc._finish(
        cc.Result(
            "CT-01",
            "t",
            cc.CONSISTENT,
            "v",
            "m",
            [cc.Quote(1, "not on the page", False)],
        )
    )
    assert r.outcome == cc.ENGINEER


def test_a_label_held_under_several_higher_parts_is_not_credited_to_any_one_of_them():
    package = {
        "doc_a2": [(1, 'SCHEDULE "A"\nATTACHMENT II\nManpower')],
        "doc_h2": [(1, 'SCHEDULE "H"\nATTACHMENT II\nDivision of responsibilities')],
    }
    agreement = [(1, "FORM OF AGREEMENT\n1.1 The manpower plan is in Attachment II.")]
    a = _one(cc.check_attachments(agreement, package), "CT-02", "Attachment II")
    assert a.outcome == cc.ENGINEER and a.value == "higher part not named"
    one = {
        "doc_a2": package["doc_a2"]
    }  # even one holder: the agreement does not say whose Attachment II it means
    assert (
        _one(cc.check_attachments(agreement, one), "CT-02", "Attachment II").value
        == "higher part not named"
    )
    schedule_h = [
        (1, 'SCHEDULE "H"\nSpecial terms\n1.1 The split of work is in Attachment II.')
    ]
    h = _one(cc.check_attachments(schedule_h, package), "CT-02", "Attachment II")
    assert h.value == "present (held document doc_h2)"  # the paper's own Attachment II


def test_in_a_schedule_an_attachment_with_no_named_parent_is_never_another_schedules():
    package = {"doc_w1": [(1, 'SCHEDULE "W"\nATTACHMENT I\nTools')]}
    schedule_k = [
        (1, 'SCHEDULE "K"\nScope of work\n1.1 Offices are listed in Attachment I.')
    ]
    r = _one(cc.check_attachments(schedule_k, package), "CT-02", "Attachment I")
    assert r.outcome == cc.ENGINEER and r.value.startswith("not held")
    attachment_w2 = [
        (
            1,
            'SCHEDULE "W"\nATTACHMENT II\nProcurement\n1.1 Tools are listed in Attachment I.',
        )
    ]
    sib = _one(cc.check_attachments(attachment_w2, package), "CT-02", "Attachment I")
    assert (
        sib.value == "present (held document doc_w1)"
    )  # a sibling under the paper's own schedule


def test_a_schedule_that_names_itself_is_present_as_this_paper():
    schedule_k = [
        (
            1,
            'SCHEDULE "K"\nGeneral terms\n1.1 This Schedule K and its attachments govern the work.',
        )
    ]
    r = _one(cc.check_attachments(schedule_k), "CT-02", "Schedule K")
    assert r.outcome == cc.CONSISTENT and r.value == "present (this paper)"


# ------------------------------------------------------------------------------------------------ guards on AI comments

from app import contract_checks as core  # noqa: E402

AGREEMENT = [
    (1, "FORM OF AGREEMENT\n1.4 In case of conflict the following order of precedence shall govern:\n1.\nThis Form of Agreement\n"
        '2.\nSchedule "L" and its Attachments\n3.\nSchedule "P" (drawings)'),
    (2, "Header of the contract\nPage 2\n4.\nSchedule \"T\" and its Attachments\n5.\nSchedule \"K\"\n1.5 Notices are given in"
        " writing to the addresses below.\n8.3 Retention Bond\nThe Contractor shall furnish a bank guarantee as set"
        ' forth in Sub-Article\n9.7 of SCHEDULE "D" ("Retention Bond") in an amount stated there.'),
]  # fmt: skip
SCHEDULE_A = {
    "doc_a": [
        (1, 'SCHEDULE "D"\nGeneral terms'),
        (2, "9.7 Retention Bond\nThe bond is valid until completion."),
    ]
}


def test_the_precedence_list_is_read_in_order_across_pages_and_ends_at_a_numbered_clause():
    ranks = [
        (r, core._name((k, None)), p) for r, k, p in core.precedence_list(AGREEMENT)
    ]
    assert ranks == [
        (2, "Schedule L", 1),
        (3, "Schedule P", 1),
        (4, "Schedule T", 2),
        (5, "Schedule K", 2),
    ]


def test_a_ranking_the_list_contradicts_goes_to_the_engineer_and_a_right_one_stands():
    ranks = core.precedence_list(AGREEMENT)
    wrong = core.guard_ranking(
        "This conflicts with the ranking of P at 3, below Schedule T.", ranks
    )
    assert wrong == "the list on page 1 ranks Schedule P above Schedule T"
    assert (
        core.guard_ranking("Schedule T ranks below Schedule P, as it should.", ranks)
        is None
    )
    assert "ranks Schedule P at 3, not 7" in core.guard_ranking(
        "It puts the ranking of P at 7 in the list.", ranks
    )
    assert (
        core.guard_ranking(
            "The retention stays below the cap after the first invoice.", ranks
        )
        is None
    )


def test_a_term_called_absent_that_the_paper_refers_to_a_held_clause_goes_to_the_engineer():
    comment = "The Retention Bond has no stated validity or release trigger."
    why = core.guard_referred(comment, AGREEMENT, SCHEDULE_A)
    assert (
        why
        == "the paper (page 2) refers Retention Bond to 9.7 of Schedule D, which is held (doc_a, page 2)"
    )
    assert (
        core.guard_referred(comment, AGREEMENT, {"doc_a": SCHEDULE_A["doc_a"][:1]})
        is None
    )  # clause not held
    assert (
        core.guard_referred(comment, AGREEMENT, {}) is None
    )  # the referred part not held
    assert (
        core.guard_referred("The Warranty has no start date.", AGREEMENT, SCHEDULE_A)
        is None
    )  # not referred


def test_a_guarded_comment_never_stands_as_firm():
    g = core.guard_comment(
        "This conflicts with the ranking of P at 3, below Schedule T.",
        AGREEMENT,
        SCHEDULE_A,
    )
    assert (
        g["outcome"] == cc.ENGINEER
        and g["rule"] == "precedence list"
        and g["reason"].startswith("engineer to check")
    )
    assert (
        core.guard_comment("The insurance amount is left blank.", AGREEMENT, SCHEDULE_A)
        is None
    )


def test_the_command_guards_a_stored_runs_lines_read_only_and_prints_no_comment_text(
    tmp_path, capsys
):
    db = tmp_path / "copy.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT)")
    conn.execute(
        "CREATE TABLE agent_review_line (run_id TEXT, item_id TEXT, verdict_class TEXT, line_json TEXT)"
    )
    conn.executemany("INSERT INTO pages VALUES ('doc_x', ?, ?)", AGREEMENT)
    conn.executemany("INSERT INTO pages VALUES ('doc_a', ?, ?)", SCHEDULE_A["doc_a"])
    lines = [("G-1", "This conflicts with the ranking of P at 3, below Schedule T."),
             ("G-2", "The insurance amount is left blank in the special clause.")]  # fmt: skip
    conn.executemany(
        "INSERT INTO agent_review_line VALUES ('r', ?, 'AI note, no rule book', ?)",
        [(i, json.dumps({"text": t})) for i, t in lines],
    )
    conn.commit()
    conn.close()
    before = db.stat().st_mtime_ns
    assert (
        cc.main(
            [
                "--db",
                str(db),
                "--document",
                "doc_x",
                "--package",
                "doc_a",
                "--guard-run",
                "r",
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert (
        "G-1 [AI note, no rule book] -> precedence list: engineer to check" in printed
    )
    assert (
        "G-2 [AI note, no rule book] -> untouched" in printed
        and "insurance amount" not in printed
    )
    assert db.stat().st_mtime_ns == before
