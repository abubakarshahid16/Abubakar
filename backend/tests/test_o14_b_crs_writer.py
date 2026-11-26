"""Order 14 lane B (owner, 16 Nov 2026): the shared CRS writer. Real clause quotes, no noise rows, one comment per field or topic in EVERY
CRS file (the AI run's own file too, through `crs_comments.group`), and the "N rules could not be matched" lines as ONE coverage note.
Invented data only; no model, no network."""

from __future__ import annotations

import io
import json

import openpyxl

from app import agent_review_wording as W
from app import crs_ai_words as words
from app import crs_ai_workbook as WB
from app import crs_comments, crs_completeness, crs_layout, crs_one

META = {
    "paper": "Paper A",
    "run_id": "run-1",
    "date": "2026-11-16",
    "header": {"project": "Project Q"},
}
SK = {"S-1", "S-2"}
OK = {"source": "rule", "rule_label": {"tier": "AI approved"}}
BOOK_WORDS = (
    "The relief device shall be set at or below the design pressure of the vessel"
)
OUR_WORDS = "Set pressure stated and not above design pressure"


def mk(iid, verdict="Query", ai=None, item=OK, **kw):
    base = {
        "item_id": iid, "source": item["source"], "standard": "STD-1", "clause": "4.1", "verdict": verdict,
        "decided_by": "decided by code", "ai_verdict": ai, "paper_page": 2, "paper_quote": "Set pressure 10 barg",
        "clause_quote": BOOK_WORDS, "quotes_checked": {"paper": True, "clause": True}, "reasoning": "It is stated.",
        "model": "lead-m", "field": "Set pressure", "reason_code": "needs_drawing_or_calc",
    }  # fmt: skip
    if verdict == "Pass":
        base["compare"] = {"decided": True, "verdict": "meets"}
    base.update(kw)
    if (
        "rule_label" not in kw and base.get("field")
    ):  # a comment is named by the item's field role (lead, R94): invent one from the field
        base["rule_label"] = {
            "tier": "AI approved",
            "field": "_".join(str(base["field"]).lower().split()),
        }
    return W.final_cap(base, item, skill_ids=SK)


def _group_line(book="STD-1", n=7):
    return {"item_id": f"G-{book}", "source": "group", "standard": book, "clause": "", "verdict": "Query", "decided_by": "engineer",
            "why": f"{n} rules of {book} could not be matched to a field of this paper: an engineer checks them",
            "comment": "x", "reasoning": "x", "group_count": n}  # fmt: skip


def _crs_rows(view):
    return view["rows"]


def _view(lines):
    return WB.layout_view(lines, META, "internal")


# ------------------------------------------------------------------------------------------------ 1. the book's verified words only


def test_the_comment_quotes_the_verified_clause_whole_never_the_checklist_wording(
    monkeypatch,
):
    monkeypatch.setattr(WB, "checklist_wording", lambda _i: OUR_WORDS)
    line = mk(
        "S-1",
        item={"source": "skill", "item_id": "S-1"},
        clause_quote=BOOK_WORDS + " " + "and so on " * 20,
    )
    assert WB._item_ask(line) == " ".join(
        (BOOK_WORDS + " " + "and so on " * 20).split()
    )  # whole: never cut
    cell = _crs_rows(_view([line]))[0][3]
    assert BOOK_WORDS in cell and OUR_WORDS not in cell


def test_no_verified_quote_is_said_in_plain_words_and_our_wording_is_labelled_as_ours(
    monkeypatch,
):
    monkeypatch.setattr(WB, "checklist_wording", lambda _i: OUR_WORDS)
    line = mk(
        "S-1",
        item={"source": "skill", "item_id": "S-1"},
        quotes_checked={"paper": True, "clause": False},
    )
    assert WB._item_ask(line) == ""  # nothing is shown as the book's words
    cell = _crs_rows(_view([line]))[0][3]
    assert WB.NO_QUOTE in cell
    assert f'Our checklist asks (our words, not the book\'s): "{OUR_WORDS}"' in cell
    assert f'requires: "{OUR_WORDS}' not in cell


# ------------------------------------------------------------------------------------------------ 2. noise rows leave the comment list


def test_a_met_field_is_not_a_comment_and_is_counted_apart():
    met = mk("R-1", "Pass", field="Body material", reason_code=None)
    ask = mk("R-2", field="Set pressure")
    view = _view([met, ask])
    assert len(view["rows"]) == 1 and "Set pressure" in view["rows"][0][2]
    other = {r[0]: r[4] for r in view["other"]["rows"]}
    assert other[2] == words.KIND_NOTHING_TO_CHANGE
    assert view["other"]["name"] == words.NOT_A_COMMENT_SHEET
    notes = {r[0]: r[1] for r in view["notes"]["rows"]}
    assert notes[f"Count: {words.KIND_NOTHING_TO_CHANGE}"] == 1


def test_the_readers_view_never_prints_no_correction_needed():
    """A "met" the guard held because the value is open stays a question; the AI's "No correction needed" is not printed, its other
    words are."""
    line = mk("R-1", "Query", ai="Pass", paper_quote="Set pressure TBA", reason_code="met",
              comment="No correction needed; confirm the mark at vendor stage.")  # fmt: skip
    cell = _crs_rows(_view([line]))[0][3]
    assert words.NOISE.search(cell) is None
    assert "the requirement is met. Confirm the mark at vendor stage." in cell


def test_only_a_met_with_a_verified_paper_quote_is_ticked_and_every_real_question_stays_a_comment():
    """R91: the tick list takes a "met" whose paper quote code verified and whose only doubt is the clause quote. A paper quote not
    verified, readers who disagree, words saying the value is not stated, a value left open: all stay comments."""

    def met(i, field, **kw):
        return mk(i, "Query", ai="Pass", reason_code="met", field=field, **kw)

    tick = met("R-1", "Body", quotes_checked={"paper": True, "clause": False})
    unverified = met("R-2", "Seal", quotes_checked={"paper": False, "clause": True})
    disagree = met(
        "R-3",
        "Fluid",
        quotes_checked={"paper": True, "clause": False},
        second_opinion={"agree": False},
    )
    not_stated = met(
        "R-4",
        "Gasket",
        quotes_checked={"paper": True, "clause": False},
        not_mentioned_hold=True,
    )
    open_value = met("R-5", "Set pressure", paper_quote="Set pressure TBA")
    view = _view([tick, unverified, disagree, not_stated, open_value])
    assert sorted(r[2].split(" - ")[1] for r in view["rows"]) == [
        "Fluid",
        "Gasket",
        "Seal",
        "Set pressure",
    ]
    other = {r[0]: r for r in view["other"]["rows"]}
    assert [r[4] for r in other.values()] == [
        words.KIND_MET_NOT_CONFIRMED
    ] and "The engineer ticks it." in list(other.values())[0][5]


def test_drop_noise_keeps_the_rest_and_leaves_other_text_alone():
    assert (
        words.drop_noise("No correction needed; consider the blank field.")
        == "Consider the blank field."
    )
    assert words.drop_noise("No correction needed.") == ""
    assert words.drop_noise("the value is 5 barg") == "the value is 5 barg"
    assert (
        words.plain("Values found none. The sheet is fine.")
        == "Values The sheet is fine."
    )


# ------------------------------------------------------------------------------------------------ 3. one comment per field, every file


def test_the_run_file_holds_one_comment_per_field_and_lists_the_others():
    lines = [
        mk("R-1", field="Set pressure", clause="4.1"),
        mk("R-2", field="Set Pressure:", clause="8", standard="STD-2"),
        mk("R-3", field="SET-PRESSURE", clause="9"),
        mk("R-4", field="Over pressure %"),
        mk("R-5", field="Overpressure"),
    ]
    view = _view(lines)
    assert len(view["rows"]) == 2
    first = view["rows"][0][3]
    assert (
        "Also on this field, a question for the engineer under STD-2 clause 8 (page 2): Contractor to confirm"
        in first
    )
    assert (
        "Also on this field, a question for the engineer under STD-1 clause 9 (page 2):"
        in first
    )
    kinds = [r[4] for r in view["other"]["rows"]]
    assert (
        kinds.count(words.KIND_IN_COMMENT.format(n=1)) == 2
        and kinds.count(words.KIND_IN_COMMENT.format(n=2)) == 1
    )
    items, others = WB.ordered_item_lines(lines), WB.other_lines(lines)
    assert (
        len(items) + len(others) == len(lines) == len(view["evidence"]["rows"])
    )  # every line keeps its Evidence row


def test_a_point_with_no_field_is_never_merged_by_the_pages_fixed_name():
    a = {
        "id": "a",
        "rank": 4,
        "tile": "questions",
        "name": "A point of the AI review",
        "_line": {"source": "skill", "item_id": "S-9"},
    }
    b = {
        "id": "b",
        "rank": 4,
        "tile": "questions",
        "name": "A point of the AI review",
        "_line": {"source": "skill", "item_id": "S-8"},
    }
    assert len(crs_comments.group([a, b])) == 2


def test_the_page_grouping_sets_aside_fields_with_no_finding_and_keeps_a_disagreement():
    def pt(i, field, rank, tile, **kw):
        return {"id": i, "name": field, "rank": rank, "tile": tile, **kw}

    pts = [
        pt("1", "Body", 5, "met"), pt("2", "Body", 7, "met"),
        pt("3", "Location", 8, "does_not_apply", other_kind=words.KIND_UNAPPROVED),
        pt("4", "Set pressure", 3, "not_met", rule_book="STD-1", clause="8", rule_text="r"), pt("5", "Set pressure", 5, "met", rule_book="STD-1", clause="8", rule_text="r"),
        pt("6", "Fluid", 4, "questions"),
    ]  # fmt: skip
    got = crs_comments.group(pts)
    assert (
        [c["name"] for c in got] == ["Set pressure", "Fluid"]
        and got[0]["disagree"]
        and got[0]["n_points"] == 2
    )
    aside = {c["name"]: kind for c, kind in crs_comments.set_aside(pts)}
    assert aside == {
        "Body": words.KIND_NOTHING_TO_CHANGE,
        "Location": words.KIND_UNAPPROVED,
    }
    assert sum(c["n_points"] for c in got) + sum(
        c["n_points"] for c, _k in crs_comments.set_aside(pts)
    ) == len(pts)


# ------------------------------------------------------------------------------------------------ 4. one coverage note


def test_rules_not_matched_become_one_coverage_note_not_comment_rows():
    lines = [mk("R-1"), _group_line("STD-1", 7), _group_line("STD-2", 3)]
    view = _view(lines)
    assert len(view["rows"]) == 1
    header = dict(view["header"])
    assert header["Coverage note:"].startswith(
        "10 rules of the rule books this review selected could not be matched"
    )
    assert "STD-1: 7; STD-2: 3" in header["Coverage note:"]
    assert [r[4] for r in view["other"]["rows"]] == [
        words.KIND_COVERAGE,
        words.KIND_COVERAGE,
    ]
    wb = openpyxl.load_workbook(io.BytesIO(crs_layout.build_layout_crs(view)))
    assert words.NOT_A_COMMENT_SHEET in wb.sheetnames


def test_the_coverage_note_counts_a_book_the_caller_may_not_read_without_naming_it():
    note = crs_comments.coverage_note(
        [{"_line": {**_group_line("STD-1", 4), "standard": ""}}]
    )
    assert note.startswith("4 rules of the rule books") and "(" not in note


# ------------------------------------------------------------------------------------------------ 5. completeness still holds


def _team_book(comment_points: list[int], aside_points: list[int] | None) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = crs_one.TEAM_SHEET
    ws.append(["Comment", "Points"])
    for n, k in enumerate(comment_points, start=1):
        ws.append([n, k])
    if aside_points is not None:
        ws2 = wb.create_sheet(crs_one.NOT_A_COMMENT_SHEET)
        ws2.append(["Field or item", "What it is", "Points"])
        for k in aside_points:
            ws2.append(["f", "k", k])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_the_page_accounting_counts_the_fields_that_are_not_comments():
    pts = [
        {"id": "1", "name": "Body", "rank": 5, "tile": "met"},
        {"id": "2", "name": "Fluid", "rank": 4, "tile": "questions"},
    ]
    assert crs_completeness._comment_accounting(_team_book([1], [1]), pts) == []
    assert crs_completeness._comment_accounting(
        _team_book([1], None), pts
    )  # the sheet is missing: refused
    assert crs_completeness._comment_accounting(
        _team_book([1], []), pts
    )  # a field with no finding left out: refused


def test_a_proven_fail_reaches_the_contractor_copy_even_when_its_field_disagrees():
    """The contractor copy chooses its lines one by one, then groups them: a proven Fail is never hidden behind its field's other lines,
    and no AI word reaches the contractor."""
    fail = mk(
        "R-1",
        "Fail",
        "Fail",
        field="Set pressure",
        reason_code=None,
        compare={"decided": True, "verdict": "does_not_meet"},
    )
    met = mk(
        "R-2",
        "Query",
        "Pass",
        field="Set pressure",
        why="no second opinion",
        reason_code=None,
    )
    ask = mk("R-3", field="Set pressure")
    internal = _view([fail, met, ask])
    assert len(internal["rows"]) == 1 and "disagree" in internal["rows"][0][3]
    contractor = WB.layout_view([fail, met, ask], META, "contractor")
    assert len(contractor["rows"]) == 1 and "Set pressure" in contractor["rows"][0][2]
    text = " ".join(str(c) for r in contractor["rows"] for c in r)
    assert "AI" not in text and "disagree" not in text
    assert len(WB.contractor_rows([fail, met, ask])) == 1


def test_near_same_fields_are_one_comment_but_a_short_word_and_two_candidates_never_merge():
    def pt(i, field, clause=None):
        return {
            "id": i,
            "name": field,
            "rank": 4,
            "tile": "questions",
            "rule_book": "STD-1" if clause else None,
            "clause": clause,
        }

    got = crs_comments.group([pt("1", "Compressibility", "5.6"), pt("2", "Compressibility factor", "5.6"), pt("3", "Required capacity"),
                              pt("4", "Required relieving capacity"), pt("5", "Gas"), pt("6", "Gas (H2 and CO2 content)"),
                              pt("7", "Inlet size"), pt("8", "Outlet size")])  # fmt: skip
    assert sorted(c["n_points"] for c in got) == [
        1,
        1,
        1,
        1,
        2,
        2,
    ]  # a one-word name joins only on a shared book and clause
    two = crs_comments.group(
        [
            pt("1", "Design pressure"),
            pt("2", "Design pressure margin"),
            pt("3", "Design pressure test"),
        ]
    )
    assert [c["n_points"] for c in two] == [
        1,
        1,
        1,
    ]  # "Design pressure" has two longer candidates: it stays alone, never guessed


def test_a_checklist_line_gets_its_own_held_book_on_the_page():
    from app import review_points as rp

    line = mk(
        "S-1",
        "Query",
        ai="Fail",
        item={"source": "skill", "item_id": "S-1"},
        standard_document_id="doc-book",
        why="x",
    )
    ctx = {"run_id": "r", "paper_document_id": "p", "book_of": {}, "readable": frozenset({"doc-book"}), "library": [],
           "everything": True, "documents": frozenset({"doc-book"})}  # fmt: skip
    assert rp.ai_point(dict(line), ctx)["rule_book"] == "STD-1"
    assert (
        rp.ai_point(dict(line), {**ctx, "documents": frozenset()})["rule_book"] is None
    )  # a book that is not held is never named


def test_a_rule_whose_book_is_not_held_is_a_book_missing_question_with_no_rule_words():
    from app import review_points as rp

    ctx = {
        "run_id": "r",
        "paper_document_id": "p",
        "readable": frozenset({"p"}),
        "_library": [],
    }
    row = {"row_kind": "clause_review", "finding_id": "f1", "page_section": "p.2 - Seal plan", "comment": "Plan 52 is required.",
           "standard_reference": "BOOK-77", "priority": "High"}  # fmt: skip
    finding = {"standard_document_id": None, "standard_clause": "8.5", "requirement_source_text": "Plan 52 shall be used.",
               "requirement": "Plan 52 shall be used.", "reason_code": "NON_COMPLIANT"}  # fmt: skip
    p = rp.rule_point(row, ctx, finding, {}, proof=(True, True))
    assert (
        p["rank"] == 4
        and p["clause"] is None
        and p["rule_text"] is None
        and p["clause_quote"] is None
    )
    # order 14 lane C (C1): the clause the finding names (8.5) is said with the missing book; it was dropped before
    assert (
        p["action"].startswith("Book missing: BOOK-77, clause 8.5.")
        and p["reason_words"] == "Book missing: BOOK-77, clause 8.5"
    )
    held = rp.rule_point(
        row,
        {**ctx, "_library": [{"document_number": "BOOK-77", "id": "d1"}]},
        finding,
        {},
        proof=(True, True),
    )
    assert held["clause"] == "8.5"  # a held book: unchanged
    hidden = rp.rule_point(row, ctx, finding, {}, proof=(False, False))
    assert "BOOK-77" not in str(
        hidden["action"]
    )  # a viewer for whom the reference is hidden never gets the name (rule 5)


def test_a_value_left_to_the_vendor_reads_vendor_to_provide_with_the_mark_and_page():
    star = mk(
        "R-1",
        "Query",
        reason_code="value_deferred",
        paper_quote="Seal plan *",
        deferred_page=3,
        field="Seal plan",
    )
    one = WB.layout_comment(star, *WB.status_of(star)).split("\n")[0]
    assert one.startswith(
        "Vendor to provide Seal plan (marked * on page 3); STD-1 clause 4.1 requires:"
    )
    words_mark = mk(
        "R-2",
        "Query",
        reason_code="value_deferred",
        paper_quote="By Contractor",
        field="Set pressure",
    )
    assert WB.layout_comment(words_mark, *WB.status_of(words_mark)).startswith(
        'Vendor to provide Set pressure (marked "By Contractor" on page 2)'
    )


def test_an_ai_draft_check_says_compared_only_when_code_compared():
    base = {
        "ai_draft": True,
        "why": "AI draft, engineer to confirm: The numbers read: 4 % against at most 3 %.",
    }
    compared = {**base, "compare": {"code_said": "NON_COMPLIANT"}}
    assert words.ai_draft_words(compared) == (
        "AI draft, engineer to confirm: code compared the stated value with a limit that is an AI draft; The numbers read: 4 % against at most 3 %."
    )
    missing = {
        **base,
        "why": "AI draft, engineer to confirm: the value is not given",
        "compare": {"code_said": "MISSING_INFORMATION"},
    }
    assert (
        words.ai_draft_words(missing)
        == "AI draft, engineer to confirm: the value is not given."
    )
    assert words.ai_draft_words({"why": "x"}) == ""
    line = mk("C-1", "Query", **compared, reason_code="not_decided")
    cell = WB.layout_comment(line, *WB.status_of(line))
    assert "code compared the stated value" in cell and cell.endswith(
        "Engineer to confirm the AI-draft limit of STD-1 clause 4.1, then the comparison."
    )


def test_the_general_review_file_holds_one_comment_per_topic(tmp_path):
    from app import agent_general_crs
    from app import agent_general_review as core

    def query(i, topic):
        return core.finalize_line({"part": 2, "verdict_class": core.CLASS_QUERY, "subkind": core.SUB_CHECKLIST, "line_id": f"q{i}",
                                   "document": "p.pdf", "topic": topic, "text": f"checklist: {topic}: not found in the paper"})  # fmt: skip

    lines = [
        query(1, "owner of each action"),
        query(2, "Owner of each action"),
        query(3, "test interval"),
    ]
    agent_general_crs.write_all(
        lines, tmp_path, {"paper": "p.pdf", "run_id": "r", "date": "d"}, [], {}
    )
    wb = openpyxl.load_workbook(tmp_path / "crs-internal.xlsx")
    rows = [[c.value for c in r] for r in wb["CRS"].iter_rows()]
    head = next(i for i, r in enumerate(rows) if r[0] == "Item No")
    assert len([r for r in rows[head + 1 :] if r[0] is not None]) == 2
    other = [[c.value for c in r] for r in wb[words.OTHER_SHEET].iter_rows()]
    assert any(r[4] == "Part of comment 1" for r in other)
    ev = [[c.value for c in r] for r in wb["Evidence"].iter_rows()]
    assert (
        len(
            [
                r
                for r in ev[
                    next(i for i, r in enumerate(ev) if r[0] == "Item No") + 1 :
                ]
                if r[0] is not None
            ]
        )
        == 3
    )  # every line kept


def test_contract_check_results_list_what_to_look_at_and_count_the_consistent_ones():
    from types import SimpleNamespace as NS

    q = [
        NS(page=4, text="Stage 1: 30 %", verified=True),
        NS(page=5, text="not on the page", verified=False),
    ]
    results = [NS(ct="CT-01", topic="payment stages", outcome="inconsistent", value="90 %", message="Stages add to 90 %, not 100 %.", quotes=q),
               NS(ct="CT-02", topic="attachments", outcome="consistent", value="5 of 5", message="", quotes=[]),
               NS(ct="CT-03", topic="guarantee names", outcome="engineer to check", value="2 names", message="Two names.", quotes=[])]  # fmt: skip
    rows, consistent = crs_one.contract_rows(results)
    assert consistent == 1 and [r[1] for r in rows] == ["CT-01", "CT-03"]
    assert (
        rows[0][6] == '"Stage 1: 30 %" (page 4)'
        and rows[0][7] == crs_one.CONTRACT_CLASS
    )  # only the verified quote


def test_two_near_same_candidates_join_the_one_that_shares_a_book_clause():
    def pt(i, field, clause):
        return {
            "id": i,
            "name": field,
            "rank": 4,
            "tile": "questions",
            "rule_book": "STD-1",
            "clause": clause,
        }

    got = crs_comments.group(
        [
            pt("1", "Design pressure", "8"),
            pt("2", "Design pressure margin", "8"),
            pt("3", "Design pressure test", "9"),
        ]
    )
    assert sorted(c["n_points"] for c in got) == [1, 2]


def test_each_cited_book_says_what_the_edition_cutoff_says_of_it():
    binds = {
        "status": "held edition binds",
        "held": "2019",
        "binding": "2019",
        "caveat": "",
    }
    later = {
        "status": "held edition is later than the cutoff: for information only",
        "held": "2023",
        "binding": "2016",
    }
    assert words.edition_words(binds) == "edition: binds"
    assert (
        words.edition_words(later)
        == "edition: later, for information only (the edition that binds: 2016)"
    )
    assert (
        words.edition_words(None)
        == words.edition_words({"status": "a new word"})
        == "edition: not known"
    )
    view = WB.layout_view(
        [mk("R-1", field="Set pressure")],
        {**META, "editions": {"STD-1": binds}},
        "internal",
    )
    assert (
        dict(view["header"])["Rule books used (reviewed lines):"]
        == "STD-1 (edition: binds)"
    )
    pts = [
        {"books": [{"name": "STD-1"}]},
        {"books": [{"name": "STD-1"}, {"name": "STD-2"}]},
    ]
    assert (
        crs_one._books_line(pts, {"STD-1": binds})
        == "STD-1 (2; edition: binds); STD-2 (1; edition: not known)"
    )
    assert crs_one._books_line(pts) == "STD-1 (2); STD-2 (1)"


def test_the_wrong_merges_r91_found_stay_apart():
    """R91 (pump C22, valve C36, valve C15): different things that only look alike are never one comment."""

    def pt(i, field, clause=None):
        return {
            "id": i,
            "name": field,
            "rank": 4,
            "tile": "questions",
            "rule_book": "STD-1" if clause else None,
            "clause": clause,
        }

    impeller = crs_comments.group(
        [pt("1", "Impeller", "4.13.4"), pt("2", "Impeller material")]
    )
    assert [c["n_points"] for c in impeller] == [
        1,
        1,
    ]  # a one-word name with no shared evidence
    pressures = crs_comments.group(
        [
            pt("1", "Design pressure"),
            pt("2", "Operating pressure"),
            pt("3", "Design/Operating pressure"),
        ]
    )
    assert [c["n_points"] for c in pressures] == [
        1,
        1,
        1,
    ]  # the paper's combined label of two values joins nothing
    back = crs_comments.group([pt("1", "Back press. Constant"), pt("2", "Back press. Variable"),
                               pt("3", "Valve type / Back press. Constant/Variable")])  # fmt: skip
    assert [c["n_points"] for c in back] == [1, 1, 1]


def test_the_ai_draft_words_appear_once_and_the_detail_comes_from_compare_reason():
    line = {"ai_draft": True, "why": "AI draft, engineer to confirm: Inlet drop was not read as a value",
            "compare": {"code_said": "MISSING_INFORMATION", "reason": "Inlet drop was not read as a value"}}  # fmt: skip
    got = words.ai_draft_words(line)
    assert (
        got == "AI draft, engineer to confirm: Inlet drop was not read as a value."
        and got.count(words.AI_DRAFT) == 1
    )
    cell = WB.layout_comment(
        mk("C-2", "Query", reason_code="not_decided", **line), "Query", 3
    )
    assert cell.count(words.AI_DRAFT) == 1


def _reread_db(monkeypatch):
    import sqlite3

    from app import db

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE standard_requirements (id TEXT, standard_document_id TEXT, clause TEXT, requirement_text TEXT, source_text TEXT,"
        " superseded_at TEXT, chunk_id TEXT); CREATE TABLE chunks (id TEXT, section TEXT);"
    )
    rows = [
        (
            "old1",
            "bk",
            "2.5",
            "Nozzles shall be X.",
            "Nozzles shall be X.",
            "t",
            None,
        ),  # false label, superseded
        (
            "new1",
            "bk",
            "UG-17",
            "Nozzles shall be X.",
            "Nozzles shall be X.",
            None,
            None,
        ),  # its successor: identical text
        (
            "old2",
            "bk",
            "7.16",
            "UG-49 BOLTS Bolts shall be Y.",
            "UG-49 BOLTS Bolts shall be Y.",
            "t",
            None,
        ),  # read the heading as text
        (
            "new2",
            "bk",
            "UG-49",
            "Bolts shall be Y.",
            "Bolts shall be Y.",
            None,
            "c2",
        ),  # successor once its heading is put back
        ("old3", "bk", "2.5", "Lost text.", "Lost text.", "t", None),  # no successor
        (
            "cur",
            "bk",
            "UG-20",
            "Current text.",
            "Current text.",
            None,
            None,
        ),  # not superseded: untouched
    ]
    conn.executemany("INSERT INTO standard_requirements VALUES (?,?,?,?,?,?,?)", rows)
    conn.execute("INSERT INTO chunks VALUES ('c2', 'UG-49 BOLTS')")
    monkeypatch.setattr(db, "connect", lambda: conn)
    return conn


def test_a_superseded_requirement_shows_its_successors_clause_never_the_old_false_one(
    monkeypatch,
):
    from app import paragraph_ids
    from app import review_points as rp

    _reread_db(monkeypatch)
    fs = [
        {"requirement_id": i, "standard_clause": c}
        for i, c in (
            ("old1", "2.5"),
            ("old2", "7.16"),
            ("old3", "2.5"),
            ("cur", "UG-20"),
        )
    ]
    rp.reread_clauses(fs)
    cited = [paragraph_ids.cited(f) for f in fs]
    assert cited == [
        " cl. UG-17 (clause re-read)",
        " cl. UG-49 (clause re-read)",
        "",
        " cl. UG-20",
    ]
    assert [f["standard_clause"] for f in fs] == [
        "2.5",
        "7.16",
        "2.5",
        "UG-20",
    ]  # the stored clause (decision keys) is untouched


def test_the_rule_checks_crs_rows_pass_through_the_re_read(monkeypatch):
    """The rule check's CRS rows (`crs_mapping.build_crs_rows`) never print a superseded clause: they run the re-read first."""
    from app import crs_mapping
    from app import review_points as rp

    seen = []
    monkeypatch.setattr(
        rp, "reread_clauses", lambda findings, cache=None: seen.append(list(findings))
    )
    crs_mapping.build_crs_rows([], [], "paper.pdf")
    assert seen == [[]]


def test_a_cut_off_second_reader_is_said_as_such_never_as_unconfirmed():
    from app import agent_review_wording as wording

    assert (
        words.why_phrase(words.CUT_OFF_WHY)
        == "the second AI reader's answer was cut off, so the two readers did not agree"
    )
    assert words.why_phrase(words.CUT_OFF_WHY) != words.UNKNOWN_WHY
    assert (
        getattr(wording, "CUT_OFF_WHY", words.CUT_OFF_WHY) == words.CUT_OFF_WHY
    )  # lane D's constant, once merged, is the same text


def test_a_comment_is_named_by_the_fixed_field_list_never_by_what_the_ai_quoted(
    monkeypatch,
):
    """Lead's decision after R94: a comment's name is DETERMINISTIC: the item's field role as the equipment's fixed field list names it,
    a checklist topic mapped to the one field it names, a rule-check label mapped to its field; never the label the AI quoted."""
    role = {"tier": "AI approved", "field": "set_pressure"}
    run1 = mk(
        "R-1",
        field="Max. inlet pr. at design temp",
        field_label_ai="Max. inlet pr.",
        rule_label=role,
    )
    run2 = mk("R-1", field="Required relieving capacity", rule_label=role)
    assert WB.field_name(run1) == WB.field_name(run2) == "Set pressure"
    assert (
        WB.field_name(
            mk(
                "R-2",
                field="Fluid",
                field_label_ai="Fluid",
                rule_label={"tier": "AI approved"},
            )
        )
        == ""
    )  # no role: never the AI's quoted label
    monkeypatch.setattr(
        WB,
        "_skill_item",
        lambda _i: {"topic": "PSV orifice designation and size", "expected": "x"},
    )
    assert (
        WB.field_name(mk("S-1", item={"source": "skill", "item_id": "S-1"}))
        == "Orifice designation"
    )
    monkeypatch.setattr(
        WB,
        "_skill_item",
        lambda _i: {"topic": "PSV inlet and outlet size and rating", "expected": "x"},
    )
    assert (
        WB.field_name(mk("S-1", item={"source": "skill", "item_id": "S-1"}))
        == "PSV inlet and outlet size and rating"
    )  # several fields
    assert (
        crs_comments.label_name("Compressibility factor")
        == crs_comments.label_name("Compressibility")
        == "Compressibility"
    )
    assert (
        crs_comments.label_name("Code symbol stamping") == "Code symbol stamping"
    )  # not on the list: the label itself


def test_two_proven_fails_on_one_field_keep_their_own_requirement_and_action_everywhere():
    """R91: a second proven Fail on a field is never folded away: the contractor copy has one row per proven Fail, each with its own
    requirement and action; the internal comment says the other Fail's status and ask."""
    a = mk(
        "R-1",
        "Fail",
        "Fail",
        field="Nozzle rating",
        clause="4.1",
        reason_code=None,
        compare={"decided": True, "verdict": "does_not_meet"},
    )
    b = mk("R-2", "Fail", "Fail", field="Nozzle rating", clause="9.9", standard="STD-2", clause_quote="Ratings shall be class 300",
           reason_code=None, compare={"decided": True, "verdict": "does_not_meet"})  # fmt: skip
    contractor = WB.layout_view([a, b], META, "contractor")
    assert len(contractor["rows"]) == 2 and len(WB.contractor_rows([a, b])) == 2
    cells = " ".join(r[3] for r in contractor["rows"])
    assert (
        "STD-2 clause 9.9 requires" in cells
        and "Contractor to revise Nozzle rating to meet STD-2 clause 9.9" in cells
    )
    internal = _view([a, b])["rows"][0][3]
    assert (
        "Also on this field, not met (proven by code) under STD-2 clause 9.9 (page 2): Contractor to revise Nozzle rating"
        in internal
    )


def test_the_general_review_joins_exact_topics_only(tmp_path):
    from app import agent_general_crs
    from app import agent_general_review as core

    def query(i, topic):
        return core.finalize_line({"part": 2, "verdict_class": core.CLASS_QUERY, "subkind": core.SUB_CHECKLIST, "line_id": f"q{i}",
                                   "document": "p.pdf", "topic": topic, "text": f"checklist: {topic}: not found in the paper"})  # fmt: skip

    agent_general_crs.write_all(
        [query(1, "Liquidated damages"), query(2, "Liquidated damages cap")],
        tmp_path,
        {"paper": "p.pdf", "run_id": "r", "date": "d"},
        [],
        {},
    )
    rows = [
        [c.value for c in r]
        for r in openpyxl.load_workbook(tmp_path / "crs-internal.xlsx")[
            "CRS"
        ].iter_rows()
    ]
    head = next(i for i, r in enumerate(rows) if r[0] == "Item No")
    assert (
        len([r for r in rows[head + 1 :] if r[0] is not None]) == 2
    )  # "X" and "X cap" are two findings


def test_our_checklist_wording_is_never_the_rules_text_on_the_page():
    from app import review_points as rp

    assert rp.is_check_text({"origin": "datasheet_check"})
    assert rp.is_check_text(
        {
            "requirement_source_text": "Datasheet check PSV-07: The back pressure is stated."
        }
    )
    assert not rp.is_check_text(
        {"requirement_source_text": "The back pressure shall be stated on the sheet."}
    )
    said = crs_one.rule_requires(
        {"check_text": "Datasheet check PSV-07: The back pressure is stated."}
    )
    assert (
        said
        == 'Our checklist asks (our words, not the book\'s): "Datasheet check PSV-07: The back pressure is stated."'
    )


def test_an_older_run_file_missing_a_line_is_refused(monkeypatch):
    """The older stored file of a run is refused when its Evidence sheet holds fewer rows than the run has lines (`older_report`)."""
    import sqlite3

    from app import db

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE agent_review_line (run_id TEXT, item_id TEXT, line_json TEXT); CREATE TABLE agent_review_general (run_id TEXT);"
        # order 14: the count reads the lines as the file does, with the run's books not held (`stored_lines`)
        "CREATE TABLE agent_review_missing_book (run_id TEXT, name TEXT, why TEXT);"
    )
    lines = [mk("R-1", field="A"), mk("R-2", field="B")]
    conn.executemany(
        "INSERT INTO agent_review_line VALUES ('run', ?, ?)",
        [(ln["item_id"], json.dumps(ln)) for ln in lines],
    )
    monkeypatch.setattr(crs_completeness, "connect", lambda: conn)
    monkeypatch.setattr(db, "connect", lambda: conn)
    data = crs_layout.build_layout_crs(WB.layout_view(lines, META, "internal"))
    assert crs_completeness.older_report("run", "internal", data)["ok"]
    conn.execute(
        "INSERT INTO agent_review_line VALUES ('run', 'R-3', ?)",
        (json.dumps(mk("R-3", field="C")),),
    )
    got = crs_completeness.older_report("run", "internal", data)
    assert not got["ok"] and got["expected"] == 3


def test_an_older_run_file_with_a_comment_row_dropped_is_refused(monkeypatch):
    """R91 section 1: the older run file's sheets CRS and Not a comment must hold every line too, not only its Evidence sheet."""
    import sqlite3

    from app import db

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE agent_review_line (run_id TEXT, item_id TEXT, line_json TEXT); CREATE TABLE agent_review_general (run_id TEXT);"
        # order 14: the count reads the lines as the file does, with the run's books not held (`stored_lines`)
        "CREATE TABLE agent_review_missing_book (run_id TEXT, name TEXT, why TEXT);"
    )
    lines = [mk("R-1", field="A"), mk("R-2", field="B")]
    conn.executemany(
        "INSERT INTO agent_review_line VALUES ('run', ?, ?)",
        [(ln["item_id"], json.dumps(ln)) for ln in lines],
    )
    monkeypatch.setattr(crs_completeness, "connect", lambda: conn)
    monkeypatch.setattr(db, "connect", lambda: conn)
    view = WB.layout_view(lines, META, "internal")
    assert crs_completeness.older_report(
        "run", "internal", crs_layout.build_layout_crs(view)
    )["ok"]
    view["rows"] = view["rows"][:1]
    view["statuses"] = view["statuses"][:1]
    assert not crs_completeness.older_report(
        "run", "internal", crs_layout.build_layout_crs(view)
    )["ok"]


def test_a_met_on_one_rule_and_a_not_met_on_another_is_no_disagreement():
    """R94 (Body material: SAES-J-600 9.7.5 not met, 6.1.1 met): different rules on one field keep the strongest status; only two
    answers to the SAME rule are "the readers disagree"."""

    def pt(i, rank, tile, clause):
        return {
            "id": i,
            "name": "Body material",
            "rank": rank,
            "tile": tile,
            "rule_book": "SAES-J-600",
            "clause": clause,
            "rule_text": "the requirement",
        }

    got = crs_comments.group(
        [pt("1", 3, "not_met", "9.7.5"), pt("2", 6, "met", "6.1.1")]
    )[0]
    assert not got["disagree"] and got["rank"] == 3 and "disagree" not in got["pill"]
    same = crs_comments.group(
        [pt("1", 3, "not_met", "6.1.1"), pt("2", 6, "met", "6.1.1")]
    )[0]
    assert same["disagree"] and same["rank"] == 4


def test_a_met_the_pass_guard_objected_to_is_never_nothing_to_change_and_its_objection_is_said():
    """R94: an AI "met" the pass guard objected to is never "Checked, nothing to change": the engineer ticks it and the objection is
    said; a question whose reason is such an objection is never ticked, it stays a comment."""
    held = mk(
        "R-9",
        "Query",
        ai="Pass",
        field="Seal",
        reason_code="pass_field_unknown",
        why="no second opinion",
    )
    st, order = WB.status_of(held)
    assert st == words.STATUS_QUERY  # order 14 (G6): a guarded AI "met" is a question in every run, worded for the engineer (R94)
    assert (
        f"Engineer to check the AI reviewer's view: {words.guard_words(held)}."
        in WB.layout_comment(held, st, order)
    )
    query = mk("S-1", "Query", ai="Pass", item={"source": "skill", "item_id": "S-1"}, field="Body", reason_code="pass_field_not_quoted",
               quotes_checked={"paper": True, "clause": False})  # fmt: skip
    assert not crs_comments.tick_only({"_line": query})
    assert (
        words.guard_words(query)
        == "the field's words are not on the quoted line or the line above it"
    )


def test_a_label_only_met_with_an_unverified_clause_stays_a_comment():
    """R94 H7: the guard names the clause doubt before the label-only one, so the label-only check is needed on its own."""
    line = mk("R-1", "Query", ai="Pass", reason_code="met", field="Body material", paper_quote="Body material",
              quotes_checked={"paper": True, "clause": False})  # fmt: skip
    assert not crs_comments.tick_only({"_line": line})


def test_a_rule_check_point_with_our_checklist_text_carries_check_text_not_rule_text():
    """R94 H11b: the USE of is_check_text in rule_point."""
    from app import review_points as rp

    row = {"row_kind": "clause_review", "finding_id": "f1", "page_section": "p.2 - Back pressure", "comment": "Engineer to check.",
           "standard_reference": "BOOK-1"}  # fmt: skip
    finding = {
        "standard_document_id": "d1",
        "origin": "datasheet_check",
        "requirement_source_text": "Datasheet check PSV-07: Back pressure stated.",
    }
    p = rp.rule_point(
        row,
        {"run_id": "r", "paper_document_id": "p", "readable": frozenset({"p", "d1"})},
        finding,
        {},
        proof=(True, True),
    )
    assert (
        p["rule_text"] is None
        and p["check_text"] == "Datasheet check PSV-07: Back pressure stated."
    )


def test_the_page_comment_lists_each_other_point_with_its_class_and_action():
    """R94 H16: the page CRS Note column lists every other point of a comment."""
    a = {
        "id": "a",
        "name": "Set pressure",
        "rank": 3,
        "tile": "not_met",
        "pill": "Not met · one reader",
        "rule_book": "STD-1",
        "clause": "8",
        "action": "Contractor to correct the set pressure.",
        "decision": {},
        "tags": [],
        "page": 1,
    }
    b = {
        **a,
        "id": "b",
        "rank": 4,
        "tile": "questions",
        "pill": "Question",
        "clause": "9",
        "action": "Contractor to confirm the margin.",
    }
    c = crs_comments.group([a, b])[0]
    cells, _cut = crs_one.comment_cells(c, {"a": a, "b": b})
    note = cells[crs_one.COMMENT_COLUMNS.index("Note")]
    assert (
        "Also: Question, Set pressure (STD-1 9): Contractor to confirm the margin."
        in note
    )


def test_an_older_run_file_missing_a_whole_sheet_is_refused(monkeypatch):
    """R94: the Evidence layout always has the sheets CRS and Not a comment; a file without one is refused, never skipped."""
    import sqlite3

    from app import db

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE agent_review_line (run_id TEXT, item_id TEXT, line_json TEXT); CREATE TABLE agent_review_general (run_id TEXT);"
        # order 14: the count reads the lines as the file does, with the run's books not held (`stored_lines`)
        "CREATE TABLE agent_review_missing_book (run_id TEXT, name TEXT, why TEXT);"
    )
    lines = [mk("R-1", field="A"), mk("R-2", field="B")]
    conn.executemany(
        "INSERT INTO agent_review_line VALUES ('run', ?, ?)",
        [(ln["item_id"], json.dumps(ln)) for ln in lines],
    )
    monkeypatch.setattr(crs_completeness, "connect", lambda: conn)
    monkeypatch.setattr(db, "connect", lambda: conn)
    wb = openpyxl.load_workbook(
        io.BytesIO(crs_layout.build_layout_crs(WB.layout_view(lines, META, "internal")))
    )
    del wb[words.NOT_A_COMMENT_SHEET]
    buf = io.BytesIO()
    wb.save(buf)
    assert not crs_completeness.older_report("run", "internal", buf.getvalue())["ok"]


def test_rule_check_labels_of_one_listed_field_are_one_comment():
    """Two spellings of one field on the equipment's fixed field list ("Compressibility", "Compressibility factor") are one comment, even
    with no shared clause; a label the list does not know keeps its own name."""

    def pt(i, name):
        return {"id": i, "name": name, "rank": 4, "tile": "questions"}

    got = crs_comments.group(
        [
            pt("1", "Compressibility"),
            pt("2", "Compressibility factor"),
            pt("3", "Code symbol stamping"),
        ]
    )
    assert sorted(c["n_points"] for c in got) == [1, 2]


def test_the_words_name_the_paper_field_when_the_item_names_none_but_never_the_ais_unverified_label():
    """The comment's KEY is deterministic (`field_name`); its WORDS may say the field as the paper prints it when code verified that
    label, so a line with no role still reads "Contractor to confirm Gasket ...", never "the item"; the AI's unverified label never."""
    verified = mk("R-1", field="Gasket", rule_label={"tier": "AI approved"})
    assert WB.field_name(verified) == "" and WB.field_words(verified) == "Gasket"
    assert "Contractor to confirm Gasket against STD-1 clause 4.1" in WB.layout_comment(
        verified, *WB.status_of(verified)
    )
    unverified = mk(
        "R-2", field=None, field_label_ai="Gasket", rule_label={"tier": "AI approved"}
    )
    assert WB.field_words(unverified) == ""


def test_a_cut_off_second_reader_never_reads_the_readers_disagree():
    """R98 (rule 8, every home): a line whose reason is the cut-off second reader says so in its action, its reason and its Evidence
    row, never "the readers disagree" / "disagreed"."""
    from app import agent_review_crs as C
    from app import crs_ai_actions as actions

    line = mk("R-1", "Query", ai="Pass", field="Seal plan", not_proven_reason=words.CUT_OFF_WHY,
              second_opinion={"agree": None, "reason": "stop_max_tokens"}, reason_code="met")  # fmt: skip
    line = {**line, "not_proven_reason": words.CUT_OFF_WHY}
    assert actions.action_case(line) == "cut_off"
    said = actions.query_action(line, "Seal plan", "STD-1 clause 4.1")
    assert (
        said
        == "Engineer to check Seal plan: the second AI reader's answer was cut off, so the two readers did not agree."
    )
    assert "disagree" not in said
    assert words.why_phrase(line["not_proven_reason"]) == words.CUT_OFF_WHY
    assert C._second_reader(line) == "asked: answer cut off"


def test_a_deferred_value_is_worded_as_the_sheet_shows_it():
    """Lane D (valve S-EQ-02 "315 psig By Contractor"): a figure beside the deferral mark is a provisional value to CONFIRM; a lone star
    or words only is a value to PROVIDE; the mark and the page are said either way."""
    from app import crs_ai_actions as actions

    figure = mk(
        "R-1",
        "Query",
        reason_code="value_deferred",
        paper_quote="315 psig (By Contractor, as per Code)",
        paper_page=1,
    )
    assert actions.provisional(figure)
    assert actions.query_action(figure, "Set pressure", "STD-1 clause 4.1") == (
        'Contractor to confirm the provisional value of Set pressure (marked "315 psig (By Contractor, as per Code)" on page 1) '
        "against STD-1 clause 4.1."
    )
    assert WB.layout_comment(figure, *WB.status_of(figure)).startswith(
        "Contractor to confirm the provisional value of Set pressure"
    )
    star = mk(
        "R-2",
        "Query",
        reason_code="value_deferred",
        paper_quote="Rated curve BEP flow *",
        deferred_page=2,
    )
    assert not actions.provisional(star)
    assert (
        actions.query_action(star, "Rated flow", "")
        == "Contractor to provide Rated flow (marked * on page 2); it is deferred on the sheet."
    )
    note = mk(
        "R-3",
        "Query",
        reason_code="value_deferred",
        paper_quote="By Contractor / Vendor (Note-2, 4)",
    )
    assert not actions.provisional(note)  # a note's number is no value


# ------------------------------------------------------------------------------------------------ R101 round 4


def test_two_requirements_of_one_clause_are_two_comments_and_never_a_disagreement():
    """R101 F1 (pump, one clause holding a drain connection and a material): points with no field join only on the same book, clause
    AND requirement; a met and a not-met of two requirements of one clause stay apart and keep their own status, never "disagree"."""

    def pt(i, rank, tile, req):
        return {
            "id": i,
            "rank": rank,
            "tile": tile,
            "name": None,
            "rule_book": "STD-1",
            "clause": "4.8",
            "rule_text": req,
        }

    apart = crs_comments.group([pt("1", 6, "not_met", "a drain connection"), pt("2", 5, "met", "a non-sparking material")],
                               findings_only=False)  # fmt: skip
    assert [c["n_points"] for c in apart] == [1, 1] and not any(
        c["disagree"] for c in apart
    )
    by_member = {tuple(c["member_ids"]): c["rank"] for c in apart}
    assert by_member == {
        ("1",): 6,
        ("2",): 5,
    }  # each keeps its own status; the not-met is never lowered to a question
    same = crs_comments.group([pt("1", 6, "not_met", "a drain connection"), pt("2", 5, "met", "A drain  connection.")],
                              findings_only=False)  # fmt: skip
    assert [c["n_points"] for c in same] == [2] and same[0]["disagree"]
    nothing = crs_comments.group(
        [pt("1", 6, "not_met", ""), pt("2", 6, "not_met", "")], findings_only=False
    )
    assert [c["n_points"] for c in nothing] == [
        1,
        1,
    ]  # no requirement text: each point stands alone


def test_a_field_with_two_requirements_of_one_clause_is_no_disagreement():
    """R101 F1: "the readers disagree" needs the same rule: the same item, or the same book, clause AND requirement."""

    def pt(i, rank, tile, req):
        return {
            "id": i,
            "rank": rank,
            "tile": tile,
            "name": "Coupling guard",
            "rule_book": "STD-1",
            "clause": "4.8",
            "rule_text": req,
        }

    got = crs_comments.group(
        [pt("1", 3, "not_met", "a window"), pt("2", 5, "met", "a material")],
        findings_only=False,
    )[0]
    assert not got["disagree"] and got["rank"] == 3


def test_a_comment_joined_by_its_requirement_never_says_on_this_field():
    """R101 F1: the run file's also-line of a comment keyed by book, clause and requirement says "on this requirement"."""
    a = mk("R-1", "Query", ai="Fail", field=None, reason_code="not_met")
    b = mk("R-2", "Query", ai="Fail", field=None, reason_code="not_met", paper_page=3)
    rows, _ = crs_comments.group_lines([(ln, *WB.status_of(ln)) for ln in (a, b)])
    assert len(rows) == 1
    said = crs_comments.also_words(rows[0][0])
    assert (
        said
        and said[0].startswith("Also on this requirement,")
        and not any("on this field" in s for s in said)
    )


def test_cut_off_is_read_from_the_second_opinions_own_marker_never_the_reason_text():
    """R101 F2: a cut-off second reader is known by its own marker (no agree, reason "stop_max_tokens"; or a retry with no true/false
    answer), whatever reason an earlier step wrote; a second reader that gave no usable answer for another reason is never "disagreed"."""
    from app import agent_review_crs as C
    from app import crs_ai_actions as actions

    cut = mk("R-1", "Query", ai="Pass", field="Seal type", reason_code="met", second_opinion={"agree": None, "reason": "stop_max_tokens"},
             not_proven_reason="the AI reviewer was silent")  # fmt: skip
    assert actions.second_cut_off(cut) and actions.action_case(cut) == "cut_off"
    assert C._second_reader(cut) == "asked: answer cut off"
    retried = {
        **cut,
        "second_opinion": {"agree": None, "reason": "no_json", "retried": True},
    }
    assert actions.second_cut_off(retried)
    failed = {**cut, "second_opinion": {"agree": None, "reason": "no_json"}}
    assert (
        not actions.second_cut_off(failed) and actions.action_case(failed) != "cut_off"
    )
    assert C._second_reader(failed) == "asked: no usable answer"
    assert (
        C._second_reader({**cut, "second_opinion": {"agree": False}})
        == "asked: disagreed"
    )
    odd = {**cut, "second_opinion": {"agree": "yes", "reason": "stop_max_tokens"}}
    assert not actions.second_cut_off(
        odd
    )  # only an answer that is NO answer (agree None) was cut off, as lane A's rule
    text_only = {
        **cut,
        "second_opinion": {"agree": False},
        "not_proven_reason": words.CUT_OFF_WHY,
    }
    assert not actions.second_cut_off(text_only)


def test_the_cut_off_rule_equals_lane_as_when_it_is_merged():
    """R101 F2: the writer's cut-off rule is lane A's `agent_review_two_reader.second_cut_off` on every shape of second opinion."""
    import importlib

    from app import crs_ai_actions as actions

    two = importlib.import_module("app.agent_review_two_reader")
    if not hasattr(two, "second_cut_off"):
        import pytest

        pytest.skip("lane A's second_cut_off is not on this branch yet")
    shapes = [None, {}, {"agree": True}, {"agree": False}, {"agree": None}, {"agree": None, "reason": "stop_max_tokens"},
              {"agree": None, "reason": " stop_max_tokens "}, {"agree": "yes", "reason": "stop_max_tokens"},
              {"agree": None, "reason": "no_json"}, {"agree": None, "retried": True}, {"agree": True, "retried": True},
              {"agree": "x", "retried": True}]  # fmt: skip
    for s in shapes:
        line = {"second_opinion": s}
        assert actions.second_cut_off(line) == two.second_cut_off(line), s


def test_a_name_only_half_of_a_longer_one_joins_it_only_on_shared_evidence():
    """R101 H24 (R94): a two-word name that is exactly HALF of a four-word name joins it only when they share a paper line or a rule;
    a name more than half of the longer one joins it on the name alone."""

    def pt(i, name, **kw):
        return {"id": i, "rank": 3, "tile": "not_met", "name": name, **kw}

    half = crs_comments.group(
        [pt("1", "Rated head"), pt("2", "Max rated head impeller")], findings_only=False
    )
    assert [c["n_points"] for c in half] == [1, 1]
    shared = crs_comments.group([pt("1", "Rated head", paper_quote="x 10 m", page=2), pt("2", "Max rated head impeller", paper_quote="x 10 m", page=2)],
                                findings_only=False)  # fmt: skip
    assert [c["n_points"] for c in shared] == [2]
    more = crs_comments.group(
        [pt("1", "Rated head"), pt("2", "Rated head max")], findings_only=False
    )
    assert [c["n_points"] for c in more] == [2]


def test_a_guard_objected_ai_met_tells_the_engineer_the_objection():
    """R101 H25: the run file's action for an AI "met" the pass guard objected to says the objection; one with no objection never asks."""
    held = mk(
        "R-9",
        "Query",
        ai="Pass",
        field="Seal",
        reason_code="pass_field_unknown",
        why="no second opinion",
    )
    st, order = WB.status_of(held)
    said = WB.layout_comment(held, st, order)
    assert (
        f"Engineer to check the AI reviewer's view: {words.guard_words(held)}." in said
    )
    plain = mk(
        "R-8",
        "Query",
        ai="Pass",
        field="Seal",
        reason_code="met",
        why="no second opinion",
    )
    if WB.status_of(plain) == (st, order):
        assert "Engineer to check the AI reviewer's view" not in WB.layout_comment(
            plain, st, order
        )


def test_a_role_is_named_by_the_fixed_field_list_not_by_its_own_words():
    """R101 H28: `role_name` gives the fixed field list's name ("Rated relieving capacity"), never the role's words ("Rated capacity")."""
    listed = crs_comments._role_names()[1]
    role = next(r for r, n in listed.items() if n.lower() != r.replace("_", " "))
    assert (
        crs_comments.role_name(role)
        == listed[role]
        != role.replace("_", " ").capitalize()
    )
    assert crs_comments.role_name("not_on_any_list") == "Not on any list"
