"""Order 139 part 2, item 5 (spec sections e and f): every CRS row has plain
COMPANY Comments text, and the sheet is ranked - out of limit, then missing
value, then engineer to check, then the engineer's own chat comments - on
every row kind, not only the requirement rows. Invented data only.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import access, comparison
from app import crs_mapping as m
from app import main as main_mod
from app.api import run_summary
from app.main import app
from tests.test_w5_677_scope_ledger import review_run, temp_storage  # noqa: F401


def _std(**over) -> dict:
    """A requirement finding against an invented standard."""
    return {"standard_name": "STD-INV-001.pdf", "standard_clause": "4.1", "standard_page": 3,
            "requirement_source_text": "4.1 The widget rating shall be at least 5 units.",
            **over}


def _with(base: dict, over: dict) -> dict:
    return {**base, **over}


def BREACH(**over):
    return _with(_std(id="breach", compliance_status="NON_COMPLIANT", contractor_page=9, fact_id="f9",
                contractor_evidence_text="3 units", crs_field_label="WIDGET RATING"), over)


def BLANK(**over):
    return _with(_std(id="blank", compliance_status="MISSING_INFORMATION", contractor_page=5,
                fact_id="f5", contractor_evidence_text="TBA", crs_is_blank=True,
                crs_field_label="GADGET SIZE", standard_clause="4.2",
                requirement_source_text="4.2 The gadget size shall be stated."), over)


def NOT_FOUND(**over):
    return _with(_std(id="notfound", compliance_status="MISSING_INFORMATION",
                standard_clause="4.3", requirement_source_text="4.3 The sprocket count shall be stated.",
                ai_rationale="no_field_matched: none of the fields read"), over)


def QUESTION(**over):
    return _with(_std(id="question", compliance_status="NEEDS_ENGINEER_REVIEW", contractor_page=1,
                fact_id="f1", crs_field_label="LEVER LENGTH", standard_clause="4.4",
                requirement_source_text="4.4 The lever length shall suit the frame.",
                ai_rationale="unit_mismatch: the requirement has no unit"), over)


def CHECK(status: str, **over) -> dict:
    return {"id": f"check-{status}", "origin": "datasheet_check", "compliance_status": status,
            "requirement_source_text": "Datasheet check DS-M1: the rated value is stated.",
            "finding": "Datasheet check DS-M1: the invented rated value is checked.",
            "contractor_section": "Rated value", "contractor_page": 2, **over}


AI = {"id": "ai", "origin": "ai_engineering_check", "compliance_status": "NEEDS_ENGINEER_REVIEW",
      "finding": "Confirm the invented coupling guard is fitted.", "contractor_page": 1,
      "ai_rationale": "Relates to: STD-INV-002."}
WEB = {"id": "web", "origin": "web_standard_check", "compliance_status": "NEEDS_ENGINEER_REVIEW",
       "finding": "Confirm the invented edition is current.", "contractor_page": 1}
CHAT = {"id": "chat", "origin": "chat", "finding": "Please add the invented nameplate photo.",
        "contractor_page": 1, "confirmed_by": "eng-1"}
TICK = _std(id="tick", compliance_status="COMPLIANT", show_for_engineer_tick=1, contractor_page=1,
            contractor_evidence_text="7 units", crs_field_label="WIDGET RATING")
STANDARDS = {"required_not_cited": [{"identifier": "STD-INV-009", "reason": "an invented reason"}],
             "cited_not_applicable": [{"identifier": "STD-INV-008", "reason": "another one"}]}


# ------------------------------------------------------------- f: the rank

def test_rows_rank_out_of_limit_then_missing_then_engineer_to_check():
    """The owner's order: out of limit first, then missing values, then what
    the engineer must check - whatever the pages say (the question is on
    p.1, the breach on p.9) and whatever order the findings came in."""
    rows = m.build_crs_rows([QUESTION(), BLANK(), BREACH()], [], "s.pdf")
    assert [r["priority"] for r in rows] == [1, 2, 3]
    assert [r["finding_id"] for r in rows] == ["breach", "blank", "question"]


def test_within_a_rank_rows_go_by_page_then_clause():
    """Inside one rank the datasheet's page decides, across row kinds: a
    datasheet check's missing value on p.2 comes before a blank on p.5 (both
    rank 2), though the check's reference sorts after the blank's clause."""
    rows = m.build_crs_rows([BLANK(), CHECK("MISSING_INFORMATION")], [], "s.pdf")
    assert [r["priority"] for r in rows] == [2, 2]
    assert [r["finding_id"] for r in rows] == ["check-MISSING_INFORMATION", "blank"]
    # same page: the clause decides (4.2 before 4.10, numbers not text)
    a = BLANK(id="a", standard_clause="4.10", fact_id="fa", crs_field_label="A",
              requirement_source_text="4.10 Rule A shall be stated.")
    b = BLANK(id="b", standard_clause="4.2", fact_id="fb", crs_field_label="B",
              requirement_source_text="4.2 Rule B shall be stated.")
    assert [r["finding_id"] for r in m.build_crs_rows([a, b], [], "s.pdf")] == ["b", "a"]


def test_not_found_ranks_with_engineer_to_check():
    """A value NOT FOUND is the system's miss until an engineer says
    otherwise (honesty audit 50): it is never ranked "Missing value", which
    would read as the contractor's gap."""
    rows = m.build_crs_rows([NOT_FOUND(), BLANK()], [], "s.pdf")
    by_id = {r["finding_id"]: r["priority"] for r in rows}
    assert by_id == {"blank": m.PRIORITY_MISSING_VALUE, "notfound": m.PRIORITY_ENGINEER_TO_CHECK}
    assert [r["finding_id"] for r in rows] == ["blank", "notfound"]


def test_a_datasheet_check_ranks_by_its_own_status():
    """A datasheet self-check out of limit is rank 1, a value it found
    missing rank 2, a check held for the engineer (rule not proven) rank 3."""
    held = CHECK("NEEDS_ENGINEER_REVIEW", rule_said="NON_COMPLIANT")
    rows = m.build_crs_rows([held, CHECK("MISSING_INFORMATION"), CHECK("NON_COMPLIANT")], [], "s.pdf")
    assert [(r["finding_id"], r["priority"]) for r in rows] == [
        ("check-NON_COMPLIANT", 1), ("check-MISSING_INFORMATION", 2),
        ("check-NEEDS_ENGINEER_REVIEW", 3)]


def test_rank_holds_across_every_row_kind():
    """ONE order over every kind of row: breaches, blanks, not found,
    datasheet checks, questions, safety ticks, chat comments, AI and web
    items, and the required-vs-cited rows. The kind of row no longer decides
    the order (the old sheet put every AI item after every chat comment, and
    the standards rows last of all)."""
    findings = [CHAT, AI, WEB, TICK, QUESTION(), NOT_FOUND(), CHECK("NON_COMPLIANT"),
                BLANK(), BREACH()]
    rows = m.build_crs_rows(findings, [], "s.pdf", standards_check=STANDARDS)
    ranks = [r["priority"] for r in rows]
    assert ranks == sorted(ranks), ranks
    assert all(isinstance(r["priority"], int) for r in rows)
    kinds = [r["row_kind"] for r in rows]
    assert set(kinds) == {
        m.ROW_KIND_NON_COMPLIANT, m.ROW_KIND_DATASHEET_CHECK, m.ROW_KIND_MISSING_INFORMATION,
        m.ROW_KIND_STANDARD_NOT_CITED, m.ROW_KIND_NEEDS_ENGINEER_REVIEW, m.ROW_KIND_SAFETY_TICK,
        m.ROW_KIND_AI_ENGINEERING_CHECK, m.ROW_KIND_WEB_STANDARD_CHECK,
        m.ROW_KIND_STANDARD_NOT_APPLICABLE, m.ROW_KIND_ENGINEER_COMMENT}
    # a standard not referenced asks the contractor for something: rank 2,
    # before every engineer-to-check row; the chat comment is last (rank 4)
    assert kinds.index(m.ROW_KIND_STANDARD_NOT_CITED) < kinds.index(m.ROW_KIND_NEEDS_ENGINEER_REVIEW)
    assert kinds[-1] == m.ROW_KIND_ENGINEER_COMMENT
    # a required-vs-cited row sorts after the finding rows of its own rank
    assert kinds.index(m.ROW_KIND_STANDARD_NOT_APPLICABLE) == len(kinds) - 2


def test_the_order_does_not_depend_on_the_input_order():
    findings = [CHAT, AI, WEB, TICK, QUESTION(), NOT_FOUND(), CHECK("NON_COMPLIANT"),
                BLANK(), BREACH()]
    once = m.build_crs_rows(findings, [], "s.pdf", standards_check=STANDARDS)
    again = m.build_crs_rows(list(reversed(findings)), [], "s.pdf", standards_check=STANDARDS)
    assert [r["comment_key"] for r in once] == [r["comment_key"] for r in again]


def test_row_priority_refuses_a_kind_it_cannot_rank():
    """A blank and a not-found share `row_kind` but not a rank: the caller
    must say which. A kind it does not know is refused, never guessed."""
    for kind in (m.ROW_KIND_MISSING_INFORMATION, "something new"):
        try:
            m.row_priority(kind)
        except ValueError:
            continue
        raise AssertionError(f"{kind!r} was given a rank")
    assert m.row_priority(m.ROW_KIND_CARRIED_FORWARD) == m.PRIORITY_CARRIED_FORWARD


def test_rank_words_are_never_a_confidence():
    """Rule 4: a rank is not a confidence - never "high", "low", "critical"."""
    words = " ".join([*m.PRIORITY_WORDS.values(), *m.ISSUE_PRIORITY_WORDS.values()]).lower()
    for banned in ("high", "low", "critical", "medium"):
        assert banned not in words
    assert m.priority_word(None) == "" and m.priority_word(99) == ""
    assert m.priority_word(3, "issue") == "Clarification"


# ------------------------------------------------- e: no empty COMPANY Comments

def test_every_internal_row_has_company_comment_text():
    """THE OWNER'S COUNT: 12 AI-written lines had an empty COMPANY Comments
    cell. An unconfirmed AI or web item now says, in plain words, that it is
    a suggestion awaiting an engineer and where its words are - never the
    draft itself, which stays in AI Review Comments (owner order 2d/2f)."""
    findings = [CHAT, AI, WEB, TICK, QUESTION(), NOT_FOUND(), CHECK("NON_COMPLIANT"),
                BLANK(), BREACH()]
    rows = m.build_crs_rows(findings, [], "s.pdf", standards_check=STANDARDS)
    assert all(str(r["comment"]).strip() for r in rows), [r["row_kind"] for r in rows
                                                          if not str(r["comment"]).strip()]
    ai = next(r for r in rows if r["row_kind"] == m.ROW_KIND_AI_ENGINEERING_CHECK)
    web = next(r for r in rows if r["row_kind"] == m.ROW_KIND_WEB_STANDARD_CHECK)
    assert ai["comment"] == m.AI_UNCONFIRMED_COMMENT
    assert web["comment"] == m.WEB_UNCONFIRMED_COMMENT
    assert AI["finding"] in ai["ai_review_comment"] and AI["finding"] not in ai["comment"]
    assert WEB["finding"] in web["ai_review_comment"] and WEB["finding"] not in web["comment"]
    assert ai["engineer_confirmed"] is False and web["engineer_confirmed"] is False


def test_a_confirmed_ai_item_prints_its_words_not_the_waiting_sentence():
    rows = m.build_crs_rows([dict(AI, confirmed_by="eng-1", confirmed_by_name="Eng One")], [], "s.pdf")
    assert AI["finding"] in rows[0]["comment"]
    assert m.AI_UNCONFIRMED_COMMENT not in rows[0]["comment"]
    assert rows[0]["ai_review_comment"] == ""


# ------------------------------------------------- the run summary sends the rank

def test_priority_labels_match_crs_mapping_words():
    """The summary's Literal is the internal words of ranks 1-4 (a finding is
    never carried forward, so 5 is not one of them)."""
    literal = run_summary.TierRow.model_fields["crs_priority_label"].annotation
    words = set(literal.__args__[0].__args__)
    assert words == {m.PRIORITY_WORDS[i] for i in (1, 2, 3, 4)}


def test_summary_sends_each_findings_rank_the_files_rank(review_run):  # noqa: F811
    """The screen's rank word is the file's: each finding row of the summary
    carries the priority of the CRS row its finding lands on, from the same
    `build_crs_rows`; a finding that is no row of the sheet carries none."""
    run, _ids, scope = review_run
    comparison.run_comparison(run, allowed_document_ids=scope)
    body = TestClient(app).get(f"/api/reviews/runs/{run}/summary").json()
    sent = {r["finding_id"]: (r.get("crs_priority"), r.get("crs_priority_label"))
            for r in body["rows"]}
    rows, _meta, _name, _stamp = main_mod._crs_content(
        run, access.AccessScope(user_id="eng", allowed_document_ids=scope), "internal")
    on_sheet = {fid: row["priority"] for row in rows
                for fid in (row.get("finding_ids") or [row.get("finding_id")]) if fid}
    assert on_sheet, "the fixture run produced CRS rows"
    for fid, rank in on_sheet.items():
        assert sent[fid] == (rank, m.priority_word(rank)), fid
    for fid, (rank, label) in sent.items():
        if fid not in on_sheet:
            assert rank is None and label is None, fid


def test_the_shared_tier_counting_builds_no_sheet(review_run):  # noqa: F811
    """`/counts` (up to 200 runs) shares `_tiers` with `/summary`; the rank is
    added by the summary route only, never in the shared counting."""
    run, _ids, scope = review_run
    comparison.run_comparison(run, allowed_document_ids=scope)
    tiers = run_summary._tiers(run, scope)[0]
    assert tiers["rows"] and not any("crs_priority" in r for r in tiers["rows"])
