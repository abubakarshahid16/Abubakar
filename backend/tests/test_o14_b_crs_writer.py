"""Order 14 lane B (owner, 16 Nov 2026): the shared CRS writer. Real clause quotes, no noise rows, one comment per field or topic in EVERY
CRS file (the AI run's own file too, through `crs_comments.group`), and the "N rules could not be matched" lines as ONE coverage note.
Invented data only; no model, no network."""

from __future__ import annotations

import io

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


def test_a_met_code_could_not_confirm_is_ticked_not_commented_but_an_open_value_stays():
    unverified = mk(
        "R-1",
        "Query",
        ai="Pass",
        quotes_checked={"paper": False, "clause": True},
        reason_code="met",
        field="Body",
    )
    open_value = mk(
        "R-2",
        "Query",
        ai="Pass",
        paper_quote="Set pressure TBA",
        reason_code="pass_field_unknown",
        field="Set pressure",
    )
    view = _view([unverified, open_value])
    assert [r[2] for r in view["rows"]] == ["p.2 - Set pressure"]
    other = {r[0]: r for r in view["other"]["rows"]}
    assert (
        other[2][4] == words.KIND_MET_NOT_CONFIRMED
        and "The engineer ticks it." in other[2][5]
    )


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
        "Also checked on this field: STD-2 clause 8 (page 2); STD-1 clause 9 (page 2)."
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
        pt("4", "Set pressure", 3, "not_met"), pt("5", "Set pressure", 5, "met"),
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
    def pt(i, field):
        return {"id": i, "name": field, "rank": 4, "tile": "questions"}

    got = crs_comments.group([pt("1", "Compressibility"), pt("2", "Compressibility factor"), pt("3", "Required capacity"),
                              pt("4", "Required relieving capacity"), pt("5", "Gas"), pt("6", "Gas (H2 and CO2 content)"),
                              pt("7", "Inlet size"), pt("8", "Outlet size")])  # fmt: skip
    assert sorted(c["n_points"] for c in got) == [1, 1, 1, 1, 2, 2]
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
    assert (
        p["action"].startswith("Book missing: BOOK-77.")
        and p["reason_words"] == "Book missing: BOOK-77"
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


def test_a_name_whose_candidates_are_already_one_comment_joins_it():
    def pt(i, field):
        return {"id": i, "name": field, "rank": 4, "tile": "questions"}

    got = crs_comments.group([pt("1", "Back press. Variable"), pt("2", "Back press. Constant/Variable"),
                              pt("3", "Valve type / Back press. Constant/Variable")])  # fmt: skip
    assert [c["n_points"] for c in got] == [3]


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
