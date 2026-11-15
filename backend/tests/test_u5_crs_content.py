"""U5d: the one CRS carries each point's own content: field, paper value, rule text, action, reason, Checked by, pages, rule reference.
Invented findings only; nothing here depends on a stored paper."""

from __future__ import annotations

from app import crs_one, review_points
from app import review_points_content as c
from tests.test_b1_review_points import world_with_both
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_k4_one_crs import on, rows_after, scope_all, sheet  # noqa: F401 - fixtures and helpers

CTX = {"run_id": "r", "paper_document_id": "doc1", "readable": frozenset({"doc1"})}
PLACEHOLDER = "AI suggestion awaiting an engineer's decision - its words are in AI Review Comments. Not issued to the contractor until an engineer confirms it."


def row(kind="clause_review", **kw) -> dict:
    return {"row_kind": kind, "finding_id": "f1", "page_section": "", "comment": PLACEHOLDER, "standard_reference": "STD-9 (edition not recorded) cl. 5.3",
            "ai_review_comment": "Check that both assessments follow the procedure.", **kw}  # fmt: skip


FINDING = {"id": "f1", "standard_clause": "5.3", "requirement": "Both assessments shall follow the written procedure.", "requirement_source_text": "",
           "contractor_evidence_text": "Assessments are done by the team.", "contractor_page": 8, "compliance_status": "NEEDS_ENGINEER_REVIEW"}  # fmt: skip


# ------------------------------------------------------------------------------------------------ the pieces


def test_a_placeholder_or_a_page_label_is_never_the_field():
    # a clause point is named by its reference and clause number, never by the first words of the book's sentence
    assert c.field_of("p.22", row(), FINDING) == "STD-9 (edition not recorded) cl. 5.3"
    assert "Both assessments" not in c.field_of("", row(), FINDING)
    assert c.field_of(PLACEHOLDER, row(), FINDING).startswith("STD-9")
    assert c.field_of("", row(), FINDING, allow_rule=False) == c.HIDDEN_FIELD  # a book the viewer may not read: nothing derived from it
    assert "clause clause" not in c.field_of("", row(), FINDING) and "5.3 clause 5.3" not in c.field_of("", row(), FINDING)  # the clause is said once
    assert c.field_of("Set pressure", row(), FINDING) == "Set pressure"
    assert c.field_of("", row("playbook_check", comment="HAZOP scope and objectives", standard_reference=""), None) == "HAZOP scope and objectives"


def test_the_words_the_placeholder_points_to_are_in_the_cell_labelled_as_the_ais():
    text, source = c.action_of(row(), FINDING)
    assert (text, source) == ("Check that both assessments follow the procedure.", "ai_suggestion")
    assert c.action_of(row(comment="Contractor to confirm the rating."), FINDING) == ("Contractor to confirm the rating.", "check")
    assert c.action_of(row(comment=PLACEHOLDER, ai_review_comment=""), {"required_action": "Provide the procedure."}) == ("Provide the procedure.", "ai_suggestion")
    assert c.action_of(row(comment="", ai_review_comment=""), {}) == ("", "")


def test_stored_values_are_returned_as_stored_and_nothing_is_invented():
    assert c.paper_value(FINDING) == ("Assessments are done by the team.", 8)
    assert c.paper_value({}) == ("", None)
    assert c.rule_text(FINDING) == "Both assessments shall follow the written procedure."
    assert c.rule_text({}) == ""
    assert c.rule_ref(row(), FINDING) == {"name": "STD-9 (edition not recorded) cl. 5.3", "clause": "", "page": None}  # the clause already in the name
    assert c.rule_ref(row(standard_reference="STD-9"), FINDING)["clause"] == "5.3"


def test_the_reason_is_plain_words_per_kind_never_the_source_label():
    for kind in ("datasheet_check", "clause_review", "playbook_check", "ai_engineering_check", "needs_engineer_review", "standard_not_cited", "safety_tick"):
        got = c.reason_words(kind, FINDING)
        assert got and got.lower() not in ("datasheet check", "clause review", "playbook check", "ai engineering check", kind.replace("_", " "))
        assert "_" not in got
    assert "not compare" in c.reason_words("needs_engineer_review", {"reason_code": "quantity_kind_unsure"})
    assert c.checked_by("clause_review") == "Rule check: clause review (AI)" and c.checked_by("playbook_check") == "Rule check: playbook check"


# ------------------------------------------------------------------------------------------------ the point and the cells


def test_a_clause_review_point_carries_its_own_content():
    p = review_points.rule_point(row(), CTX, FINDING, {})
    assert p["name"].startswith("STD-9") and "awaiting" not in p["name"]
    assert p["action"] == "Check that both assessments follow the procedure." and p["action_source"] == "ai_suggestion"
    assert p["paper_value"] == "Assessments are done by the team." and p["paper_quote"] is None  # stored, NOT verified
    assert p["rule_text"].startswith("Both assessments") and p["checked_by"] == "Rule check: clause review (AI)"
    assert p["page"] == 8 and p["reason_words"]


def test_the_cells_say_stored_not_verified_and_say_nothing_recorded_once():
    p = review_points.rule_point(row(), CTX, FINDING, {})
    assert 'not verified by code' in crs_one.paper_shows(p) and '"Assessments are done by the team."' in crs_one.paper_shows(p)
    assert "verified by code)" not in crs_one.paper_shows(p).replace("not verified by code)", "")  # never worded as verified
    assert "not verified by code" in crs_one.rule_requires(p)
    empty = review_points.rule_point(row(), CTX, {"id": "f2"}, {})
    assert crs_one.paper_shows(empty) == c.NOTHING and crs_one.rule_requires(empty) == c.NOTHING
    assert "No verified quote" not in crs_one.paper_shows(p) + crs_one.rule_requires(p) + crs_one.paper_shows(empty)


def test_the_ai_suggestion_is_labelled_internal_and_never_reaches_the_contractor():
    p = review_points.rule_point(row(), CTX, FINDING, {})
    action = crs_one.full_texts({**p, "decision": {}})["action"]
    assert action.startswith("The AI's suggestion (internal") and "Check that both assessments" in action
    proven = {**p, "rank": 1, "decision": {"state": "keep"}}  # even a kept rank-1 point: the AI's suggestion is not issued
    assert crs_one.issuable_text(proven) == ""
    edited = {**p, "decision": {"state": "edit", "text": "Revise the procedure."}}
    assert crs_one.issuable_text(edited) == "Revise the procedure."


# ------------------------------------------------------------------------------------------------ the file


def test_the_team_file_has_no_placeholder_no_blanket_quote_wall_and_a_checked_by_column():
    doc, rc, ai, client = world_with_both()
    data = crs_one.build_team(doc, scope_all())
    head, rows = rows_after(sheet(data), "Comment")
    text = "\n".join(str(x) for r in rows for x in r if x is not None)
    assert "AI suggestion awaiting" not in text and "No verified quote" not in text
    by = head.index("Checked by")
    assert all(r[by] for r in rows)
    for col in ("Rule books and clauses",):  # said, or plainly not recorded; never a silent empty
        assert head.index(col) is not None


def test_the_pages_line_cannot_contradict_itself_and_the_files_line_has_no_api_path():
    assert crs_one.pages_line({"pages_total": 7, "pages_read": []}, []) == "7 pages: 0 not fully read; how many were read in full is not recorded"
    assert crs_one.pages_line({"pages_total": 69, "pages_read": [1, 2, 3]}, [4, 5]) == "69 pages: 3 read, 2 not fully read (pages 4, 5)"
    doc, rc, ai, client = world_with_both()
    data = crs_one.build_team(doc, scope_all())
    from openpyxl import load_workbook
    from io import BytesIO

    wb = load_workbook(BytesIO(data))
    every = "\n".join(str(x) for ws in wb.worksheets for r in ws.iter_rows(values_only=True) for x in r if x is not None)
    assert "/api/" not in every and "GET " not in every


def test_the_value_a_datasheet_check_read_is_the_papers_stored_value_with_its_page():
    f = {"id": "f", "fact_id": "x", "_fact": {"field_name": "Set pressure", "field_value": "12", "unit": "bar", "page": 3}}
    assert c.paper_value(f) == ("Set pressure: 12 bar", 3)
    assert c.paper_value({"_fact": {"field_name": "Set pressure", "field_value": "", "unit": None, "page": 3}}) == ("", 3)  # blank: no value invented
    p = review_points.rule_point(row("datasheet_check", comment="Datasheet check: Set pressure was read."), CTX, f, {})
    assert p["paper_value"] == "Set pressure: 12 bar" and p["page"] == 3 and p["paper_quote"] is None  # stored, not verified


def test_a_comment_with_no_rule_book_says_so_and_never_looks_rule_backed():
    p = review_points.rule_point(row("playbook_check", standard_reference="", comment="HAZOP scope"), CTX, None, {})
    assert crs_one.no_rule_words([p]) == c.NO_RULE_CITED == "no rule book cited: a field check"
    from app import crs_comments

    got = crs_comments.group([{**p, "decision": {}, "tags": [], "page": None}])[0]
    assert got["book_held"] is False and crs_one.comment_full_texts(got)["clauses"] == c.NO_RULE_CITED
    # a held book the reader may not read: counted, not named, and not called "no rule book"
    held = {**p, "_book_docs": ["doc_closed"]}
    assert crs_one.no_rule_words([held]) == c.UNREADABLE_BOOK
    assert crs_comments.group([{**held, "decision": {}, "tags": [], "page": None}])[0]["book_held"] is True


# ------------------------------------------------------------------------------------------------ R73 F1: rule 5, the viewer's grants


HIDDEN_TEXT, HIDDEN_CLAUSE, HIDDEN_NAME = "Zeta vessels shall be painted vermilion", "9.9.9", "CLOSED-777"
OPEN_TEXT = "Alpha tags shall be engraved"


def _two_books_world():
    from app import db
    from tests.test_crs_endpoint import NOW, _client, _finding, _run, _submittal

    doc = _submittal()
    _submittal("doc_open", "OPEN-100.pdf")
    _submittal("doc_closed", HIDDEN_NAME + ".pdf")
    rc = _run(doc, recommended="Approved with Comments")
    _finding(doc, rc, "NEEDS_ENGINEER_REVIEW", standard_document_id="doc_open", requirement_source_text=OPEN_TEXT, requirement=OPEN_TEXT,
             standard_clause="4.1", equipment_tag="TAG-OPEN")  # fmt: skip
    _finding(doc, rc, "NEEDS_ENGINEER_REVIEW", standard_document_id="doc_closed", requirement_source_text=HIDDEN_TEXT, requirement=HIDDEN_TEXT,
             standard_clause=HIDDEN_CLAUSE, equipment_tag="TAG-CLOSED")  # fmt: skip
    return doc, _client(doc, "doc_open")  # the viewer may read the paper and ONE book


def _every_string(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _every_string(k)
            yield from _every_string(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _every_string(v)
    elif obj is not None:
        yield str(obj)


def test_a_viewer_who_may_not_read_a_rule_book_gets_nothing_of_it_on_the_page_or_in_either_file():
    from io import BytesIO

    from openpyxl import load_workbook

    from app import access, db, review_points_service

    doc, client = _two_books_world()
    scope = access.AccessScope(user_id="eng", allowed_document_ids=frozenset({doc, "doc_open"}))
    listing = review_points_service.assemble(doc, scope)
    team = crs_one.build_team(doc, scope)
    contractor = crs_one.build_contractor(doc, scope)
    texts = list(_every_string(listing["points"])) + list(_every_string(listing["counts"]))
    for data in (team, contractor):
        wb = load_workbook(BytesIO(data))
        texts += [str(x) for ws in wb.worksheets for r in ws.iter_rows(values_only=True) for x in r if x is not None]
    blob = "\n".join(texts)
    for hidden in (HIDDEN_TEXT, HIDDEN_CLAUSE, HIDDEN_NAME, "vermilion"):
        assert hidden not in blob, hidden
    # the readable book's content still appears, on the page and in the team file
    assert OPEN_TEXT in blob and "OPEN-100" in blob
    # the hidden point is counted and says so in words
    assert any(p.get("rule_hidden") for p in review_points_service.export_listing(doc, scope)[1])
    assert c.UNREADABLE_BOOK in blob or c.HIDDEN_FIELD in blob


def test_the_same_world_read_by_a_viewer_of_both_books_shows_the_secret_content():
    from app import access, review_points_service

    doc, _client = _two_books_world()
    scope = access.AccessScope(user_id="eng", allowed_document_ids=frozenset({doc, "doc_open", "doc_closed"}))
    blob = "\n".join(_every_string(review_points_service.assemble(doc, scope)["points"]))
    assert HIDDEN_TEXT in blob  # the guard hides it from the other viewer only


# ------------------------------------------------------------------------------------------------ R73b: fail closed when readability is not proven


LIB = [{"id": "doc_open", "filename": "OPEN-100.pdf", "document_number": "OPEN-100"}, {"id": "doc_closed", "filename": "CLOSED-777.pdf", "document_number": "CLOSED-777"}]
READ = frozenset({"paper", "doc_open"})


def proof(reference="", finding=None, docs=(), readable=READ, everything=False):
    from app import review_points_service as svc

    return svc.readability_proof({"standard_reference": reference}, finding, list(docs), readable, LIB, everything)


def test_the_readability_proof_is_proven_or_hidden():
    # (a) a linked book: all linked books must be readable
    assert proof(docs=["doc_open"]) == (True, True)
    assert proof(docs=["doc_open", "doc_closed"]) == (False, False)
    assert proof(docs=["doc_closed"]) == (False, False)
    # (b) no link: the stored reference must resolve to held books that are ALL readable
    assert proof("OPEN-100 cl. 4.1") == (True, True)
    assert proof("CLOSED-777 cl. 9.9") == (False, False)  # resolves to a book the viewer may not read
    assert proof("NOWHERE-5 cl. 1") == (False, False)  # unresolved
    assert proof("") == (False, False)  # no reference at all
    # (c) the app's own approved checklist proves the origin from the stored column and the entry id; the reference still needs its books
    chk = {"origin": "datasheet_check", "requirement_source_text": "Datasheet check DS-C1: the tag is stated."}
    assert proof("", chk) == (True, True)
    assert proof("CLOSED-777 cl. 9.9", chk) == (True, False)  # the text is the app's own; the closed book's NAME is not shown
    assert proof("", {"origin": "datasheet_check", "requirement_source_text": "Datasheet check NOT-AN-ENTRY-9: x"}) == (False, False)  # cannot be proven: hidden
    assert proof("", {"origin": None, "requirement_source_text": "Datasheet check DS-C1: the tag is stated."}) == (False, False)  # the origin is the stored column, not the wording
    # a viewer who may read the whole library is not restricted
    assert proof("NOWHERE-5", everything=True) == (True, True)


def _unlinked_world():
    from tests.test_crs_endpoint import _client, _finding, _run, _submittal

    doc = _submittal()
    _submittal("doc_open", "OPEN-100.pdf")
    rc = _run(doc, recommended="Approved with Comments")
    # unlinked, no checklist origin, no reference: unproven
    _finding(doc, rc, "NEEDS_ENGINEER_REVIEW", standard_document_id=None, requirement_source_text="Gamma flanges shall be lined with teflon", requirement="Gamma flanges shall be lined with teflon", standard_clause="7.7.7", equipment_tag="TAG-A")  # fmt: skip
    # checklist origin, proven by the stored column and the entry id
    _finding(doc, rc, "NEEDS_ENGINEER_REVIEW", standard_document_id=None, origin="datasheet_check", requirement_source_text="Datasheet check DS-C1: Delta plates are riveted per Zulu-Book clause 3.3", requirement="Datasheet check DS-C1: Delta plates are riveted per Zulu-Book clause 3.3", ai_rationale="Zulu-Book clause 3.3 says Delta plates", equipment_tag="TAG-B")  # fmt: skip
    # a checklist-looking text whose entry does not exist and whose origin is not the checklist: unproven
    _finding(doc, rc, "NEEDS_ENGINEER_REVIEW", standard_document_id=None, origin="datasheet_check", requirement_source_text="Datasheet check NOT-AN-ENTRY-9: Epsilon rods are copper", requirement="Epsilon rods are copper", equipment_tag="TAG-C")  # fmt: skip
    return doc


def test_a_restricted_viewer_gets_no_unproven_requirement_words_and_the_proven_ones_stay():
    from io import BytesIO

    from openpyxl import load_workbook

    from app import access, review_points_service

    doc = _unlinked_world()
    restricted = access.AccessScope(user_id="eng", allowed_document_ids=frozenset({doc}))
    full = access.AccessScope(user_id="eng", allowed_document_ids=frozenset({doc, "doc_open"}))

    def blob(scope):
        listing = review_points_service.assemble(doc, scope)
        texts = list(_every_string(listing["points"]))
        for data in (crs_one.build_team(doc, scope), crs_one.build_contractor(doc, scope)):
            texts += [str(x) for ws in load_workbook(BytesIO(data)).worksheets for r in ws.iter_rows(values_only=True) for x in r if x is not None]
        return "\n".join(texts), listing

    got, listing = blob(restricted)
    for hidden in ("Gamma flanges", "teflon", "7.7.7", "Epsilon rods", "copper", "OPEN-100", "NOT-AN-ENTRY"):
        assert hidden not in got, hidden
    # the app's own checklist: shown, but ONLY the text of the approved file (read from the JSON by the proven entry id), never the stored row's words
    json_text = "The design pressure should be at least the operating pressure."
    assert json_text in got and "Delta plates" not in got and "Zulu-Book" not in got and "clause 3.3" not in got
    flags = {p["rule_hidden"] for p in listing["points"] if p["source"] == "rule_check"}
    assert flags == {True, False}
    assert c.UNREADABLE_BOOK in got or c.HIDDEN_FIELD in got
    # a viewer who may read every document sees all of it (nothing is hidden for him)
    seen, listing2 = blob(full)
    assert "Gamma flanges" in seen and "Epsilon rods" in seen and not any(p.get("rule_hidden") for p in listing2["points"])
    assert "Delta plates are riveted per Zulu-Book" in seen  # a viewer of the whole library sees the stored text, as before


def test_a_hidden_point_never_uses_the_ais_or_the_findings_words_and_the_hand_revert_fails():
    hidden_row = row(ai_review_comment="Check against OPEN-100 clause 4.1 as the book says.")
    p = review_points.rule_point(hidden_row, CTX, FINDING, {}, proof=(False, False))
    assert p["rule_hidden"] is True and p["rule_text"] is None and p["clause"] is None and p["rule_ref"] is None
    assert p["action"] == c.HIDDEN_ACTION and p["action_source"] == "hidden"  # not the row's AI-review comment, not the finding's
    assert "OPEN-100" not in p["action"] and p["ai_reasoning"] == ""
    proven = review_points.rule_point(hidden_row, CTX, FINDING, {}, proof=(True, True))
    assert proven["rule_hidden"] is False and proven["action_source"] == "ai_suggestion"
    # the reference may be withheld while the app's own checklist text stays
    half = review_points.rule_point(row("datasheet_check", comment="A check.", standard_reference="CLOSED-777 cl. 9.9"), CTX, FINDING, {}, proof=(True, False))
    assert half["rule_hidden"] is False and half["rule_ref"] is None and half["clause"] is None and half["rule_text"]
    assert "CLOSED-777" not in str(half["name"])
    # an AI point of a hidden book drops the AI's free words too
    line = {"item_id": "R-1", "source": "rule", "standard": "CLOSED-777", "clause": "9.9", "verdict": "Query", "reasoning": "Per CLOSED-777 the rod is wrong.",
            "standard_document_id": "doc_closed", "quotes_checked": {}}  # fmt: skip
    ai = review_points.ai_point(line, {"run_id": "r", "paper_document_id": "paper", "book_of": {"R-1": ("doc_closed", "CLOSED-777")}, "readable": frozenset({"paper"})})
    assert ai["ai_reasoning"] == "" and "CLOSED-777" not in str(review_points.public(ai))


# ------------------------------------------------------------------------------------------------ R73c: checklist text from the file, AI free text, matched phrase


def test_r1_a_checklist_point_for_a_restricted_viewer_takes_no_ai_or_finding_words():
    placeholder_row = row("datasheet_check", ai_review_comment="Per Zulu-Book clause 3.3 the plates are wrong.")  # comment is the placeholder
    p = review_points.rule_point(placeholder_row, CTX, FINDING, {}, proof=(True, True), app_text_only=True)
    assert p["action"] == c.HIDDEN_ACTION and "Zulu" not in str(review_points.public(p))
    full = review_points.rule_point(placeholder_row, CTX, FINDING, {}, proof=(True, True))
    assert "Zulu-Book" in full["action"]  # a whole-library viewer: unchanged


def test_r1_the_json_entry_text_is_what_a_restricted_viewer_gets_and_an_entry_without_text_is_hidden():
    from app import review_points_service as svc

    hit = svc._checklist_entry_of({"origin": "datasheet_check", "requirement_source_text": "Datasheet check DS-C1: stored words"})
    assert hit and hit[0] == "DS-C1" and hit[1]["text"] == "The design pressure should be at least the operating pressure."
    assert svc._checklist_entry_of({"origin": "datasheet_check", "requirement_source_text": "Datasheet check NO-SUCH-1: x"}) is None
    assert svc._checklist_entry_of({"origin": None, "requirement_source_text": "Datasheet check DS-C1: x"}) is None


def _ai_line(**kw):
    base = {"item_id": "S-1", "source": "skill", "standard": "", "clause": "", "verdict": "Query", "quotes_checked": {}, "reasoning": "The sheet is silent."}
    return {**base, **kw}


def _ai_ctx(readable, everything=False):
    return {"run_id": "r", "paper_document_id": "paper", "book_of": {}, "readable": frozenset(readable), "library": LIB, "everything": everything}


def test_r2_ai_free_text_with_no_linked_book_is_shown_only_when_it_cannot_name_a_closed_book():
    ok = _ai_ctx({"paper", "doc_open"})
    # cites no rule and names no held book the viewer may not read: kept
    assert review_points.ai_point(_ai_line(), ok)["ai_reasoning"]
    # its free words name a held book the viewer may not read (the same matcher): dropped
    assert review_points.ai_point(_ai_line(reasoning="Per CLOSED-777 the rod is wrong."), ok)["ai_reasoning"] == ""
    # a book he may read may be named
    assert "OPEN-100" in review_points.ai_point(_ai_line(reasoning="Per OPEN-100 the rod is right."), ok)["ai_reasoning"]
    # it cites a reference: the reference must resolve to books he may ALL read
    assert review_points.ai_point(_ai_line(standard="OPEN-100"), ok)["ai_reasoning"]
    assert review_points.ai_point(_ai_line(standard="CLOSED-777"), ok)["ai_reasoning"] == ""
    assert review_points.ai_point(_ai_line(standard="NOWHERE-5"), ok)["ai_reasoning"] == ""  # unresolved
    # a whole-library viewer sees it all
    assert review_points.ai_point(_ai_line(reasoning="Per CLOSED-777 the rod is wrong."), _ai_ctx({"paper", "doc_open", "doc_closed"}, True))["ai_reasoning"]


def test_r3_the_matched_phrase_comes_from_the_requirement_and_needs_the_rule_content_to_be_visible():
    f = {"matched_phrase": "Flange face finish", "contractor_section": "Section 4"}
    assert c.field_of("", row(standard_reference=""), f, allow_rule=False) == "Section 4"  # the paper's own label stays
    assert c.field_of("", row(standard_reference=""), f, allow_rule=True) == "Flange face finish"
    assert c.field_of("", row(), {"matched_phrase": "Flange face finish"}, allow_rule=False) == c.HIDDEN_FIELD
